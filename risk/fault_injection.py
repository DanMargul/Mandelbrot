#!/usr/bin/env python3
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from broker import MarkedContract, OrderIntent, PaperBroker  # noqa: E402
from faults import (  # noqa: E402
    NO_FAULT,
    PARTIAL_FILL,
    PHANTOM_POSITION,
    SILENTLY_DROPPED,
    STALE_SNAPSHOT,
    UNREACHABLE_AFTER,
    UNREACHABLE_BEFORE,
    FaultInjectingBroker,
)
from gate import BookState, OrderRejectedError, RiskGate  # noqa: E402
from limits import ContractGreeks, GreekBudgets, RiskLimits  # noqa: E402
from reconcile import reconcile  # noqa: E402
from volarb_py.execution import Quote  # noqa: E402

MOMENT: Final[datetime] = datetime(2026, 8, 25, 15, 0, 0, tzinfo=UTC)
SYMBOL: Final[str] = "SPX260918C05000000"
UNDERLYING: Final[str] = "SPX"
MULTIPLIER: Final[int] = 100
ORDER_QUANTITY: Final[int] = 4
QUOTE: Final[Quote] = Quote(bid_price=41.0, ask_price=42.0, bid_size=50, ask_size=50)
LEG_GREEKS: Final[ContractGreeks] = ContractGreeks(delta=0.52, gamma=0.0009, vega=8.4, theta=-2.1)
EXIT_OK: Final[int] = 0

LIMITS: Final[RiskLimits] = RiskLimits(
    reconciliation_interval=timedelta(minutes=30),
    position_limit=25,
    underlying_limit=40,
    greek_budgets=GreekBudgets(delta=5_000.0, gamma=10.0, vega=40_000.0, theta=8_000.0),
    orders_per_window=6,
    rate_window=timedelta(minutes=1),
    fat_finger_quantity=20,
    fat_finger_notional=250_000.0,
    stale_mark_horizon=timedelta(minutes=5),
)


@dataclass(frozen=True)
class InjectionResult:
    fault: str
    raised: str
    halted: bool
    our_position: int
    their_position: int
    reconciled: bool


def fresh_book(positions: dict[str, int]) -> BookState:
    return BookState(
        positions=positions,
        owner={SYMBOL: UNDERLYING},
        greeks={SYMBOL: LEG_GREEKS},
        multipliers={SYMBOL: MULTIPLIER},
        marks={SYMBOL: MarkedContract(SYMBOL, QUOTE, MULTIPLIER, MOMENT)},
    )


def inject(fault: str) -> InjectionResult:
    broker = FaultInjectingBroker(inner=PaperBroker(), fault=fault)
    gate = RiskGate(broker=broker, limits=LIMITS)
    if fault == STALE_SNAPSHOT:
        broker.freeze(MOMENT)
    gate.reconcile_now(MOMENT)
    intent = OrderIntent(SYMBOL, ORDER_QUANTITY, QUOTE, MULTIPLIER)
    raised = "-"
    try:
        gate.submit(intent, fresh_book(gate.positions), MOMENT)
    except OrderRejectedError as rejection:
        raised = f"rejected: {rejection.breaches[0].kind}"
    except Exception as failure:
        raised = type(failure).__name__
    after = gate.reconcile_now(MOMENT)
    report = reconcile(gate.positions, gate.cash, broker.snapshot(MOMENT))
    return InjectionResult(
        fault=fault,
        raised=raised if raised != "-" or not after else f"break: {len(after)}",
        halted=gate.halt_reason is not None,
        our_position=gate.positions.get(SYMBOL, 0),
        their_position=broker.inner.positions.get(SYMBOL, 0),
        reconciled=report.is_clean,
    )


def main() -> int:
    faults = (
        NO_FAULT,
        UNREACHABLE_BEFORE,
        UNREACHABLE_AFTER,
        SILENTLY_DROPPED,
        PARTIAL_FILL,
        PHANTOM_POSITION,
        STALE_SNAPSHOT,
    )
    header = f"{'fault':<42} {'raised':<22} {'halted':>7} {'ours':>5} {'theirs':>7} {'clean':>6}"
    print(header)
    print("-" * len(header))
    for fault in faults:
        result = inject(fault)
        print(
            f"{result.fault:<42} {result.raised:<22} {result.halted!s:>7} "
            f"{result.our_position:>5} {result.their_position:>7} {result.reconciled!s:>6}"
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
