from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, Literal

from volarb_py.pricing import standard_normal_cumulative_distribution
from volarb_py.svi import (
    BUTTERFLY_TOLERANCE,
    GOLDEN_SECTION_RATIO,
    MINIMUM_TOTAL_VARIANCE,
    REFINEMENT_PASSES,
    SviParameters,
    density_weight,
    durrleman_value,
    total_variance,
    total_variance_first_derivative,
    total_variance_second_derivative,
    validate_svi_parameters,
)

SviSurfaceStatus = Literal[
    "arbitrage_free_on_grid",
    "butterfly_arbitrage_found",
    "calendar_arbitrage_found",
    "invalid_surface",
]

DEFAULT_SURFACE_SCAN_STEPS: Final[int] = 256
MINIMUM_SURFACE_SCAN_STEPS: Final[int] = 2
MINIMUM_SURFACE_SLICES: Final[int] = 2
DEFAULT_TIME_STEPS_PER_INTERVAL: Final[int] = 8
MINIMUM_TIME_STEPS_PER_INTERVAL: Final[int] = 1
CALENDAR_TOLERANCE: Final[float] = -1e-12
MINIMUM_DURRLEMAN_DENOMINATOR: Final[float] = 1e-12
ROUND_TRIP_MONEYNESS_STEP: Final[float] = 1e-4
ROUND_TRIP_TIME_STEP: Final[float] = 1e-5
ROUND_TRIP_LOCAL_VARIANCE_FLOOR: Final[float] = 1e-6


class InvalidSviSurfaceError(ValueError):
    pass


@dataclass(frozen=True)
class SviSurfaceSlice:
    years_to_expiry: float
    parameters: SviParameters


@dataclass(frozen=True)
class SurfaceInterval:
    earlier: SviSurfaceSlice
    later: SviSurfaceSlice


@dataclass(frozen=True)
class InterpolatedSlice:
    earlier: SviParameters
    later: SviParameters
    fraction: float
    time_span: float


@dataclass(frozen=True)
class SviSurfaceScan:
    slice_count: int
    scan_steps: int
    time_steps_per_interval: int
    minimum_durrleman_value: float
    log_moneyness_at_minimum_durrleman_value: float
    years_to_expiry_at_minimum_durrleman_value: float
    minimum_risk_neutral_density: float
    minimum_total_variance_time_slope: float
    log_moneyness_at_minimum_time_slope: float
    years_to_expiry_at_minimum_time_slope: float
    minimum_local_variance: float
    log_moneyness_at_minimum_local_variance: float
    years_to_expiry_at_minimum_local_variance: float
    worst_local_variance_round_trip_error: float
    log_moneyness_at_worst_round_trip_error: float
    round_trip_point_count: int
    status: SviSurfaceStatus


def validate_svi_surface(slices: list[SviSurfaceSlice]) -> None:
    if len(slices) < MINIMUM_SURFACE_SLICES:
        raise InvalidSviSurfaceError(
            f"a surface needs at least {MINIMUM_SURFACE_SLICES} slices, got {len(slices)}"
        )
    for entry in slices:
        if entry.years_to_expiry <= 0.0:
            raise InvalidSviSurfaceError(f"years_to_expiry must be positive, got {entry.years_to_expiry}")
        validate_svi_parameters(entry.parameters)
    for earlier, later in pairwise(slices):
        span = later.years_to_expiry - earlier.years_to_expiry
        if span <= 0.0:
            raise InvalidSviSurfaceError("slices must be strictly increasing in years_to_expiry")
        if span <= 2.0 * ROUND_TRIP_TIME_STEP:
            raise InvalidSviSurfaceError(
                f"adjacent expiries must be more than {2.0 * ROUND_TRIP_TIME_STEP} years apart, got {span}"
            )


def interpolated_slice_between(
    earlier: SviSurfaceSlice, later: SviSurfaceSlice, fraction: float
) -> InterpolatedSlice:
    return InterpolatedSlice(
        earlier=earlier.parameters,
        later=later.parameters,
        fraction=fraction,
        time_span=later.years_to_expiry - earlier.years_to_expiry,
    )


