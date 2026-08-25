from __future__ import annotations

import pytest
from volarb_py.svi import SviParameters, durrleman_function, scan_svi_slice, total_variance
from volarb_py.svi_surface import (
    InvalidSviSurfaceError,
    ScanGrid,
    SurfaceInterval,
    SviSurfaceSlice,
    durrleman_profile,
    interpolated_durrleman_value,
    interpolated_local_variance,
    interpolated_slice_between,
    interpolated_time_slope,
    interpolated_total_variance,
    local_variance_from_prices,
    moneyness_grid,
    scan_svi_surface,
)

HEALTHY = [
    SviSurfaceSlice(0.0833, SviParameters(0.0015, 0.030, -0.70, 0.010, 0.10)),
    SviSurfaceSlice(0.2500, SviParameters(0.0060, 0.055, -0.65, 0.015, 0.15)),
    SviSurfaceSlice(0.5000, SviParameters(0.0140, 0.075, -0.60, 0.020, 0.22)),
    SviSurfaceSlice(1.0000, SviParameters(0.0300, 0.100, -0.55, 0.030, 0.32)),
]
CALENDAR_VIOLATION = [
    HEALTHY[0],
    HEALTHY[1],
    SviSurfaceSlice(0.5000, SviParameters(0.0040, 0.055, -0.60, 0.020, 0.22)),
    HEALTHY[3],
]
BUTTERFLY_VIOLATION = [
    HEALTHY[1],
    SviSurfaceSlice(0.7500, SviParameters(0.0002, 0.350, -0.85, 0.000, 0.02)),
]
CLEAN_KNOTS_NEAR_EXPIRY = 0.25
CLEAN_KNOTS_FAR_EXPIRY = 1.00
CLEAN_KNOTS_MARGIN = 0.02
CLEAN_KNOTS_LOWEST = -1.0
CLEAN_KNOTS_HIGHEST = 1.0
DEPTH_GAIN_FROM_REFINEMENT = 1.25
CLEAN_KNOTS_THAT_INTERPOLATE_BADLY = [
    SviSurfaceSlice(CLEAN_KNOTS_NEAR_EXPIRY, SviParameters(-0.127, 0.379, -0.598, 0.088, 0.419)),
    SviSurfaceSlice(CLEAN_KNOTS_FAR_EXPIRY, SviParameters(0.077, 0.396, -0.617, 0.191, 0.079)),
]
LOWEST = -1.5
HIGHEST = 1.5
ROUND_TRIP_BUDGET = 1e-5


def test_a_monotone_term_structure_of_clean_slices_is_arbitrage_free_on_the_grid() -> None:
    scan = scan_svi_surface(HEALTHY, LOWEST, HIGHEST)
    assert scan.status == "arbitrage_free_on_grid"
    assert scan.minimum_durrleman_value > 0.0
    assert scan.minimum_risk_neutral_density > 0.0
    assert scan.minimum_total_variance_time_slope > 0.0
    assert scan.minimum_local_variance > 0.0
    assert scan.slice_count == len(HEALTHY)


def test_a_slice_that_falls_in_total_variance_is_a_calendar_violation() -> None:
    for entry in CALENDAR_VIOLATION:
        assert scan_svi_slice(entry.parameters, LOWEST, HIGHEST).status == "arbitrage_free_on_grid"

    scan = scan_svi_surface(CALENDAR_VIOLATION, LOWEST, HIGHEST)
    assert scan.status == "calendar_arbitrage_found"
    assert scan.minimum_total_variance_time_slope < 0.0
    assert scan.minimum_local_variance < 0.0


def test_a_slice_with_too_much_curvature_is_a_butterfly_violation() -> None:
    scan = scan_svi_surface(BUTTERFLY_VIOLATION, LOWEST, HIGHEST)
    assert scan.status == "butterfly_arbitrage_found"
    assert scan.minimum_durrleman_value < 0.0
    assert scan.minimum_risk_neutral_density < 0.0


def test_an_unchanged_term_structure_sits_exactly_on_the_calendar_boundary() -> None:
    flat = [HEALTHY[1], SviSurfaceSlice(0.75, HEALTHY[1].parameters)]
    scan = scan_svi_surface(flat, LOWEST, HIGHEST)
    assert scan.status == "arbitrage_free_on_grid"
    assert scan.minimum_total_variance_time_slope == 0.0
    assert scan.minimum_local_variance == 0.0


def test_local_variance_is_the_time_slope_over_the_durrleman_function() -> None:
    midpoint = interpolated_slice_between(HEALTHY[1], HEALTHY[2], 0.5)
    for index in range(41):
        point = -1.0 + 2.0 * index / 40
        expected = interpolated_time_slope(midpoint, point) / interpolated_durrleman_value(midpoint, point)
        assert interpolated_local_variance(midpoint, point) == pytest.approx(expected, rel=1e-12)


def test_the_dupire_round_trip_reproduces_the_analytic_local_variance() -> None:
    scan = scan_svi_surface(HEALTHY, LOWEST, HIGHEST)
    assert scan.round_trip_point_count > 0
    assert scan.worst_local_variance_round_trip_error < ROUND_TRIP_BUDGET


@pytest.mark.parametrize("fraction", [0.25, 0.5, 0.75])
def test_the_price_space_route_agrees_with_the_total_variance_route(fraction: float) -> None:
    interpolated = interpolated_slice_between(HEALTHY[2], HEALTHY[3], fraction)
    for index in range(21):
        point = -1.0 + 2.0 * index / 20
        analytic = interpolated_local_variance(interpolated, point)
        assert local_variance_from_prices(interpolated, point) == pytest.approx(
            analytic, rel=ROUND_TRIP_BUDGET
        )


