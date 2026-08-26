#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "research"))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from correlation_run import (  # noqa: E402
    AT_THE_MONEY,
    BasketDefinition,
    SliceRequest,
    basket_definition,
    slice_points,
    volatility_at,
)
from engine import BacktestRequest, StepContext, run_backtest  # noqa: E402
from volarb_py.factors import score_residual  # noqa: E402
from volarb_py.implied_correlation import (  # noqa: E402
    BasketConstituent,
    dispersion_vega_weights,
    imply_correlation,
)
from volarb_py.market_data import ContractQuote  # noqa: E402
from volarb_py.pricing import BlackScholesInputs, black_scholes_price_and_greeks  # noqa: E402

DAYS_PER_YEAR: Final[float] = 365.0
INDEX_STRADDLES: Final[int] = 10
ENTRY_Z_SCORE: Final[float] = 1.0
WARMUP_STEPS: Final[int] = 20
QUOTED_EXPIRY: Final[int] = 1
STRADDLE_LEGS: Final[int] = 2
CAPITAL: Final[float] = 5_000_000.0
MINIMUM_STRADDLE_VEGA: Final[float] = 1e-9
EXIT_OK: Final[int] = 0


@dataclass(frozen=True)
class StraddleLeg:
    call_symbol: str
    put_symbol: str
    vega_per_straddle: float
    implied_volatility: float


@dataclass(frozen=True)
class DispersionSettings:
    entry_z_score: float
    index_straddles: int
    warmup_steps: int
    expiry_index: int


def years_to(moment: datetime, expiry: date, settlement_hour_utc: int) -> float:
    settlement = datetime(expiry.year, expiry.month, expiry.day, settlement_hour_utc, tzinfo=UTC)
    return (settlement - moment).total_seconds() / (DAYS_PER_YEAR * 24.0 * 3600.0)


def nearest_pair(
    quotes: list[ContractQuote], expiry: date, forward: float
) -> tuple[ContractQuote, ContractQuote] | None:
    calls = {
        quote.strike: quote for quote in quotes if quote.expiry_date == expiry and quote.option_type == "call"
    }
    puts = {
        quote.strike: quote for quote in quotes if quote.expiry_date == expiry and quote.option_type == "put"
    }
    shared = sorted(set(calls) & set(puts))
    if not shared:
        return None
    chosen = min(shared, key=lambda strike: abs(math.log(strike / forward)))
    return calls[chosen], puts[chosen]


def straddle_for(
    quotes: list[ContractQuote], moment: datetime, definition: BasketDefinition, expiry: date
) -> StraddleLeg | None:
    points = slice_points(
        SliceRequest(quotes, moment, expiry, definition.settlement_hour_utc, definition.risk_free_rate)
    )
    if not points:
        return None
    years = years_to(moment, expiry, definition.settlement_hour_utc)
    discount = math.exp(-definition.risk_free_rate * years)
    forward = quotes[0].underlying_price / discount
    pair = nearest_pair(quotes, expiry, forward)
    if pair is None:
        return None
    call, put = pair
    volatility = volatility_at(points, AT_THE_MONEY)
    greeks = black_scholes_price_and_greeks(
        BlackScholesInputs(forward, call.strike, years, volatility, discount, "call")
    )
    return StraddleLeg(
        call_symbol=call.contract_symbol,
        put_symbol=put.contract_symbol,
        vega_per_straddle=STRADDLE_LEGS * greeks.vega_with_respect_to_volatility * call.contract_multiplier,
        implied_volatility=volatility,
    )


@dataclass(frozen=True)
class BasketSnapshot:
    index_leg: StraddleLeg
    name_legs: dict[str, StraddleLeg]
    correlation: float


def snapshot_of(context: StepContext, definition: BasketDefinition, expiry: date) -> BasketSnapshot | None:
    grouped = context.quotes_by_underlying
    if definition.index_symbol not in grouped or not grouped[definition.index_symbol]:
        return None
    index_leg = straddle_for(grouped[definition.index_symbol], context.observation_time, definition, expiry)
    if index_leg is None:
        return None
    name_legs: dict[str, StraddleLeg] = {}
    for symbol in sorted(definition.weights):
        if not grouped.get(symbol):
            return None
        leg = straddle_for(grouped[symbol], context.observation_time, definition, expiry)
        if leg is None:
            return None
        name_legs[symbol] = leg
    constituents = [
        BasketConstituent(symbol, definition.weights[symbol], name_legs[symbol].implied_volatility)
        for symbol in sorted(definition.weights)
    ]
    report = imply_correlation(constituents, index_leg.implied_volatility)
    if not report.is_admissible:
        return None
    return BasketSnapshot(index_leg, name_legs, report.clean_correlation)


