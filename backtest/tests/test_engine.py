from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from engine import (
    BacktestRequest,
    ContractMark,
    InvalidBacktestError,
    StepContext,
    mark_positions,
    quotes_by_symbol,
    reader_at_step,
    run_backtest,
    trade_towards,
)
from volarb_py.market_data import AsOfChainReader, ContractQuote

DATASET = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "datasets" / "synthetic_chain"
STEPS = [datetime(2026, 8, 21, hour, 0, 0, tzinfo=UTC) for hour in (15, 16, 17)]
LATE_HORIZON = datetime(2026, 8, 23, 0, 0, 0, tzinfo=UTC)
CAPITAL = 1_000_000.0
UNDERLYING = "SPX"
STRADDLE_LEGS = 8
LOTS = 5
EXPECTED_STEPS = 3
REQUEST = BacktestRequest(DATASET, UNDERLYING, STEPS, CAPITAL)
DIGEST_LENGTH = 64


def hold_nothing(context: StepContext) -> dict[str, int]:
    return dict(context.positions)


def short_straddle(context: StepContext) -> dict[str, int]:
    if context.step_index != 0:
        return dict(context.positions)
    return {
        quote.contract_symbol: (-LOTS if quote.option_type == "call" else LOTS)
        for quote in context.quotes[:STRADDLE_LEGS]
    }


def test_a_backtest_that_never_trades_has_no_profit_and_no_cost() -> None:
    outcome = run_backtest(REQUEST, hold_nothing)
    assert len(outcome.steps) == EXPECTED_STEPS
    assert outcome.gross_profit == 0.0
    assert outcome.transaction_cost == 0.0
    assert outcome.net_profit == 0.0
    assert outcome.returns == [0.0] * EXPECTED_STEPS


def test_the_dataset_digest_is_carried_onto_the_result() -> None:
    outcome = run_backtest(REQUEST, hold_nothing)
    assert len(outcome.dataset_digest) == DIGEST_LENGTH


def test_opening_the_book_costs_the_spread_and_nothing_later_does() -> None:
    outcome = run_backtest(REQUEST, short_straddle)
    assert outcome.steps[0].transaction_cost > 0.0
    assert outcome.steps[0].filled_quantity == STRADDLE_LEGS * LOTS
    assert all(step.transaction_cost == 0.0 for step in outcome.steps[1:])
    assert outcome.net_profit == pytest.approx(outcome.gross_profit - outcome.transaction_cost, rel=1e-12)


def reader_frozen_at_the_end(dataset_root: Path, _: datetime) -> AsOfChainReader:
    return reader_at_step(dataset_root, LATE_HORIZON)


def test_a_backtest_cannot_see_a_revision_that_had_not_arrived() -> None:
    honest = run_backtest(REQUEST, short_straddle)
    cheating = run_backtest(REQUEST, short_straddle, reader_frozen_at_the_end)

    assert cheating.net_profit != honest.net_profit
    assert cheating.returns[:2] == honest.returns[:2]
    assert cheating.returns[2] != honest.returns[2]


def test_the_horizon_moves_with_the_step() -> None:
    seen: list[datetime] = []

    def recording(dataset_root: Path, moment: datetime) -> AsOfChainReader:
        seen.append(moment)
        return reader_at_step(dataset_root, moment)

    run_backtest(REQUEST, hold_nothing, recording)
    assert seen == STEPS


def test_a_position_in_an_unquoted_contract_is_carried_not_dropped() -> None:
    marks = {"GONE": ContractMark(price=3.0, contract_multiplier=100)}
    result = mark_positions({"GONE": 2}, {}, marks)
    assert result.stale_count == 1
    assert result.value == pytest.approx(2 * 3.0 * 100)


def test_a_position_never_quoted_is_an_error_rather_than_a_silent_zero() -> None:
    with pytest.raises(InvalidBacktestError):
        mark_positions({"UNKNOWN": 1}, {}, {})


def test_an_order_larger_than_the_book_is_partly_unfilled() -> None:
    outcome = run_backtest(REQUEST, hold_nothing)
    assert outcome.steps[0].unfilled_quantity == 0

    def oversized(context: StepContext) -> dict[str, int]:
        if context.step_index != 0:
            return dict(context.positions)
        return {context.quotes[0].contract_symbol: 100_000}

    stretched = run_backtest(REQUEST, oversized)
    assert stretched.steps[0].unfilled_quantity > 0


def test_trading_to_the_same_target_is_free() -> None:
    empty: dict[str, ContractQuote] = {}
    assert trade_towards({}, {}, empty).cost == 0.0
    assert trade_towards({"A": 3}, {"A": 3}, empty).cost == 0.0


def test_malformed_runs_are_rejected() -> None:
    with pytest.raises(InvalidBacktestError):
        run_backtest(BacktestRequest(DATASET, UNDERLYING, [], CAPITAL), hold_nothing)
    with pytest.raises(InvalidBacktestError):
        run_backtest(BacktestRequest(DATASET, UNDERLYING, STEPS, 0.0), hold_nothing)
    with pytest.raises(InvalidBacktestError):
        run_backtest(BacktestRequest(DATASET, UNDERLYING, list(reversed(STEPS)), CAPITAL), hold_nothing)


def test_quotes_are_indexed_by_contract_symbol() -> None:
    seen: list[ContractQuote] = []

    def capture(context: StepContext) -> dict[str, int]:
        seen.extend(context.quotes)
        return {}

    run_backtest(BacktestRequest(DATASET, UNDERLYING, STEPS[:1], CAPITAL), capture)
    assert len(quotes_by_symbol(seen)) == len(seen)
