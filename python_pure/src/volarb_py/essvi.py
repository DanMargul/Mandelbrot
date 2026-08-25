from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, Literal

from volarb_py.simplex import SimplexOutcome, minimise_by_simplex
from volarb_py.svi import SviParameters, durrleman_function, total_variance
from volarb_py.svi_calibration import (
    MAXIMUM_CORRELATION,
    MINIMUM_OBSERVATIONS,
    REFERENCE_LOG_MONEYNESS_STEPS,
    SliceObservation,
    bounded_exponential,
    reference_log_moneyness,
)
from volarb_py.svi_surface import (
    DEFAULT_SURFACE_SCAN_STEPS,
    DEFAULT_TIME_STEPS_PER_INTERVAL,
    SviSurfaceSlice,
    scan_svi_surface,
)

EssviStatus = Literal[
    "converged",
    "too_few_slices",
    "too_few_observations",
    "simplex_budget_exhausted",
    "arbitrage_not_eliminated",
]

GLOBAL_PARAMETER_COUNT: Final[int] = 4
MINIMUM_ESSVI_SLICES: Final[int] = 2
BUTTERFLY_PENALTY_WEIGHT: Final[float] = 1e4
CALENDAR_PENALTY_WEIGHT: Final[float] = 1e4
PENALTY_GRID_STEPS: Final[int] = 64
MAXIMUM_POWER_LAW_EXPONENT: Final[float] = 1.0
SEED_CORRELATIONS: Final[tuple[float, ...]] = (-0.7, -0.3, 0.0)
SEED_CURVATURE_FRACTIONS: Final[tuple[float, ...]] = (0.1, 0.3, 0.6)
MAXIMUM_CURVATURE_FRACTION: Final[float] = 0.9999
MINIMUM_CURVATURE_FRACTION: Final[float] = 1e-12
DURRLEMAN_SUFFICIENT_BOUND: Final[float] = 4.0
MINIMUM_SEED_VARIANCE: Final[float] = 1e-8
MINIMUM_SEED_INCREMENT: Final[float] = 1e-10
REFERENCE_POINTS_PER_SLICE: Final[int] = REFERENCE_LOG_MONEYNESS_STEPS + 1


class InvalidEssviInputsError(ValueError):
    pass


@dataclass(frozen=True)
class EssviSliceQuotes:
    years_to_expiry: float
    observations: list[SliceObservation]


@dataclass(frozen=True)
class EssviParameters:
    atm_total_variance: list[float]
    curvature_scale: float
    power_law_exponent: float
    correlation_intercept: float
    correlation_slope: float


@dataclass(frozen=True)
class EssviCalibration:
    parameters: EssviParameters
    slices: list[SviParameters]
    objective: float
    weighted_root_mean_square_residual: float
    simplex_iterations: int
    slice_count: int
    observation_count: int
    fitted_surface: list[float]
    surface_minimum_durrleman_value: float
    surface_minimum_total_variance_time_slope: float
    status: EssviStatus


def bounded_correlation(argument: float) -> float:
    return min(max(math.tanh(argument), -MAXIMUM_CORRELATION), MAXIMUM_CORRELATION)


def atm_total_variance_from_coordinates(coordinates: list[float], slice_count: int) -> list[float]:
    levels: list[float] = []
    running = 0.0
    for index in range(slice_count):
        running += bounded_exponential(coordinates[index])
        levels.append(running)
    return levels


def power_law_exponent_from_coordinate(coordinate: float) -> float:
    return MAXIMUM_POWER_LAW_EXPONENT * 0.5 * (1.0 + math.tanh(coordinate))


def normalized_position(levels: list[float], index: int) -> float:
    span = levels[-1] - levels[0]
    if span <= 0.0:
        return 0.0
    return (levels[index] - levels[0]) / span


def bounded_power(base: float, exponent: float) -> float:
    return bounded_exponential(exponent * math.log(base))


def curvature_fraction_from_coordinate(coordinate: float) -> float:
    fraction = 0.5 * (1.0 + math.tanh(coordinate))
    return min(max(fraction, MINIMUM_CURVATURE_FRACTION), MAXIMUM_CURVATURE_FRACTION)


def maximum_curvature_scale(levels: list[float], correlations: list[float], exponent: float) -> float:
    bound = math.inf
    for level, correlation in zip(levels, correlations, strict=True):
        weight = 1.0 + abs(correlation)
        slope_bound = DURRLEMAN_SUFFICIENT_BOUND / (bounded_power(level, 1.0 - exponent) * weight)
        curvature_bound = math.sqrt(
            DURRLEMAN_SUFFICIENT_BOUND / (bounded_power(level, 1.0 - 2.0 * exponent) * weight)
        )
        bound = min(bound, slope_bound, curvature_bound)
    return bound


