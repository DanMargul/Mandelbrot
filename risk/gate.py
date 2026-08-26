from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from broker import (
    ACCEPTED,
    UNKNOWN,
    Broker,
    BrokerUnreachableError,
    MarkedContract,
    OrderIntent,
    OrderOutcome,
    stale_marks,
)
from limits import (
    KILL_SWITCH_BREACH,
    RECONCILIATION_DUE_BREACH,
    STALE_MARK_BREACH,
    Breach,
    ContractGreeks,
    RiskLimits,
    aggregate_greeks,
    fat_finger_breaches,
    greek_breaches,
    inside_window,
    position_breaches,
    rate_breaches,
    unmeasured_breaches,
)
from reconcile import breaches_from, reconcile

HALTED_BY_OPERATOR: Final[str] = "halted by the operator"
HALTED_BY_BREAK: Final[str] = "halted by a reconciliation break"
HALTED_BY_UNKNOWN_ORDER: Final[str] = "halted by an order of unknown outcome"


class OrderRejectedError(RuntimeError):
    def __init__(self, breaches: list[Breach]) -> None:
        super().__init__("; ".join(f"{breach.kind}: {breach.detail}" for breach in breaches))
        self.breaches = breaches


@dataclass(frozen=True)
class BookState:
    positions: dict[str, int]
    owner: dict[str, str]
    greeks: dict[str, ContractGreeks]
    multipliers: dict[str, int]
    marks: dict[str, MarkedContract]


@dataclass
class RiskGate:
    broker: Broker
    limits: RiskLimits
    positions: dict[str, int] = field(default_factory=dict)
    cash: float = 0.0
    submissions: list[datetime] = field(default_factory=list)
    halt_reason: str | None = None
    rejected: int = 0
    accepted: int = 0
    last_clean_reconciliation: datetime | None = None

    def halt(self, reason: str) -> None:
        self.halt_reason = reason

    def resume(self, moment: datetime) -> list[Breach]:
        report = reconcile(self.positions, self.cash, self.broker.snapshot(moment))
        if not report.is_clean:
            self.halt(HALTED_BY_BREAK)
            return breaches_from(report)
        self.last_clean_reconciliation = moment
        self.halt_reason = None
        return []

    def reconcile_now(self, moment: datetime) -> list[Breach]:
        report = reconcile(self.positions, self.cash, self.broker.snapshot(moment))
        if report.is_clean:
            self.last_clean_reconciliation = moment
            return []
        self.halt(HALTED_BY_BREAK)
        return breaches_from(report)

    def reconciliation_breaches(self, moment: datetime) -> list[Breach]:
        stamp = self.last_clean_reconciliation
        if stamp is None:
            return [Breach(RECONCILIATION_DUE_BREACH, "no clean reconciliation has been recorded")]
        if moment - stamp > self.limits.reconciliation_interval:
            return [
                Breach(
                    RECONCILIATION_DUE_BREACH,
                    f"the last clean reconciliation was at {stamp:%Y-%m-%d %H:%M:%S}, "
                    f"beyond an interval of {self.limits.reconciliation_interval}",
                )
            ]
        return []

    def projected(self, intent: OrderIntent) -> dict[str, int]:
        projected = dict(self.positions)
        projected[intent.contract_symbol] = projected.get(intent.contract_symbol, 0) + intent.quantity
        return projected

    def pre_trade_breaches(self, intent: OrderIntent, book: BookState, moment: datetime) -> list[Breach]:
        if self.halt_reason is not None:
            return [Breach(KILL_SWITCH_BREACH, self.halt_reason)]
        breaches = self.reconciliation_breaches(moment)
        breaches.extend(rate_breaches(self.submissions, moment, self.limits))
        breaches.extend(
            fat_finger_breaches(intent.contract_symbol, intent.quantity, intent.quote, self.limits)
        )
        stale = stale_marks(book.marks, moment, self.limits.stale_mark_horizon)
        if stale:
            breaches.append(Breach(STALE_MARK_BREACH, f"marks not refreshed for {', '.join(stale)}"))
        projected = self.projected(intent)
        breaches.extend(position_breaches(projected, book.owner, self.limits))
        aggregate = aggregate_greeks(projected, book.greeks, book.multipliers)
        breaches.extend(unmeasured_breaches(aggregate))
        breaches.extend(greek_breaches(aggregate.totals, self.limits.greek_budgets))
        return breaches

    def submit(self, intent: OrderIntent, book: BookState, moment: datetime) -> OrderOutcome:
        breaches = self.pre_trade_breaches(intent, book, moment)
        if breaches:
            self.rejected += 1
            raise OrderRejectedError(breaches)
        self.submissions = inside_window(self.submissions, moment, self.limits.rate_window)
        self.submissions.append(moment)
        try:
            outcome = self.broker.submit(intent, moment)
        except BrokerUnreachableError:
            self.halt(HALTED_BY_UNKNOWN_ORDER)
            self.record_uncertainty()
            return OrderOutcome(
                order_id="",
                contract_symbol=intent.contract_symbol,
                requested_quantity=intent.quantity,
                filled_quantity=0,
                cash_flow=0.0,
                status=UNKNOWN,
            )
        if outcome.status == ACCEPTED:
            self.accepted += 1
            self.positions[intent.contract_symbol] = (
                self.positions.get(intent.contract_symbol, 0) + outcome.filled_quantity
            )
            self.cash += outcome.cash_flow
        return outcome

    def record_uncertainty(self) -> None:
        self.last_clean_reconciliation = None
