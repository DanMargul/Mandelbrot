from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Final, Literal

from volarb_py.american import (
    AmericanInversionInputs,
    LatticeInputs,
    early_exercise_premium,
    invert_american_implied_volatility,
)
from volarb_py.market_data import ContractQuote

ForwardCurveStatus = Literal[
    "converged",
    "too_few_pairs",
    "degenerate_strike_range",
    "non_positive_discount_factor",
    "american_quotes_not_stripped",
]

MINIMUM_PARITY_PAIRS: Final[int] = 4
MAXIMUM_TRIMMING_PASSES: Final[int] = 5
OUTLIER_REJECTION_SIGMAS: Final[float] = 4.0
MEDIAN_ABSOLUTE_DEVIATION_SCALE: Final[float] = 1.4826
MINIMUM_HALF_SPREAD: Final[float] = 1e-8
EXPIRY_SETTLEMENT_HOUR_UTC: Final[int] = 21
DAYS_PER_YEAR: Final[float] = 365.0
SECONDS_PER_DAY: Final[float] = 86400.0
MAXIMUM_STRIPPING_PASSES: Final[int] = 4
FORWARD_STRIPPING_TOLERANCE: Final[float] = 1e-6
MINIMUM_COVARIANCE_INFLATION: Final[float] = 1.0


@dataclass(frozen=True)
class ParityPair:
    strike: float
    call_minus_put_mid: float
    weight: float


@dataclass(frozen=True)
class ForwardCurvePoint:
    expiry_date: date
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


@dataclass(frozen=True)
class WeightedLineFit:
    slope: float
    weighted_mean_strike: float
    weighted_mean_value: float
    slope_variance: float
    mean_value_variance: float
    chi_square_per_degree_of_freedom: float

    def value_at(self, strike: float) -> float:
        return self.weighted_mean_value + self.slope * (strike - self.weighted_mean_strike)


