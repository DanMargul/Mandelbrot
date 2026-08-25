from __future__ import annotations

from itertools import pairwise

import pytest
from volarb_py.essvi import (
    EssviParameters,
    EssviSliceQuotes,
    InvalidEssviInputsError,
    calibrate_essvi_surface,
    correlation_at,
    curvature_at,
    maximum_curvature_scale,
    parameters_from_coordinates,
    slices_from_parameters,
    svi_slice_from_essvi,
)
from volarb_py.svi import SviParameters, total_variance, validate_svi_parameters
from volarb_py.svi_calibration import SliceObservation

EXPIRIES = [0.0833, 0.25, 0.5, 1.0]
TRUTH = EssviParameters(
    atm_total_variance=[0.0033, 0.0100, 0.0200, 0.0400],
    curvature_scale=0.35,
    power_law_exponent=0.45,
    correlation_intercept=-0.85,
    correlation_slope=0.30,
)
HEALTHY = [
    SviParameters(0.0015, 0.030, -0.70, 0.010, 0.10),
    SviParameters(0.0060, 0.055, -0.65, 0.015, 0.15),
    SviParameters(0.0140, 0.075, -0.60, 0.020, 0.22),
    SviParameters(0.0300, 0.100, -0.55, 0.030, 0.32),
]
CALENDAR_VIOLATING = [
    HEALTHY[0],
    HEALTHY[1],
    SviParameters(0.0040, 0.055, -0.60, 0.020, 0.22),
    HEALTHY[3],
]
BUTTERFLY_VIOLATING = [
    HEALTHY[0],
    HEALTHY[1],
    SviParameters(0.0002, 0.350, -0.85, 0.000, 0.02),
    HEALTHY[3],
]
LOWEST = -0.6
HIGHEST = 0.6
EXACT_REFIT_BUDGET = 1e-10


def quotes_from(slices: list[SviParameters]) -> list[EssviSliceQuotes]:
    return [
        EssviSliceQuotes(
            years_to_expiry=years,
            observations=[
                SliceObservation(
                    log_moneyness=-0.4 + 0.8 * index / 20,
                    total_variance=total_variance(parameters, -0.4 + 0.8 * index / 20),
                    weight=1.0,
                )
                for index in range(21)
            ],
        )
        for years, parameters in zip(EXPIRIES, slices, strict=True)
    ]


def test_an_essvi_surface_is_recovered_from_its_own_samples() -> None:
    fit = calibrate_essvi_surface(quotes_from(slices_from_parameters(TRUTH)), LOWEST, HIGHEST)
    assert fit.status == "converged"
    assert fit.weighted_root_mean_square_residual < EXACT_REFIT_BUDGET
    assert fit.parameters.curvature_scale == pytest.approx(TRUTH.curvature_scale, rel=1e-6)
    assert fit.parameters.power_law_exponent == pytest.approx(TRUTH.power_law_exponent, rel=1e-6)
    assert fit.parameters.correlation_intercept == pytest.approx(TRUTH.correlation_intercept, rel=1e-6)
    assert fit.parameters.correlation_slope == pytest.approx(TRUTH.correlation_slope, rel=1e-6)
    for fitted, expected in zip(fit.parameters.atm_total_variance, TRUTH.atm_total_variance, strict=True):
        assert fitted == pytest.approx(expected, rel=1e-6)


def test_the_fitted_surface_passes_the_acceptance_test() -> None:
    fit = calibrate_essvi_surface(quotes_from(HEALTHY), LOWEST, HIGHEST)
    assert fit.status == "converged"
    assert fit.surface_minimum_durrleman_value > 0.0
    assert fit.surface_minimum_total_variance_time_slope > 0.0
    assert len(fit.slices) == len(EXPIRIES)


def test_a_calendar_violation_in_the_data_is_repaired_by_the_fit() -> None:
    fit = calibrate_essvi_surface(quotes_from(CALENDAR_VIOLATING), LOWEST, HIGHEST)
    assert fit.status == "converged"
    assert fit.surface_minimum_total_variance_time_slope > 0.0
    assert fit.surface_minimum_durrleman_value > 0.0


