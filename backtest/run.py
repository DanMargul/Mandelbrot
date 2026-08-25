#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "research"))

from engine import (  # noqa: E402
    BacktestOutcome,
    BacktestRequest,
    DecisionFunction,
    StepContext,
    run_backtest,
)
from pins import pins_for  # noqa: E402
from registry import record_outcome, register_trial  # noqa: E402
from results import write_return_series  # noqa: E402

STRATEGY_NAME: Final[str] = "short_front_straddle"
STRADDLE_LEGS: Final[int] = 8
STRADDLE_LOTS: Final[int] = 5
EXIT_OK: Final[int] = 0


@dataclass(frozen=True)
class RunConfiguration:
    underlying_symbol: str
    capital: float
    straddle_legs: int
    straddle_lots: int


def configuration_payload(configuration: RunConfiguration) -> dict[str, Any]:
    return {
        "underlying_symbol": configuration.underlying_symbol,
        "capital": configuration.capital,
        "straddle_legs": configuration.straddle_legs,
        "straddle_lots": configuration.straddle_lots,
    }


def short_front_straddle(configuration: RunConfiguration) -> DecisionFunction:
    def decide(context: StepContext) -> dict[str, int]:
        if context.step_index != 0:
            return dict(context.positions)
        target: dict[str, int] = {}
        for quote in context.quotes[: configuration.straddle_legs]:
            lots = configuration.straddle_lots
            target[quote.contract_symbol] = -lots if quote.option_type == "call" else lots
        return target

    return decide


def step_times_from(text: str) -> list[datetime]:
    return [datetime.fromisoformat(entry) for entry in text.split(",")]


def report(outcome: BacktestOutcome, digest: str, trial_id: str) -> None:
    print(f"underlying:        {outcome.underlying_symbol}")
    print(f"dataset digest:    {outcome.dataset_digest[:16]}...")
    print(f"steps:             {len(outcome.steps)}")
    print(f"gross profit:      {outcome.gross_profit:,.2f}")
    print(f"transaction cost:  {outcome.transaction_cost:,.2f}")
    print(f"net profit:        {outcome.net_profit:,.2f}")
    print(f"trial:             {trial_id}")
    print(f"return series:     {digest[:16]}...")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="backtest")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--underlying", required=True)
    parser.add_argument("--steps", required=True)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    arguments = parser.parse_args(argv)

    configuration = RunConfiguration(
        underlying_symbol=arguments.underlying,
        capital=arguments.capital,
        straddle_legs=STRADDLE_LEGS,
        straddle_lots=STRADDLE_LOTS,
    )
    payload = configuration_payload(configuration)
    pins = pins_for(REPOSITORY_ROOT, payload, seed=0, dataset_root=arguments.dataset)
    started = register_trial(arguments.registry, STRATEGY_NAME, payload, pins)

    outcome = run_backtest(
        BacktestRequest(
            dataset_root=arguments.dataset,
            underlying_symbol=configuration.underlying_symbol,
            step_times=step_times_from(arguments.steps),
            capital=configuration.capital,
        ),
        short_front_straddle(configuration),
    )
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
            "transaction_cost": outcome.transaction_cost,
            "return_series_digest": stored.digest,
            "observation_count": stored.observation_count,
        },
    )
    report(outcome, stored.digest, started.trial_id)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
