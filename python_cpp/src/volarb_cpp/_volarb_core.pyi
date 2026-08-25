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
class ChainDatasetError(ValueError): ...
class LookaheadRequestedError(ChainDatasetError): ...
class CorruptDatasetError(ChainDatasetError): ...

class ContractQuote:
    contract_symbol: str
    exercise_style: ExerciseStyle
    expiry_date: str
    strike: float
    option_type: OptionType
    contract_multiplier: int
    is_standard_deliverable: bool
    event_time: str
    knowledge_time: str
    ingest_sequence: int
    underlying_price: float
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int

class AsOfChainReader:
    dataset_digest: str
    knowledge_horizon: str
    def chain_as_of(
        self,
        *,
        underlying_symbol: str,
        observation_time: str,
        include_adjusted_contracts: bool,
    ) -> list[ContractQuote]: ...

def open_chain_dataset(dataset_root: str, knowledge_horizon: str) -> AsOfChainReader: ...

ForwardCurveStatus = Literal[
    "converged",
    "too_few_pairs",
    "degenerate_strike_range",
    "non_positive_discount_factor",
    "american_quotes_not_stripped",
]

class ForwardCurvePoint:
    expiry_date: str
    years_to_expiry: float
    spot_price: float
    forward: float
    forward_standard_error: float | None
    discount_factor: float
    discount_factor_standard_error: float | None
    implied_zero_rate: float | None
    implied_carry_rate: float | None
    parity_pair_count: int
    active_pair_count: int
    chi_square_per_degree_of_freedom: float | None
    early_exercise_premium_stripped: bool
    discount_factor_is_monotone_in_expiry: bool
    status: ForwardCurveStatus

ExerciseStyle = Literal["european", "american"]

class InvalidLatticeInputsError(ValueError): ...
class InvalidSviParametersError(ValueError): ...

SviStatus = Literal["arbitrage_free_on_grid", "butterfly_arbitrage_found", "invalid_parameters"]

class SviSliceScan:
    minimum_durrleman_value: float
    log_moneyness_at_minimum: float
    minimum_total_variance: float
    minimum_risk_neutral_density: float
    scan_steps: int
    status: SviStatus

class InvalidCalibrationInputsError(ValueError): ...

SviCalibrationStatus = Literal["converged", "too_few_observations", "simplex_budget_exhausted"]

class SviCalibration:
    a: float
    b: float
    rho: float
    m: float
    sigma: float
    objective: float
    weighted_root_mean_square_residual: float
    simplex_iterations: int
    observation_count: int
    fitted_curve: list[float]
    status: SviCalibrationStatus

def calibrate_svi_slice(
    *,
    log_moneyness: list[float],
    total_variances: list[float],
    weights: list[float],
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
) -> SviCalibration: ...

DEFAULT_SCAN_STEPS: int

def scan_svi_slice(
    *,
    a: float,
    b: float,
    rho: float,
    m: float,
    sigma: float,
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
    scan_steps: int,
) -> SviSliceScan: ...

class InvalidRateCurveError(ValueError): ...

def rate_curve_discount_factor(
    *, years_to_maturity: list[float], continuously_compounded_zero_rate: list[float], years: float
) -> float: ...
def rate_curve_zero_rate(
    *, years_to_maturity: list[float], continuously_compounded_zero_rate: list[float], years: float
) -> float: ...
def rate_curve_integrated_rate(
    *, years_to_maturity: list[float], continuously_compounded_zero_rate: list[float], years: float
) -> float: ...
def rate_curve_forward_rate(
    *,
    years_to_maturity: list[float],
    continuously_compounded_zero_rate: list[float],
    start_years: float,
    end_years: float,
) -> float: ...
def rate_curve_forward_discount_factor(
    *,
    years_to_maturity: list[float],
    continuously_compounded_zero_rate: list[float],
    start_years: float,
    end_years: float,
) -> float: ...

class InvalidQuoteError(ValueError): ...
class InvalidOrderError(ValueError): ...

FillStatus = Literal["filled", "partially_filled", "unfilled"]

class PackageFill:
    requested_quantity: int
    filled_quantity: int
    total_cost_against_mid: float
    net_vega: float
    net_vega_is_negligible: bool
    round_trip_cost_in_volatility_points: float
    leg_filled_quantity: list[int]
    leg_touch_price: list[float]
    leg_mid_price: list[float]
    leg_half_spread: list[float]
    leg_cost_against_mid: list[float]
    leg_status: list[FillStatus]
    status: FillStatus

