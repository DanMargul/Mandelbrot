from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

from volarb_py.simplex import SimplexOutcome, minimise_by_simplex
from volarb_py.svi import SviParameters, durrleman_function, total_variance

SviCalibrationStatus = Literal[
    "converged",
    "too_few_observations",
    "simplex_budget_exhausted",
]

PARAMETER_COUNT: Final[int] = 5
MINIMUM_OBSERVATIONS: Final[int] = 5
BUTTERFLY_PENALTY_WEIGHT: Final[float] = 1e4
PENALTY_GRID_STEPS: Final[int] = 64
MAXIMUM_LOG_PARAMETER: Final[float] = 30.0
MAXIMUM_CORRELATION: Final[float] = 0.9999
REFERENCE_LOG_MONEYNESS_LOWEST: Final[float] = -0.4
REFERENCE_LOG_MONEYNESS_HIGHEST: Final[float] = 0.4
REFERENCE_LOG_MONEYNESS_STEPS: Final[int] = 16
SEED_CORRELATIONS: Final[tuple[float, ...]] = (-0.7, -0.3, 0.0, 0.3)
SEED_WIDTH_MULTIPLIERS: Final[tuple[float, ...]] = (0.5, 1.0, 2.0)


class InvalidCalibrationInputsError(ValueError):
    pass


@dataclass(frozen=True)
class SliceObservation:
    log_moneyness: float
    total_variance: float
    weight: float


@dataclass(frozen=True)
class SviCalibration:
    parameters: SviParameters
    objective: float
    weighted_root_mean_square_residual: float
    simplex_iterations: int
    observation_count: int
    fitted_curve: list[float]
    status: SviCalibrationStatus


def bounded_exponential(coordinate: float) -> float:
    return math.exp(min(max(coordinate, -MAXIMUM_LOG_PARAMETER), MAXIMUM_LOG_PARAMETER))


def reference_log_moneyness() -> list[float]:
    span = REFERENCE_LOG_MONEYNESS_HIGHEST - REFERENCE_LOG_MONEYNESS_LOWEST
    return [
        REFERENCE_LOG_MONEYNESS_LOWEST + span * index / REFERENCE_LOG_MONEYNESS_STEPS
        for index in range(REFERENCE_LOG_MONEYNESS_STEPS + 1)
    ]


def fitted_curve(parameters: SviParameters) -> list[float]:
    return [total_variance(parameters, point) for point in reference_log_moneyness()]


def parameters_from_coordinates(coordinates: list[float]) -> SviParameters:
    minimum_variance = bounded_exponential(coordinates[0])
    b = bounded_exponential(coordinates[1])
    rho = min(max(math.tanh(coordinates[2]), -MAXIMUM_CORRELATION), MAXIMUM_CORRELATION)
    m = coordinates[3]
    sigma = bounded_exponential(coordinates[4])
    a = minimum_variance - b * sigma * math.sqrt(1.0 - rho * rho)
    return SviParameters(a=a, b=b, rho=rho, m=m, sigma=sigma)


def weighted_squared_residuals(parameters: SviParameters, observations: list[SliceObservation]) -> float:
    total = 0.0
    for observation in observations:
        residual = total_variance(parameters, observation.log_moneyness) - observation.total_variance
        total += observation.weight * residual * residual
    return total


def butterfly_penalty(
    parameters: SviParameters, lowest_log_moneyness: float, highest_log_moneyness: float
) -> float:
    span = highest_log_moneyness - lowest_log_moneyness
    total = 0.0
    for index in range(PENALTY_GRID_STEPS + 1):
        point = lowest_log_moneyness + span * index / PENALTY_GRID_STEPS
        shortfall = -durrleman_function(parameters, point)
        if shortfall > 0.0:
            total += shortfall * shortfall
    return BUTTERFLY_PENALTY_WEIGHT * total


def calibration_objective(
    coordinates: list[float],
    observations: list[SliceObservation],
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
) -> float:
    parameters = parameters_from_coordinates(coordinates)
    return weighted_squared_residuals(parameters, observations) + butterfly_penalty(
        parameters, lowest_log_moneyness, highest_log_moneyness
    )


def seed_coordinates(observations: list[SliceObservation]) -> list[list[float]]:
    variances = [observation.total_variance for observation in observations]
    moneyness = [observation.log_moneyness for observation in observations]
    smallest = max(min(variances), 1e-8)
    at_minimum = moneyness[variances.index(min(variances))]
    width = max(max(moneyness) - min(moneyness), 1e-3)
    slope = (max(variances) - smallest) / width

    seeds: list[list[float]] = []
    for correlation in SEED_CORRELATIONS:
        for multiplier in SEED_WIDTH_MULTIPLIERS:
            seeds.append(
                [
                    math.log(smallest),
                    math.log(max(slope, 1e-6)),
                    math.atanh(correlation),
                    at_minimum,
                    math.log(width * multiplier * 0.25),
                ]
            )
    return seeds


def weighted_root_mean_square_residual(
    parameters: SviParameters, observations: list[SliceObservation]
) -> float:
    total_weight = sum(observation.weight for observation in observations)
    if total_weight <= 0.0:
        return 0.0
    return math.sqrt(weighted_squared_residuals(parameters, observations) / total_weight)


def calibrate_svi_slice(
    observations: list[SliceObservation],
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
) -> SviCalibration:
    if len(observations) < MINIMUM_OBSERVATIONS:
        return SviCalibration(
            parameters=SviParameters(0.0, 0.0, 0.0, 0.0, 1.0),
            objective=0.0,
            weighted_root_mean_square_residual=0.0,
            simplex_iterations=0,
            observation_count=len(observations),
            fitted_curve=[0.0] * (REFERENCE_LOG_MONEYNESS_STEPS + 1),
            status="too_few_observations",
        )
    if not highest_log_moneyness > lowest_log_moneyness:
        raise InvalidCalibrationInputsError("the penalty range must be non-empty and increasing")

    best_outcome: SimplexOutcome | None = None
    total_iterations = 0
    for seed in seed_coordinates(observations):
        outcome = minimise_by_simplex(
            lambda coordinates: calibration_objective(
                coordinates, observations, lowest_log_moneyness, highest_log_moneyness
            ),
            seed,
        )
        total_iterations += outcome.iterations
        if best_outcome is None or outcome.value < best_outcome.value:
            best_outcome = outcome

    assert best_outcome is not None
    parameters = parameters_from_coordinates(best_outcome.coordinates)
    return SviCalibration(
        parameters=parameters,
        objective=best_outcome.value,
        weighted_root_mean_square_residual=weighted_root_mean_square_residual(parameters, observations),
        simplex_iterations=total_iterations,
        observation_count=len(observations),
        fitted_curve=fitted_curve(parameters),
        status="converged" if best_outcome.settled else "simplex_budget_exhausted",
    )
