from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

OptionType = Literal["call", "put"]

SQUARE_ROOT_OF_TWO: Final[float] = math.sqrt(2.0)
INVERSE_SQUARE_ROOT_OF_TWO_PI: Final[float] = 1.0 / math.sqrt(2.0 * math.pi)


class InvalidOptionInputsError(ValueError):
    pass


@dataclass(frozen=True)
class BlackScholesInputs:
    forward: float
    strike: float
    years_to_expiry: float
    volatility: float
    discount_factor: float
    option_type: OptionType


@dataclass(frozen=True)
class BlackScholesGreeks:
    price: float
    delta_with_respect_to_forward: float
    gamma_with_respect_to_forward: float
    vega_with_respect_to_volatility: float
    theta_with_respect_to_time: float


def standard_normal_cumulative_distribution(x: float) -> float:
    return 0.5 * math.erfc(-x / SQUARE_ROOT_OF_TWO)


def standard_normal_probability_density(x: float) -> float:
    return INVERSE_SQUARE_ROOT_OF_TWO_PI * math.exp(-0.5 * x * x)


def validate_black_scholes_inputs(inputs: BlackScholesInputs) -> None:
    if not inputs.forward > 0.0:
        raise InvalidOptionInputsError(f"forward must be positive, got {inputs.forward}")
    if not inputs.strike > 0.0:
        raise InvalidOptionInputsError(f"strike must be positive, got {inputs.strike}")
    if not inputs.discount_factor > 0.0:
        raise InvalidOptionInputsError(f"discount_factor must be positive, got {inputs.discount_factor}")
    if inputs.years_to_expiry < 0.0:
        raise InvalidOptionInputsError(f"years_to_expiry must not be negative, got {inputs.years_to_expiry}")
    if inputs.volatility < 0.0:
        raise InvalidOptionInputsError(f"volatility must not be negative, got {inputs.volatility}")


def has_degenerate_expiry(inputs: BlackScholesInputs) -> bool:
    return inputs.years_to_expiry <= 0.0 or inputs.volatility <= 0.0


def forward_intrinsic_value(inputs: BlackScholesInputs) -> float:
    if inputs.option_type == "call":
        return inputs.discount_factor * max(inputs.forward - inputs.strike, 0.0)
    return inputs.discount_factor * max(inputs.strike - inputs.forward, 0.0)


def forward_intrinsic_delta(inputs: BlackScholesInputs) -> float:
    is_above_strike = inputs.forward > inputs.strike
    if inputs.option_type == "call":
        return inputs.discount_factor if is_above_strike else 0.0
    return 0.0 if is_above_strike else -inputs.discount_factor


def degenerate_greeks(inputs: BlackScholesInputs) -> BlackScholesGreeks:
    return BlackScholesGreeks(
        price=forward_intrinsic_value(inputs),
        delta_with_respect_to_forward=forward_intrinsic_delta(inputs),
        gamma_with_respect_to_forward=0.0,
        vega_with_respect_to_volatility=0.0,
        theta_with_respect_to_time=0.0,
    )


def standardized_moneyness_pair(inputs: BlackScholesInputs) -> tuple[float, float]:
    standard_deviation = inputs.volatility * math.sqrt(inputs.years_to_expiry)
    d1 = (
        math.log(inputs.forward / inputs.strike) + 0.5 * standard_deviation * standard_deviation
    ) / standard_deviation
    return d1, d1 - standard_deviation


def largest_price_term_magnitude(inputs: BlackScholesInputs) -> float:
    validate_black_scholes_inputs(inputs)
    if has_degenerate_expiry(inputs):
        return inputs.discount_factor * max(inputs.forward, inputs.strike)
    d1, d2 = standardized_moneyness_pair(inputs)
    normal = standard_normal_cumulative_distribution
    if inputs.option_type == "call":
        return inputs.discount_factor * max(inputs.forward * normal(d1), inputs.strike * normal(d2))
    return inputs.discount_factor * max(inputs.strike * normal(-d2), inputs.forward * normal(-d1))


def black_scholes_price(inputs: BlackScholesInputs) -> float:
    validate_black_scholes_inputs(inputs)
    if has_degenerate_expiry(inputs):
        return forward_intrinsic_value(inputs)
    d1, d2 = standardized_moneyness_pair(inputs)
    normal = standard_normal_cumulative_distribution
    if inputs.option_type == "call":
        return inputs.discount_factor * (inputs.forward * normal(d1) - inputs.strike * normal(d2))
    return inputs.discount_factor * (inputs.strike * normal(-d2) - inputs.forward * normal(-d1))


def black_scholes_price_and_greeks(inputs: BlackScholesInputs) -> BlackScholesGreeks:
    validate_black_scholes_inputs(inputs)
    if has_degenerate_expiry(inputs):
        return degenerate_greeks(inputs)

    d1, d2 = standardized_moneyness_pair(inputs)
    normal = standard_normal_cumulative_distribution
    density_at_d1 = standard_normal_probability_density(d1)
    square_root_of_years = math.sqrt(inputs.years_to_expiry)

    if inputs.option_type == "call":
        price = inputs.discount_factor * (inputs.forward * normal(d1) - inputs.strike * normal(d2))
        delta = inputs.discount_factor * normal(d1)
    else:
        price = inputs.discount_factor * (inputs.strike * normal(-d2) - inputs.forward * normal(-d1))
        delta = -inputs.discount_factor * normal(-d1)

    return BlackScholesGreeks(
        price=price,
        delta_with_respect_to_forward=delta,
        gamma_with_respect_to_forward=inputs.discount_factor
        * density_at_d1
        / (inputs.forward * inputs.volatility * square_root_of_years),
        vega_with_respect_to_volatility=inputs.discount_factor
        * inputs.forward
        * density_at_d1
        * square_root_of_years,
        theta_with_respect_to_time=-inputs.discount_factor
        * inputs.forward
        * density_at_d1
        * inputs.volatility
        / (2.0 * square_root_of_years),
    )
