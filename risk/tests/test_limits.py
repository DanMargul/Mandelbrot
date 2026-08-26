from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from limits import (
    FAT_FINGER_BREACH,
    GREEK_LIMIT_BREACH,
    ORDER_RATE_BREACH,
    POSITION_LIMIT_BREACH,
    UNDERLYING_LIMIT_BREACH,
    UNMEASURED_BREACH,
    Breach,
    ContractGreeks,
    GreekBudgets,
    RiskLimits,
    aggregate_greeks,
    fat_finger_breaches,
    greek_breaches,
    inside_window,
    position_breaches,
    rate_breaches,
    unmeasured_breaches,
)
from volarb_py.execution import Quote

MOMENT = datetime(2026, 8, 25, 15, 0, 0, tzinfo=UTC)
SYMBOL = "SPX260918C05000000"
GHOST = "GHOST260918C09999000"
UNDERLYING = "SPX"
MULTIPLIER = 100
QUOTE = Quote(bid_price=41.0, ask_price=42.0, bid_size=50, ask_size=50)
LEG = ContractGreeks(delta=0.52, gamma=0.0009, vega=8.4, theta=-2.1)
BUDGETS = GreekBudgets(delta=5_000.0, gamma=10.0, vega=40_000.0, theta=8_000.0)
LIMITS = RiskLimits(
    reconciliation_interval=timedelta(minutes=30),
    position_limit=25,
    underlying_limit=40,
    greek_budgets=BUDGETS,
    orders_per_window=6,
    rate_window=timedelta(minutes=1),
    fat_finger_quantity=20,
    fat_finger_notional=250_000.0,
    stale_mark_horizon=timedelta(minutes=5),
)
INSIDE_POSITION = 10
OVER_POSITION = 26
HUGE_POSITION = 10_000
BURST = 6
FAT_QUANTITY = 40
NOTIONAL_QUANTITY = 19


def kinds(breaches: list[Breach]) -> set[str]:
    return {breach.kind for breach in breaches}


def test_a_position_inside_every_limit_raises_nothing() -> None:
    assert position_breaches({SYMBOL: INSIDE_POSITION}, {SYMBOL: UNDERLYING}, LIMITS) == []


def test_a_single_contract_over_its_limit_is_reported() -> None:
    breaches = position_breaches({SYMBOL: OVER_POSITION}, {SYMBOL: UNDERLYING}, LIMITS)
    assert POSITION_LIMIT_BREACH in kinds(breaches)


def test_two_contracts_inside_their_own_limits_can_break_the_underlying() -> None:
    positions = {SYMBOL: INSIDE_POSITION * 2, f"{SYMBOL}X": INSIDE_POSITION * 2 + 1}
    owner = {symbol: UNDERLYING for symbol in positions}
    breaches = position_breaches(positions, owner, LIMITS)
    assert POSITION_LIMIT_BREACH not in kinds(breaches)
    assert UNDERLYING_LIMIT_BREACH in kinds(breaches)


def test_a_short_position_counts_against_the_underlying_the_same_as_a_long() -> None:
    longs = position_breaches({SYMBOL: OVER_POSITION}, {SYMBOL: UNDERLYING}, LIMITS)
    shorts = position_breaches({SYMBOL: -OVER_POSITION}, {SYMBOL: UNDERLYING}, LIMITS)
    assert kinds(longs) == kinds(shorts)


def test_an_unmeasured_holding_contributes_nothing_and_says_so() -> None:
    book = aggregate_greeks(
        {SYMBOL: INSIDE_POSITION, GHOST: HUGE_POSITION}, {SYMBOL: LEG}, {SYMBOL: MULTIPLIER}
    )
    assert book.unmeasured == [GHOST]
    assert greek_breaches(book.totals, BUDGETS) == []
    assert UNMEASURED_BREACH in kinds(unmeasured_breaches(book))


def test_a_measured_book_that_exceeds_a_budget_is_reported() -> None:
    book = aggregate_greeks({SYMBOL: HUGE_POSITION}, {SYMBOL: LEG}, {SYMBOL: MULTIPLIER})
    assert book.unmeasured == []
    assert GREEK_LIMIT_BREACH in kinds(greek_breaches(book.totals, BUDGETS))


def test_an_empty_holding_is_not_called_unmeasured() -> None:
    assert aggregate_greeks({GHOST: 0}, {}, {}).unmeasured == []


def test_an_oversized_order_is_a_fat_finger() -> None:
    breaches = fat_finger_breaches(SYMBOL, FAT_QUANTITY, QUOTE, LIMITS)
    assert FAT_FINGER_BREACH in kinds(breaches)


def test_an_order_inside_the_quantity_bound_can_still_be_too_much_money() -> None:
    rich = Quote(bid_price=20_000.0, ask_price=20_100.0, bid_size=50, ask_size=50)
    assert fat_finger_breaches(SYMBOL, NOTIONAL_QUANTITY, QUOTE, LIMITS) == []
    assert FAT_FINGER_BREACH in kinds(fat_finger_breaches(SYMBOL, NOTIONAL_QUANTITY, rich, LIMITS))


def test_the_rate_limit_counts_only_what_is_inside_the_window() -> None:
    burst = [MOMENT - timedelta(seconds=second) for second in range(BURST)]
    assert ORDER_RATE_BREACH in kinds(rate_breaches(burst, MOMENT, LIMITS))
    old = [MOMENT - timedelta(minutes=minute + 1) for minute in range(BURST)]
    assert rate_breaches(old, MOMENT, LIMITS) == []


def test_the_window_filter_keeps_only_recent_stamps() -> None:
    stamps = [MOMENT - timedelta(seconds=30), MOMENT - timedelta(minutes=5)]
    assert inside_window(stamps, MOMENT, LIMITS.rate_window) == [stamps[0]]


def test_a_stamp_exactly_at_the_window_edge_has_left_it() -> None:
    assert inside_window([MOMENT - LIMITS.rate_window], MOMENT, LIMITS.rate_window) == []


def test_every_budget_is_checked_not_just_the_first() -> None:
    over = ContractGreeks(delta=1e9, gamma=1e9, vega=1e9, theta=1e9)
    assert len(greek_breaches(over, BUDGETS)) == len(
        (BUDGETS.delta, BUDGETS.gamma, BUDGETS.vega, BUDGETS.theta)
    )


@pytest.mark.parametrize("sign", [1, -1])
def test_a_budget_is_two_sided(sign: int) -> None:
    over = ContractGreeks(delta=sign * (BUDGETS.delta + 1.0), gamma=0.0, vega=0.0, theta=0.0)
    assert GREEK_LIMIT_BREACH in kinds(greek_breaches(over, BUDGETS))
