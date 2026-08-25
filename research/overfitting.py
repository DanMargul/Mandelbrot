from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations, pairwise
from typing import Final

MINIMUM_BLOCK_COUNT: Final[int] = 4
MINIMUM_TRIALS_TO_RANK: Final[int] = 2
MINIMUM_PERIODS_PER_BLOCK: Final[int] = 2
MINIMUM_STANDARD_DEVIATION: Final[float] = 1e-12
MINIMUM_WALK_FORWARD_FOLDS: Final[int] = 1


class InvalidPerformanceError(ValueError):
    pass


@dataclass(frozen=True)
class TrialPerformance:
    trial_id: str
    returns: list[float]


@dataclass(frozen=True)
class RunningMoments:
    count: int
    mean: float
    sum_of_squared_deviations: float


@dataclass(frozen=True)
class OverfittingReport:
    trial_count: int
    period_count: int
    block_count: int
    split_count: int
    probability_of_backtest_overfitting: float
    median_logit: float
    median_in_sample_sharpe: float
    median_out_of_sample_sharpe: float
    median_performance_degradation: float


@dataclass(frozen=True)
class WalkForwardReport:
    fold_count: int
    selected_trial_ids: list[str]
    out_of_sample_returns: list[float]
    out_of_sample_sharpe: float
    best_in_sample_sharpe: float
    selection_changed_count: int


def moments_of(values: list[float]) -> RunningMoments:
    count = len(values)
    mean = math.fsum(values) / count
    return RunningMoments(count, mean, math.fsum((value - mean) * (value - mean) for value in values))


def merged_moments(left: RunningMoments, right: RunningMoments) -> RunningMoments:
    count = left.count + right.count
    difference = right.mean - left.mean
    mean = left.mean + difference * right.count / count
    squared = (
        left.sum_of_squared_deviations
        + right.sum_of_squared_deviations
        + difference * difference * left.count * right.count / count
    )
    return RunningMoments(count, mean, squared)


def sharpe_of_moments(moments: RunningMoments) -> float:
    if moments.count < MINIMUM_TRIALS_TO_RANK:
        raise InvalidPerformanceError(f"a Sharpe ratio needs at least two periods, got {moments.count}")
    variance = moments.sum_of_squared_deviations / (moments.count - 1)
    return moments.mean / max(math.sqrt(max(variance, 0.0)), MINIMUM_STANDARD_DEVIATION)


