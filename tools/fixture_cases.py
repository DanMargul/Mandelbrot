from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

ORDINARY_STRIKES: Final[tuple[float, ...]] = (60.0, 80.0, 95.0, 99.0, 100.0, 101.0, 105.0, 120.0, 160.0)
ORDINARY_EXPIRIES: Final[tuple[float, ...]] = (0.019178, 0.083333, 0.25, 0.5, 1.0, 2.0)
ORDINARY_VOLATILITIES: Final[tuple[float, ...]] = (0.08, 0.12, 0.18, 0.25, 0.40, 0.75)

REFERENCE_FORWARD: Final[float] = 100.0
REFERENCE_DISCOUNT_FACTOR: Final[float] = 0.9876543


@dataclass(frozen=True)
class PricingCase:
    id: str
    forward: float
    strike: float
    years_to_expiry: float
    volatility: float
    discount_factor: float
    option_type: str


def ordinary_pricing_cases() -> list[PricingCase]:
    cases: list[PricingCase] = []
    for strike in ORDINARY_STRIKES:
        for years in ORDINARY_EXPIRIES:
            for volatility in ORDINARY_VOLATILITIES:
                for option_type in ("call", "put"):
                    identifier = f"k{strike:g}_t{years:g}_v{volatility:g}_{option_type}"
                    cases.append(
                        PricingCase(
                            id=identifier,
                            forward=REFERENCE_FORWARD,
                            strike=strike,
                            years_to_expiry=years,
                            volatility=volatility,
                            discount_factor=REFERENCE_DISCOUNT_FACTOR,
                            option_type=option_type,
                        )
                    )
    return cases


def degenerate_pricing_cases() -> list[PricingCase]:
    specifications = (
        ("expired_in_the_money", 100.0, 90.0, 0.0, 0.20),
        ("expired_out_of_the_money", 100.0, 110.0, 0.0, 0.20),
        ("expired_at_the_kink", 100.0, 100.0, 0.0, 0.20),
        ("zero_volatility_in_the_money", 100.0, 90.0, 1.0, 0.0),
        ("zero_volatility_out_of_the_money", 100.0, 110.0, 1.0, 0.0),
        ("zero_volatility_at_the_kink", 100.0, 100.0, 1.0, 0.0),
        ("one_day_at_the_money", 100.0, 100.0, 0.002740, 0.20),
        ("very_low_volatility", 100.0, 100.0, 1.0, 0.001),
        ("very_high_volatility", 100.0, 100.0, 1.0, 4.0),
        ("long_dated", 100.0, 100.0, 10.0, 0.30),
    )
    cases: list[PricingCase] = []
    for name, forward, strike, years, volatility in specifications:
        for option_type in ("call", "put"):
            cases.append(
                PricingCase(
                    id=f"{name}_{option_type}",
                    forward=forward,
                    strike=strike,
                    years_to_expiry=years,
                    volatility=volatility,
                    discount_factor=REFERENCE_DISCOUNT_FACTOR,
                    option_type=option_type,
                )
            )
    return cases


def wing_pricing_cases() -> list[PricingCase]:
    specifications = (
        ("deep_out_of_the_money_call", 100.0, 400.0, 0.25, 0.30, "call"),
        ("deep_out_of_the_money_put", 100.0, 25.0, 0.25, 0.30, "put"),
        ("deep_in_the_money_call", 100.0, 25.0, 0.25, 0.30, "call"),
        ("deep_in_the_money_put", 100.0, 400.0, 0.25, 0.30, "put"),
        ("far_wing_short_dated_call", 100.0, 200.0, 0.019178, 0.60, "call"),
        ("far_wing_short_dated_put", 100.0, 50.0, 0.019178, 0.60, "put"),
        ("low_forward_low_strike_call", 2.5, 2.0, 0.5, 0.45, "call"),
        ("high_forward_high_strike_put", 5400.0, 5600.0, 0.75, 0.14, "put"),
    )
    return [
        PricingCase(
            id=name,
            forward=forward,
            strike=strike,
            years_to_expiry=years,
            volatility=volatility,
            discount_factor=REFERENCE_DISCOUNT_FACTOR,
            option_type=option_type,
        )
        for name, forward, strike, years, volatility, option_type in specifications
    ]


