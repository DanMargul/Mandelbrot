from __future__ import annotations

from broker import BrokerSnapshot
from fault_injection import MOMENT, SYMBOL
from limits import UNRECONCILED_BREACH
from reconcile import CASH_TOLERANCE, breaches_from, reconcile

OTHER = "SPX260918P05000000"
HELD = 4
CASH = -16_800.0
INSIDE_TOLERANCE = CASH_TOLERANCE / 2.0
OUTSIDE_TOLERANCE = CASH_TOLERANCE * 2.0
BOTH_CONTRACTS = 2


def snapshot(positions: dict[str, int], cash: float) -> BrokerSnapshot:
    return BrokerSnapshot(MOMENT, positions, cash)


def test_agreeing_books_reconcile() -> None:
    report = reconcile({SYMBOL: HELD}, CASH, snapshot({SYMBOL: HELD}, CASH))
    assert report.is_clean
    assert report.position_breaks == []
    assert breaches_from(report) == []


def test_a_position_we_hold_and_they_do_not_is_a_break() -> None:
    report = reconcile({SYMBOL: HELD}, CASH, snapshot({}, CASH))
    assert not report.is_clean
    assert report.position_breaks[0].ours == HELD
    assert report.position_breaks[0].theirs == 0


def test_a_position_they_hold_and_we_do_not_is_a_break() -> None:
    report = reconcile({}, CASH, snapshot({SYMBOL: HELD}, CASH))
    assert not report.is_clean
    assert report.position_breaks[0].ours == 0
    assert report.position_breaks[0].theirs == HELD


def test_every_contract_is_checked_not_only_the_ones_we_know() -> None:
    report = reconcile({SYMBOL: HELD}, CASH, snapshot({OTHER: HELD}, CASH))
    assert report.checked_contracts == BOTH_CONTRACTS
    assert len(report.position_breaks) == BOTH_CONTRACTS


def test_cash_inside_the_tolerance_is_not_a_break() -> None:
    report = reconcile({SYMBOL: HELD}, CASH, snapshot({SYMBOL: HELD}, CASH + INSIDE_TOLERANCE))
    assert report.is_clean


def test_cash_outside_the_tolerance_is_a_break_even_when_positions_agree() -> None:
    report = reconcile({SYMBOL: HELD}, CASH, snapshot({SYMBOL: HELD}, CASH + OUTSIDE_TOLERANCE))
    assert not report.is_clean
    assert report.position_breaks == []
    assert breaches_from(report)[0].kind == UNRECONCILED_BREACH


def test_an_empty_book_on_both_sides_reconciles() -> None:
    report = reconcile({}, 0.0, snapshot({}, 0.0))
    assert report.is_clean
    assert report.checked_contracts == 0


def test_a_flat_position_on_one_side_only_still_agrees() -> None:
    assert reconcile({SYMBOL: 0}, 0.0, snapshot({}, 0.0)).is_clean
