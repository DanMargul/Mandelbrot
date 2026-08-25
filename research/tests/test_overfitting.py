from __future__ import annotations

import math
import random

import pytest
from overfitting import (
    InvalidPerformanceError,
    TrialPerformance,
    combinatorially_symmetric_cross_validation,
    merged_moments,
    moments_of,
    sharpe_of_moments,
    walk_forward_selection,
)

PERIODS = 252 * 4
BLOCKS = 8
DAILY_VOLATILITY = 0.01
NOISE_DATASETS = 40
NOISE_CONFIGURATIONS = 20
EXPECTED_NOISE_PBO = 0.5
NOISE_PBO_TOLERANCE = 0.08
SINGLE_DATASET_SPREAD = 0.35
CROWDED_CONFIGURATIONS = 100
SPARSE_CONFIGURATIONS = 2
WALK_FORWARD_FOLDS = 4
STRONG_EDGE_SHARPE = 4.0
MODERATE_EDGE_SHARPE = 2.0
CROWDING_SEEDS = (2000, 3100, 4200, 5300, 6400)


def noise_configurations(count: int, seed: int) -> list[TrialPerformance]:
    generator = random.Random(seed)
    return [
        TrialPerformance(
            f"noise_{index}", [DAILY_VOLATILITY * generator.gauss(0.0, 1.0) for _ in range(PERIODS)]
        )
        for index in range(count)
    ]


def one_real_edge(count: int, seed: int, annualised_sharpe: float) -> list[TrialPerformance]:
    generator = random.Random(seed)
    drift = DAILY_VOLATILITY * annualised_sharpe / math.sqrt(252)
    real = TrialPerformance(
        "real", [drift + DAILY_VOLATILITY * generator.gauss(0.0, 1.0) for _ in range(PERIODS)]
    )
    return [real, *noise_configurations(count - 1, seed + 1)]


def test_merged_block_moments_agree_with_the_whole_series() -> None:
    generator = random.Random(11)
    values = [DAILY_VOLATILITY * generator.gauss(0.0, 1.0) for _ in range(1000)]
    blocks = [values[start : start + 125] for start in range(0, 1000, 125)]

    combined = moments_of(blocks[0])
    for block in blocks[1:]:
        combined = merged_moments(combined, moments_of(block))

    direct = moments_of(values)
    assert combined.count == direct.count
    assert combined.mean == pytest.approx(direct.mean, rel=1e-14)
    assert sharpe_of_moments(combined) == pytest.approx(sharpe_of_moments(direct), rel=1e-12)


def test_pure_noise_puts_the_overfitting_probability_at_a_half() -> None:
    probabilities = [
        combinatorially_symmetric_cross_validation(
            noise_configurations(NOISE_CONFIGURATIONS, 90000 + dataset), BLOCKS
        ).probability_of_backtest_overfitting
        for dataset in range(NOISE_DATASETS)
    ]
    mean = sum(probabilities) / len(probabilities)
    assert mean == pytest.approx(EXPECTED_NOISE_PBO, abs=NOISE_PBO_TOLERANCE)


def test_a_single_dataset_gives_a_noisy_estimate() -> None:
    probabilities = [
        combinatorially_symmetric_cross_validation(
            noise_configurations(NOISE_CONFIGURATIONS, 90000 + dataset), BLOCKS
        ).probability_of_backtest_overfitting
        for dataset in range(NOISE_DATASETS)
    ]
    assert max(probabilities) - min(probabilities) > SINGLE_DATASET_SPREAD


def test_an_edge_far_above_the_noise_survives_any_amount_of_crowding() -> None:
    for count in (SPARSE_CONFIGURATIONS, CROWDED_CONFIGURATIONS):
        report = combinatorially_symmetric_cross_validation(
            one_real_edge(count, 2000, STRONG_EDGE_SHARPE), BLOCKS
        )
        assert report.probability_of_backtest_overfitting == 0.0
        assert report.median_out_of_sample_sharpe > 0.0


def mean_out_of_sample_sharpe(count: int, annualised_sharpe: float) -> float:
    reports = [
        combinatorially_symmetric_cross_validation(one_real_edge(count, seed, annualised_sharpe), BLOCKS)
        for seed in CROWDING_SEEDS
    ]
    return sum(report.median_out_of_sample_sharpe for report in reports) / len(reports)


