from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.execution import Quote, mid_price  # noqa: E402

POSITION_LIMIT_BREACH: Final[str] = "position_limit"
UNDERLYING_LIMIT_BREACH: Final[str] = "underlying_limit"
GREEK_LIMIT_BREACH: Final[str] = "greek_limit"
ORDER_RATE_BREACH: Final[str] = "order_rate"
FAT_FINGER_BREACH: Final[str] = "fat_finger"
STALE_MARK_BREACH: Final[str] = "stale_mark"
KILL_SWITCH_BREACH: Final[str] = "kill_switch"
UNRECONCILED_BREACH: Final[str] = "unreconciled"
UNMEASURED_BREACH: Final[str] = "unmeasured_position"
RECONCILIATION_DUE_BREACH: Final[str] = "reconciliation_due"


@dataclass(frozen=True)
class ContractGreeks:
    delta: float
    gamma: float
    vega: float
    theta: float


@dataclass(frozen=True)
class GreekBudgets:
    delta: float
    gamma: float
    vega: float
    theta: float


@dataclass(frozen=True)
class RiskLimits:
    reconciliation_interval: timedelta
    position_limit: int
    underlying_limit: int
    greek_budgets: GreekBudgets
    orders_per_window: int
    rate_window: timedelta
    fat_finger_quantity: int
    fat_finger_notional: float
    stale_mark_horizon: timedelta


@dataclass(frozen=True)
class Breach:
    kind: str
    detail: str


def signed_totals(positions: dict[str, int], owner: dict[str, str]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for symbol, quantity in positions.items():
        underlying = owner.get(symbol, symbol)
        totals[underlying] = totals.get(underlying, 0) + abs(quantity)
    return totals


@dataclass(frozen=True)
class BookGreeks:
    totals: ContractGreeks
    unmeasured: list[str]


def aggregate_greeks(
    positions: dict[str, int], greeks: dict[str, ContractGreeks], multipliers: dict[str, int]
) -> BookGreeks:
    delta = gamma = vega = theta = 0.0
    unmeasured: list[str] = []
    for symbol, quantity in sorted(positions.items()):
        leg = greeks.get(symbol)
        if leg is None:
            if quantity != 0:
                unmeasured.append(symbol)
            continue
        scale = quantity * multipliers.get(symbol, 1)
        delta += scale * leg.delta
        gamma += scale * leg.gamma
        vega += scale * leg.vega
        theta += scale * leg.theta
    return BookGreeks(ContractGreeks(delta, gamma, vega, theta), unmeasured)


def unmeasured_breaches(book: BookGreeks) -> list[Breach]:
    return [
        Breach(
            UNMEASURED_BREACH,
            f"{symbol} is held but carries no greeks, so no budget can be checked against it",
        )
        for symbol in book.unmeasured
    ]


def greek_breaches(book: ContractGreeks, budgets: GreekBudgets) -> list[Breach]:
    pairs = (
        ("delta", book.delta, budgets.delta),
        ("gamma", book.gamma, budgets.gamma),
        ("vega", book.vega, budgets.vega),
        ("theta", book.theta, budgets.theta),
    )
    return [
        Breach(GREEK_LIMIT_BREACH, f"{name} of {value:.6g} exceeds a budget of {budget:.6g}")
        for name, value, budget in pairs
        if abs(value) > budget
    ]


def position_breaches(positions: dict[str, int], owner: dict[str, str], limits: RiskLimits) -> list[Breach]:
    breaches: list[Breach] = []
    for symbol, quantity in sorted(positions.items()):
        if abs(quantity) > limits.position_limit:
            breaches.append(
                Breach(
                    POSITION_LIMIT_BREACH,
                    f"{symbol} would hold {quantity} against a limit of {limits.position_limit}",
                )
            )
    for underlying, total in sorted(signed_totals(positions, owner).items()):
        if total > limits.underlying_limit:
            breaches.append(
                Breach(
                    UNDERLYING_LIMIT_BREACH,
                    f"{underlying} would hold {total} contracts against a limit of {limits.underlying_limit}",
                )
            )
    return breaches


def fat_finger_breaches(
    contract_symbol: str, quantity: int, quote: Quote, limits: RiskLimits
) -> list[Breach]:
    breaches: list[Breach] = []
    if abs(quantity) > limits.fat_finger_quantity:
        breaches.append(
            Breach(
                FAT_FINGER_BREACH,
                f"{contract_symbol} order of {quantity} exceeds the single-order bound of "
                f"{limits.fat_finger_quantity}",
            )
        )
    notional = abs(quantity) * mid_price(quote)
    if notional > limits.fat_finger_notional:
        breaches.append(
            Breach(
                FAT_FINGER_BREACH,
                f"{contract_symbol} order notional of {notional:.2f} exceeds "
                f"{limits.fat_finger_notional:.2f}",
            )
        )
    return breaches


def inside_window(recent: list[datetime], moment: datetime, window: timedelta) -> list[datetime]:
    return [stamp for stamp in recent if moment - stamp < window]


def rate_breaches(recent: list[datetime], moment: datetime, limits: RiskLimits) -> list[Breach]:
    inside = inside_window(recent, moment, limits.rate_window)
    if len(inside) >= limits.orders_per_window:
        return [
            Breach(
                ORDER_RATE_BREACH,
                f"{len(inside)} orders in the last {limits.rate_window} reaches a limit of "
                f"{limits.orders_per_window}",
            )
        ]
    return []
