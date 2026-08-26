from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from broker import (
    ACCEPTED,
    BrokerSnapshot,
    BrokerUnreachableError,
    OrderIntent,
    OrderOutcome,
    PaperBroker,
)

NO_FAULT: Final[str] = "none"
UNREACHABLE_BEFORE: Final[str] = "unreachable_before_the_venue_saw_it"
UNREACHABLE_AFTER: Final[str] = "unreachable_after_the_venue_took_it"
SILENTLY_DROPPED: Final[str] = "acknowledged_but_never_executed"
PARTIAL_FILL: Final[str] = "filled_in_part"
PHANTOM_POSITION: Final[str] = "broker_reports_a_position_we_never_sent"
STALE_SNAPSHOT: Final[str] = "broker_snapshot_frozen_in_the_past"


@dataclass
class FaultInjectingBroker:
    inner: PaperBroker = field(default_factory=PaperBroker)
    fault: str = NO_FAULT
    partial_fraction: float = 0.5
    phantom_symbol: str = "GHOST"
    phantom_quantity: int = 7
    frozen: BrokerSnapshot | None = None

    def submit(self, intent: OrderIntent, moment: datetime) -> OrderOutcome:
        if self.fault == UNREACHABLE_BEFORE:
            raise BrokerUnreachableError("the connection died before the venue saw the order")
        if self.fault == SILENTLY_DROPPED:
            return OrderOutcome(
                order_id=self.inner.next_order_id(),
                contract_symbol=intent.contract_symbol,
                requested_quantity=intent.quantity,
                filled_quantity=intent.quantity,
                cash_flow=0.0,
                status=ACCEPTED,
            )
        if self.fault == PARTIAL_FILL:
            reduced = int(intent.quantity * self.partial_fraction)
            if reduced == 0:
                reduced = 1 if intent.quantity > 0 else -1
            intent = OrderIntent(intent.contract_symbol, reduced, intent.quote, intent.contract_multiplier)
        outcome = self.inner.submit(intent, moment)
        if self.fault == UNREACHABLE_AFTER:
            raise BrokerUnreachableError("the connection died after the venue took the order")
        return outcome

    def snapshot(self, moment: datetime) -> BrokerSnapshot:
        if self.fault == STALE_SNAPSHOT and self.frozen is not None:
            return self.frozen
        taken = self.inner.snapshot(moment)
        if self.fault == PHANTOM_POSITION:
            positions = dict(taken.positions)
            positions[self.phantom_symbol] = self.phantom_quantity
            return BrokerSnapshot(taken.taken_at, positions, taken.cash)
        return taken

    def freeze(self, moment: datetime) -> None:
        self.frozen = self.inner.snapshot(moment)
