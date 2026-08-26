from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from broker import ACCEPTED, UNKNOWN, MarkedContract, OrderIntent, PaperBroker
from fault_injection import (
    LEG_GREEKS,
    LIMITS,
    MOMENT,
    MULTIPLIER,
    QUOTE,
    SYMBOL,
    UNDERLYING,
    fresh_book,
)
from faults import (
    NO_FAULT,
    PARTIAL_FILL,
    PHANTOM_POSITION,
    SILENTLY_DROPPED,
    STALE_SNAPSHOT,
    UNREACHABLE_AFTER,
    UNREACHABLE_BEFORE,
    FaultInjectingBroker,
)
from gate import BookState, OrderRejectedError, RiskGate
from limits import (
    KILL_SWITCH_BREACH,
    ORDER_RATE_BREACH,
    RECONCILIATION_DUE_BREACH,
    STALE_MARK_BREACH,
    UNMEASURED_BREACH,
)

ORDER = 4
GHOST = "GHOST260918C09999000"
HUGE = 10_000
BURST_ORDERS = 20
FAT_ORDER = 40
PARTIAL = 2


def armed_gate(fault: str = NO_FAULT) -> tuple[RiskGate, FaultInjectingBroker]:
    broker = FaultInjectingBroker(inner=PaperBroker(), fault=NO_FAULT)
    gate = RiskGate(broker=broker, limits=LIMITS)
    gate.reconcile_now(MOMENT)
    broker.fault = fault
    return gate, broker


def book_at(positions: dict[str, int], moment: datetime) -> BookState:
    return BookState(
        positions=positions,
        owner={SYMBOL: UNDERLYING},
        greeks={SYMBOL: LEG_GREEKS},
        multipliers={SYMBOL: MULTIPLIER},
        marks={SYMBOL: MarkedContract(SYMBOL, QUOTE, MULTIPLIER, moment)},
    )


def test_a_clean_order_fills_and_leaves_the_gate_running() -> None:
    gate, broker = armed_gate()
    outcome = gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert outcome.status == ACCEPTED
    assert gate.positions[SYMBOL] == ORDER
    assert broker.inner.positions[SYMBOL] == ORDER
    assert gate.halt_reason is None
    assert gate.reconcile_now(MOMENT) == []


def test_nothing_trades_before_a_clean_reconciliation() -> None:
    gate = RiskGate(broker=PaperBroker(), limits=LIMITS)
    with pytest.raises(OrderRejectedError) as rejection:
        gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert rejection.value.breaches[0].kind == RECONCILIATION_DUE_BREACH


def test_a_reconciliation_goes_out_of_date() -> None:
    gate, _ = armed_gate()
    late = MOMENT + LIMITS.reconciliation_interval + timedelta(minutes=1)
    with pytest.raises(OrderRejectedError) as rejection:
        gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), book_at({}, late), late)
    assert rejection.value.breaches[0].kind == RECONCILIATION_DUE_BREACH


