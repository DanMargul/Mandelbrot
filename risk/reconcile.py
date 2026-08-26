from __future__ import annotations

from dataclasses import dataclass

from broker import BrokerSnapshot
from limits import UNRECONCILED_BREACH, Breach

CASH_TOLERANCE = 0.005


@dataclass(frozen=True)
class PositionBreak:
    contract_symbol: str
    ours: int
    theirs: int


@dataclass(frozen=True)
class Reconciliation:
    checked_contracts: int
    position_breaks: list[PositionBreak]
    cash_difference: float
    is_clean: bool


def reconcile(ours: dict[str, int], cash: float, theirs: BrokerSnapshot) -> Reconciliation:
    symbols = sorted(set(ours) | set(theirs.positions))
    breaks = [
        PositionBreak(symbol, ours.get(symbol, 0), theirs.positions.get(symbol, 0))
        for symbol in symbols
        if ours.get(symbol, 0) != theirs.positions.get(symbol, 0)
    ]
    difference = cash - theirs.cash
    return Reconciliation(
        checked_contracts=len(symbols),
        position_breaks=breaks,
        cash_difference=difference,
        is_clean=not breaks and abs(difference) <= CASH_TOLERANCE,
    )


def breaches_from(report: Reconciliation) -> list[Breach]:
    breaches = [
        Breach(
            UNRECONCILED_BREACH,
            f"{entry.contract_symbol}: we hold {entry.ours}, the broker holds {entry.theirs}",
        )
        for entry in report.position_breaks
    ]
    if abs(report.cash_difference) > CASH_TOLERANCE:
        breaches.append(Breach(UNRECONCILED_BREACH, f"cash differs by {report.cash_difference:.4f}"))
    return breaches
