from __future__ import annotations

from pathlib import Path

import pytest
from allocator_decision import (
    REVERSION_HORIZON_STEPS,
    BookSettings,
    allocated_book,
    expected_log_variance_capture,
)
from engine import BacktestRequest, run_backtest
from residual_run import (
    StrategySettings,
    business_days,
    observed_surface,
    residual_strategy,
)
from volarb_py.factors import score_residual
from volarb_py.market_data import ChainQuery, KnowledgeHorizon, open_chain_dataset

DATASET = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "datasets" / "synthetic_history"
CAPITAL = 1_000_000.0
INDEX = "IDXH"
SINGLE_NAME = "NAMEH"
STEPS = 120
LOTS = 5
WARMUP = 40
ENTRY_Z = 1.5
BASIS_ORTHOGONALITY_TOLERANCE = 1e-9
RESIDUAL_SUM_TOLERANCE = 1e-9
PERSISTENT_AUTOCORRELATION = 0.7
CAPTURE_TOLERANCE = 1e-12


def settings_for(underlying: str, *, use_allocator: bool) -> StrategySettings:
    return StrategySettings(
        underlying_symbol=underlying,
        entry_z_score=ENTRY_Z,
        lot_size=LOTS,
        warmup_steps=WARMUP,
        use_allocator=use_allocator,
    )


def outcome_for(underlying: str, *, use_allocator: bool) -> tuple[float, float, int]:
    settings = settings_for(underlying, use_allocator=use_allocator)
    request = BacktestRequest(DATASET, underlying, business_days(STEPS), CAPITAL)
    result = run_backtest(request, residual_strategy(settings))
    traded = sum(step.filled_quantity for step in result.steps)
    return result.gross_profit, result.net_profit, traded


def first_surface(underlying: str) -> tuple[list[float], dict[str, list[float]]]:
    moment = business_days(STEPS)[0]
    reader = open_chain_dataset(DATASET, KnowledgeHorizon(as_of=moment))
    quotes = reader.chain_as_of(ChainQuery(underlying_symbol=underlying, observation_time=moment))
    surface = observed_surface(moment, quotes)
    return list(surface.residuals.values()), surface.factor_exposures


def test_the_surface_fit_leaves_residuals_orthogonal_to_every_factor() -> None:
    residuals, exposures = first_surface(INDEX)
    assert residuals
    ordered = list(exposures.values())
    for index in range(len(ordered[0])):
        projection = 0.0
        for residual, loadings in zip(residuals, ordered, strict=True):
            projection += residual * loadings[index]
        assert abs(projection) < BASIS_ORTHOGONALITY_TOLERANCE


def test_the_residuals_sum_to_nothing_because_the_level_factor_is_fitted() -> None:
    residuals, _ = first_surface(INDEX)
    assert abs(sum(residuals)) < RESIDUAL_SUM_TOLERANCE


def test_a_persistent_residual_is_scored_as_persistent() -> None:
    _, exposures = first_surface(INDEX)
    assert exposures
    series = [0.5 * index for index in range(REVERSION_HORIZON_STEPS * 2)]
    assert score_residual(series).lag_one_autocorrelation > PERSISTENT_AUTOCORRELATION


def test_the_expected_capture_opposes_the_current_deviation() -> None:
    rising = score_residual([float(index) for index in range(REVERSION_HORIZON_STEPS * 2)])
    falling = score_residual([-float(index) for index in range(REVERSION_HORIZON_STEPS * 2)])
    assert expected_log_variance_capture(rising) < 0.0
    assert expected_log_variance_capture(falling) > 0.0


def test_a_residual_sitting_at_its_own_mean_is_worth_nothing() -> None:
    balanced = score_residual([1.0, -1.0] * REVERSION_HORIZON_STEPS + [0.0])
    assert abs(expected_log_variance_capture(balanced)) < CAPTURE_TOLERANCE


def test_no_history_means_no_book() -> None:
    moment = business_days(STEPS)[0]
    reader = open_chain_dataset(DATASET, KnowledgeHorizon(as_of=moment))
    quotes = reader.chain_as_of(ChainQuery(underlying_symbol=INDEX, observation_time=moment))
    surface = observed_surface(moment, quotes)
    book, allocation = allocated_book(
        surface.states, {}, BookSettings(LOTS, surface.states[0].forward, surface.factor_exposures)
    )
    assert book == {}
    assert allocation.objective == pytest.approx(0.0)


def test_the_threshold_rule_finds_the_planted_signal_but_cannot_pay_for_it() -> None:
    gross, net, traded = outcome_for(INDEX, use_allocator=False)
    assert gross > 0.0
    assert net < 0.0
    assert traded > 0


def test_pricing_the_spread_turns_the_same_signal_profitable() -> None:
    threshold_gross, threshold_net, threshold_traded = outcome_for(INDEX, use_allocator=False)
    allocator_gross, allocator_net, allocator_traded = outcome_for(INDEX, use_allocator=True)
    assert allocator_net > 0.0 > threshold_net
    assert allocator_gross > threshold_gross
    assert allocator_traded < threshold_traded


def test_the_allocator_refuses_a_signal_the_wider_market_cannot_pay_for() -> None:
    _, threshold_net, threshold_traded = outcome_for(SINGLE_NAME, use_allocator=False)
    _, allocator_net, allocator_traded = outcome_for(SINGLE_NAME, use_allocator=True)
    assert allocator_traded * 2 < threshold_traded
    assert allocator_net > threshold_net
