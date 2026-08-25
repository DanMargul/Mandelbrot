from __future__ import annotations

import pytest
from volarb_py.svi import SviParameters, scan_svi_slice, total_variance
from volarb_py.svi_calibration import (
    MINIMUM_OBSERVATIONS,
    REFERENCE_LOG_MONEYNESS_STEPS,
    SliceObservation,
    calibrate_svi_slice,
    parameters_from_coordinates,
)

TRUTH = SviParameters(a=0.0002, b=0.018, rho=-0.65, m=0.01, sigma=0.10)
FLAT = SviParameters(a=0.0400, b=0.002, rho=-0.10, m=0.00, sigma=0.50)
PENALTY_LOWER = -0.6
PENALTY_UPPER = 0.6
EXTREME_COORDINATE = 10_000.0


def sample(parameters: SviParameters, lowest: float, highest: float, count: int) -> list[SliceObservation]:
    return [
        SliceObservation(
            log_moneyness=lowest + (highest - lowest) * index / (count - 1),
            total_variance=total_variance(parameters, lowest + (highest - lowest) * index / (count - 1)),
            weight=1.0,
        )
        for index in range(count)
    ]


@pytest.mark.parametrize("parameters", [TRUTH, FLAT])
def test_calibration_refits_a_slice_it_was_sampled_from(parameters: SviParameters) -> None:
    observations = sample(parameters, -0.30, 0.30, 21)
    calibration = calibrate_svi_slice(observations, PENALTY_LOWER, PENALTY_UPPER)
    assert calibration.status == "converged"
    for observation in observations:
        fitted = total_variance(calibration.parameters, observation.log_moneyness)
        assert fitted == pytest.approx(observation.total_variance, rel=1e-6)


@pytest.mark.parametrize("parameters", [TRUTH, FLAT])
def test_a_calibrated_slice_passes_the_arbitrage_scan(parameters: SviParameters) -> None:
    calibration = calibrate_svi_slice(sample(parameters, -0.30, 0.30, 21), PENALTY_LOWER, PENALTY_UPPER)
    scan = scan_svi_slice(calibration.parameters, PENALTY_LOWER, PENALTY_UPPER)
    assert scan.status == "arbitrage_free_on_grid"


def test_the_fitted_parameters_are_valid_by_construction() -> None:
    calibration = calibrate_svi_slice(sample(TRUTH, -0.30, 0.30, 21), PENALTY_LOWER, PENALTY_UPPER)
    fitted = calibration.parameters
    assert fitted.b >= 0.0
    assert abs(fitted.rho) < 1.0
    assert fitted.sigma > 0.0


def test_the_coordinate_transform_cannot_produce_an_invalid_slice() -> None:
    for coordinate in (-EXTREME_COORDINATE, 0.0, EXTREME_COORDINATE):
        parameters = parameters_from_coordinates([coordinate] * 5)
        assert parameters.b >= 0.0
        assert abs(parameters.rho) < 1.0
        assert parameters.sigma > 0.0


def test_an_extreme_coordinate_does_not_overflow() -> None:
    observations = sample(TRUTH, -0.30, 0.30, 21)
    calibration = calibrate_svi_slice(observations, PENALTY_LOWER, PENALTY_UPPER)
    assert calibration.objective >= 0.0
    assert calibration.objective == calibration.objective


def test_the_fitted_curve_has_the_agreed_length() -> None:
    calibration = calibrate_svi_slice(sample(TRUTH, -0.30, 0.30, 21), PENALTY_LOWER, PENALTY_UPPER)
    assert len(calibration.fitted_curve) == REFERENCE_LOG_MONEYNESS_STEPS + 1
    assert all(value > 0.0 for value in calibration.fitted_curve)


def test_too_few_observations_is_reported_rather_than_fitted() -> None:
    calibration = calibrate_svi_slice(
        sample(TRUTH, -0.1, 0.1, MINIMUM_OBSERVATIONS - 1), PENALTY_LOWER, PENALTY_UPPER
    )
    assert calibration.status == "too_few_observations"
    assert calibration.simplex_iterations == 0