def all_pricing_cases() -> dict[str, list[PricingCase]]:
    return {
        "ordinary": ordinary_pricing_cases(),
        "degenerate": degenerate_pricing_cases(),
        "wings": wing_pricing_cases(),
    }


@dataclass(frozen=True)
class AmericanCase:
    id: str
    spot_price: float
    strike: float
    years_to_expiry: float
    volatility: float
    zero_rate: float
    carry_rate: float
    option_type: Literal["call", "put"]
    exercise_style: Literal["european", "american"]


AMERICAN_STRIKES: Final[tuple[float, ...]] = (70.0, 90.0, 100.0, 110.0, 140.0)
AMERICAN_EXPIRIES: Final[tuple[float, ...]] = (0.083333, 0.5, 2.0)
AMERICAN_VOLATILITIES: Final[tuple[float, ...]] = (0.12, 0.30, 0.65)
AMERICAN_CARRY_RATES: Final[tuple[float, ...]] = (0.0, 0.025, 0.070)
AMERICAN_SPOT: Final[float] = 100.0
AMERICAN_ZERO_RATE: Final[float] = 0.0425


def american_pricing_cases() -> list[AmericanCase]:
    cases: list[AmericanCase] = []
    for strike in AMERICAN_STRIKES:
        for years in AMERICAN_EXPIRIES:
            for volatility in AMERICAN_VOLATILITIES:
                for carry_rate in AMERICAN_CARRY_RATES:
                    option_types: tuple[Literal["call", "put"], ...] = ("call", "put")
                    styles: tuple[Literal["european", "american"], ...] = ("european", "american")
                    for option_type in option_types:
                        for exercise_style in styles:
                            identifier = (
                                f"k{strike:g}_t{years:g}_v{volatility:g}"
                                f"_q{carry_rate:g}_{option_type}_{exercise_style}"
                            )
                            cases.append(
                                AmericanCase(
                                    id=identifier,
                                    spot_price=AMERICAN_SPOT,
                                    strike=strike,
                                    years_to_expiry=years,
                                    volatility=volatility,
                                    zero_rate=AMERICAN_ZERO_RATE,
                                    carry_rate=carry_rate,
                                    option_type=option_type,
                                    exercise_style=exercise_style,
                                )
                            )
    return cases


def degenerate_american_cases() -> list[AmericanCase]:
    specifications = (
        ("expired_in_the_money", 100.0, 90.0, 0.0, 0.30),
        ("expired_out_of_the_money", 100.0, 110.0, 0.0, 0.30),
        ("zero_volatility", 100.0, 95.0, 1.0, 0.0),
        ("deep_in_the_money_long_dated", 100.0, 250.0, 3.0, 0.20),
        ("deep_out_of_the_money_short_dated", 100.0, 220.0, 0.019178, 0.20),
        ("negative_carry", 100.0, 100.0, 1.0, 0.25),
    )
    cases: list[AmericanCase] = []
    degenerate_types: tuple[Literal["call", "put"], ...] = ("call", "put")
    for name, spot_price, strike, years, volatility in specifications:
        carry_rate = -0.030 if name == "negative_carry" else 0.020
        for option_type in degenerate_types:
            cases.append(
                AmericanCase(
                    id=f"{name}_{option_type}",
                    spot_price=spot_price,
                    strike=strike,
                    years_to_expiry=years,
                    volatility=volatility,
                    zero_rate=AMERICAN_ZERO_RATE,
                    carry_rate=carry_rate,
                    option_type=option_type,
                    exercise_style="american",
                )
            )
    return cases


def all_american_cases() -> dict[str, list[AmericanCase]]:
    return {"lattice": american_pricing_cases(), "degenerate": degenerate_american_cases()}