def fill_package(
    *,
    bid_price: list[float],
    ask_price: list[float],
    bid_size: list[int],
    ask_size: list[int],
    side: list[str],
    quantity: list[int],
    contract_multiplier: list[int],
    vega_with_respect_to_volatility: list[float],
) -> PackageFill: ...

class InvalidEssviInputsError(ValueError): ...

EssviStatus = Literal[
    "converged",
    "too_few_slices",
    "too_few_observations",
    "simplex_budget_exhausted",
    "arbitrage_not_eliminated",
]

class EssviCalibration:
    objective: float
    weighted_root_mean_square_residual: float
    simplex_iterations: int
    slice_count: int
    observation_count: int
    atm_total_variance: list[float]
    curvature_scale: float
    power_law_exponent: float
    correlation_intercept: float
    correlation_slope: float
    slice_a: list[float]
    slice_b: list[float]
    slice_rho: list[float]
    slice_m: list[float]
    slice_sigma: list[float]
    fitted_surface: list[float]
    surface_minimum_durrleman_value: float
    surface_minimum_total_variance_time_slope: float
    status: EssviStatus

def calibrate_essvi_surface(
    *,
    years_to_expiry: list[float],
    log_moneyness: list[list[float]],
    total_variances: list[list[float]],
    weights: list[list[float]],
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
) -> EssviCalibration: ...

class InvalidSviSurfaceError(ValueError): ...

SviSurfaceStatus = Literal[
    "arbitrage_free_on_grid",
    "butterfly_arbitrage_found",
    "calendar_arbitrage_found",
    "invalid_surface",
]

class SviSurfaceScan:
    slice_count: int
    scan_steps: int
    time_steps_per_interval: int
    minimum_durrleman_value: float
    log_moneyness_at_minimum_durrleman_value: float
    years_to_expiry_at_minimum_durrleman_value: float
    minimum_risk_neutral_density: float
    minimum_total_variance_time_slope: float
    log_moneyness_at_minimum_time_slope: float
    years_to_expiry_at_minimum_time_slope: float
    minimum_local_variance: float
    log_moneyness_at_minimum_local_variance: float
    years_to_expiry_at_minimum_local_variance: float
    worst_local_variance_round_trip_error: float
    log_moneyness_at_worst_round_trip_error: float
    round_trip_point_count: int
    status: SviSurfaceStatus

DEFAULT_SURFACE_SCAN_STEPS: int
DEFAULT_TIME_STEPS_PER_INTERVAL: int

def scan_svi_surface(
    *,
    years_to_expiry: list[float],
    a: list[float],
    b: list[float],
    rho: list[float],
    m: list[float],
    sigma: list[float],
    lowest_log_moneyness: float,
    highest_log_moneyness: float,
    scan_steps: int,
    time_steps_per_interval: int,
) -> SviSurfaceScan: ...

class LatticeInputs:
    spot_price: float
    strike: float
    years_to_expiry: float
    volatility: float
    zero_rate: float
    carry_rate: float
    def __init__(
        self,
        *,
        spot_price: float,
        strike: float,
        years_to_expiry: float,
        volatility: float,
        zero_rate: float,
        carry_rate: float,
        option_type: OptionType,
        exercise_style: ExerciseStyle,
    ) -> None: ...

RICHARDSON_BASE_STEPS: int

def richardson_extrapolated_price(inputs: LatticeInputs) -> float: ...
def european_price(inputs: LatticeInputs) -> float: ...
def early_exercise_premium(inputs: LatticeInputs) -> float: ...

AmericanInversionStatus = Literal[
    "converged",
    "below_intrinsic",
    "above_no_arbitrage_bound",
    "at_exercise_boundary",
    "above_volatility_ceiling",
    "not_converged",
    "degenerate_expiry",
]

class AmericanInversionResult:
    volatility: float
    status: AmericanInversionStatus
    iterations: int
    absolute_price_error: float

def invert_american_implied_volatility(
    *,
    spot_price: float,
    strike: float,
    years_to_expiry: float,
    zero_rate: float,
    carry_rate: float,
    option_price: float,
    option_type: OptionType,
    exercise_style: ExerciseStyle,
) -> AmericanInversionResult: ...
def imply_forward_curve(
    quotes: list[ContractQuote], observation_time: str, zero_rate: float | None
) -> list[ForwardCurvePoint]: ...

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