def parameters_from_coordinates(coordinates: list[float], slice_count: int) -> EssviParameters:
    levels = atm_total_variance_from_coordinates(coordinates, slice_count)
    exponent = power_law_exponent_from_coordinate(coordinates[slice_count + 1])
    intercept = coordinates[slice_count + 2]
    slope = coordinates[slice_count + 3]
    correlations = [
        bounded_correlation(intercept + slope * normalized_position(levels, index))
        for index in range(slice_count)
    ]
    fraction = curvature_fraction_from_coordinate(coordinates[slice_count])
    return EssviParameters(
        atm_total_variance=levels,
        curvature_scale=fraction * maximum_curvature_scale(levels, correlations, exponent),
        power_law_exponent=exponent,
        correlation_intercept=intercept,
        correlation_slope=slope,
    )


def curvature_at(parameters: EssviParameters, index: int) -> float:
    level = parameters.atm_total_variance[index]
    exponent = math.log(parameters.curvature_scale) - parameters.power_law_exponent * math.log(level)
    return bounded_exponential(exponent)


def correlation_at(parameters: EssviParameters, index: int) -> float:
    position = normalized_position(parameters.atm_total_variance, index)
    return bounded_correlation(parameters.correlation_intercept + parameters.correlation_slope * position)


def svi_slice_from_essvi(level: float, curvature: float, correlation: float) -> SviParameters:
    complement = math.sqrt(1.0 - correlation * correlation)
    return SviParameters(
        a=0.5 * level * (1.0 - correlation * correlation),
        b=0.5 * level * curvature,
        rho=correlation,
        m=-correlation / curvature,
        sigma=complement / curvature,
    )


def slices_from_parameters(parameters: EssviParameters) -> list[SviParameters]:
    return [
        svi_slice_from_essvi(
            parameters.atm_total_variance[index],
            curvature_at(parameters, index),
            correlation_at(parameters, index),
        )
        for index in range(len(parameters.atm_total_variance))
    ]


def penalty_grid(lowest_log_moneyness: float, highest_log_moneyness: float) -> list[float]:
    span = highest_log_moneyness - lowest_log_moneyness
    return [
        lowest_log_moneyness + span * index / PENALTY_GRID_STEPS for index in range(PENALTY_GRID_STEPS + 1)
    ]


def butterfly_penalty(slices: list[SviParameters], grid: list[float]) -> float:
    total = 0.0
    for parameters in slices:
        for point in grid:
            shortfall = -durrleman_function(parameters, point)
            if shortfall > 0.0:
                total += shortfall * shortfall
    return BUTTERFLY_PENALTY_WEIGHT * total


def calendar_penalty(slices: list[SviParameters], grid: list[float]) -> float:
    total = 0.0
    for earlier, later in pairwise(slices):
        for point in grid:
            shortfall = total_variance(earlier, point) - total_variance(later, point)
            if shortfall > 0.0:
                total += shortfall * shortfall
    return CALENDAR_PENALTY_WEIGHT * total


def weighted_squared_residuals(slices: list[SviParameters], quotes: list[EssviSliceQuotes]) -> float:
    total = 0.0
    for parameters, entry in zip(slices, quotes, strict=True):
        for observation in entry.observations:
            residual = total_variance(parameters, observation.log_moneyness) - observation.total_variance
            total += observation.weight * residual * residual
    return total


def calibration_objective(
    coordinates: list[float], quotes: list[EssviSliceQuotes], grid: list[float]
) -> float:
    parameters = parameters_from_coordinates(coordinates, len(quotes))
    slices = slices_from_parameters(parameters)
    return (
        weighted_squared_residuals(slices, quotes)
        + butterfly_penalty(slices, grid)
        + calendar_penalty(slices, grid)
    )


def at_the_money_variance(entry: EssviSliceQuotes) -> float:
    closest = min(entry.observations, key=lambda item: (abs(item.log_moneyness), item.log_moneyness))
    return max(closest.total_variance, MINIMUM_SEED_VARIANCE)


def level_increment_coordinates(quotes: list[EssviSliceQuotes]) -> list[float]:
    levels = [at_the_money_variance(entry) for entry in quotes]
    coordinates = [math.log(levels[0])]
    for earlier, later in pairwise(levels):
        coordinates.append(math.log(max(later - earlier, MINIMUM_SEED_INCREMENT)))
    return coordinates


