#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "research"))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from allocator_decision import (  # noqa: E402
    BookSettings,
    ContractState,
    allocated_book,
)
from engine import BacktestRequest, StepContext, run_backtest  # noqa: E402
from pins import pins_for  # noqa: E402
from registry import record_outcome, register_trial  # noqa: E402
from results import write_return_series  # noqa: E402
from volarb_py.factors import (  # noqa: E402
    SurfacePoint,
    orthonormal_basis,
    project_onto,
    raw_factor_vectors,
    reconstruct_from,
    score_residual,
)
from volarb_py.implied_vol import (  # noqa: E402
    ImpliedVolatilityInputs,
    invert_black_implied_volatility,
)
from volarb_py.market_data import ContractQuote  # noqa: E402

STRATEGY_NAME: Final[str] = "residual_convergence"
OBSERVATION_HOUR_UTC: Final[int] = 20
RISK_FREE_RATE: Final[float] = 0.0425
DAYS_PER_YEAR: Final[float] = 365.0
SETTLEMENT_HOUR_UTC: Final[int] = 21
WARMUP_STEPS: Final[int] = 40
ENTRY_Z_SCORE: Final[float] = 1.5
LOT_SIZE: Final[int] = 5
LAST_WEEKDAY: Final[int] = 5
MINIMUM_SURFACE_POINTS: Final[int] = 6
EXIT_OK: Final[int] = 0

DecisionFunction = Callable[[StepContext], dict[str, int]]


@dataclass(frozen=True)
class StrategySettings:
    underlying_symbol: str
    entry_z_score: float
    lot_size: int
    warmup_steps: int
    use_allocator: bool


def settings_payload(settings: StrategySettings) -> dict[str, Any]:
    return {
        "underlying_symbol": settings.underlying_symbol,
        "entry_z_score": settings.entry_z_score,
        "lot_size": settings.lot_size,
        "warmup_steps": settings.warmup_steps,
        "use_allocator": settings.use_allocator,
    }


def years_to_expiry(moment: datetime, quote: ContractQuote) -> float:
    settlement = datetime(
        quote.expiry_date.year,
        quote.expiry_date.month,
        quote.expiry_date.day,
        SETTLEMENT_HOUR_UTC,
        tzinfo=UTC,
    )
    return (settlement - moment).total_seconds() / (DAYS_PER_YEAR * 24.0 * 3600.0)


def implied_volatility_of(moment: datetime, quote: ContractQuote) -> float | None:
    years = years_to_expiry(moment, quote)
    if years <= 0.0:
        return None
    discount = math.exp(-RISK_FREE_RATE * years)
    mid = 0.5 * (quote.bid_price + quote.ask_price)
    inverted = invert_black_implied_volatility(
        ImpliedVolatilityInputs(
            forward=quote.underlying_price / discount,
            strike=quote.strike,
            years_to_expiry=years,
            discount_factor=discount,
            option_price=mid,
            option_type=quote.option_type,
        )
    )
    return inverted.volatility if inverted.status == "converged" else None


def surface_observation(
    moment: datetime, quotes: list[ContractQuote]
) -> tuple[list[str], list[SurfacePoint], list[float]]:
    symbols: list[str] = []
    grid: list[SurfacePoint] = []
    values: list[float] = []
    for quote in quotes:
        volatility = implied_volatility_of(moment, quote)
        years = years_to_expiry(moment, quote)
        if volatility is None or volatility <= 0.0 or years <= 0.0:
            continue
        discount = math.exp(-RISK_FREE_RATE * years)
        forward = quote.underlying_price / discount
        symbols.append(quote.contract_symbol)
        grid.append(SurfacePoint(log_moneyness=math.log(quote.strike / forward), years_to_expiry=years))
        values.append(math.log(volatility * volatility * years))
    return symbols, grid, values


def surface_residuals(moment: datetime, quotes: list[ContractQuote]) -> dict[str, float]:
    return observed_surface(moment, quotes).residuals


@dataclass(frozen=True)
class ObservedSurface:
    residuals: dict[str, float]
    states: list[ContractState]
    factor_exposures: dict[str, list[float]]


def contract_state(moment: datetime, quote: ContractQuote, volatility: float) -> ContractState:
    years = years_to_expiry(moment, quote)
    discount = math.exp(-RISK_FREE_RATE * years)
    forward = quote.underlying_price / discount
    return ContractState(
        contract_symbol=quote.contract_symbol,
        grid_point=SurfacePoint(log_moneyness=math.log(quote.strike / forward), years_to_expiry=years),
        forward=forward,
        strike=quote.strike,
        discount_factor=discount,
        option_type=quote.option_type,
        volatility=volatility,
        half_spread=0.5 * (quote.ask_price - quote.bid_price),
        contract_multiplier=quote.contract_multiplier,
    )