def straddle_count(target_vega: float, leg: StraddleLeg) -> int:
    if abs(leg.vega_per_straddle) < MINIMUM_STRADDLE_VEGA:
        return 0
    return round(target_vega / leg.vega_per_straddle)


def book_from(snapshot: BasketSnapshot, definition: BasketDefinition, index_straddles: int) -> dict[str, int]:
    index_vega = index_straddles * snapshot.index_leg.vega_per_straddle
    constituents = [
        BasketConstituent(symbol, definition.weights[symbol], snapshot.name_legs[symbol].implied_volatility)
        for symbol in sorted(definition.weights)
    ]
    weights = dispersion_vega_weights(constituents, snapshot.correlation, index_vega)
    book: dict[str, int] = {}
    index_count = -index_straddles
    book[snapshot.index_leg.call_symbol] = index_count
    book[snapshot.index_leg.put_symbol] = index_count
    for symbol, vega in zip(sorted(definition.weights), weights, strict=True):
        leg = snapshot.name_legs[symbol]
        count = straddle_count(vega, leg)
        book[leg.call_symbol] = count
        book[leg.put_symbol] = count
    return {symbol: count for symbol, count in book.items() if count != 0}


def dispersion_strategy(
    definition: BasketDefinition, settings: DispersionSettings
) -> Callable[[StepContext], dict[str, int]]:
    expiry = definition.expiry_dates[settings.expiry_index]
    history: list[float] = []

    def decide(context: StepContext) -> dict[str, int]:
        snapshot = snapshot_of(context, definition, expiry)
        if snapshot is None:
            return {}
        history.append(snapshot.correlation)
        if len(history) < settings.warmup_steps:
            return {}
        score = score_residual(history)
        if score.residual_is_degenerate:
            return {}
        if score.naive_z_score > settings.entry_z_score:
            return book_from(snapshot, definition, settings.index_straddles)
        if score.naive_z_score < -settings.entry_z_score:
            return book_from(snapshot, definition, -settings.index_straddles)
        return {}

    return decide


def step_times(definition: BasketDefinition) -> list[datetime]:
    return [
        datetime.strptime(str(observation["observation_date"]), "%Y-%m-%d").replace(
            hour=definition.observation_hour_utc, tzinfo=UTC
        )
        for observation in definition.observations
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dispersion-backtest")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--entry-z", type=float, default=ENTRY_Z_SCORE)
    parser.add_argument("--index-straddles", type=int, default=INDEX_STRADDLES)
    parser.add_argument("--expiry-index", type=int, default=QUOTED_EXPIRY)
    arguments = parser.parse_args(argv)

    definition = basket_definition(arguments.dataset)
    settings = DispersionSettings(
        entry_z_score=arguments.entry_z,
        index_straddles=arguments.index_straddles,
        warmup_steps=WARMUP_STEPS,
        expiry_index=arguments.expiry_index,
    )
    request = BacktestRequest(
        dataset_root=arguments.dataset,
        underlying_symbols=[definition.index_symbol, *sorted(definition.weights)],
        step_times=step_times(definition),
        capital=CAPITAL,
    )
    outcome = run_backtest(request, dispersion_strategy(definition, settings))
    traded = sum(step.filled_quantity for step in outcome.steps)
    active = sum(1 for step in outcome.steps if step.filled_quantity > 0)
    print(f"underlyings:       {len(request.underlying_symbols)}")
    print(f"steps:             {len(outcome.steps)}")
    print(f"steps that traded: {active}")
    print(f"gross profit:      {outcome.gross_profit:>14,.2f}")
    print(f"transaction cost:  {outcome.transaction_cost:>14,.2f}")
    print(f"net profit:        {outcome.net_profit:>14,.2f}")
    print(f"contracts traded:  {traded:>14,}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
