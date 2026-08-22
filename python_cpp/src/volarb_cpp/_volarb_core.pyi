from typing import Literal

OptionType = Literal["call", "put"]
InversionStatus = Literal[
    "converged",
    "below_intrinsic",
    "above_no_arbitrage_bound",
    "below_volatility_floor",
    "above_volatility_ceiling",
    "not_converged",
    "degenerate_expiry",
]

class InvalidOptionInputsError(ValueError): ...

class BlackScholesInputs:
    forward: float
    strike: float
    years_to_expiry: float
    volatility: float
    discount_factor: float
    option_type: OptionType
    def __init__(
        self,
        *,
        forward: float,
        strike: float,
        years_to_expiry: float,
        volatility: float,
        discount_factor: float,
        option_type: OptionType,
    ) -> None: ...

class BlackScholesGreeks:
    price: float
    delta_with_respect_to_forward: float
    gamma_with_respect_to_forward: float
    vega_with_respect_to_volatility: float
    theta_with_respect_to_time: float

class ImpliedVolatilityInputs:
    forward: float
    strike: float
    years_to_expiry: float
    discount_factor: float
    option_price: float
    option_type: OptionType
    def __init__(
        self,
        *,
        forward: float,
        strike: float,
        years_to_expiry: float,
        discount_factor: float,
        option_price: float,
        option_type: OptionType,
    ) -> None: ...

class ImpliedVolatilityResult:
    volatility: float
    status: InversionStatus
    iterations: int
    absolute_price_error: float
    volatility_uncertainty: float

def standard_normal_cumulative_distribution(x: float) -> float: ...
def standard_normal_probability_density(x: float) -> float: ...
def black_scholes_price(inputs: BlackScholesInputs) -> float: ...
def black_scholes_price_and_greeks(inputs: BlackScholesInputs) -> BlackScholesGreeks: ...
def black_scholes_price_and_greeks_batch(
    batch: list[BlackScholesInputs],
) -> list[BlackScholesGreeks]: ...
def invert_black_implied_volatility(inputs: ImpliedVolatilityInputs) -> ImpliedVolatilityResult: ...
def invert_black_implied_volatility_batch(
    batch: list[ImpliedVolatilityInputs],
) -> list[ImpliedVolatilityResult]: ...
def out_of_the_money_option_type(forward: float, strike: float) -> OptionType: ...