def test_a_fit_that_cannot_eliminate_arbitrage_says_so() -> None:
    fit = calibrate_essvi_surface(quotes_from(BUTTERFLY_VIOLATING), LOWEST, HIGHEST)
    assert fit.status == "arbitrage_not_eliminated"
    assert fit.surface_minimum_durrleman_value < 0.0 or fit.surface_minimum_total_variance_time_slope < 0.0


def test_the_atm_total_variance_is_increasing_by_construction() -> None:
    for coordinates in ([0.0] * 8, [5.0, -3.0, 2.0, -8.0, 1.0, 0.0, 0.0, 0.0], [-40.0] * 8):
        parameters = parameters_from_coordinates(coordinates, 4)
        levels = parameters.atm_total_variance
        assert all(later > earlier for earlier, later in pairwise(levels))
        assert levels[0] > 0.0


def test_every_reachable_coordinate_maps_to_a_valid_slice() -> None:
    for extreme in (-1e4, -40.0, -1.0, 0.0, 1.0, 40.0, 1e4):
        coordinates = [extreme] * 8
        parameters = parameters_from_coordinates(coordinates, 4)
        for fitted in slices_from_parameters(parameters):
            validate_svi_parameters(fitted)


def test_the_slice_map_puts_the_atm_total_variance_where_it_belongs() -> None:
    for level in (1e-6, 1e-3, 0.04, 1.0, 10.0):
        for correlation in (-0.9999, -0.5, 0.0, 0.5, 0.9999):
            for curvature in (1e-4, 0.35, 50.0):
                fitted = svi_slice_from_essvi(level, curvature, correlation)
                validate_svi_parameters(fitted)
                assert total_variance(fitted, 0.0) == pytest.approx(level, rel=1e-12)


def test_the_curvature_bound_keeps_every_reachable_slice_butterfly_free() -> None:
    levels = [0.0033, 0.0100, 0.0200, 0.0400]
    correlations = [-0.9, -0.6, -0.3, 0.0]
    for exponent in (0.0, 0.25, 0.5, 0.75, 1.0):
        bound = maximum_curvature_scale(levels, correlations, exponent)
        for level, correlation in zip(levels, correlations, strict=True):
            curvature = bound * level**-exponent
            assert level * curvature * (1.0 + abs(correlation)) <= 4.0 + 1e-12
            assert level * curvature * curvature * (1.0 + abs(correlation)) <= 4.0 + 1e-12


def test_the_reported_parameters_reproduce_the_reported_slices() -> None:
    fit = calibrate_essvi_surface(quotes_from(HEALTHY), LOWEST, HIGHEST)
    for index, fitted in enumerate(fit.slices):
        expected = svi_slice_from_essvi(
            fit.parameters.atm_total_variance[index],
            curvature_at(fit.parameters, index),
            correlation_at(fit.parameters, index),
        )
        assert fitted == expected


def test_too_few_slices_or_observations_is_reported_rather_than_fitted() -> None:
    full = quotes_from(HEALTHY)
    assert calibrate_essvi_surface(full[:1], LOWEST, HIGHEST).status == "too_few_slices"

    sparse = [full[0], EssviSliceQuotes(full[1].years_to_expiry, full[1].observations[:3])]
    assert calibrate_essvi_surface(sparse, LOWEST, HIGHEST).status == "too_few_observations"


def test_expiries_out_of_order_or_an_inverted_range_are_rejected() -> None:
    full = quotes_from(HEALTHY)
    with pytest.raises(InvalidEssviInputsError):
        calibrate_essvi_surface([full[1], full[0]], LOWEST, HIGHEST)
    with pytest.raises(InvalidEssviInputsError):
        calibrate_essvi_surface(full[:2], HIGHEST, LOWEST)
