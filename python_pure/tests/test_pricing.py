from __future__ import annotations

import math
import sys

import pytest
from volarb_py.pricing import (
    BlackScholesInputs,
    InvalidOptionInputsError,
    black_scholes_price,
    black_scholes_price_and_greeks,
    standard_normal_cumulative_distribution,
    standard_normal_probability_density,
)

STRIKES = (60.0, 90.0, 99.0, 100.0, 101.0, 130.0, 250.0)
EXPIRIES = (0.019178, 0.25, 1.0, 5.0)
VOLATILITIES = (0.05, 0.15, 0.35, 1.2)
FORWARD = 100.0
DISCOUNT_FACTOR = 0.9876543
DOUBLE_PRECISION_EPSILON = sys.float_info.epsilon
RELATIVE_BUMP = 1e-3
NORMAL_CUMULATIVE_DISTRIBUTION_AT_ZERO = 0.5


def inputs_for(strike: float, years: float, volatility: float, option_type: str) -> BlackScholesInputs:
    return BlackScholesInputs(
        forward=FORWARD,
        strike=strike,
        years_to_expiry=years,
        volatility=volatility,
        discount_factor=DISCOUNT_FACTOR,
        option_type=option_type,
    )


def every_ordinary_case() -> list[tuple[float, float, float]]:
    return [
        (strike, years, volatility) for strike in STRIKES for years in EXPIRIES for volatility in VOLATILITIES
    ]


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_put_call_parity_holds(strike: float, years: float, volatility: float) -> None:
    call = black_scholes_price(inputs_for(strike, years, volatility, "call"))
    put = black_scholes_price(inputs_for(strike, years, volatility, "put"))
    expected = DISCOUNT_FACTOR * (FORWARD - strike)
    assert call - put == pytest.approx(expected, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_delta_parity_holds(strike: float, years: float, volatility: float) -> None:
    call = black_scholes_price_and_greeks(inputs_for(strike, years, volatility, "call"))
    put = black_scholes_price_and_greeks(inputs_for(strike, years, volatility, "put"))
    difference = call.delta_with_respect_to_forward - put.delta_with_respect_to_forward
    assert difference == pytest.approx(DISCOUNT_FACTOR, rel=1e-12)


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_second_order_greeks_are_type_independent(strike: float, years: float, volatility: float) -> None:
    call = black_scholes_price_and_greeks(inputs_for(strike, years, volatility, "call"))
    put = black_scholes_price_and_greeks(inputs_for(strike, years, volatility, "put"))
    assert call.gamma_with_respect_to_forward == pytest.approx(put.gamma_with_respect_to_forward, rel=1e-14)
    assert call.vega_with_respect_to_volatility == pytest.approx(
        put.vega_with_respect_to_volatility, rel=1e-14
    )
    assert call.theta_with_respect_to_time == pytest.approx(put.theta_with_respect_to_time, rel=1e-14)


@pytest.mark.parametrize("option_type", ["call", "put"])
@pytest.mark.parametrize("strike", STRIKES)
def test_price_is_monotone_in_volatility(option_type: str, strike: float) -> None:
    prices = [
        black_scholes_price(inputs_for(strike, 1.0, volatility, option_type)) for volatility in VOLATILITIES
    ]
    assert prices == sorted(prices)


@pytest.mark.parametrize("option_type", ["call", "put"])
@pytest.mark.parametrize("strike", STRIKES)
def test_price_respects_no_arbitrage_bounds(option_type: str, strike: float) -> None:
    price = black_scholes_price(inputs_for(strike, 1.0, 0.35, option_type))
    intrinsic = max(FORWARD - strike, 0.0) if option_type == "call" else max(strike - FORWARD, 0.0)
    ceiling = FORWARD if option_type == "call" else strike
    assert DISCOUNT_FACTOR * intrinsic <= price <= DISCOUNT_FACTOR * ceiling


def central_difference_in_volatility(strike: float, years: float, volatility: float, bump: float) -> float:
    up = black_scholes_price(inputs_for(strike, years, volatility + bump, "call"))
    down = black_scholes_price(inputs_for(strike, years, volatility - bump, "call"))
    return (up - down) / (2.0 * bump)


def richardson_extrapolated_vega(strike: float, years: float, volatility: float) -> float:
    coarse_bump = RELATIVE_BUMP * volatility
    coarse = central_difference_in_volatility(strike, years, volatility, coarse_bump)
    fine = central_difference_in_volatility(strike, years, volatility, coarse_bump / 2.0)
    return (4.0 * fine - coarse) / 3.0


def finite_difference_noise_floor(strike: float, volatility: float) -> float:
    price_representation_noise = DOUBLE_PRECISION_EPSILON * max(FORWARD, strike) * DISCOUNT_FACTOR
    smallest_bump = 0.5 * RELATIVE_BUMP * volatility
    return price_representation_noise / smallest_bump


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_vega_matches_a_numerical_derivative(strike: float, years: float, volatility: float) -> None:
    analytic = black_scholes_price_and_greeks(inputs_for(strike, years, volatility, "call"))
    numerical = richardson_extrapolated_vega(strike, years, volatility)
    assert numerical == pytest.approx(
        analytic.vega_with_respect_to_volatility,
        rel=1e-7,
        abs=finite_difference_noise_floor(strike, volatility),
    )


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_expired_option_is_worth_forward_intrinsic(option_type: str) -> None:
    greeks = black_scholes_price_and_greeks(inputs_for(90.0, 0.0, 0.2, option_type))
    expected = DISCOUNT_FACTOR * (10.0 if option_type == "call" else 0.0)
    assert greeks.price == pytest.approx(expected, rel=1e-15)
    assert greeks.gamma_with_respect_to_forward == 0.0
    assert greeks.vega_with_respect_to_volatility == 0.0
    assert greeks.theta_with_respect_to_time == 0.0


def test_delta_parity_holds_at_the_expiry_kink() -> None:
    call = black_scholes_price_and_greeks(inputs_for(FORWARD, 0.0, 0.2, "call"))
    put = black_scholes_price_and_greeks(inputs_for(FORWARD, 0.0, 0.2, "put"))
    assert call.delta_with_respect_to_forward == 0.0
    assert put.delta_with_respect_to_forward == -DISCOUNT_FACTOR
    assert call.delta_with_respect_to_forward - put.delta_with_respect_to_forward == DISCOUNT_FACTOR


def test_deep_wing_put_delta_keeps_relative_precision() -> None:
    greeks = black_scholes_price_and_greeks(inputs_for(60.0, 0.019178, 0.25, "put"))
    assert greeks.delta_with_respect_to_forward < 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("forward", 0.0),
        ("forward", -1.0),
        ("strike", 0.0),
        ("discount_factor", 0.0),
        ("years_to_expiry", -1.0),
        ("volatility", -0.1),
    ],
)
def test_invalid_inputs_are_rejected(field: str, value: float) -> None:
    base = inputs_for(100.0, 1.0, 0.2, "call")
    broken = BlackScholesInputs(**{**vars(base), field: value})
    with pytest.raises(InvalidOptionInputsError):
        black_scholes_price(broken)


def test_normal_distribution_matches_known_values() -> None:
    assert standard_normal_cumulative_distribution(0.0) == NORMAL_CUMULATIVE_DISTRIBUTION_AT_ZERO
    assert standard_normal_probability_density(0.0) == pytest.approx(
        1.0 / math.sqrt(2.0 * math.pi), rel=1e-15
    )
    assert standard_normal_cumulative_distribution(-1.0) == pytest.approx(0.15865525393145705, rel=1e-15)
    assert standard_normal_cumulative_distribution(1.0) == pytest.approx(0.8413447460685429, rel=1e-15)


def test_normal_left_tail_stays_positive_until_it_underflows() -> None:
    assert standard_normal_cumulative_distribution(-37.0) == pytest.approx(5.72557e-300, rel=1e-4)
    assert standard_normal_cumulative_distribution(-38.4) > 0.0
    assert standard_normal_cumulative_distribution(-38.5) == 0.0
    assert standard_normal_cumulative_distribution(40.0) == 1.0
