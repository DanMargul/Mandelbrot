from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.execution import OrderSide, Quote, fill_at_touch, mid_price  # noqa: E402
from volarb_py.market_data import (  # noqa: E402
    AsOfChainReader,
    ChainQuery,
    ContractQuote,
    KnowledgeHorizon,
    open_chain_dataset,
)

MINIMUM_CAPITAL: Final[float] = 1e-9


class InvalidBacktestError(ValueError):
    pass


@dataclass(frozen=True)
class BacktestRequest:
    dataset_root: Path
    underlying_symbol: str
    step_times: list[datetime]
    capital: float


@dataclass(frozen=True)
class StepContext:
    step_index: int
    observation_time: datetime
    quotes: list[ContractQuote]
    positions: dict[str, int]


@dataclass(frozen=True)
class BacktestStep:
    observation_time: datetime
    quote_count: int
    marked_value: float
    holding_profit: float
    transaction_cost: float
    net_profit: float
    filled_quantity: int
    unfilled_quantity: int
    stale_mark_count: int


@dataclass(frozen=True)
class BacktestOutcome:
    underlying_symbol: str
    dataset_digest: str
    capital: float
    steps: list[BacktestStep]
    returns: list[float]
    gross_profit: float
    transaction_cost: float
    net_profit: float


DecisionFunction = Callable[[StepContext], dict[str, int]]
ReaderFactory = Callable[[Path, datetime], AsOfChainReader]


def reader_at_step(dataset_root: Path, moment: datetime) -> AsOfChainReader:
    return open_chain_dataset(dataset_root, KnowledgeHorizon(as_of=moment))


def validate_run(step_times: list[datetime], capital: float) -> None:
    if not step_times:
        raise InvalidBacktestError("a backtest needs at least one step")
    if capital <= MINIMUM_CAPITAL:
        raise InvalidBacktestError(f"capital must be positive, got {capital}")
    for earlier, later in pairwise(step_times):
        if later <= earlier:
            raise InvalidBacktestError("step times must be strictly increasing")


def quotes_by_symbol(quotes: list[ContractQuote]) -> dict[str, ContractQuote]:
    return {quote.contract_symbol: quote for quote in quotes}


def quote_of(quote: ContractQuote) -> Quote:
    return Quote(
        bid_price=quote.bid_price,
        ask_price=quote.ask_price,
        bid_size=quote.bid_size,
        ask_size=quote.ask_size,
    )


@dataclass(frozen=True)
class ContractMark:
    price: float
    contract_multiplier: int


@dataclass(frozen=True)
class MarkResult:
    value: float
    marks: dict[str, ContractMark]
    stale_count: int


def mark_positions(
    positions: dict[str, int],
    available: dict[str, ContractQuote],
    previous_marks: dict[str, ContractMark],
) -> MarkResult:
    value = 0.0
    marks: dict[str, ContractMark] = dict(previous_marks)
    stale = 0
    for symbol in sorted(positions):
        quantity = positions[symbol]
        if quantity == 0:
            continue
        quote = available.get(symbol)
        if quote is None:
            carried = previous_marks.get(symbol)
            if carried is None:
                raise InvalidBacktestError(f"{symbol} is held but has never been quoted")
            stale += 1
            marks[symbol] = carried
        else:
            marks[symbol] = ContractMark(
                price=mid_price(quote_of(quote)), contract_multiplier=quote.contract_multiplier
            )
        value += quantity * marks[symbol].price * marks[symbol].contract_multiplier
    return MarkResult(value=value, marks=marks, stale_count=stale)


@dataclass(frozen=True)
class TradeResult:
    cost: float
    filled: int
    unfilled: int
    positions: dict[str, int]


def trade_towards(
    positions: dict[str, int], target: dict[str, int], available: dict[str, ContractQuote]
) -> TradeResult:
    updated = dict(positions)
    cost = 0.0
    filled = 0
    unfilled = 0
    for symbol in sorted(set(positions) | set(target)):
        wanted = target.get(symbol, 0) - positions.get(symbol, 0)
        if wanted == 0:
            continue
        quote = available.get(symbol)
        if quote is None:
            unfilled += abs(wanted)
            continue
        side: OrderSide = "buy" if wanted > 0 else "sell"
        fill = fill_at_touch(quote_of(quote), side, abs(wanted), quote.contract_multiplier)
        cost += fill.cost_against_mid
        filled += fill.filled_quantity
        unfilled += fill.requested_quantity - fill.filled_quantity
        signed = fill.filled_quantity if wanted > 0 else -fill.filled_quantity
        updated[symbol] = positions.get(symbol, 0) + signed
    return TradeResult(cost=cost, filled=filled, unfilled=unfilled, positions=updated)


def run_backtest(
    request: BacktestRequest,
    decide: DecisionFunction,
    open_reader: ReaderFactory = reader_at_step,
) -> BacktestOutcome:
    validate_run(request.step_times, request.capital)

    positions: dict[str, int] = {}
    previous_marks: dict[str, ContractMark] = {}
    previous_value = 0.0
    steps: list[BacktestStep] = []
    returns: list[float] = []
    gross = 0.0
    total_cost = 0.0
    dataset_digest = ""

    for index, moment in enumerate(request.step_times):
        reader = open_reader(request.dataset_root, moment)
        dataset_digest = reader.dataset_digest
        quotes = reader.chain_as_of(
            ChainQuery(underlying_symbol=request.underlying_symbol, observation_time=moment)
        )
        available = quotes_by_symbol(quotes)

        opening = mark_positions(positions, available, previous_marks)
        holding_profit = opening.value - previous_value

        target = decide(
            StepContext(
                step_index=index,
                observation_time=moment,
                quotes=quotes,
                positions=dict(positions),
            )
        )
        trade = trade_towards(positions, target, available)
        positions = trade.positions

        closing = mark_positions(positions, available, opening.marks)
        net = holding_profit - trade.cost
        gross += holding_profit
        total_cost += trade.cost

        steps.append(
            BacktestStep(
                observation_time=moment,
                quote_count=len(quotes),
                marked_value=closing.value,
                holding_profit=holding_profit,
                transaction_cost=trade.cost,
                net_profit=net,
                filled_quantity=trade.filled,
                unfilled_quantity=trade.unfilled,
                stale_mark_count=opening.stale_count,
            )
        )
        returns.append(net / request.capital)
        previous_marks = closing.marks
        previous_value = closing.value

    return BacktestOutcome(
        underlying_symbol=request.underlying_symbol,
        dataset_digest=dataset_digest,
        capital=request.capital,
        steps=steps,
        returns=returns,
        gross_profit=gross,
        transaction_cost=total_cost,
        net_profit=gross - total_cost,
    )
