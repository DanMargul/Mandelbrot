from __future__ import annotations

import math
from dataclasses import replace

import pytest
from volarb_py.svi import (
    InvalidSviParametersError,
    SviParameters,
    durrleman_function,
    implied_volatility,
    risk_neutral_density,
    scan_svi_slice,
    total_variance,
    total_variance_first_derivative,
    total_variance_second_derivative,
)

BENIGN = SviParameters(a=0.0002, b=0.018, rho=-0.65, m=0.01, sigma=0.10)
VIOLATING = SviParameters(a=0.0002, b=0.350, rho=-0.85, m=0.00, sigma=0.02)
SCAN_LOWER = -0.6
SCAN_UPPER = 0.6
COARSE_STEPS = 16
DERIVATIVE_BUMP = 1e-5


def grid(steps: int) -> list[float]:
    span = SCAN_UPPER - SCAN_LOWER
    return [SCAN_LOWER + span * index / steps for index in range(steps + 1)]


def test_a_well_shaped_slice_is_free_of_butterfly_arbitrage() -> None:
    scan = scan_svi_slice(BENIGN, SCAN_LOWER, SCAN_UPPER)
    assert scan.status == "arbitrage_free_on_grid"
    assert scan.minimum_durrleman_value > 0.0
    assert scan.minimum_risk_neutral_density > 0.0
    assert scan.minimum_total_variance > 0.0


def test_curvature_too_large_for_the_level_is_caught() -> None:
    scan = scan_svi_slice(VIOLATING, SCAN_LOWER, SCAN_UPPER)
    assert scan.status == "butterfly_arbitrage_found"
    assert scan.minimum_durrleman_value < 0.0
    assert scan.minimum_risk_neutral_density < 0.0


@pytest.mark.parametrize("parameters", [BENIGN, VIOLATING])
def test_the_density_and_the_durrleman_function_share_a_sign(parameters: SviParameters) -> None:
    for point in grid(200):
        assert (durrleman_function(parameters, point) < 0.0) == (
            risk_neutral_density(parameters, point) < 0.0
        )


def test_refinement_finds_a_deeper_minimum_than_a_coarse_grid_alone() -> None:
    scan = scan_svi_slice(VIOLATING, SCAN_LOWER, SCAN_UPPER, COARSE_STEPS)
    grid_minimum = min(durrleman_function(VIOLATING, point) for point in grid(COARSE_STEPS))
    assert scan.minimum_durrleman_value < grid_minimum


def test_the_reported_minimum_never_exceeds_any_grid_value() -> None:
    scan = scan_svi_slice(BENIGN, SCAN_LOWER, SCAN_UPPER, 64)
    for point in grid(64):
        assert scan.minimum_durrleman_value <= durrleman_function(BENIGN, point) + 1e-15


@pytest.mark.parametrize("parameters", [BENIGN, VIOLATING])
def test_the_analytic_derivatives_match_a_numerical_one(parameters: SviParameters) -> None:
    for point in (-0.3, -0.05, 0.0, 0.05, 0.3):
        up = total_variance(parameters, point + DERIVATIVE_BUMP)
        down = total_variance(parameters, point - DERIVATIVE_BUMP)
        centre = total_variance(parameters, point)
        numerical_slope = (up - down) / (2.0 * DERIVATIVE_BUMP)
        numerical_curvature = (up - 2.0 * centre + down) / (DERIVATIVE_BUMP * DERIVATIVE_BUMP)
        assert total_variance_first_derivative(parameters, point) == pytest.approx(
            numerical_slope, rel=1e-6, abs=1e-10
        )
        assert total_variance_second_derivative(parameters, point) == pytest.approx(
            numerical_curvature, rel=1e-3, abs=1e-6
        )


def test_total_variance_and_implied_volatility_agree() -> None:
    years = 0.25
    for point in (-0.3, 0.0, 0.3):
        volatility = implied_volatility(BENIGN, point, years)
        assert volatility * volatility * years == pytest.approx(total_variance(BENIGN, point), rel=1e-14)


def test_the_minimum_of_total_variance_matches_the_closed_form() -> None:
    expected = BENIGN.a + BENIGN.b * BENIGN.sigma * math.sqrt(1.0 - BENIGN.rho * BENIGN.rho)
    scan = scan_svi_slice(BENIGN, -3.0, 3.0, 4096)
    assert scan.minimum_total_variance >= expected
    assert scan.minimum_total_variance == pytest.approx(expected, rel=1e-4)


@pytest.mark.parametrize(
    ("field", "value"),
    [("b", -1.0), ("rho", 1.0), ("rho", -1.0), ("sigma", 0.0), ("sigma", -0.1), ("a", -1.0)],
)
def test_invalid_parameters_are_rejected(field: str, value: float) -> None:
    with pytest.raises(InvalidSviParametersError):
        scan_svi_slice(replace(BENIGN, **{field: value}), SCAN_LOWER, SCAN_UPPER)


def test_an_empty_or_inverted_scan_range_is_rejected() -> None:
    with pytest.raises(InvalidSviParametersError, match="increasing"):
        scan_svi_slice(BENIGN, SCAN_UPPER, SCAN_LOWER)


def test_too_few_scan_steps_are_rejected() -> None:
    with pytest.raises(InvalidSviParametersError, match="scan_steps"):
        scan_svi_slice(BENIGN, SCAN_LOWER, SCAN_UPPER, 1)
