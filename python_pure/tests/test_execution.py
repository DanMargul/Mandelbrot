from __future__ import annotations

import pytest
from volarb_py.execution import (
    InvalidOrderError,
    InvalidQuoteError,
    PackageLeg,
    Quote,
    fill_at_touch,
    fill_package,
    half_spread,
    mid_price,
)

LIQUID = Quote(bid_price=10.00, ask_price=10.20, bid_size=50, ask_size=40)
WIDE = Quote(bid_price=1.00, ask_price=1.40, bid_size=10, ask_size=10)
MULTIPLIER = 100
LOT = 10
LIQUID_VEGA = 0.20
WIDE_VEGA = 0.05
OVERSIZED_LOT = 100


def test_a_taker_pays_the_touch_and_never_the_mid() -> None:
    bought = fill_at_touch(LIQUID, "buy", LOT, MULTIPLIER)
    assert bought.touch_price == LIQUID.ask_price
    assert bought.mid_price == mid_price(LIQUID)
    assert bought.cost_against_mid == pytest.approx(LOT * MULTIPLIER * half_spread(LIQUID))
    assert bought.status == "filled"

    sold = fill_at_touch(LIQUID, "sell", LOT, MULTIPLIER)
    assert sold.touch_price == LIQUID.bid_price
    assert sold.cost_against_mid == pytest.approx(bought.cost_against_mid)


def test_size_beyond_the_touch_is_not_filled_rather_than_filled_worse() -> None:
    fill = fill_at_touch(LIQUID, "buy", OVERSIZED_LOT, MULTIPLIER)
    assert fill.filled_quantity == LIQUID.ask_size
    assert fill.requested_quantity == OVERSIZED_LOT
    assert fill.status == "partially_filled"
    assert fill.cost_against_mid == pytest.approx(LIQUID.ask_size * MULTIPLIER * half_spread(LIQUID))


def test_an_empty_book_fills_nothing() -> None:
    fill = fill_at_touch(Quote(10.00, 10.20, 0, 0), "buy", 5, MULTIPLIER)
    assert fill.filled_quantity == 0
    assert fill.status == "unfilled"
    assert fill.cost_against_mid == 0.0


def test_a_package_pays_the_full_spread_on_every_leg() -> None:
    legs = [
        PackageLeg(LIQUID, "buy", LOT, MULTIPLIER, LIQUID_VEGA),
        PackageLeg(WIDE, "sell", LOT, MULTIPLIER, WIDE_VEGA),
    ]
    fill = fill_package(legs)
    assert fill.status == "filled"
    assert fill.total_cost_against_mid == pytest.approx(
        LOT * MULTIPLIER * (half_spread(LIQUID) + half_spread(WIDE))
    )
    assert fill.net_vega == pytest.approx(LOT * MULTIPLIER * (LIQUID_VEGA - WIDE_VEGA))
    assert not fill.net_vega_is_negligible
    assert fill.round_trip_cost_in_volatility_points == pytest.approx(
        2.0 * fill.total_cost_against_mid / fill.net_vega
    )


def test_a_vega_neutral_package_pays_spread_for_no_exposure() -> None:
    legs = [
        PackageLeg(LIQUID, "buy", LOT, MULTIPLIER, LIQUID_VEGA),
        PackageLeg(LIQUID, "sell", LOT, MULTIPLIER, LIQUID_VEGA),
    ]
    fill = fill_package(legs)
    assert fill.total_cost_against_mid > 0.0
    assert fill.net_vega == pytest.approx(0.0)
    assert fill.net_vega_is_negligible
    assert fill.round_trip_cost_in_volatility_points > 0.0


def test_a_partly_filled_package_reports_the_vega_it_actually_got() -> None:
    thin = Quote(bid_price=10.00, ask_price=10.20, bid_size=50, ask_size=3)
    fill = fill_package([PackageLeg(thin, "buy", LOT, MULTIPLIER, LIQUID_VEGA)])
    assert fill.status == "partially_filled"
    assert fill.filled_quantity == thin.ask_size
    assert fill.net_vega == pytest.approx(thin.ask_size * MULTIPLIER * LIQUID_VEGA)


def test_a_crossed_book_is_rejected_rather_than_traded() -> None:
    with pytest.raises(InvalidQuoteError):
        fill_at_touch(Quote(10.30, 10.20, 10, 10), "buy", 1, MULTIPLIER)


def test_negative_prices_sizes_quantities_and_multipliers_are_rejected() -> None:
    with pytest.raises(InvalidQuoteError):
        fill_at_touch(Quote(-1.0, 1.0, 1, 1), "buy", 1, MULTIPLIER)
    with pytest.raises(InvalidQuoteError):
        fill_at_touch(Quote(1.0, 2.0, -1, 1), "buy", 1, MULTIPLIER)
    with pytest.raises(InvalidOrderError):
        fill_at_touch(LIQUID, "buy", 0, MULTIPLIER)
    with pytest.raises(InvalidOrderError):
        fill_at_touch(LIQUID, "buy", 1, 0)
    with pytest.raises(InvalidOrderError):
        fill_package([])


def test_a_locked_book_costs_nothing_to_cross() -> None:
    locked = Quote(10.10, 10.10, 5, 5)
    fill = fill_at_touch(locked, "buy", 5, MULTIPLIER)
    assert half_spread(locked) == 0.0
    assert fill.cost_against_mid == 0.0
    assert fill.touch_price == mid_price(locked)


def test_the_cost_in_volatility_points_does_not_depend_on_the_multiplier() -> None:
    for multiplier in (1, 10, 100, 1000):
        fill = fill_package([PackageLeg(LIQUID, "buy", LOT, multiplier, LIQUID_VEGA)])
        assert fill.round_trip_cost_in_volatility_points == pytest.approx(
            2.0 * half_spread(LIQUID) / LIQUID_VEGA
        )