def seed_coordinates(quotes: list[EssviSliceQuotes]) -> list[list[float]]:
    increments = level_increment_coordinates(quotes)
    seeds: list[list[float]] = []
    for correlation in SEED_CORRELATIONS:
        for fraction in SEED_CURVATURE_FRACTIONS:
            seeds.append(
                [
                    *increments,
                    math.atanh(2.0 * fraction - 1.0),
                    0.0,
                    math.atanh(correlation),
                    0.0,
                ]
            )
    return seeds


def fitted_surface(slices: list[SviParameters]) -> list[float]:
    points = reference_log_moneyness()
    return [total_variance(parameters, point) for parameters in slices for point in points]


def total_observation_count(quotes: list[EssviSliceQuotes]) -> int:
    return sum(len(entry.observations) for entry in quotes)


def unfitted_result(quotes: list[EssviSliceQuotes], status: EssviStatus) -> EssviCalibration:
    return EssviCalibration(
        parameters=EssviParameters([], 0.0, 0.0, 0.0, 0.0),
        slices=[],
        objective=0.0,
        weighted_root_mean_square_residual=0.0,
        simplex_iterations=0,
        slice_count=len(quotes),
        observation_count=total_observation_count(quotes),
        fitted_surface=[],
        surface_minimum_durrleman_value=0.0,
        surface_minimum_total_variance_time_slope=0.0,
        status=status,
    )


def weighted_root_mean_square_residual(slices: list[SviParameters], quotes: list[EssviSliceQuotes]) -> float:
    total_weight = sum(observation.weight for entry in quotes for observation in entry.observations)
    if total_weight <= 0.0:
        return 0.0
    return math.sqrt(weighted_squared_residuals(slices, quotes) / total_weight)


def validate_quotes(quotes: list[EssviSliceQuotes]) -> None:
    for entry in quotes:
        if entry.years_to_expiry <= 0.0:
            raise InvalidEssviInputsError(f"years_to_expiry must be positive, got {entry.years_to_expiry}")
    for earlier, later in pairwise(quotes):
        if later.years_to_expiry <= earlier.years_to_expiry:
            raise InvalidEssviInputsError("slices must be strictly increasing in years_to_expiry")


def calibration_status(settled: bool, surface_status: str) -> EssviStatus:
    if surface_status != "arbitrage_free_on_grid":
        return "arbitrage_not_eliminated"
    if not settled:
        return "simplex_budget_exhausted"
    return "converged"


def calibrate_essvi_surface(
    quotes: list[EssviSliceQuotes], lowest_log_moneyness: float, highest_log_moneyness: float
) -> EssviCalibration:
    if len(quotes) < MINIMUM_ESSVI_SLICES:
        return unfitted_result(quotes, "too_few_slices")
    validate_quotes(quotes)
    if any(len(entry.observations) < MINIMUM_OBSERVATIONS for entry in quotes):
        return unfitted_result(quotes, "too_few_observations")
    if not highest_log_moneyness > lowest_log_moneyness:
        raise InvalidEssviInputsError("the penalty range must be non-empty and increasing")

    grid = penalty_grid(lowest_log_moneyness, highest_log_moneyness)
    best_outcome: SimplexOutcome | None = None
    total_iterations = 0
    for seed in seed_coordinates(quotes):
        outcome = minimise_by_simplex(
            lambda coordinates: calibration_objective(coordinates, quotes, grid), seed
        )
        total_iterations += outcome.iterations
        if best_outcome is None or outcome.value < best_outcome.value:
            best_outcome = outcome

    assert best_outcome is not None
    parameters = parameters_from_coordinates(best_outcome.coordinates, len(quotes))
    slices = slices_from_parameters(parameters)
    scan = scan_svi_surface(
        [
            SviSurfaceSlice(entry.years_to_expiry, fitted)
            for entry, fitted in zip(quotes, slices, strict=True)
        ],
        lowest_log_moneyness,
        highest_log_moneyness,
        DEFAULT_SURFACE_SCAN_STEPS,
        DEFAULT_TIME_STEPS_PER_INTERVAL,
    )
    return EssviCalibration(
        parameters=parameters,
        slices=slices,
        objective=best_outcome.value,
        weighted_root_mean_square_residual=weighted_root_mean_square_residual(slices, quotes),
        simplex_iterations=total_iterations,
        slice_count=len(quotes),
        observation_count=total_observation_count(quotes),
        fitted_surface=fitted_surface(slices),
        surface_minimum_durrleman_value=scan.minimum_durrleman_value,
        surface_minimum_total_variance_time_slope=scan.minimum_total_variance_time_slope,
        status=calibration_status(best_outcome.settled, scan.status),
    )
