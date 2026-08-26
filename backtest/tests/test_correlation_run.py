from __future__ import annotations

import math
from pathlib import Path

import pytest
from correlation_run import (
    AT_THE_MONEY,
    DOWNSIDE_MONEYNESS,
    UPSIDE_MONEYNESS,
    DayCorrelation,
    MissingSurfaceError,
    SlicePoint,
    basket_definition,
    day_correlations,
    volatility_at,
)

DATASET = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "datasets" / "synthetic_basket"
QUOTED_EXPIRY = 1
RECOVERY_TOLERANCE = 1e-4
DIRTY_FORMULA_FLOOR = 0.05
SLICE_LEVEL = 0.26
SLICE_SLOPE = -0.30
SLICE_CURVATURE = 0.45
SLICE_MONEYNESS = (-0.30, -0.15, 0.0, 0.15, 0.30)
FIT_TOLERANCE = 1e-12
FULLY_COVERED = 3
WEIGHT_TOTAL_TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def days() -> list[DayCorrelation]:
    return day_correlations(DATASET, QUOTED_EXPIRY)


def exact_slice() -> list[SlicePoint]:
    return [
        SlicePoint(
            moneyness,
            math.log(SLICE_LEVEL) + SLICE_SLOPE * moneyness + SLICE_CURVATURE * moneyness * moneyness,
        )
        for moneyness in SLICE_MONEYNESS
    ]


def test_the_planted_weights_sum_to_one() -> None:
    definition = basket_definition(DATASET)
    assert abs(sum(definition.weights.values()) - 1.0) < WEIGHT_TOTAL_TOLERANCE


def test_the_quadratic_fit_reproduces_an_exactly_quadratic_slice() -> None:
    points = exact_slice()
    for point in points:
        assert volatility_at(points, point.log_moneyness) == pytest.approx(
            math.exp(point.log_volatility), rel=FIT_TOLERANCE
        )


def test_the_fit_needs_enough_strikes_and_distinct_ones() -> None:
    points = exact_slice()
    with pytest.raises(MissingSurfaceError):
        volatility_at(points[:2], AT_THE_MONEY)
    with pytest.raises(MissingSurfaceError):
        volatility_at([points[0], points[0], points[0]], AT_THE_MONEY)


def test_the_planted_correlation_survives_the_whole_pipeline(days: list[DayCorrelation]) -> None:
    for day in days:
        assert day.reports[AT_THE_MONEY].clean_correlation == pytest.approx(
            day.planted, abs=RECOVERY_TOLERANCE
        )


def test_every_day_implies_an_admissible_correlation(days: list[DayCorrelation]) -> None:
    for day in days:
        for report in day.reports.values():
            assert report.is_admissible
            assert not report.exceeds_perfect_correlation


def test_dropping_the_diagonal_is_useless_on_a_basket_this_concentrated(
    days: list[DayCorrelation],
) -> None:
    for day in days:
        report = day.reports[AT_THE_MONEY]
        assert report.dirty_correlation - report.clean_correlation > DIRTY_FORMULA_FLOOR


def test_a_steeper_index_skew_implies_correlation_rising_into_the_downside(
    days: list[DayCorrelation],
) -> None:
    for day in days:
        assert (
            day.reports[DOWNSIDE_MONEYNESS].clean_correlation
            > day.reports[AT_THE_MONEY].clean_correlation
            > day.reports[UPSIDE_MONEYNESS].clean_correlation
        )


def test_extrapolating_the_slice_costs_accuracy_even_when_the_form_is_exact(
    days: list[DayCorrelation],
) -> None:
    def root_mean_square(group: list[DayCorrelation]) -> float:
        errors = [day.reports[AT_THE_MONEY].clean_correlation - day.planted for day in group]
        return math.sqrt(math.fsum(error * error for error in errors) / len(errors))

    covered = [day for day in days if day.targets_inside_quoted_range == FULLY_COVERED]
    reached = [day for day in days if day.targets_inside_quoted_range < FULLY_COVERED]
    assert covered
    assert reached
    assert root_mean_square(reached) > root_mean_square(covered)