def observed_surface(moment: datetime, quotes: list[ContractQuote]) -> ObservedSurface:
    states: list[ContractState] = []
    values: list[float] = []
    for quote in quotes:
        volatility = implied_volatility_of(moment, quote)
        if volatility is None or volatility <= 0.0 or years_to_expiry(moment, quote) <= 0.0:
            continue
        state = contract_state(moment, quote, volatility)
        states.append(state)
        values.append(math.log(volatility * volatility * state.grid_point.years_to_expiry))
    grid = [state.grid_point for state in states]
    if len(grid) < MINIMUM_SURFACE_POINTS:
        return ObservedSurface({}, [], {})
    basis = orthonormal_basis(raw_factor_vectors(grid))
    if not basis:
        return ObservedSurface({}, [], {})
    fitted = reconstruct_from(basis, project_onto(basis, values))
    residuals = {
        state.contract_symbol: value - approximation
        for state, value, approximation in zip(states, values, fitted, strict=True)
    }
    exposures = {
        state.contract_symbol: [vector[index] for vector in basis] for index, state in enumerate(states)
    }
    return ObservedSurface(residuals, states, exposures)


def business_days(count: int) -> list[datetime]:
    days: list[datetime] = []
    current = datetime(2026, 1, 5, OBSERVATION_HOUR_UTC, tzinfo=UTC)
    while len(days) < count:
        if current.weekday() < LAST_WEEKDAY:
            days.append(current)
        current += timedelta(days=1)
    return days


def threshold_book(histories: dict[str, list[float]], settings: StrategySettings) -> dict[str, int]:
    target: dict[str, int] = {}
    for symbol, series in sorted(histories.items()):
        if len(series) < settings.warmup_steps:
            continue
        score = score_residual(series)
        if score.residual_is_degenerate:
            continue
        if score.naive_z_score > settings.entry_z_score:
            target[symbol] = -settings.lot_size
        elif score.naive_z_score < -settings.entry_z_score:
            target[symbol] = settings.lot_size
    return target


def residual_strategy(settings: StrategySettings) -> DecisionFunction:
    histories: dict[str, list[float]] = {}

    def decide(context: StepContext) -> dict[str, int]:
        surface = observed_surface(context.observation_time, context.quotes)
        for symbol, value in surface.residuals.items():
            histories.setdefault(symbol, []).append(value)
        if context.step_index < settings.warmup_steps:
            return {}
        if not settings.use_allocator:
            return threshold_book(histories, settings)
        spot = surface.states[0].forward if surface.states else 1.0
        book, _ = allocated_book(
            surface.states,
            histories,
            BookSettings(settings.lot_size, spot, surface.factor_exposures),
        )
        return book

    return decide


def report(outcome: Any, settings: StrategySettings) -> None:
    print(f"underlying:        {settings.underlying_symbol}")
    print(f"steps:             {len(outcome.steps)}")
    print(f"gross profit:      {outcome.gross_profit:>14,.2f}")
    print(f"transaction cost:  {outcome.transaction_cost:>14,.2f}")
    print(f"net profit:        {outcome.net_profit:>14,.2f}")
    traded = sum(step.filled_quantity for step in outcome.steps)
    print(f"contracts traded:  {traded:>14,}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="residual-backtest")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--underlying", required=True)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--entry-z", type=float, default=ENTRY_Z_SCORE)
    parser.add_argument("--allocator", action="store_true")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--results", type=Path)
    arguments = parser.parse_args(argv)

    settings = StrategySettings(
        underlying_symbol=arguments.underlying,
        entry_z_score=arguments.entry_z,
        lot_size=LOT_SIZE,
        warmup_steps=WARMUP_STEPS,
        use_allocator=arguments.allocator,
    )
    request = BacktestRequest(
        dataset_root=arguments.dataset,
        underlying_symbol=settings.underlying_symbol,
        step_times=business_days(arguments.steps),
        capital=arguments.capital,
    )
    started = None
    if arguments.registry is not None:
        pins = pins_for(REPOSITORY_ROOT, settings_payload(settings), seed=0, dataset_root=arguments.dataset)
        started = register_trial(arguments.registry, STRATEGY_NAME, settings_payload(settings), pins)

    outcome = run_backtest(request, residual_strategy(settings))
    report(outcome, settings)

    if started is not None and arguments.results is not None:
        stored = write_return_series(
            arguments.results,
            started.trial_id,
            outcome.dataset_digest,
            outcome.returns,
            {"gross_profit": outcome.gross_profit, "transaction_cost": outcome.transaction_cost},
        )
        record_outcome(
            arguments.registry,
            started,
            {
                "net_profit": outcome.net_profit,
                "gross_profit": outcome.gross_profit,
                "transaction_cost": outcome.transaction_cost,
                "return_series_digest": stored.digest,
            },
        )
        print(f"trial:             {started.trial_id}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
