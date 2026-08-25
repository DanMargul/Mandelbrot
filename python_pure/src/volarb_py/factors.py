from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

FACTOR_COUNT: Final[int] = 4
MINIMUM_OBSERVATIONS: Final[int] = 2
MINIMUM_GRID_POINTS: Final[int] = 4
MINIMUM_BASIS_NORM: Final[float] = 1e-10
MINIMUM_TOTAL_VARIANCE: Final[float] = 1e-12
MINIMUM_STANDARD_DEVIATION: Final[float] = 1e-12
MAXIMUM_AUTOCORRELATION: Final[float] = 0.99
GRAM_SCHMIDT_PASSES: Final[int] = 2


class InvalidFactorInputsError(ValueError):
    pass


@dataclass(frozen=True)
class SurfacePoint:
    log_moneyness: float
    years_to_expiry: float


@dataclass(frozen=True)
class FactorLoadings:
    level: float
    term_slope: float
    skew: float
    curvature: float


@dataclass(frozen=True)
class FactorDecomposition:
    observation_count: int
    grid_point_count: int
    identified_factor_count: int
    loadings: list[FactorLoadings]
    residuals: list[list[float]]
    variance_explained: float
    residual_share: float
    worst_residual_factor_correlation: float


@dataclass(frozen=True)
class NeutralisedResidual:
    values: list[float]
    worst_factor_correlation: float
    worst_factor_correlation_before: float


@dataclass(frozen=True)
class ResidualScore:
    observation_count: int
    mean: float
    standard_deviation: float
    lag_one_autocorrelation: float
    effective_sample_size: float
    naive_z_score: float
    adjusted_z_score: float
    naive_overstatement: float
    residual_is_degenerate: bool


def validate_grid(grid: list[SurfacePoint]) -> None:
    if len(grid) < MINIMUM_GRID_POINTS:
        raise InvalidFactorInputsError(f"a grid needs at least {MINIMUM_GRID_POINTS} points, got {len(grid)}")
    for point in grid:
        if point.years_to_expiry <= 0.0:
            raise InvalidFactorInputsError(f"years_to_expiry must be positive, got {point.years_to_expiry}")


def validate_observations(grid: list[SurfacePoint], observations: list[list[float]]) -> None:
    if len(observations) < MINIMUM_OBSERVATIONS:
        raise InvalidFactorInputsError(
            f"a decomposition needs at least {MINIMUM_OBSERVATIONS} observations, got {len(observations)}"
        )
    for observation in observations:
        if len(observation) != len(grid):
            raise InvalidFactorInputsError(
                f"an observation has {len(observation)} values against {len(grid)} grid points"
            )
        for value in observation:
            if value <= 0.0:
                raise InvalidFactorInputsError(f"total variance must be positive, got {value}")


def log_total_variance(observation: list[float]) -> list[float]:
    return [math.log(max(value, MINIMUM_TOTAL_VARIANCE)) for value in observation]


def raw_factor_vectors(grid: list[SurfacePoint]) -> list[list[float]]:
    return [
        [1.0 for _ in grid],
        [math.log(point.years_to_expiry) for point in grid],
        [point.log_moneyness for point in grid],
        [point.log_moneyness * point.log_moneyness for point in grid],
    ]


def accumulated(values: list[float]) -> float:
    total = 0.0
    for value in values:
        total += value
    return total


def inner_product(left: list[float], right: list[float]) -> float:
    return accumulated([one * other for one, other in zip(left, right, strict=True)])


def norm_of(vector: list[float]) -> float:
    return math.sqrt(max(inner_product(vector, vector), 0.0))


def subtract_projection(vector: list[float], basis: list[float]) -> list[float]:
    overlap = inner_product(vector, basis)
    return [value - overlap * component for value, component in zip(vector, basis, strict=True)]


def orthonormal_basis(vectors: list[list[float]]) -> list[list[float]]:
    basis: list[list[float]] = []
    for vector in vectors:
        candidate = list(vector)
        for _ in range(GRAM_SCHMIDT_PASSES):
            for existing in basis:
                candidate = subtract_projection(candidate, existing)
        length = norm_of(candidate)
        if length < MINIMUM_BASIS_NORM:
            continue
        basis.append([value / length for value in candidate])
    return basis


def loadings_from(coefficients: list[float], identified: int) -> FactorLoadings:
    padded = [*coefficients, *([0.0] * (FACTOR_COUNT - identified))]
    return FactorLoadings(level=padded[0], term_slope=padded[1], skew=padded[2], curvature=padded[3])


def project_onto(basis: list[list[float]], values: list[float]) -> list[float]:
    return [inner_product(values, vector) for vector in basis]


def reconstruct_from(basis: list[list[float]], coefficients: list[float]) -> list[float]:
    return [
        accumulated(
            [coefficient * vector[index] for coefficient, vector in zip(coefficients, basis, strict=True)]
        )
        for index in range(len(basis[0]))
    ]


def centred(values: list[float]) -> list[float]:
    mean = accumulated(values) / len(values)
    return [value - mean for value in values]


def correlation_of(left: list[float], right: list[float]) -> float:
    one = centred(left)
    other = centred(right)
    scale = norm_of(one) * norm_of(other)
    if scale < MINIMUM_BASIS_NORM:
        return 0.0
    return inner_product(one, other) / scale


