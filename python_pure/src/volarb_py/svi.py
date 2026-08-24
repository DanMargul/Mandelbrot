from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

SviStatus = Literal[
    "arbitrage_free_on_grid",
    "butterfly_arbitrage_found",
    "invalid_parameters",
]

MINIMUM_TOTAL_VARIANCE: Final[float] = 1e-12
DEFAULT_SCAN_STEPS: Final[int] = 512
MINIMUM_SCAN_STEPS: Final[int] = 2
REFINEMENT_PASSES: Final[int] = 60
GOLDEN_SECTION_RATIO: Final[float] = 0.6180339887498949
BUTTERFLY_TOLERANCE: Final[float] = -1e-12


class InvalidSviParametersError(ValueError):
    pass


@dataclass(frozen=True)
class SviParameters:
    a: float
    b: float
    rho: float
    m: float
    sigma: float


@dataclass(frozen=True)
class SviSliceScan:
    minimum_durrleman_value: float
    log_moneyness_at_minimum: float
    minimum_total_variance: float
    minimum_risk_neutral_density: float
    scan_steps: int
    status: SviStatus


def validate_svi_parameters(parameters: SviParameters) -> None:
    if parameters.b < 0.0:
        raise InvalidSviParametersError(f"b must not be negative, got {parameters.b}")
    if not -1.0 < parameters.rho < 1.0:
        raise InvalidSviParametersError(f"rho must lie strictly inside (-1, 1), got {parameters.rho}")
    if parameters.sigma <= 0.0:
        raise InvalidSviParametersError(f"sigma must be positive, got {parameters.sigma}")
    floor = parameters.a + parameters.b * parameters.sigma * math.sqrt(1.0 - parameters.rho * parameters.rho)
    if floor < 0.0:
        raise InvalidSviParametersError(f"minimum total variance must not be negative, got {floor}")


def total_variance(parameters: SviParameters, log_moneyness: float) -> float:
    centred = log_moneyness - parameters.m
    root = math.sqrt(centred * centred + parameters.sigma * parameters.sigma)
    return parameters.a + parameters.b * (parameters.rho * centred + root)


def total_variance_first_derivative(parameters: SviParameters, log_moneyness: float) -> float:
    centred = log_moneyness - parameters.m
    root = math.sqrt(centred * centred + parameters.sigma * parameters.sigma)
    return parameters.b * (parameters.rho + centred / root)


def total_variance_second_derivative(parameters: SviParameters, log_moneyness: float) -> float:
    centred = log_moneyness - parameters.m
    root = math.sqrt(centred * centred + parameters.sigma * parameters.sigma)
    return parameters.b * parameters.sigma * parameters.sigma / (root * root * root)


def implied_volatility(parameters: SviParameters, log_moneyness: float, years_to_expiry: float) -> float:
    return math.sqrt(max(total_variance(parameters, log_moneyness), 0.0) / years_to_expiry)


def durrleman_function(parameters: SviParameters, log_moneyness: float) -> float:
    variance = max(total_variance(parameters, log_moneyness), MINIMUM_TOTAL_VARIANCE)
    slope = total_variance_first_derivative(parameters, log_moneyness)
    curvature = total_variance_second_derivative(parameters, log_moneyness)
    balance = 1.0 - log_moneyness * slope / (2.0 * variance)
    return balance * balance - 0.25 * slope * slope * (1.0 / variance + 0.25) + 0.5 * curvature


def risk_neutral_density(parameters: SviParameters, log_moneyness: float) -> float:
    variance = max(total_variance(parameters, log_moneyness), MINIMUM_TOTAL_VARIANCE)
    root = math.sqrt(variance)
    standardized = -log_moneyness / root - 0.5 * root
    weight = math.exp(-0.5 * standardized * standardized) / math.sqrt(2.0 * math.pi * variance)
    return durrleman_function(parameters, log_moneyness) * weight


def refined_minimum(parameters: SviParameters, lower: float, upper: float) -> tuple[float, float]:
    left = upper - GOLDEN_SECTION_RATIO * (upper - lower)
    right = lower + GOLDEN_SECTION_RATIO * (upper - lower)
    left_value = durrleman_function(parameters, left)
    right_value = durrleman_function(parameters, right)

    for _ in range(REFINEMENT_PASSES):
        if left_value < right_value:
            upper, right, right_value = right, left, left_value
            left = upper - GOLDEN_SECTION_RATIO * (upper - lower)
            left_value = durrleman_function(parameters, left)
        else:
            lower, left, left_value = left, right, right_value
            right = lower + GOLDEN_SECTION_RATIO * (upper - lower)
            right_value = durrleman_function(parameters, right)

    if left_value <= right_value:
        return left, left_value
    return right, right_value


def scan_svi_slice(
    parameters: SviParameters,
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
    scan_steps: int = DEFAULT_SCAN_STEPS,
) -> SviSliceScan:
    validate_svi_parameters(parameters)
    if not highest_log_moneyness > lowest_log_moneyness:
        raise InvalidSviParametersError("the scan range must be non-empty and increasing")
    if scan_steps < MINIMUM_SCAN_STEPS:
        raise InvalidSviParametersError(f"scan_steps must be at least {MINIMUM_SCAN_STEPS}, got {scan_steps}")

    span = highest_log_moneyness - lowest_log_moneyness
    grid = [lowest_log_moneyness + span * index / scan_steps for index in range(scan_steps + 1)]
    values = [durrleman_function(parameters, point) for point in grid]

    best_index = min(range(len(values)), key=lambda index: (values[index], index))
    neighbourhood_lower = grid[max(best_index - 1, 0)]
    neighbourhood_upper = grid[min(best_index + 1, scan_steps)]
    refined_point, refined_value = refined_minimum(parameters, neighbourhood_lower, neighbourhood_upper)

    if refined_value <= values[best_index]:
        worst_point, worst_value = refined_point, refined_value
    else:
        worst_point, worst_value = grid[best_index], values[best_index]

    return SviSliceScan(
        minimum_durrleman_value=worst_value,
        log_moneyness_at_minimum=worst_point,
        minimum_total_variance=min(total_variance(parameters, point) for point in grid),
        minimum_risk_neutral_density=risk_neutral_density(parameters, worst_point),
        scan_steps=scan_steps,
        status="arbitrage_free_on_grid"
        if worst_value >= BUTTERFLY_TOLERANCE
        else "butterfly_arbitrage_found",
    )