def interpolated_total_variance(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    earlier = total_variance(interpolated.earlier, log_moneyness)
    later = total_variance(interpolated.later, log_moneyness)
    return (1.0 - interpolated.fraction) * earlier + interpolated.fraction * later


def interpolated_first_derivative(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    earlier = total_variance_first_derivative(interpolated.earlier, log_moneyness)
    later = total_variance_first_derivative(interpolated.later, log_moneyness)
    return (1.0 - interpolated.fraction) * earlier + interpolated.fraction * later


def interpolated_second_derivative(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    earlier = total_variance_second_derivative(interpolated.earlier, log_moneyness)
    later = total_variance_second_derivative(interpolated.later, log_moneyness)
    return (1.0 - interpolated.fraction) * earlier + interpolated.fraction * later


def interpolated_time_slope(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    earlier = total_variance(interpolated.earlier, log_moneyness)
    later = total_variance(interpolated.later, log_moneyness)
    return (later - earlier) / interpolated.time_span


def interpolated_durrleman_value(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    variance = max(interpolated_total_variance(interpolated, log_moneyness), MINIMUM_TOTAL_VARIANCE)
    slope = interpolated_first_derivative(interpolated, log_moneyness)
    curvature = interpolated_second_derivative(interpolated, log_moneyness)
    return durrleman_value(log_moneyness, variance, slope, curvature)


def interpolated_risk_neutral_density(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    variance = max(interpolated_total_variance(interpolated, log_moneyness), MINIMUM_TOTAL_VARIANCE)
    return interpolated_durrleman_value(interpolated, log_moneyness) * density_weight(log_moneyness, variance)


def interpolated_local_variance(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    denominator = max(
        interpolated_durrleman_value(interpolated, log_moneyness), MINIMUM_DURRLEMAN_DENOMINATOR
    )
    return interpolated_time_slope(interpolated, log_moneyness) / denominator


def refined_minimum_of(evaluate: Callable[[float], float], lower: float, upper: float) -> tuple[float, float]:
    left = upper - GOLDEN_SECTION_RATIO * (upper - lower)
    right = lower + GOLDEN_SECTION_RATIO * (upper - lower)
    left_value = evaluate(left)
    right_value = evaluate(right)

    for _ in range(REFINEMENT_PASSES):
        if left_value < right_value:
            upper, right, right_value = right, left, left_value
            left = upper - GOLDEN_SECTION_RATIO * (upper - lower)
            left_value = evaluate(left)
        else:
            lower, left, left_value = left, right, right_value
            right = lower + GOLDEN_SECTION_RATIO * (upper - lower)
            right_value = evaluate(right)

    if left_value <= right_value:
        return left, left_value
    return right, right_value


def out_of_the_money_price(
    interpolated: InterpolatedSlice, log_moneyness: float, use_put_branch: bool
) -> float:
    variance = max(interpolated_total_variance(interpolated, log_moneyness), MINIMUM_TOTAL_VARIANCE)
    root = math.sqrt(variance)
    d1 = -log_moneyness / root + 0.5 * root
    d2 = d1 - root
    if use_put_branch:
        return math.exp(log_moneyness) * standard_normal_cumulative_distribution(
            -d2
        ) - standard_normal_cumulative_distribution(-d1)
    return standard_normal_cumulative_distribution(d1) - math.exp(
        log_moneyness
    ) * standard_normal_cumulative_distribution(d2)


def shifted_in_time(interpolated: InterpolatedSlice, years_offset: float) -> InterpolatedSlice:
    return InterpolatedSlice(
        earlier=interpolated.earlier,
        later=interpolated.later,
        fraction=interpolated.fraction + years_offset / interpolated.time_span,
        time_span=interpolated.time_span,
    )


def price_space_curvature(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    use_put_branch = log_moneyness < 0.0
    centre = out_of_the_money_price(interpolated, log_moneyness, use_put_branch)
    above = out_of_the_money_price(interpolated, log_moneyness + ROUND_TRIP_MONEYNESS_STEP, use_put_branch)
    below = out_of_the_money_price(interpolated, log_moneyness - ROUND_TRIP_MONEYNESS_STEP, use_put_branch)
    first = (above - below) / (2.0 * ROUND_TRIP_MONEYNESS_STEP)
    second = (above - 2.0 * centre + below) / (ROUND_TRIP_MONEYNESS_STEP * ROUND_TRIP_MONEYNESS_STEP)
    return 0.5 * (second - first)


def local_variance_from_prices(interpolated: InterpolatedSlice, log_moneyness: float) -> float:
    curvature = price_space_curvature(interpolated, log_moneyness)
    if curvature <= 0.0:
        raise InvalidSviSurfaceError(
            f"the price space density is not positive at {log_moneyness}, got {curvature}"
        )
    use_put_branch = log_moneyness < 0.0
    later = shifted_in_time(interpolated, ROUND_TRIP_TIME_STEP)
    earlier = shifted_in_time(interpolated, -ROUND_TRIP_TIME_STEP)
    time_derivative = (
        out_of_the_money_price(later, log_moneyness, use_put_branch)
        - out_of_the_money_price(earlier, log_moneyness, use_put_branch)
    ) / (2.0 * ROUND_TRIP_TIME_STEP)
    return time_derivative / curvature


def moneyness_grid(lowest: float, highest: float, scan_steps: int) -> list[float]:
    span = highest - lowest
    return [lowest + span * index / scan_steps for index in range(scan_steps + 1)]


def scan_times_for_interval(time_steps_per_interval: int, include_lower_knot: bool) -> list[float]:
    first = 0 if include_lower_knot else 1
    return [index / time_steps_per_interval for index in range(first, time_steps_per_interval + 1)]


@dataclass(frozen=True)
class ScanGrid:
    log_moneyness: list[float]
    scan_steps: int
    time_steps_per_interval: int


@dataclass
class SurfaceExtremes:
    durrleman_value: float = math.inf
    durrleman_log_moneyness: float = 0.0
    durrleman_years: float = 0.0
    risk_neutral_density: float = 0.0
    time_slope: float = math.inf
    time_slope_log_moneyness: float = 0.0
    time_slope_years: float = 0.0
    local_variance: float = math.inf
    local_variance_log_moneyness: float = 0.0
    local_variance_years: float = 0.0
    round_trip_error: float = 0.0
    round_trip_log_moneyness: float = 0.0
    round_trip_points: int = 0


def grid_minimum_with_refinement(evaluate: Callable[[float], float], grid: ScanGrid) -> tuple[float, float]:
    points = grid.log_moneyness
    values = [evaluate(point) for point in points]
    best_index = min(range(len(values)), key=lambda index: (values[index], index))
    lower = points[max(best_index - 1, 0)]
    upper = points[min(best_index + 1, grid.scan_steps)]
    refined_point, refined_value = refined_minimum_of(evaluate, lower, upper)
    if refined_value > values[best_index]:
        return points[best_index], values[best_index]
    return refined_point, refined_value


def record_durrleman(
    extremes: SurfaceExtremes, interpolated: InterpolatedSlice, grid: ScanGrid, years: float
) -> tuple[float, float]:
    point, value = grid_minimum_with_refinement(
        lambda argument: interpolated_durrleman_value(interpolated, argument), grid
    )
    if value < extremes.durrleman_value:
        extremes.durrleman_value = value
        extremes.durrleman_log_moneyness = point
        extremes.durrleman_years = years
        extremes.risk_neutral_density = interpolated_risk_neutral_density(interpolated, point)
    return point, value


def record_time_slope(
    extremes: SurfaceExtremes, interpolated: InterpolatedSlice, grid: ScanGrid, years: float
) -> None:
    point, value = grid_minimum_with_refinement(
        lambda argument: interpolated_time_slope(interpolated, argument), grid
    )
    if value < extremes.time_slope:
        extremes.time_slope = value
        extremes.time_slope_log_moneyness = point
        extremes.time_slope_years = years


def record_local_variance(
    extremes: SurfaceExtremes, interpolated: InterpolatedSlice, grid: ScanGrid, years: float
) -> None:
    point, value = grid_minimum_with_refinement(
        lambda argument: interpolated_local_variance(interpolated, argument), grid
    )
    if value < extremes.local_variance:
        extremes.local_variance = value
        extremes.local_variance_log_moneyness = point
        extremes.local_variance_years = years


def record_round_trip(extremes: SurfaceExtremes, interpolated: InterpolatedSlice, grid: list[float]) -> None:
    for point in grid:
        analytic = interpolated_local_variance(interpolated, point)
        if analytic < ROUND_TRIP_LOCAL_VARIANCE_FLOOR:
            continue
        if price_space_curvature(interpolated, point) <= 0.0:
            continue
        error = abs(local_variance_from_prices(interpolated, point) - analytic) / analytic
        extremes.round_trip_points += 1
        if error > extremes.round_trip_error:
            extremes.round_trip_error = error
            extremes.round_trip_log_moneyness = point


def surface_status(extremes: SurfaceExtremes) -> SviSurfaceStatus:
    if extremes.durrleman_value < BUTTERFLY_TOLERANCE:
        return "butterfly_arbitrage_found"
    if extremes.time_slope < CALENDAR_TOLERANCE:
        return "calendar_arbitrage_found"
    return "arbitrage_free_on_grid"


def slice_at_fraction(interval: SurfaceInterval, fraction: float) -> InterpolatedSlice:
    return interpolated_slice_between(interval.earlier, interval.later, fraction)


def years_at_fraction(interval: SurfaceInterval, fraction: float) -> float:
    span = interval.later.years_to_expiry - interval.earlier.years_to_expiry
    return interval.earlier.years_to_expiry + fraction * span


def record_at_fraction(
    extremes: SurfaceExtremes, interval: SurfaceInterval, grid: ScanGrid, fraction: float
) -> tuple[float, float]:
    interpolated = slice_at_fraction(interval, fraction)
    years = years_at_fraction(interval, fraction)
    point, value = record_durrleman(extremes, interpolated, grid, years)
    record_local_variance(extremes, interpolated, grid, years)
    return point, value


def durrleman_profile(interval: SurfaceInterval, grid: ScanGrid, fraction: float) -> float:
    interpolated = slice_at_fraction(interval, fraction)
    _, value = grid_minimum_with_refinement(
        lambda argument: interpolated_durrleman_value(interpolated, argument), grid
    )
    return value


def refine_durrleman_in_time(
    extremes: SurfaceExtremes, interval: SurfaceInterval, grid: ScanGrid, fraction: float
) -> None:
    step = 1.0 / grid.time_steps_per_interval
    lower = max(fraction - step, 0.0)
    upper = min(fraction + step, 1.0)
    if not upper > lower:
        return
    refined_fraction, _ = refined_minimum_of(
        lambda argument: durrleman_profile(interval, grid, argument), lower, upper
    )
    record_at_fraction(extremes, interval, grid, refined_fraction)


def scan_surface_interval(
    extremes: SurfaceExtremes, interval: SurfaceInterval, grid: ScanGrid, include_lower_knot: bool
) -> None:
    worst_fraction = 0.0
    worst_value = math.inf
    for fraction in scan_times_for_interval(grid.time_steps_per_interval, include_lower_knot):
        _, value = record_at_fraction(extremes, interval, grid, fraction)
        if value < worst_value:
            worst_fraction, worst_value = fraction, value

    refine_durrleman_in_time(extremes, interval, grid, worst_fraction)

    record_time_slope(extremes, slice_at_fraction(interval, 0.0), grid, interval.later.years_to_expiry)
    record_round_trip(extremes, slice_at_fraction(interval, 0.5), grid.log_moneyness)


def scan_svi_surface(
    slices: list[SviSurfaceSlice],
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
    scan_steps: int = DEFAULT_SURFACE_SCAN_STEPS,
    time_steps_per_interval: int = DEFAULT_TIME_STEPS_PER_INTERVAL,
) -> SviSurfaceScan:
    validate_svi_surface(slices)
    if not highest_log_moneyness > lowest_log_moneyness:
        raise InvalidSviSurfaceError("the scan range must be non-empty and increasing")
    if scan_steps < MINIMUM_SURFACE_SCAN_STEPS:
        raise InvalidSviSurfaceError(
            f"scan_steps must be at least {MINIMUM_SURFACE_SCAN_STEPS}, got {scan_steps}"
        )
    if time_steps_per_interval < MINIMUM_TIME_STEPS_PER_INTERVAL:
        raise InvalidSviSurfaceError(
            f"time_steps_per_interval must be at least {MINIMUM_TIME_STEPS_PER_INTERVAL}, "
            f"got {time_steps_per_interval}"
        )

    grid = ScanGrid(
        log_moneyness=moneyness_grid(lowest_log_moneyness, highest_log_moneyness, scan_steps),
        scan_steps=scan_steps,
        time_steps_per_interval=time_steps_per_interval,
    )
    extremes = SurfaceExtremes()
    for index, (earlier, later) in enumerate(pairwise(slices)):
        scan_surface_interval(extremes, SurfaceInterval(earlier, later), grid, index == 0)

    return SviSurfaceScan(
        slice_count=len(slices),
        scan_steps=scan_steps,
        time_steps_per_interval=time_steps_per_interval,
        minimum_durrleman_value=extremes.durrleman_value,
        log_moneyness_at_minimum_durrleman_value=extremes.durrleman_log_moneyness,
        years_to_expiry_at_minimum_durrleman_value=extremes.durrleman_years,
        minimum_risk_neutral_density=extremes.risk_neutral_density,
        minimum_total_variance_time_slope=extremes.time_slope,
        log_moneyness_at_minimum_time_slope=extremes.time_slope_log_moneyness,
        years_to_expiry_at_minimum_time_slope=extremes.time_slope_years,
        minimum_local_variance=extremes.local_variance,
        log_moneyness_at_minimum_local_variance=extremes.local_variance_log_moneyness,
        years_to_expiry_at_minimum_local_variance=extremes.local_variance_years,
        worst_local_variance_round_trip_error=extremes.round_trip_error,
        log_moneyness_at_worst_round_trip_error=extremes.round_trip_log_moneyness,
        round_trip_point_count=extremes.round_trip_points,
        status=surface_status(extremes),
    )
