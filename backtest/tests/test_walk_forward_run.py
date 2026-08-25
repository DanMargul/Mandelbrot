from __future__ import annotations

from pathlib import Path
from statistics import deflated_sharpe_ratio, sharpe_sample_of

import pytest
from overfitting import (
    combinatorially_symmetric_cross_validation,
    moments_of,
    sharpe_of_moments,
)
from walk_forward_run import (
    BLOCK_COUNT,
    DEFLATION_THRESHOLD,
    ENTRY_Z_GRID,
    HORIZON_GRID,
    Trial,
    days_needed_for,
    grid_for,
    performances_of,
    run_grid,
)

DATASET = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "datasets" / "synthetic_history"
INDEX = "IDXH"
CERTAIN = 1.0
LOSING_SHARPE = 0.0
WEAK_EDGE = 0.05
NARROW_SEARCH = 2
SHARPE_TOLERANCE = 0.01


@pytest.fixture(scope="module")
def index_trials() -> list[Trial]:
    return run_grid(DATASET, INDEX)


def family(trials: list[Trial], name: str) -> list[Trial]:
    return [trial for trial in trials if trial.family == name]


def test_the_grid_spans_every_threshold_and_every_horizon() -> None:
    grid = grid_for(INDEX)
    assert len(grid) == len(ENTRY_Z_GRID) + len(HORIZON_GRID)
    assert {settings.entry_z_score for _, kind, settings in grid if kind == "threshold"} == set(ENTRY_Z_GRID)
    assert {settings.reversion_horizon_steps for _, kind, settings in grid if kind == "allocator"} == set(
        HORIZON_GRID
    )


def test_tuning_the_threshold_on_this_data_is_pure_overfitting(index_trials: list[Trial]) -> None:
    report = combinatorially_symmetric_cross_validation(
        performances_of(family(index_trials, "threshold")), BLOCK_COUNT
    )
    assert report.probability_of_backtest_overfitting == pytest.approx(CERTAIN)
    assert report.median_performance_degradation < 0.0


def test_every_threshold_configuration_loses_money(index_trials: list[Trial]) -> None:
    for trial in family(index_trials, "threshold"):
        assert trial.net_profit < 0.0
        assert sharpe_of_moments(moments_of(trial.returns)) < LOSING_SHARPE


def test_the_best_result_does_not_survive_the_search_that_found_it(index_trials: list[Trial]) -> None:
    best = max(index_trials, key=lambda trial: sharpe_of_moments(moments_of(trial.returns)))
    assert best.net_profit > 0.0
    sample = sharpe_sample_of(best.returns)
    deflated = deflated_sharpe_ratio(sample, len(index_trials), DEFLATION_THRESHOLD)
    assert not deflated.clears_threshold
    assert deflated.expected_maximum_under_null > deflated.sharpe_ratio


def test_a_negative_sharpe_is_never_rescued_by_more_data() -> None:
    losing = sharpe_sample_of([-WEAK_EDGE - 1.0, -WEAK_EDGE + 1.0] * BLOCK_COUNT)
    assert losing.sharpe_ratio < 0.0
    assert days_needed_for(losing, len(ENTRY_Z_GRID)) is None


def test_a_weak_edge_needs_more_days_the_wider_the_search() -> None:
    winning = sharpe_sample_of([WEAK_EDGE - 1.0, WEAK_EDGE + 1.0] * BLOCK_COUNT)
    assert winning.sharpe_ratio == pytest.approx(WEAK_EDGE, abs=SHARPE_TOLERANCE)
    narrow = days_needed_for(winning, NARROW_SEARCH)
    wide = days_needed_for(winning, len(ENTRY_Z_GRID) * BLOCK_COUNT)
    assert narrow is not None
    assert wide is not None
    assert wide > narrow
