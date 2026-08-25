#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "research"))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from statistics import (  # noqa: E402
    SharpeSample,
    deflated_sharpe_ratio,
    sharpe_ratio_needed_for,
    sharpe_sample_of,
)

from engine import BacktestRequest, run_backtest  # noqa: E402
from overfitting import (  # noqa: E402
    OverfittingReport,
    TrialPerformance,
    combinatorially_symmetric_cross_validation,
    moments_of,
    sharpe_of_moments,
    walk_forward_selection,
)
from residual_run import StrategySettings, business_days, residual_strategy  # noqa: E402

ENTRY_Z_GRID: Final[tuple[float, ...]] = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5)
HORIZON_GRID: Final[tuple[int, ...]] = (5, 10, 20)
LOT_SIZE: Final[int] = 5
WARMUP_STEPS: Final[int] = 40
STEPS: Final[int] = 120
CAPITAL: Final[float] = 1_000_000.0
BLOCK_COUNT: Final[int] = 8
FOLD_COUNT: Final[int] = 4
DEFLATION_THRESHOLD: Final[float] = 0.95
LONGEST_HISTORY_CONSIDERED: Final[int] = 200_000
HISTORY_SEARCH_STEP: Final[int] = 10
EXIT_OK: Final[int] = 0


@dataclass(frozen=True)
class Trial:
    trial_id: str
    family: str
    settings: StrategySettings
    returns: list[float]
    net_profit: float


def grid_for(underlying: str) -> list[tuple[str, str, StrategySettings]]:
    grid: list[tuple[str, str, StrategySettings]] = []
    for entry in ENTRY_Z_GRID:
        grid.append(
            (
                f"threshold-z{entry}",
                "threshold",
                StrategySettings(underlying, entry, LOT_SIZE, WARMUP_STEPS, False, HORIZON_GRID[1]),
            )
        )
    for horizon in HORIZON_GRID:
        grid.append(
            (
                f"allocator-h{horizon}",
                "allocator",
                StrategySettings(underlying, ENTRY_Z_GRID[2], LOT_SIZE, WARMUP_STEPS, True, horizon),
            )
        )
    return grid


def run_grid(dataset_root: Path, underlying: str) -> list[Trial]:
    steps = business_days(STEPS)
    trials: list[Trial] = []
    for trial_id, family, settings in grid_for(underlying):
        request = BacktestRequest(dataset_root, underlying, steps, CAPITAL)
        outcome = run_backtest(request, residual_strategy(settings))
        trials.append(Trial(trial_id, family, settings, outcome.returns, outcome.net_profit))
    return trials


def performances_of(trials: list[Trial]) -> list[TrialPerformance]:
    return [TrialPerformance(trial.trial_id, trial.returns) for trial in trials]


def report_family(name: str, trials: list[Trial]) -> OverfittingReport:
    performances = performances_of(trials)
    report = combinatorially_symmetric_cross_validation(performances, BLOCK_COUNT)
    walk_forward = walk_forward_selection(performances, FOLD_COUNT)
    print(f"\n----- {name}: {len(trials)} configurations -----")
    for trial in trials:
        sharpe = sharpe_of_moments(moments_of(trial.returns))
        print(f"  {trial.trial_id:<18} net {trial.net_profit:>12,.0f}   sharpe {sharpe:>7.3f}")
    print(f"  probability of backtest overfitting  {report.probability_of_backtest_overfitting:>7.3f}")
    print(f"  median in sample sharpe              {report.median_in_sample_sharpe:>7.3f}")
    print(f"  median out of sample sharpe          {report.median_out_of_sample_sharpe:>7.3f}")
    print(f"  median degradation                   {report.median_performance_degradation:>7.3f}")
    print(f"  walk forward out of sample sharpe    {walk_forward.out_of_sample_sharpe:>7.3f}")
    print(f"  best in sample sharpe                {walk_forward.best_in_sample_sharpe:>7.3f}")
    print(f"  selection changed                    {walk_forward.selection_changed_count:>7d} times")
    return report


def days_needed_for(sample: SharpeSample, trial_count: int) -> int | None:
    if sample.sharpe_ratio <= 0.0:
        return None
    for length in range(sample.sample_length, LONGEST_HISTORY_CONSIDERED, HISTORY_SEARCH_STEP):
        lengthened = SharpeSample(sample.sharpe_ratio, length, sample.skewness, sample.excess_kurtosis)
        if sample.sharpe_ratio >= sharpe_ratio_needed_for(lengthened, trial_count, DEFLATION_THRESHOLD):
            return length
    return None


def report_deflation(trials: list[Trial]) -> None:
    best = max(trials, key=lambda trial: sharpe_of_moments(moments_of(trial.returns)))
    sample = sharpe_sample_of(best.returns)
    deflated = deflated_sharpe_ratio(sample, len(trials), DEFLATION_THRESHOLD)
    print(f"\n----- deflation across the whole search of {len(trials)} -----")
    print(f"  best configuration                   {best.trial_id}")
    print(f"  its sharpe                           {deflated.sharpe_ratio:>7.3f}")
    print(f"  expected maximum under the null      {deflated.expected_maximum_under_null:>7.3f}")
    print(f"  deflated probability                 {deflated.deflated_probability:>7.3f}")
    print(f"  clears {DEFLATION_THRESHOLD:.2f}                         {deflated.clears_threshold}")
    needed = sharpe_ratio_needed_for(sample, len(trials), DEFLATION_THRESHOLD)
    print(f"  sharpe it would have needed          {needed:>7.3f}")
    days = days_needed_for(sample, len(trials))
    reported = f"{days:>7d}" if days is not None else "  never".rjust(7)
    print(f"  days it would have needed            {reported}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="walk-forward")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--underlying", required=True)
    arguments = parser.parse_args(argv)

    trials = run_grid(arguments.dataset, arguments.underlying)
    print(f"underlying: {arguments.underlying}   steps: {STEPS}   trials: {len(trials)}")
    for family in ("threshold", "allocator"):
        members = [trial for trial in trials if trial.family == family]
        report_family(family, members)
    report_deflation(trials)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