def test_interpolation_reproduces_the_knots_at_the_ends_of_the_interval() -> None:
    lower = interpolated_slice_between(HEALTHY[0], HEALTHY[1], 0.0)
    upper = interpolated_slice_between(HEALTHY[0], HEALTHY[1], 1.0)
    for index in range(21):
        point = -1.0 + 2.0 * index / 20
        assert interpolated_total_variance(lower, point) == total_variance(HEALTHY[0].parameters, point)
        assert interpolated_total_variance(upper, point) == total_variance(HEALTHY[1].parameters, point)
        assert interpolated_durrleman_value(lower, point) == durrleman_function(HEALTHY[0].parameters, point)
        assert interpolated_durrleman_value(upper, point) == durrleman_function(HEALTHY[1].parameters, point)


def test_a_finer_grid_never_reports_a_shallower_violation() -> None:
    coarse = scan_svi_surface(CALENDAR_VIOLATION, LOWEST, HIGHEST, 16, 1)
    fine = scan_svi_surface(CALENDAR_VIOLATION, LOWEST, HIGHEST, 1024, 16)
    assert fine.minimum_total_variance_time_slope <= coarse.minimum_total_variance_time_slope + 1e-12
    assert fine.minimum_durrleman_value <= coarse.minimum_durrleman_value + 1e-9


def test_a_surface_needs_at_least_two_strictly_increasing_expiries() -> None:
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface(HEALTHY[:1], LOWEST, HIGHEST)
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface([HEALTHY[1], HEALTHY[0]], LOWEST, HIGHEST)
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface([HEALTHY[0], HEALTHY[0]], LOWEST, HIGHEST)


def test_an_inverted_or_degenerate_scan_range_is_rejected() -> None:
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface(HEALTHY, HIGHEST, LOWEST)
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface(HEALTHY, LOWEST, HIGHEST, 1)
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface(HEALTHY, LOWEST, HIGHEST, 256, 0)


def test_expiries_closer_than_the_round_trip_step_are_rejected() -> None:
    crowded = [HEALTHY[1], SviSurfaceSlice(HEALTHY[1].years_to_expiry + 1e-6, HEALTHY[2].parameters)]
    with pytest.raises(InvalidSviSurfaceError):
        scan_svi_surface(crowded, LOWEST, HIGHEST)


def test_two_arbitrage_free_knots_can_interpolate_into_a_violation() -> None:
    for entry in CLEAN_KNOTS_THAT_INTERPOLATE_BADLY:
        alone = scan_svi_slice(entry.parameters, CLEAN_KNOTS_LOWEST, CLEAN_KNOTS_HIGHEST, 20000)
        assert alone.status == "arbitrage_free_on_grid"
        assert alone.minimum_durrleman_value > CLEAN_KNOTS_MARGIN

    with_interior = scan_svi_surface(
        CLEAN_KNOTS_THAT_INTERPOLATE_BADLY, CLEAN_KNOTS_LOWEST, CLEAN_KNOTS_HIGHEST, 256, 8
    )
    assert with_interior.status == "butterfly_arbitrage_found"
    assert with_interior.minimum_durrleman_value < 0.0
    assert with_interior.minimum_risk_neutral_density < 0.0
    assert with_interior.minimum_total_variance_time_slope > 0.0
    interior_years = with_interior.years_to_expiry_at_minimum_durrleman_value
    assert CLEAN_KNOTS_NEAR_EXPIRY < interior_years < CLEAN_KNOTS_FAR_EXPIRY


def test_the_reported_depth_does_not_depend_on_either_grid_resolution() -> None:
    for lowest, highest in ((-0.6, 0.6), (CLEAN_KNOTS_LOWEST, CLEAN_KNOTS_HIGHEST)):
        reference = scan_svi_surface(CLEAN_KNOTS_THAT_INTERPOLATE_BADLY, lowest, highest, 8192, 256)
        for scan_steps in (16, 256, 512):
            for time_steps in (1, 4, 8, 16):
                scan = scan_svi_surface(
                    CLEAN_KNOTS_THAT_INTERPOLATE_BADLY, lowest, highest, scan_steps, time_steps
                )
                assert scan.minimum_durrleman_value == pytest.approx(
                    reference.minimum_durrleman_value, abs=1e-15
                )


def test_refining_the_profile_in_maturity_beats_the_grid_alone() -> None:
    interval = SurfaceInterval(*CLEAN_KNOTS_THAT_INTERPOLATE_BADLY)
    grid = ScanGrid(
        log_moneyness=moneyness_grid(CLEAN_KNOTS_LOWEST, CLEAN_KNOTS_HIGHEST, 256),
        scan_steps=256,
        time_steps_per_interval=8,
    )
    on_the_grid = min(durrleman_profile(interval, grid, index / 8) for index in range(9))
    reported = scan_svi_surface(
        CLEAN_KNOTS_THAT_INTERPOLATE_BADLY, CLEAN_KNOTS_LOWEST, CLEAN_KNOTS_HIGHEST, 256, 8
    ).minimum_durrleman_value
    assert reported < on_the_grid
    assert reported / on_the_grid > DEPTH_GAIN_FROM_REFINEMENT
