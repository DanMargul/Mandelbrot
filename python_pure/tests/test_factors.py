from __future__ import annotations

import math

import pytest
from volarb_py.factors import (
    FACTOR_COUNT,
    InvalidFactorInputsError,
    SurfacePoint,
    correlation_of,
    decompose_surface_factors,
    effective_sample_size,
    inner_product,
    lag_one_autocorrelation,
    neutralise_against_loadings,
    orthonormal_basis,
    raw_factor_vectors,
    score_residual,
)

TENORS = (0.0833, 0.25, 0.5, 1.0, 2.0)
STRIKES = (-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.4)
GRID = [SurfacePoint(strike, tenor) for tenor in TENORS for strike in STRIKES]
OBSERVATIONS = 200
ORTHOGONALITY_BUDGET = 1e-10
NEUTRALITY_BUDGET = 1e-12
SINGLE_EXPIRY_FACTORS = 3
DISGUISED_LEVEL_BET = 0.5
EXACT_RECONSTRUCTION = 0.999999
RESIDUAL_FLOOR = 1e-12
DISTURBED_POINT = 3
PERSISTENT_AUTOCORRELATION = 0.8
PERSISTENT_OVERSTATEMENT = 3.0
SERIES_LENGTH = 400


def factor_driven_surfaces(count: int) -> list[list[float]]:
    surfaces = []
    for index in range(count):
        phase = float(index)
        level = 0.04 * math.exp(0.2 * math.sin(phase * 0.31))
        slope = 1.0 + 0.1 * math.cos(phase * 0.17)
        skew = -0.35 + 0.08 * math.sin(phase * 0.23)
        curvature = 0.9 + 0.15 * math.cos(phase * 0.11)
        surfaces.append(
            [
                level * tenor**slope * math.exp(skew * strike + curvature * strike * strike)
                for tenor in TENORS
                for strike in STRIKES
            ]
        )
    return surfaces


def autoregressive_series(count: int, autocorrelation: float) -> list[float]:
    state = 1.0
    value = 0.0
    series = []
    for _ in range(count):
        state = math.fmod(state * 48271.0, 2147483647.0)
        shock = (state / 2147483647.0 - 0.5) * math.sqrt(12.0)
        value = autocorrelation * value + math.sqrt(1.0 - autocorrelation**2) * shock
        series.append(value)
    return series


def test_the_named_basis_is_orthonormal_on_the_grid() -> None:
    basis = orthonormal_basis(raw_factor_vectors(GRID))
    assert len(basis) == FACTOR_COUNT
    for row, one in enumerate(basis):
        for column, other in enumerate(basis):
            expected = 1.0 if row == column else 0.0
            assert inner_product(one, other) == pytest.approx(expected, abs=1e-12)


def test_a_surface_built_only_from_the_factors_leaves_no_residual() -> None:
    decomposition = decompose_surface_factors(GRID, factor_driven_surfaces(120))
    assert decomposition.identified_factor_count == FACTOR_COUNT
    assert decomposition.variance_explained > EXACT_RECONSTRUCTION
    for residual in decomposition.residuals:
        assert max(abs(value) for value in residual) < RESIDUAL_FLOOR


def test_residuals_are_orthogonal_to_the_basis_at_every_observation() -> None:
    decomposition = decompose_surface_factors(GRID, factor_driven_surfaces(60))
    basis = orthonormal_basis(raw_factor_vectors(GRID))
    for residual in decomposition.residuals:
        for vector in basis:
            assert inner_product(residual, vector) == pytest.approx(0.0, abs=ORTHOGONALITY_BUDGET)


def test_a_naive_residual_is_mostly_a_disguised_level_bet() -> None:
    surfaces = factor_driven_surfaces(OBSERVATIONS)
    decomposition = decompose_surface_factors(GRID, surfaces)
    level_series = [entry.level for entry in decomposition.loadings]

    point = 0
    average = sum(surface[point] for surface in surfaces) / len(surfaces)
    naive = [surface[point] - average for surface in surfaces]
    orthogonal = [residual[point] for residual in decomposition.residuals]

    assert abs(correlation_of(naive, level_series)) > DISGUISED_LEVEL_BET
    assert abs(correlation_of(orthogonal, level_series)) < abs(correlation_of(naive, level_series))