def test_crowding_the_search_degrades_what_selection_delivers() -> None:
    sparse = mean_out_of_sample_sharpe(SPARSE_CONFIGURATIONS, MODERATE_EDGE_SHARPE)
    crowded = mean_out_of_sample_sharpe(CROWDED_CONFIGURATIONS, MODERATE_EDGE_SHARPE)
    assert crowded < sparse


def test_the_estimate_is_coarse_when_only_two_configurations_compete() -> None:
    report = combinatorially_symmetric_cross_validation(
        one_real_edge(SPARSE_CONFIGURATIONS, 2000, MODERATE_EDGE_SHARPE), BLOCKS
    )
    assert abs(report.median_logit) == pytest.approx(math.log(2.0), rel=1e-12)


def test_the_split_count_is_every_symmetric_partition() -> None:
    report = combinatorially_symmetric_cross_validation(noise_configurations(5, 1), BLOCKS)
    assert report.split_count == math.comb(BLOCKS, BLOCKS // 2)
    assert report.block_count == BLOCKS
    assert report.period_count == PERIODS


def test_the_same_input_gives_the_same_report() -> None:
    first = combinatorially_symmetric_cross_validation(noise_configurations(8, 77), BLOCKS)
    second = combinatorially_symmetric_cross_validation(noise_configurations(8, 77), BLOCKS)
    assert first == second


def test_an_odd_or_tiny_block_count_is_rejected() -> None:
    performances = noise_configurations(5, 1)
    for blocks in (3, 2, 7, 0):
        with pytest.raises(InvalidPerformanceError):
            combinatorially_symmetric_cross_validation(performances, blocks)


def test_ragged_or_lonely_inputs_are_rejected() -> None:
    with pytest.raises(InvalidPerformanceError):
        combinatorially_symmetric_cross_validation(noise_configurations(1, 1), BLOCKS)

    ragged = noise_configurations(3, 1)
    ragged[1] = TrialPerformance(ragged[1].trial_id, ragged[1].returns[:-1])
    with pytest.raises(InvalidPerformanceError):
        combinatorially_symmetric_cross_validation(ragged, BLOCKS)


def test_too_few_periods_for_the_blocks_is_rejected() -> None:
    short = [TrialPerformance(f"c{index}", [0.1, 0.2, 0.3]) for index in range(3)]
    with pytest.raises(InvalidPerformanceError):
        combinatorially_symmetric_cross_validation(short, BLOCKS)


def test_walk_forward_selects_only_on_the_past() -> None:
    performances = one_real_edge(6, 3000, 1.0)
    baseline = walk_forward_selection(performances, WALK_FORWARD_FOLDS)

    boundary = PERIODS * WALK_FORWARD_FOLDS // (WALK_FORWARD_FOLDS + 1)
    disturbed = [
        TrialPerformance(
            entry.trial_id,
            [*entry.returns[:boundary], *[value + 10.0 for value in entry.returns[boundary:]]],
        )
        for entry in performances
    ]
    later = walk_forward_selection(disturbed, WALK_FORWARD_FOLDS)

    assert later.selected_trial_ids[:-1] == baseline.selected_trial_ids[:-1]


def test_walk_forward_reports_what_it_chose_and_how_often_it_changed() -> None:
    report = walk_forward_selection(one_real_edge(6, 3000, 1.0), WALK_FORWARD_FOLDS)
    assert len(report.selected_trial_ids) == WALK_FORWARD_FOLDS
    assert 0 <= report.selection_changed_count < WALK_FORWARD_FOLDS
    assert len(report.out_of_sample_returns) > 0


def test_walk_forward_is_not_flattered_by_the_best_in_sample_number() -> None:
    report = walk_forward_selection(one_real_edge(CROWDED_CONFIGURATIONS, 4000, 1.0), WALK_FORWARD_FOLDS)
    assert report.out_of_sample_sharpe < report.best_in_sample_sharpe


def test_a_fold_count_below_one_is_rejected() -> None:
    with pytest.raises(InvalidPerformanceError):
        walk_forward_selection(noise_configurations(3, 1), 0)
