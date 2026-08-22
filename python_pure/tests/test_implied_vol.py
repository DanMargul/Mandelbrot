from __future__ import annotations

import math

import pytest
from volarb_py.implied_vol import (
    VOLATILITY_CONVERGENCE_TOLERANCE,
    ImpliedVolatilityInputs,
    invert_black_implied_volatility,
    out_of_the_money_option_type,
    undiscounted_out_of_the_money_target_price,
)
from volarb_py.pricing import BlackScholesInputs, black_scholes_price

FORWARD = 100.0
DISCOUNT_FACTOR = 0.9876543
STRIKES = (50.0, 70.0, 85.0, 95.0, 99.0, 100.0, 101.0, 110.0, 130.0, 180.0, 300.0)
EXPIRIES = (0.002740, 0.019178, 0.083333, 0.25, 1.0, 3.0)
VOLATILITIES = (0.05, 0.10, 0.20, 0.45, 1.0, 2.0)
UNCERTAINTY_SAFETY_FACTOR = 64.0
RESOLVABLE_RELATIVE_UNCERTAINTY = 1e-6


def round_trip_cases() -> list[tuple[float, float, float, str]]:
    return [
        (strike, years, volatility, option_type)
        for strike in STRIKES
        for years in EXPIRIES
        for volatility in VOLATILITIES
        for option_type in ("call", "put")
    ]


def out_of_the_money_round_trip_cases() -> list[tuple[float, float, float, str]]:
    return [case for case in round_trip_cases() if case[3] == out_of_the_money_option_type(FORWARD, case[0])]


def invert_a_priced_option(
    strike: float, years: float, volatility: float, option_type: str
) -> tuple[float, object]:
    price = black_scholes_price(
        BlackScholesInputs(FORWARD, strike, years, volatility, DISCOUNT_FACTOR, option_type)
    )
    result = invert_black_implied_volatility(
        ImpliedVolatilityInputs(FORWARD, strike, years, DISCOUNT_FACTOR, price, option_type)
    )
    return price, result


@pytest.mark.parametrize(
    ("strike", "years", "volatility", "option_type"), out_of_the_money_round_trip_cases()
)
def test_resolvable_out_of_the_money_round_trip_is_exact(
    strike: float, years: float, volatility: float, option_type: str
) -> None:
    _, result = invert_a_priced_option(strike, years, volatility, option_type)
    if result.status != "converged":
        pytest.skip(f"not invertible in double precision: {result.status}")
    if result.volatility_uncertainty > RESOLVABLE_RELATIVE_UNCERTAINTY * volatility:
        pytest.skip("quote does not resolve the volatility")
    assert result.volatility == pytest.approx(volatility, rel=1.2e-12)


@pytest.mark.parametrize(("strike", "years", "volatility", "option_type"), round_trip_cases())
def test_realized_error_stays_within_the_reported_uncertainty(
    strike: float, years: float, volatility: float, option_type: str
) -> None:
    _, result = invert_a_priced_option(strike, years, volatility, option_type)
    if result.status != "converged":
        pytest.skip(f"not invertible in double precision: {result.status}")
    solver_floor = VOLATILITY_CONVERGENCE_TOLERANCE * result.volatility
    budget = UNCERTAINTY_SAFETY_FACTOR * (result.volatility_uncertainty + solver_floor)
    assert abs(result.volatility - volatility) <= budget


@pytest.mark.parametrize(("strike", "years", "volatility", "option_type"), round_trip_cases())
def test_every_result_is_finite_and_typed(
    strike: float, years: float, volatility: float, option_type: str
) -> None:
    _, result = invert_a_priced_option(strike, years, volatility, option_type)
    assert not math.isnan(result.volatility)
    assert result.volatility >= 0.0
    assert result.iterations >= 0
    if result.status != "converged":
        assert result.volatility == 0.0


def test_inversion_always_selects_the_out_of_the_money_side() -> None:
    assert out_of_the_money_option_type(100.0, 90.0) == "put"
    assert out_of_the_money_option_type(100.0, 110.0) == "call"
    assert out_of_the_money_option_type(100.0, 100.0) == "call"


def test_parity_conversion_reaches_the_same_target_from_either_side() -> None:
    call_price = black_scholes_price(BlackScholesInputs(100.0, 120.0, 1.0, 0.3, 1.0, "call"))
    put_price = black_scholes_price(BlackScholesInputs(100.0, 120.0, 1.0, 0.3, 1.0, "put"))
    from_call = undiscounted_out_of_the_money_target_price(
        ImpliedVolatilityInputs(100.0, 120.0, 1.0, 1.0, call_price, "call")
    )
    from_put = undiscounted_out_of_the_money_target_price(
        ImpliedVolatilityInputs(100.0, 120.0, 1.0, 1.0, put_price, "put")
    )
    assert from_call == pytest.approx(from_put, rel=1e-13)


def test_in_the_money_quotes_report_far_larger_uncertainty() -> None:
    _, from_out_of_the_money = invert_a_priced_option(80.0, 1.0, 0.05, "put")
    _, from_in_the_money = invert_a_priced_option(80.0, 1.0, 0.05, "call")
    assert from_out_of_the_money.volatility_uncertainty < from_in_the_money.volatility_uncertainty / 1000.0
    assert abs(from_out_of_the_money.volatility - 0.05) < abs(from_in_the_money.volatility - 0.05)


@pytest.mark.parametrize(
    ("strike", "years", "price", "option_type", "expected_status"),
    [
        (90.0, 1.0, 5.0, "call", "below_intrinsic"),
        (90.0, 1.0, 10.0, "call", "below_intrinsic"),
        (110.0, 1.0, 101.0, "call", "above_no_arbitrage_bound"),
        (90.0, 1.0, 91.0, "put", "above_no_arbitrage_bound"),
        (100.0, 0.0, 1.0, "call", "degenerate_expiry"),
        (100.0, 1.0, 1e-12, "call", "below_volatility_floor"),
        (100.0, 1.0, 99.9999995, "call", "above_volatility_ceiling"),
    ],
)
def test_boundary_conditions_report_their_cause(
    strike: float, years: float, price: float, option_type: str, expected_status: str
) -> None:
    result = invert_black_implied_volatility(
        ImpliedVolatilityInputs(100.0, strike, years, 1.0, price, option_type)
    )
    assert result.status == expected_status
    assert result.volatility == 0.0
    assert result.volatility_uncertainty == math.inf
