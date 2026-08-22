from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import mpmath

ORACLE_DECIMAL_PLACES: Final[int] = 50
mpmath.mp.dps = ORACLE_DECIMAL_PLACES


@dataclass(frozen=True)
class OraclePriceAndGreeks:
    price: mpmath.mpf
    delta_with_respect_to_forward: mpmath.mpf
    gamma_with_respect_to_forward: mpmath.mpf
    vega_with_respect_to_volatility: mpmath.mpf
    theta_with_respect_to_time: mpmath.mpf


def oracle_normal_cumulative_distribution(x: mpmath.mpf) -> mpmath.mpf:
    return mpmath.erfc(-x / mpmath.sqrt(2)) / 2


def oracle_normal_probability_density(x: mpmath.mpf) -> mpmath.mpf:
    return mpmath.exp(-x * x / 2) / mpmath.sqrt(2 * mpmath.pi)


def oracle_price_and_greeks(
    *,
    forward: float,
    strike: float,
    years_to_expiry: float,
    volatility: float,
    discount_factor: float,
    option_type: str,
) -> OraclePriceAndGreeks:
    f = mpmath.mpf(forward)
    k = mpmath.mpf(strike)
    t = mpmath.mpf(years_to_expiry)
    v = mpmath.mpf(volatility)
    df = mpmath.mpf(discount_factor)
    zero = mpmath.mpf(0)

    if t <= 0 or v <= 0:
        intrinsic = mpmath.mpf(max(f - k, zero)) if option_type == "call" else mpmath.mpf(max(k - f, zero))
        above = f > k
        delta = (df if above else zero) if option_type == "call" else (zero if above else -df)
        return OraclePriceAndGreeks(df * intrinsic, delta, zero, zero, zero)

    standard_deviation = v * mpmath.sqrt(t)
    d1 = (mpmath.log(f / k) + standard_deviation**2 / 2) / standard_deviation
    d2 = d1 - standard_deviation
    density_at_d1 = oracle_normal_probability_density(d1)
    normal = oracle_normal_cumulative_distribution

    if option_type == "call":
        price = df * (f * normal(d1) - k * normal(d2))
        delta = df * normal(d1)
    else:
        price = df * (k * normal(-d2) - f * normal(-d1))
        delta = -df * normal(-d1)

    return OraclePriceAndGreeks(
        price=price,
        delta_with_respect_to_forward=delta,
        gamma_with_respect_to_forward=df * density_at_d1 / (f * v * mpmath.sqrt(t)),
        vega_with_respect_to_volatility=df * f * density_at_d1 * mpmath.sqrt(t),
        theta_with_respect_to_time=-df * f * density_at_d1 * v / (2 * mpmath.sqrt(t)),
    )


def oracle_implied_volatility(
    *,
    forward: float,
    strike: float,
    years_to_expiry: float,
    discount_factor: float,
    option_price: float,
    option_type: str,
) -> mpmath.mpf | None:
    target = mpmath.mpf(option_price) / mpmath.mpf(discount_factor)

    def undiscounted_price_error(volatility: mpmath.mpf) -> mpmath.mpf:
        greeks = oracle_price_and_greeks(
            forward=forward,
            strike=strike,
            years_to_expiry=years_to_expiry,
            volatility=float(volatility),
            discount_factor=1.0,
            option_type=option_type,
        )
        return greeks.price - target

    try:
        return mpmath.findroot(
            undiscounted_price_error, mpmath.mpf("0.2"), solver="anderson", x1=mpmath.mpf("1.0")
        )
    except (ValueError, ZeroDivisionError):
        return None