def block_boundaries(period_count: int, block_count: int) -> list[int]:
    return [period_count * index // block_count for index in range(block_count + 1)]


def validate_performances(performances: list[TrialPerformance]) -> int:
    if len(performances) < MINIMUM_TRIALS_TO_RANK:
        raise InvalidPerformanceError(
            f"ranking needs at least {MINIMUM_TRIALS_TO_RANK} trials, got {len(performances)}"
        )
    period_count = len(performances[0].returns)
    for performance in performances:
        if len(performance.returns) != period_count:
            raise InvalidPerformanceError(
                f"{performance.trial_id} has {len(performance.returns)} periods against {period_count}"
            )
    return period_count


def block_moments_for(
    performances: list[TrialPerformance], boundaries: list[int]
) -> list[list[RunningMoments]]:
    return [
        [
            moments_of(performance.returns[boundaries[index] : boundaries[index + 1]])
            for index in range(len(boundaries) - 1)
        ]
        for performance in performances
    ]


def sharpe_over_blocks(moments: list[RunningMoments], chosen: tuple[int, ...]) -> float:
    combined = moments[chosen[0]]
    for index in chosen[1:]:
        combined = merged_moments(combined, moments[index])
    return sharpe_of_moments(combined)


def best_index(values: list[float]) -> int:
    return max(range(len(values)), key=lambda index: (values[index], -index))


def rank_of(values: list[float], target: int) -> int:
    ordered = sorted(range(len(values)), key=lambda index: (values[index], index))
    return ordered.index(target) + 1


def logit_of_relative_rank(rank: int, trial_count: int) -> float:
    relative = rank / (trial_count + 1)
    return math.log(relative / (1.0 - relative))


def median_of(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def combinatorially_symmetric_cross_validation(
    performances: list[TrialPerformance], block_count: int
) -> OverfittingReport:
    if block_count < MINIMUM_BLOCK_COUNT or block_count % 2 != 0:
        raise InvalidPerformanceError(
            f"block_count must be even and at least {MINIMUM_BLOCK_COUNT}, got {block_count}"
        )
    period_count = validate_performances(performances)
    boundaries = block_boundaries(period_count, block_count)
    for index in range(block_count):
        if boundaries[index + 1] - boundaries[index] < MINIMUM_PERIODS_PER_BLOCK:
            raise InvalidPerformanceError(
                f"{period_count} periods split into {block_count} blocks leaves a block too short"
            )

    moments = block_moments_for(performances, boundaries)
    every_block = set(range(block_count))
    logits: list[float] = []
    in_sample: list[float] = []
    out_of_sample: list[float] = []

    for training in combinations(range(block_count), block_count // 2):
        testing = tuple(sorted(every_block - set(training)))
        training_sharpes = [sharpe_over_blocks(row, training) for row in moments]
        testing_sharpes = [sharpe_over_blocks(row, testing) for row in moments]
        selected = best_index(training_sharpes)
        logits.append(logit_of_relative_rank(rank_of(testing_sharpes, selected), len(performances)))
        in_sample.append(training_sharpes[selected])
        out_of_sample.append(testing_sharpes[selected])

    degradation = [after - before for before, after in zip(in_sample, out_of_sample, strict=True)]
    return OverfittingReport(
        trial_count=len(performances),
        period_count=period_count,
        block_count=block_count,
        split_count=len(logits),
        probability_of_backtest_overfitting=sum(1 for value in logits if value <= 0.0) / len(logits),
        median_logit=median_of(logits),
        median_in_sample_sharpe=median_of(in_sample),
        median_out_of_sample_sharpe=median_of(out_of_sample),
        median_performance_degradation=median_of(degradation),
    )


def walk_forward_selection(performances: list[TrialPerformance], fold_count: int) -> WalkForwardReport:
    if fold_count < MINIMUM_WALK_FORWARD_FOLDS:
        raise InvalidPerformanceError(f"fold_count must be at least 1, got {fold_count}")
    period_count = validate_performances(performances)
    boundaries = block_boundaries(period_count, fold_count + 1)
    for index in range(fold_count + 1):
        if boundaries[index + 1] - boundaries[index] < MINIMUM_PERIODS_PER_BLOCK:
            raise InvalidPerformanceError(
                f"{period_count} periods split into {fold_count + 1} folds leaves a fold too short"
            )

    selected_trial_ids: list[str] = []
    out_of_sample_returns: list[float] = []
    for fold in range(1, fold_count + 1):
        history = [
            sharpe_of_moments(moments_of(performance.returns[: boundaries[fold]]))
            for performance in performances
        ]
        selected = best_index(history)
        selected_trial_ids.append(performances[selected].trial_id)
        out_of_sample_returns.extend(performances[selected].returns[boundaries[fold] : boundaries[fold + 1]])

    whole_sample = [sharpe_of_moments(moments_of(performance.returns)) for performance in performances]
    changes = sum(1 for earlier, later in pairwise(selected_trial_ids) if earlier != later)
    return WalkForwardReport(
        fold_count=fold_count,
        selected_trial_ids=selected_trial_ids,
        out_of_sample_returns=out_of_sample_returns,
        out_of_sample_sharpe=sharpe_of_moments(moments_of(out_of_sample_returns)),
        best_in_sample_sharpe=max(whole_sample),
        selection_changed_count=changes,
    )
