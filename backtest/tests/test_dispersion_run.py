from __future__ import annotations

import math
from pathlib import Path

from correlation_run import BasketDefinition, basket_definition
from dispersion_run import (
    WARMUP_STEPS,
    BasketSnapshot,
    DispersionSettings,
    StraddleLeg,
    book_from,
    dispersion_strategy,
    snapshot_of,
    step_times,
    straddle_count,
)
from engine import BacktestRequest, StepContext, run_backtest
from volarb_py.implied_correlation import BasketConstituent, dispersion_vega_weights
from volarb_py.market_data import ChainQuery, KnowledgeHorizon, open_chain_dataset

DATASET = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "datasets" / "synthetic_basket"
QUOTED_EXPIRY = 1
ENTRY_Z = 1.0
INDEX_STRADDLES = 10
CAPITAL = 5_000_000.0
COARSE_SIZE = 5
FINE_SIZE = 200
SPARSE_STEP_LIMIT = 5
LEG_COUNT = 8
CONSTITUENT_COST_SHARE = 0.6
NO_VEGA = 0.0


def definition_and_snapshot() -> tuple[BasketDefinition, BasketSnapshot]:
    definition = basket_definition(DATASET)
    moment = step_times(definition)[WARMUP_STEPS]
    reader = open_chain_dataset(DATASET, KnowledgeHorizon(as_of=moment))
    grouped = {
        symbol: reader.chain_as_of(ChainQuery(underlying_symbol=symbol, observation_time=moment))
        for symbol in [definition.index_symbol, *sorted(definition.weights)]
    }
    flat = [quote for quotes in grouped.values() for quote in quotes]
    snapshot = snapshot_of(
        StepContext(WARMUP_STEPS, moment, flat, {}, grouped),
        definition,
        definition.expiry_dates[QUOTED_EXPIRY],
    )
    assert snapshot is not None
    return definition, snapshot


def outcome_at(entry_z: float) -> tuple[float, float, float, int]:
    definition = basket_definition(DATASET)
    settings = DispersionSettings(entry_z, INDEX_STRADDLES, WARMUP_STEPS, QUOTED_EXPIRY)
    request = BacktestRequest(
        DATASET,
        [definition.index_symbol, *sorted(definition.weights)],
        step_times(definition),
        CAPITAL,
    )
    result = run_backtest(request, dispersion_strategy(definition, settings))
    active = sum(1 for step in result.steps if step.filled_quantity > 0)
    return result.gross_profit, result.transaction_cost, result.net_profit, active


def test_the_engine_reaches_every_underlying_in_the_basket() -> None:
    definition = basket_definition(DATASET)
    seen: list[dict[str, int]] = []

    def capture(context: StepContext) -> dict[str, int]:
        seen.append({symbol: len(quotes) for symbol, quotes in context.quotes_by_underlying.items()})
        return {}

    request = BacktestRequest(
        DATASET,
        [definition.index_symbol, *sorted(definition.weights)],
        step_times(definition)[:1],
        CAPITAL,
    )
    run_backtest(request, capture)
    assert len(seen[0]) == LEG_COUNT + 1
    assert all(count > 0 for count in seen[0].values())


def test_selling_a_rich_correlation_is_short_the_index_and_long_every_name() -> None:
    definition, snapshot = definition_and_snapshot()
    book = book_from(snapshot, definition, INDEX_STRADDLES)
    assert book[snapshot.index_leg.call_symbol] == -INDEX_STRADDLES
    assert book[snapshot.index_leg.put_symbol] == -INDEX_STRADDLES
    for leg in snapshot.name_legs.values():
        assert book[leg.call_symbol] > 0
        assert book[leg.call_symbol] == book[leg.put_symbol]


def test_buying_a_cheap_correlation_reverses_every_leg() -> None:
    definition, snapshot = definition_and_snapshot()
    rich = book_from(snapshot, definition, INDEX_STRADDLES)
    cheap = book_from(snapshot, definition, -INDEX_STRADDLES)
    for symbol, quantity in rich.items():
        assert cheap[symbol] == -quantity


def test_a_straddle_with_no_vega_is_not_sized() -> None:
    empty = StraddleLeg("CALL", "PUT", NO_VEGA, 0.2)
    assert straddle_count(1_000.0, empty) == 0


def test_contract_granularity_is_what_limits_the_hedge() -> None:
    definition, snapshot = definition_and_snapshot()
    constituents = [
        BasketConstituent(symbol, definition.weights[symbol], snapshot.name_legs[symbol].implied_volatility)
        for symbol in sorted(definition.weights)
    ]

    def hedge_error(size: int) -> float:
        wanted = dispersion_vega_weights(
            constituents, snapshot.correlation, size * snapshot.index_leg.vega_per_straddle
        )
        book = book_from(snapshot, definition, size)
        errors = [
            (
                book.get(snapshot.name_legs[symbol].call_symbol, 0)
                * snapshot.name_legs[symbol].vega_per_straddle
                - target
            )
            / abs(target)
            for symbol, target in zip(sorted(definition.weights), wanted, strict=True)
        ]
        return math.sqrt(math.fsum(error * error for error in errors) / len(errors))

    assert hedge_error(COARSE_SIZE) > hedge_error(INDEX_STRADDLES) > hedge_error(FINE_SIZE)


def test_the_correlation_signal_is_found_and_still_does_not_pay_for_the_spread() -> None:
    gross, cost, net, active = outcome_at(ENTRY_Z)
    assert gross > 0.0
    assert cost > gross
    assert net < 0.0
    assert active > SPARSE_STEP_LIMIT


def test_the_one_profitable_threshold_barely_trades() -> None:
    losing = [outcome_at(entry) for entry in (0.5, 0.75, 1.0, 1.25, 1.5)]
    assert all(net < 0.0 for _, _, net, _ in losing)
    _, _, net, active = outcome_at(2.0)
    assert net > 0.0
    assert active <= SPARSE_STEP_LIMIT


def test_the_constituent_legs_carry_most_of_the_crossing_cost() -> None:
    definition, snapshot = definition_and_snapshot()
    moment = step_times(definition)[WARMUP_STEPS]
    reader = open_chain_dataset(DATASET, KnowledgeHorizon(as_of=moment))
    quotes = {
        quote.contract_symbol: quote
        for symbol in [definition.index_symbol, *sorted(definition.weights)]
        for quote in reader.chain_as_of(ChainQuery(underlying_symbol=symbol, observation_time=moment))
    }
    book = book_from(snapshot, definition, INDEX_STRADDLES)
    index_symbols = {snapshot.index_leg.call_symbol, snapshot.index_leg.put_symbol}
    total = 0.0
    names = 0.0
    for symbol, quantity in book.items():
        quote = quotes[symbol]
        crossing = abs(quantity) * 0.5 * (quote.ask_price - quote.bid_price) * quote.contract_multiplier
        total += crossing
        if symbol not in index_symbols:
            names += crossing
    assert names / total > CONSTITUENT_COST_SHARE