def test_time_domain_neutralisation_removes_what_the_cross_section_leaves() -> None:
    surfaces = factor_driven_surfaces(OBSERVATIONS)
    disturbed = [
        [
            value * (1.0 + 0.02 * math.sin(index * 0.31)) if position == DISTURBED_POINT else value
            for position, value in enumerate(surface)
        ]
        for index, surface in enumerate(surfaces)
    ]
    decomposition = decompose_surface_factors(GRID, disturbed)
    series = [residual[DISTURBED_POINT] for residual in decomposition.residuals]
    neutralised = neutralise_against_loadings(
        series, decomposition.loadings, decomposition.identified_factor_count
    )
    assert neutralised.worst_factor_correlation < NEUTRALITY_BUDGET
    assert neutralised.worst_factor_correlation < neutralised.worst_factor_correlation_before


def test_a_single_expiry_grid_cannot_identify_a_term_slope() -> None:
    grid = [SurfacePoint(strike, 0.25) for strike in STRIKES]
    observations = [
        [0.04 * math.exp(-0.3 * strike + 0.02 * index) for strike in STRIKES] for index in range(20)
    ]
    decomposition = decompose_surface_factors(grid, observations)
    assert decomposition.identified_factor_count == SINGLE_EXPIRY_FACTORS
    assert all(entry.curvature == 0.0 for entry in decomposition.loadings)


def test_autocorrelation_inflates_the_standard_error_of_a_z_score() -> None:
    for autocorrelation in (0.0, 0.5, 0.8, 0.9):
        score = score_residual(autoregressive_series(SERIES_LENGTH, autocorrelation))
        persistent = score.lag_one_autocorrelation > 0.0
        assert (score.naive_overstatement > 1.0) == persistent
        assert (score.effective_sample_size < score.observation_count) == persistent
        if persistent:
            assert abs(score.adjusted_z_score) < abs(score.naive_z_score)


def test_a_persistent_residual_is_far_less_significant_than_it_looks() -> None:
    score = score_residual(autoregressive_series(SERIES_LENGTH, 0.9))
    assert score.lag_one_autocorrelation > PERSISTENT_AUTOCORRELATION
    assert score.naive_overstatement > PERSISTENT_OVERSTATEMENT


def test_a_mean_reverting_residual_is_more_significant_than_it_looks() -> None:
    score = score_residual(autoregressive_series(SERIES_LENGTH, -0.6))
    assert score.lag_one_autocorrelation < 0.0
    assert score.effective_sample_size > score.observation_count
    assert score.naive_overstatement < 1.0


def test_the_effective_sample_size_follows_the_autocorrelation() -> None:
    assert effective_sample_size(100, 0.0) == pytest.approx(100.0)
    assert effective_sample_size(100, 0.9) == pytest.approx(100.0 * 0.1 / 1.9)
    assert lag_one_autocorrelation([3.0] * 50) == 0.0


def test_malformed_factor_inputs_are_rejected() -> None:
    with pytest.raises(InvalidFactorInputsError):
        decompose_surface_factors([SurfacePoint(0.0, 1.0)], [[1.0], [1.0]])
    with pytest.raises(InvalidFactorInputsError):
        decompose_surface_factors(GRID, [])
    with pytest.raises(InvalidFactorInputsError):
        decompose_surface_factors(GRID, [[0.04] * len(GRID), [0.04] * 3])
    with pytest.raises(InvalidFactorInputsError):
        decompose_surface_factors(GRID, [[-0.04] * len(GRID), [0.04] * len(GRID)])
    with pytest.raises(InvalidFactorInputsError):
        score_residual([1.0])
    with pytest.raises(InvalidFactorInputsError):
        decompose_surface_factors([SurfacePoint(0.0, -1.0)] * 4, [[0.04] * 4, [0.04] * 4])
