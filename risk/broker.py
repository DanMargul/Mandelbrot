from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, Protocol

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.execution import (  # noqa: E402
    OrderSide,
    Quote,
    fill_at_touch,
)

ACCEPTED: Final[str] = "accepted"
REJECTED: Final[str] = "rejected"
UNKNOWN: Final[str] = "unknown"


class BrokerError(RuntimeError):
    pass


class BrokerUnreachableError(BrokerError):
    pass


@dataclass(frozen=True)
class OrderIntent:
    contract_symbol: str
    quantity: int
    quote: Quote
    contract_multiplier: int


@dataclass(frozen=True)
class OrderOutcome:
    order_id: str
    contract_symbol: str
    requested_quantity: int
    filled_quantity: int
    cash_flow: float
    status: str


@dataclass(frozen=True)
class BrokerSnapshot:
    taken_at: datetime
    positions: dict[str, int]
    cash: float


class Broker(Protocol):
    def submit(self, intent: OrderIntent, moment: datetime) -> OrderOutcome: ...

    def snapshot(self, moment: datetime) -> BrokerSnapshot: ...


def side_of(quantity: int) -> OrderSide:
    return "buy" if quantity > 0 else "sell"


@dataclass
class PaperBroker:
    positions: dict[str, int] = field(default_factory=dict)
    cash: float = 0.0
    submitted: int = 0
    last_submission: datetime | None = None

    def submit(self, intent: OrderIntent, moment: datetime) -> OrderOutcome:
        self.submitted += 1
        self.last_submission = moment
        if intent.quantity == 0:
            return OrderOutcome(self.next_order_id(), intent.contract_symbol, 0, 0, 0.0, REJECTED)
        side = side_of(intent.quantity)
        fill = fill_at_touch(intent.quote, side, abs(intent.quantity), intent.contract_multiplier)
        signed = fill.filled_quantity if intent.quantity > 0 else -fill.filled_quantity
        notional = fill.filled_quantity * fill.touch_price * intent.contract_multiplier
        cash_flow = -notional if intent.quantity > 0 else notional
        self.positions[intent.contract_symbol] = self.positions.get(intent.contract_symbol, 0) + signed
        self.cash += cash_flow
        return OrderOutcome(
            order_id=self.next_order_id(),
            contract_symbol=intent.contract_symbol,
            requested_quantity=intent.quantity,
            filled_quantity=signed,
            cash_flow=cash_flow,
            status=ACCEPTED,
        )

    def next_order_id(self) -> str:
        return f"paper-{self.submitted:06d}"

    def snapshot(self, moment: datetime) -> BrokerSnapshot:
        return BrokerSnapshot(moment, dict(self.positions), self.cash)


@dataclass(frozen=True)
class MarkedContract:
    contract_symbol: str
    quote: Quote
    contract_multiplier: int
    quoted_at: datetime


def stale_marks(marks: dict[str, MarkedContract], moment: datetime, horizon: timedelta) -> list[str]:
    return sorted(
        symbol
        for symbol, mark in marks.items()
        if moment - mark.quoted_at > horizon or mark.quoted_at > moment
    )