def median_of(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def years_to_expiry_from(observation_time: datetime, expiry: date) -> float:
    settlement = datetime(expiry.year, expiry.month, expiry.day, EXPIRY_SETTLEMENT_HOUR_UTC, tzinfo=UTC)
    return (settlement - observation_time).total_seconds() / (DAYS_PER_YEAR * SECONDS_PER_DAY)


def is_two_sided(quote: ContractQuote) -> bool:
    return quote.ask_price >= quote.bid_price and quote.ask_price > 0.0


def half_spread_of(quote: ContractQuote) -> float:
    return max(0.5 * (quote.ask_price - quote.bid_price), MINIMUM_HALF_SPREAD)


def mid_price_of(quote: ContractQuote) -> float:
    return 0.5 * (quote.bid_price + quote.ask_price)


def parity_pair_from(call: ContractQuote, put: ContractQuote) -> ParityPair:
    call_half_spread = half_spread_of(call)
    put_half_spread = half_spread_of(put)
    variance = call_half_spread * call_half_spread + put_half_spread * put_half_spread
    return ParityPair(
        strike=call.strike,
        call_minus_put_mid=mid_price_of(call) - mid_price_of(put),
        weight=1.0 / variance,
    )


def paired_quotes_from_chain(
    quotes: list[ContractQuote],
) -> dict[date, list[tuple[ContractQuote, ContractQuote]]]:
    calls: dict[tuple[date, float], ContractQuote] = {}
    puts: dict[tuple[date, float], ContractQuote] = {}
    for quote in quotes:
        if not is_two_sided(quote):
            continue
        side = calls if quote.option_type == "call" else puts
        side[(quote.expiry_date, quote.strike)] = quote

    paired: dict[date, list[tuple[ContractQuote, ContractQuote]]] = {}
    for key in sorted(calls.keys() & puts.keys()):
        paired.setdefault(key[0], []).append((calls[key], puts[key]))
    return paired


def parity_pairs_from_chain(quotes: list[ContractQuote]) -> dict[date, list[ParityPair]]:
    return {
        expiry_date: [parity_pair_from(call, put) for call, put in pairs]
        for expiry_date, pairs in paired_quotes_from_chain(quotes).items()
    }


def carry_rate_from(forward: float, spot_price: float, years: float, zero_rate: float) -> float:
    return zero_rate - math.log(forward / spot_price) / years


def european_equivalent_price(
    quote: ContractQuote, years: float, zero_rate: float, carry_rate: float
) -> float:
    observed = mid_price_of(quote)
    inversion = invert_american_implied_volatility(
        AmericanInversionInputs(
            spot_price=quote.underlying_price,
            strike=quote.strike,
            years_to_expiry=years,
            zero_rate=zero_rate,
            carry_rate=carry_rate,
            option_price=observed,
            option_type=quote.option_type,
            exercise_style=quote.exercise_style,
        )
    )
    if inversion.status != "converged":
        return observed
    premium = early_exercise_premium(
        LatticeInputs(
            spot_price=quote.underlying_price,
            strike=quote.strike,
            years_to_expiry=years,
            volatility=inversion.volatility,
            zero_rate=zero_rate,
            carry_rate=carry_rate,
            option_type=quote.option_type,
            exercise_style=quote.exercise_style,
        )
    )
    return observed - premium


def stripped_parity_pair(
    call: ContractQuote, put: ContractQuote, years: float, zero_rate: float, carry_rate: float
) -> ParityPair:
    call_half_spread = half_spread_of(call)
    put_half_spread = half_spread_of(put)
    return ParityPair(
        strike=call.strike,
        call_minus_put_mid=european_equivalent_price(call, years, zero_rate, carry_rate)
        - european_equivalent_price(put, years, zero_rate, carry_rate),
        weight=1.0 / (call_half_spread * call_half_spread + put_half_spread * put_half_spread),
    )


def fit_weighted_line(pairs: list[ParityPair]) -> WeightedLineFit | None:
    total_weight = sum(pair.weight for pair in pairs)
    if total_weight <= 0.0:
        return None
    mean_strike = sum(pair.weight * pair.strike for pair in pairs) / total_weight
    mean_value = sum(pair.weight * pair.call_minus_put_mid for pair in pairs) / total_weight

    centred_strike_squared = sum(pair.weight * (pair.strike - mean_strike) ** 2 for pair in pairs)
    if centred_strike_squared <= 0.0:
        return None
    centred_cross_product = sum(
        pair.weight * (pair.strike - mean_strike) * (pair.call_minus_put_mid - mean_value) for pair in pairs
    )

    slope = centred_cross_product / centred_strike_squared
    weighted_residual_sum = sum(
        pair.weight * (pair.call_minus_put_mid - (mean_value + slope * (pair.strike - mean_strike))) ** 2
        for pair in pairs
    )
    chi_square = weighted_residual_sum / float(len(pairs) - 2)
    inflation = max(chi_square, MINIMUM_COVARIANCE_INFLATION)

    return WeightedLineFit(
        slope=slope,
        weighted_mean_strike=mean_strike,
        weighted_mean_value=mean_value,
        slope_variance=inflation / centred_strike_squared,
        mean_value_variance=inflation / total_weight,
        chi_square_per_degree_of_freedom=chi_square,
    )


def trimmed_pairs(pairs: list[ParityPair]) -> list[ParityPair]:
    active = list(pairs)
    for _ in range(MAXIMUM_TRIMMING_PASSES):
        fit = fit_weighted_line(active)
        if fit is None:
            return active
        residuals = [pair.call_minus_put_mid - fit.value_at(pair.strike) for pair in active]
        centre = median_of(residuals)
        scale = MEDIAN_ABSOLUTE_DEVIATION_SCALE * median_of([abs(value - centre) for value in residuals])
        if scale <= 0.0:
            return active
        kept = [
            pair
            for pair, residual in zip(active, residuals, strict=True)
            if abs(residual - centre) <= OUTLIER_REJECTION_SIGMAS * scale
        ]
        if len(kept) < MINIMUM_PARITY_PAIRS or len(kept) == len(active):
            return active
        active = kept
    return active


def forward_from(fit: WeightedLineFit) -> float:
    return fit.weighted_mean_strike - fit.weighted_mean_value / fit.slope


def forward_variance_from(fit: WeightedLineFit) -> float:
    slope_squared = fit.slope * fit.slope
    return (
        fit.mean_value_variance / slope_squared
        + fit.weighted_mean_value
        * fit.weighted_mean_value
        * fit.slope_variance
        / (slope_squared * slope_squared)
    )


def failed_point(
    expiry_date: date, years: float, spot_price: float, pair_count: int, status: ForwardCurveStatus
) -> ForwardCurvePoint:
    return ForwardCurvePoint(
        expiry_date=expiry_date,
        years_to_expiry=years,
        spot_price=spot_price,
        forward=0.0,
        forward_standard_error=None,
        discount_factor=0.0,
        discount_factor_standard_error=None,
        implied_zero_rate=None,
        implied_carry_rate=None,
        parity_pair_count=pair_count,
        active_pair_count=0,
        chi_square_per_degree_of_freedom=None,
        early_exercise_premium_stripped=False,
        discount_factor_is_monotone_in_expiry=False,
        status=status,
    )


def curve_point_for_expiry(
    expiry_date: date, pairs: list[ParityPair], years: float, spot_price: float
) -> ForwardCurvePoint:
    if len(pairs) < MINIMUM_PARITY_PAIRS:
        return failed_point(expiry_date, years, spot_price, len(pairs), "too_few_pairs")

    active = trimmed_pairs(pairs)
    fit = fit_weighted_line(active)
    if fit is None:
        return failed_point(expiry_date, years, spot_price, len(pairs), "degenerate_strike_range")
    if fit.slope >= 0.0:
        return failed_point(expiry_date, years, spot_price, len(pairs), "non_positive_discount_factor")

    discount_factor = -fit.slope
    forward = forward_from(fit)
    zero_rate = -math.log(discount_factor) / years
    return ForwardCurvePoint(
        expiry_date=expiry_date,
        years_to_expiry=years,
        spot_price=spot_price,
        forward=forward,
        forward_standard_error=math.sqrt(max(forward_variance_from(fit), 0.0)),
        discount_factor=discount_factor,
        discount_factor_standard_error=math.sqrt(max(fit.slope_variance, 0.0)),
        implied_zero_rate=zero_rate,
        implied_carry_rate=zero_rate - math.log(forward / spot_price) / years,
        parity_pair_count=len(pairs),
        active_pair_count=len(active),
        chi_square_per_degree_of_freedom=fit.chi_square_per_degree_of_freedom,
        early_exercise_premium_stripped=False,
        discount_factor_is_monotone_in_expiry=False,
        status="converged",
    )


def discount_factors_are_monotone(points: list[ForwardCurvePoint]) -> bool:
    converged = sorted(
        (point for point in points if point.status == "converged"), key=lambda point: point.expiry_date
    )
    return all(later.discount_factor <= earlier.discount_factor for earlier, later in pairwise(converged))


def expiry_has_american_quotes(quotes: list[ContractQuote], expiry_date: date) -> bool:
    return any(quote.expiry_date == expiry_date and quote.exercise_style == "american" for quote in quotes)


def spot_price_for(quotes: list[ContractQuote], expiry_date: date) -> float:
    for quote in quotes:
        if quote.expiry_date == expiry_date:
            return quote.underlying_price
    return 0.0


def stripped_curve_point(
    expiry_date: date,
    quote_pairs: list[tuple[ContractQuote, ContractQuote]],
    years: float,
    spot_price: float,
    zero_rate: float,
) -> ForwardCurvePoint:
    seed = curve_point_for_expiry(
        expiry_date, [parity_pair_from(call, put) for call, put in quote_pairs], years, spot_price
    )
    if seed.status != "converged":
        return seed

    forward = seed.forward
    point = seed
    for _ in range(MAXIMUM_STRIPPING_PASSES):
        carry_rate = carry_rate_from(forward, spot_price, years, zero_rate)
        pairs = [stripped_parity_pair(call, put, years, zero_rate, carry_rate) for call, put in quote_pairs]
        point = curve_point_for_expiry(expiry_date, pairs, years, spot_price)
        if point.status != "converged":
            return point
        settled = abs(point.forward - forward) <= FORWARD_STRIPPING_TOLERANCE * point.forward
        forward = point.forward
        if settled:
            break
    return replace(point, early_exercise_premium_stripped=True)


def imply_forward_curve(
    quotes: list[ContractQuote], observation_time: datetime, zero_rate: float | None = None
) -> list[ForwardCurvePoint]:
    paired = paired_quotes_from_chain(quotes)
    points: list[ForwardCurvePoint] = []
    for expiry_date in sorted(paired):
        years = years_to_expiry_from(observation_time, expiry_date)
        if years <= 0.0:
            continue
        spot_price = spot_price_for(quotes, expiry_date)
        quote_pairs = paired[expiry_date]

        if not expiry_has_american_quotes(quotes, expiry_date):
            pairs = [parity_pair_from(call, put) for call, put in quote_pairs]
            points.append(curve_point_for_expiry(expiry_date, pairs, years, spot_price))
        elif zero_rate is None:
            points.append(
                failed_point(expiry_date, years, spot_price, len(quote_pairs), "american_quotes_not_stripped")
            )
        else:
            points.append(stripped_curve_point(expiry_date, quote_pairs, years, spot_price, zero_rate))

    monotone = discount_factors_are_monotone(points)
    return [replace(point, discount_factor_is_monotone_in_expiry=monotone) for point in points]
