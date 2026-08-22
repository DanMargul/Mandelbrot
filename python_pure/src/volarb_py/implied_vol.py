from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Final, Literal

from volarb_py.pricing import (
    BlackScholesInputs,
    OptionType,
    black_scholes_price_and_greeks,
    largest_price_term_magnitude,
)

InversionStatus = Literal[
    "converged",
    "below_intrinsic",
    "above_no_arbitrage_bound",
    "below_volatility_floor",
    "above_volatility_ceiling",
    "not_converged",
    "degenerate_expiry",
]

MINIMUM_VOLATILITY: Final[float] = 1e-9
MAXIMUM_VOLATILITY: Final[float] = 10.0
MAXIMUM_ITERATIONS: Final[int] = 100
VOLATILITY_CONVERGENCE_TOLERANCE: Final[float] = 1e-12
MINIMUM_USABLE_VEGA: Final[float] = 1e-12
DOUBLE_PRECISION_EPSILON: Final[float] = sys.float_info.epsilon


@dataclass(frozen=True)
class ImpliedVolatilityInputs:
    forward: float
    strike: float
    years_to_expiry: float
    discount_factor: float
    option_price: float
    option_type: OptionType


@dataclass(frozen=True)
class InversionProblem:
    forward: float
    strike: float
    years_to_expiry: float
    option_type: OptionType
    target_price: float
    quoted_undiscounted_price: float


@dataclass(frozen=True)
class ImpliedVolatilityResult:
    volatility: float
    status: InversionStatus
    iterations: int
    absolute_price_error: float
    volatility_uncertainty: float


def failed_inversion(status: InversionStatus) -> ImpliedVolatilityResult:
    return ImpliedVolatilityResult(
        volatility=0.0,
        status=status,
        iterations=0,
        absolute_price_error=0.0,
        volatility_uncertainty=math.inf,
    )


def out_of_the_money_option_type(forward: float, strike: float) -> OptionType:
    return "put" if strike < forward else "call"


def undiscounted_out_of_the_money_target_price(inputs: ImpliedVolatilityInputs) -> float:
    undiscounted_price = inputs.option_price / inputs.discount_factor
    target_type = out_of_the_money_option_type(inputs.forward, inputs.strike)
    if inputs.option_type == target_type:
        return undiscounted_price
    if target_type == "call":
        return undiscounted_price + inputs.forward - inputs.strike
    return undiscounted_price - inputs.forward + inputs.strike


def undiscounted_no_arbitrage_price_ceiling(forward: float, strike: float, option_type: OptionType) -> float:
    return forward if option_type == "call" else strike


def undiscounted_price_and_vega(
    forward: float, strike: float, years_to_expiry: float, volatility: float, option_type: OptionType
) -> tuple[float, float]:
    greeks = black_scholes_price_and_greeks(
        BlackScholesInputs(
            forward=forward,
            strike=strike,
            years_to_expiry=years_to_expiry,
            volatility=volatility,
            discount_factor=1.0,
            option_type=option_type,
        )
    )
    return greeks.price, greeks.vega_with_respect_to_volatility


def undiscounted_price(
    forward: float, strike: float, years_to_expiry: float, volatility: float, option_type: OptionType
) -> float:
    price, _ = undiscounted_price_and_vega(forward, strike, years_to_expiry, volatility, option_type)
    return price


def volatility_uncertainty_from_price_resolution(
    largest_price_term: float, quoted_undiscounted_price: float, vega: float
) -> float:
    if vega < MINIMUM_USABLE_VEGA:
        return math.inf
    largest_price_intermediate = max(largest_price_term, quoted_undiscounted_price)
    return DOUBLE_PRECISION_EPSILON * largest_price_intermediate / vega


def brenner_subrahmanyam_seed(forward: float, years_to_expiry: float, target_price: float) -> float:
    return math.sqrt(2.0 * math.pi / years_to_expiry) * target_price / forward


def clamp_into_bracket(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def next_volatility_estimate(
    volatility: float, price_error: float, vega: float, lower: float, upper: float
) -> float:
    bisection = 0.5 * (lower + upper)
    if vega < MINIMUM_USABLE_VEGA:
        return bisection
    newton_candidate = volatility - price_error / vega
    if newton_candidate <= lower or newton_candidate >= upper:
        return bisection
    return newton_candidate


def completed_inversion(
    problem: InversionProblem, volatility: float, status: InversionStatus, iterations: int
) -> ImpliedVolatilityResult:
    price, vega = undiscounted_price_and_vega(
        problem.forward, problem.strike, problem.years_to_expiry, volatility, problem.option_type
    )
    largest_price_term = largest_price_term_magnitude(
        BlackScholesInputs(
            problem.forward, problem.strike, problem.years_to_expiry, volatility, 1.0, problem.option_type
        )
    )
    return ImpliedVolatilityResult(
        volatility=volatility,
        status=status,
        iterations=iterations,
        absolute_price_error=abs(price - problem.target_price),
        volatility_uncertainty=volatility_uncertainty_from_price_resolution(
            largest_price_term, problem.quoted_undiscounted_price, vega
        ),
    )


def solve_bracketed_newton(problem: InversionProblem) -> ImpliedVolatilityResult:
    lower = MINIMUM_VOLATILITY
    upper = MAXIMUM_VOLATILITY
    seed = brenner_subrahmanyam_seed(problem.forward, problem.years_to_expiry, problem.target_price)
    volatility = clamp_into_bracket(seed, lower, upper)

    for iteration in range(1, MAXIMUM_ITERATIONS + 1):
        price, vega = undiscounted_price_and_vega(
            problem.forward, problem.strike, problem.years_to_expiry, volatility, problem.option_type
        )
        if price > problem.target_price:
            upper = volatility
        else:
            lower = volatility
        next_volatility = next_volatility_estimate(
            volatility, price - problem.target_price, vega, lower, upper
        )
        step_size = abs(next_volatility - volatility)
        volatility = next_volatility
        if step_size <= VOLATILITY_CONVERGENCE_TOLERANCE * volatility:
            return completed_inversion(problem, volatility, "converged", iteration)

    return completed_inversion(problem, volatility, "not_converged", MAXIMUM_ITERATIONS)


def invert_black_implied_volatility(inputs: ImpliedVolatilityInputs) -> ImpliedVolatilityResult:
    if inputs.years_to_expiry <= 0.0:
        return failed_inversion("degenerate_expiry")

    forward, strike, years = inputs.forward, inputs.strike, inputs.years_to_expiry
    option_type = out_of_the_money_option_type(forward, strike)
    target_price = undiscounted_out_of_the_money_target_price(inputs)

    if target_price <= 0.0:
        return failed_inversion("below_intrinsic")
    if target_price >= undiscounted_no_arbitrage_price_ceiling(forward, strike, option_type):
        return failed_inversion("above_no_arbitrage_bound")
    if target_price <= undiscounted_price(forward, strike, years, MINIMUM_VOLATILITY, option_type):
        return failed_inversion("below_volatility_floor")
    if target_price >= undiscounted_price(forward, strike, years, MAXIMUM_VOLATILITY, option_type):
        return failed_inversion("above_volatility_ceiling")

    return solve_bracketed_newton(
        InversionProblem(
            forward=forward,
            strike=strike,
            years_to_expiry=years,
            option_type=option_type,
            target_price=target_price,
            quoted_undiscounted_price=inputs.option_price / inputs.discount_factor,
        )
    )