def test_a_halted_gate_refuses_everything() -> None:
    gate, _ = armed_gate()
    gate.halt("the operator said so")
    with pytest.raises(OrderRejectedError) as rejection:
        gate.submit(OrderIntent(SYMBOL, 1, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert rejection.value.breaches[0].kind == KILL_SWITCH_BREACH


def test_resuming_requires_the_books_to_agree() -> None:
    gate, broker = armed_gate(PHANTOM_POSITION)
    assert gate.reconcile_now(MOMENT)
    assert gate.halt_reason is not None
    assert gate.resume(MOMENT)
    assert gate.halt_reason is not None
    broker.fault = NO_FAULT
    assert gate.resume(MOMENT) == []
    assert gate.halt_reason is None


def test_a_stale_mark_blocks_the_order_it_cannot_price() -> None:
    gate, _ = armed_gate()
    late = MOMENT + LIMITS.stale_mark_horizon + timedelta(seconds=1)
    with pytest.raises(OrderRejectedError) as rejection:
        gate.submit(OrderIntent(SYMBOL, 1, QUOTE, MULTIPLIER), fresh_book({}), late)
    assert STALE_MARK_BREACH in {breach.kind for breach in rejection.value.breaches}


def test_a_mark_from_the_future_is_stale_too() -> None:
    gate, _ = armed_gate()
    early = MOMENT - timedelta(minutes=1)
    with pytest.raises(OrderRejectedError) as rejection:
        gate.submit(OrderIntent(SYMBOL, 1, QUOTE, MULTIPLIER), fresh_book({}), early)
    assert STALE_MARK_BREACH in {breach.kind for breach in rejection.value.breaches}


def test_a_position_the_gate_cannot_measure_stops_it_trading() -> None:
    gate, _ = armed_gate()
    gate.positions[GHOST] = HUGE
    with pytest.raises(OrderRejectedError) as rejection:
        gate.submit(OrderIntent(SYMBOL, 1, QUOTE, MULTIPLIER), fresh_book(gate.positions), MOMENT)
    assert UNMEASURED_BREACH in {breach.kind for breach in rejection.value.breaches}


def test_a_fat_finger_never_reaches_the_broker() -> None:
    gate, broker = armed_gate()
    with pytest.raises(OrderRejectedError):
        gate.submit(OrderIntent(SYMBOL, FAT_ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert broker.inner.submitted == 0


def test_a_burst_is_throttled_and_the_log_stays_the_size_of_the_window() -> None:
    gate, _ = armed_gate()
    throttled = 0
    for second in range(BURST_ORDERS):
        moment = MOMENT + timedelta(seconds=second)
        try:
            gate.submit(OrderIntent(SYMBOL, 1, QUOTE, MULTIPLIER), book_at({}, moment), moment)
        except OrderRejectedError as rejection:
            if rejection.breaches[0].kind == ORDER_RATE_BREACH:
                throttled += 1
    assert throttled == BURST_ORDERS - LIMITS.orders_per_window
    assert len(gate.submissions) <= LIMITS.orders_per_window


def test_a_connection_that_dies_before_the_venue_halts_and_still_reconciles() -> None:
    gate, broker = armed_gate(UNREACHABLE_BEFORE)
    outcome = gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert outcome.status == UNKNOWN
    assert gate.halt_reason is not None
    assert gate.positions.get(SYMBOL, 0) == 0
    assert broker.inner.positions.get(SYMBOL, 0) == 0


def test_a_connection_that_dies_after_the_venue_leaves_a_break_the_gate_finds() -> None:
    gate, broker = armed_gate(UNREACHABLE_AFTER)
    gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert gate.halt_reason is not None
    assert gate.positions.get(SYMBOL, 0) == 0
    assert broker.inner.positions[SYMBOL] == ORDER
    broker.fault = NO_FAULT
    assert gate.reconcile_now(MOMENT)


def test_an_order_acknowledged_but_never_executed_is_caught_by_reconciliation() -> None:
    gate, broker = armed_gate(SILENTLY_DROPPED)
    gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert gate.positions[SYMBOL] == ORDER
    assert broker.inner.positions.get(SYMBOL, 0) == 0
    assert gate.reconcile_now(MOMENT)
    assert gate.halt_reason is not None


def test_a_partial_fill_is_believed_rather_than_assumed_away() -> None:
    gate, broker = armed_gate(PARTIAL_FILL)
    outcome = gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    assert outcome.filled_quantity == PARTIAL
    assert gate.positions[SYMBOL] == PARTIAL
    broker.fault = NO_FAULT
    assert gate.reconcile_now(MOMENT) == []
    assert gate.halt_reason is None


def test_a_frozen_broker_snapshot_is_indistinguishable_from_a_break_and_halts() -> None:
    gate, broker = armed_gate()
    broker.freeze(MOMENT)
    gate.submit(OrderIntent(SYMBOL, ORDER, QUOTE, MULTIPLIER), fresh_book({}), MOMENT)
    broker.fault = STALE_SNAPSHOT
    assert gate.reconcile_now(MOMENT)
    assert gate.halt_reason is not None