def worst_correlation_with_factors(
    residuals: list[list[float]], loadings: list[FactorLoadings], identified: int
) -> float:
    columns = loading_columns(loadings, identified)
    return max(
        worst_correlation_against([residual[index] for residual in residuals], columns)
        for index in range(len(residuals[0]))
    )


def decompose_surface_factors(
    grid: list[SurfacePoint], observations: list[list[float]]
) -> FactorDecomposition:
    validate_grid(grid)
    validate_observations(grid, observations)

    basis = orthonormal_basis(raw_factor_vectors(grid))
    if not basis:
        raise InvalidFactorInputsError("no factor direction is identifiable on this grid")

    loadings: list[FactorLoadings] = []
    residuals: list[list[float]] = []
    total_energy = 0.0
    residual_energy = 0.0
    for observation in observations:
        values = log_total_variance(observation)
        coefficients = project_onto(basis, values)
        fitted = reconstruct_from(basis, coefficients)
        residual = [value - approximation for value, approximation in zip(values, fitted, strict=True)]
        loadings.append(loadings_from(coefficients, len(basis)))
        residuals.append(residual)
        total_energy += inner_product(values, values)
        residual_energy += inner_product(residual, residual)

    share = residual_energy / total_energy if total_energy > 0.0 else 0.0
    return FactorDecomposition(
        observation_count=len(observations),
        grid_point_count=len(grid),
        identified_factor_count=len(basis),
        loadings=loadings,
        residuals=residuals,
        variance_explained=1.0 - share,
        residual_share=share,
        worst_residual_factor_correlation=worst_correlation_with_factors(residuals, loadings, len(basis)),
    )


def loading_columns(loadings: list[FactorLoadings], identified: int) -> list[list[float]]:
    return [
        [entry.level for entry in loadings],
        [entry.term_slope for entry in loadings],
        [entry.skew for entry in loadings],
        [entry.curvature for entry in loadings],
    ][:identified]


def worst_correlation_against(series: list[float], columns: list[list[float]]) -> float:
    return max((abs(correlation_of(series, column)) for column in columns), default=0.0)


def neutralise_against_loadings(
    series: list[float], loadings: list[FactorLoadings], identified: int
) -> NeutralisedResidual:
    if len(series) != len(loadings):
        raise InvalidFactorInputsError(
            f"the series has {len(series)} points against {len(loadings)} observations"
        )
    columns = loading_columns(loadings, identified)
    design = [[1.0 for _ in series], *columns]
    basis = orthonormal_basis(design)
    fitted = reconstruct_from(basis, project_onto(basis, series))
    neutralised = [value - approximation for value, approximation in zip(series, fitted, strict=True)]
    return NeutralisedResidual(
        values=neutralised,
        worst_factor_correlation=worst_correlation_against(neutralised, columns),
        worst_factor_correlation_before=worst_correlation_against(series, columns),
    )


def lag_one_autocorrelation(series: list[float]) -> float:
    if len(series) < MINIMUM_OBSERVATIONS:
        raise InvalidFactorInputsError(
            f"an autocorrelation needs at least {MINIMUM_OBSERVATIONS} points, got {len(series)}"
        )
    deviations = centred(series)
    variance = inner_product(deviations, deviations)
    if variance < MINIMUM_BASIS_NORM:
        return 0.0
    covariance = accumulated([earlier * later for earlier, later in pairwise(deviations)])
    return min(max(covariance / variance, -MAXIMUM_AUTOCORRELATION), MAXIMUM_AUTOCORRELATION)


def effective_sample_size(count: int, autocorrelation: float) -> float:
    return count * (1.0 - autocorrelation) / (1.0 + autocorrelation)


def score_residual(series: list[float]) -> ResidualScore:
    if len(series) < MINIMUM_OBSERVATIONS:
        raise InvalidFactorInputsError(
            f"a score needs at least {MINIMUM_OBSERVATIONS} points, got {len(series)}"
        )
    count = len(series)
    mean = accumulated(series) / count
    deviations = centred(series)
    variance = inner_product(deviations, deviations) / (count - 1)
    deviation = math.sqrt(max(variance, 0.0))
    if deviation < MINIMUM_STANDARD_DEVIATION:
        return ResidualScore(
            observation_count=count,
            mean=mean,
            standard_deviation=deviation,
            lag_one_autocorrelation=0.0,
            effective_sample_size=float(count),
            naive_z_score=0.0,
            adjusted_z_score=0.0,
            naive_overstatement=1.0,
            residual_is_degenerate=True,
        )

    autocorrelation = lag_one_autocorrelation(series)
    effective = max(effective_sample_size(count, autocorrelation), 1.0)
    inflation = math.sqrt(count / effective)
    naive = (series[-1] - mean) / deviation
    return ResidualScore(
        observation_count=count,
        mean=mean,
        standard_deviation=deviation,
        lag_one_autocorrelation=autocorrelation,
        effective_sample_size=effective,
        naive_z_score=naive,
        adjusted_z_score=naive / inflation,
        naive_overstatement=inflation,
        residual_is_degenerate=False,
    )
