from __future__ import annotations

import math
from statistics import (
    InvalidStatisticsInputsError,
    SharpeSample,
    deflated_sharpe_ratio,
    expected_maximum_sharpe_ratio,
    sharpe_ratio_needed_for,
    sharpe_standard_error,
    standard_normal_upper_tail,
    upper_tail_quantile,
)

import pytest

TRADING_DAYS = 252
THREE_YEARS = TRADING_DAYS * 3
NULL_SAMPLE = SharpeSample(0.0, THREE_YEARS, -0.5, 3.0)


@pytest.mark.parametrize("tail", [0.4, 0.1, 0.01, 1e-3, 1e-6, 1e-9, 1e-12, 1e-30, 1e-100, 1e-200])
def test_the_quantile_inverts_the_tail_it_came_from(tail: float) -> None:
    assert standard_normal_upper_tail(upper_tail_quantile(tail)) == pytest.approx(tail, rel=1e-12)


def test_the_quantile_is_symmetric_about_the_median() -> None:
    for tail in (0.1, 0.25, 0.4):
        assert upper_tail_quantile(tail) == pytest.approx(-upper_tail_quantile(1.0 - tail), rel=1e-12)
    assert upper_tail_quantile(0.5) == pytest.approx(0.0, abs=1e-12)


def test_a_tail_probability_outside_the_unit_interval_is_rejected() -> None:
    for tail in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(InvalidStatisticsInputsError):
            upper_tail_quantile(tail)


def test_a_single_trial_needs_no_deflation() -> None:
    assert expected_maximum_sharpe_ratio(1, 0.05) == 0.0


def test_the_expected_maximum_grows_with_the_trial_count() -> None:
    standard_error = sharpe_standard_error(NULL_SAMPLE)
    previous = -math.inf
    for count in (1, 2, 10, 100, 1000, 10_000, 100_000):
        current = expected_maximum_sharpe_ratio(count, standard_error)
        assert current > previous
        previous = current


def test_the_bar_a_result_must_clear_rises_with_the_trial_count() -> None:
    previous = -math.inf
    for count in (1, 10, 100, 1000, 10_000):
        needed = sharpe_ratio_needed_for(NULL_SAMPLE, count, 0.95)
        assert needed > previous
        previous = needed


def test_the_same_backtest_stops_being_significant_as_trials_accumulate() -> None:
    observed = SharpeSample(1.5 / math.sqrt(TRADING_DAYS), THREE_YEARS, -0.5, 3.0)
    assert deflated_sharpe_ratio(observed, 1, 0.95).clears_threshold
    assert not deflated_sharpe_ratio(observed, 10, 0.95).clears_threshold

    previous = math.inf
    for count in (1, 10, 100, 1000, 10_000):
        probability = deflated_sharpe_ratio(observed, count, 0.95).deflated_probability
        assert probability < previous
        previous = probability


def test_negative_skew_and_fat_tails_widen_the_standard_error() -> None:
    observed = 1.5 / math.sqrt(TRADING_DAYS)
    normal = SharpeSample(observed, THREE_YEARS, 0.0, 0.0)
    realistic = SharpeSample(observed, THREE_YEARS, -0.5, 3.0)
    assert sharpe_standard_error(realistic) > sharpe_standard_error(normal)


def test_an_impossible_moment_combination_is_rejected_rather_than_returned() -> None:
    with pytest.raises(InvalidStatisticsInputsError):
        sharpe_standard_error(SharpeSample(2.0, THREE_YEARS, 5.0, 0.0))
    with pytest.raises(InvalidStatisticsInputsError):
        sharpe_standard_error(SharpeSample(0.1, 1, 0.0, 0.0))


def test_an_invalid_threshold_is_rejected() -> None:
    for threshold in (0.0, 1.0, -0.5):
        with pytest.raises(InvalidStatisticsInputsError):
            deflated_sharpe_ratio(NULL_SAMPLE, 10, threshold)
