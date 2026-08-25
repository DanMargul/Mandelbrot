from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

from volarb_py.pricing import BlackScholesInputs, black_scholes_price_and_greeks
from volarb_py.random_source import seeded_source, standard_normals

BandRule = Literal["fixed", "whalley_wilmott"]

WHALLEY_WILMOTT_FACTOR: Final[float] = 1.5
MINIMUM_BAND: Final[float] = 1e-12
MINIMUM_RISK_AVERSION: Final[float] = 1e-12
MINIMUM_PATHS: Final[int] = 2
MINIMUM_STEPS: Final[int] = 1
ONE_THIRD: Final[float] = 1.0 / 3.0


class InvalidHedgingInputsError(ValueError):
    pass


@dataclass(frozen=True)
class HedgingInputs:
    spot: float
    strike: float
    years_to_expiry: float
    volatility: float
    steps: int
    proportional_cost: float
    risk_aversion: float


@dataclass(frozen=True)
class BandPolicy:
    rule: BandRule
    fixed_width: float


@dataclass(frozen=True)
class PathOutcome:
    terminal_profit: float
    transaction_cost: float
    rebalance_count: int


@dataclass(frozen=True)
class HedgingStatistics:
    path_count: int
    mean_profit: float
    profit_standard_deviation: float
    mean_transaction_cost: float
    mean_rebalance_count: float
    certainty_equivalent: float


def validate_inputs(inputs: HedgingInputs) -> None:
    if inputs.spot <= 0.0:
        raise InvalidHedgingInputsError(f"spot must be positive, got {inputs.spot}")
    if inputs.strike <= 0.0:
        raise InvalidHedgingInputsError(f"strike must be positive, got {inputs.strike}")
    if inputs.years_to_expiry <= 0.0:
        raise InvalidHedgingInputsError(f"years_to_expiry must be positive, got {inputs.years_to_expiry}")
    if inputs.volatility <= 0.0:
        raise InvalidHedgingInputsError(f"volatility must be positive, got {inputs.volatility}")
    if inputs.steps < MINIMUM_STEPS:
        raise InvalidHedgingInputsError(f"steps must be at least {MINIMUM_STEPS}, got {inputs.steps}")
    if inputs.proportional_cost < 0.0:
        raise InvalidHedgingInputsError(
            f"proportional_cost must not be negative, got {inputs.proportional_cost}"
        )
    if inputs.risk_aversion <= MINIMUM_RISK_AVERSION:
        raise InvalidHedgingInputsError(f"risk_aversion must be positive, got {inputs.risk_aversion}")


def validate_policy(policy: BandPolicy) -> None:
    if policy.rule == "fixed" and policy.fixed_width < 0.0:
        raise InvalidHedgingInputsError(f"fixed_width must not be negative, got {policy.fixed_width}")


def whalley_wilmott_band(spot: float, gamma: float, proportional_cost: float, risk_aversion: float) -> float:
    if risk_aversion <= MINIMUM_RISK_AVERSION:
        raise InvalidHedgingInputsError(f"risk_aversion must be positive, got {risk_aversion}")
    numerator = WHALLEY_WILMOTT_FACTOR * proportional_cost * spot * gamma * gamma
    return math.pow(numerator / risk_aversion, ONE_THIRD)


def call_greeks(inputs: HedgingInputs, spot: float, remaining: float) -> tuple[float, float, float]:
    priced = black_scholes_price_and_greeks(
        BlackScholesInputs(
            forward=spot,
            strike=inputs.strike,
            years_to_expiry=remaining,
            volatility=inputs.volatility,
            discount_factor=1.0,
            option_type="call",
        )
    )
    return (
        priced.price,
        priced.delta_with_respect_to_forward,
        priced.gamma_with_respect_to_forward,
    )


def band_for(policy: BandPolicy, inputs: HedgingInputs, spot: float, gamma: float) -> float:
    if policy.rule == "fixed":
        return policy.fixed_width
    return whalley_wilmott_band(spot, gamma, inputs.proportional_cost, inputs.risk_aversion)


def hedge_one_path(inputs: HedgingInputs, policy: BandPolicy, shocks: list[float]) -> PathOutcome:
    step_years = inputs.years_to_expiry / inputs.steps
    drift = -0.5 * inputs.volatility * inputs.volatility * step_years
    diffusion = inputs.volatility * math.sqrt(step_years)

    spot = inputs.spot
    opening_price, opening_delta, _ = call_greeks(inputs, spot, inputs.years_to_expiry)
    hedge = opening_delta
    cost = inputs.proportional_cost * abs(hedge) * spot
    rebalances = 1
    hedge_profit = 0.0

    for index in range(inputs.steps):
        moved = spot * math.exp(drift + diffusion * shocks[index])
        hedge_profit += hedge * (moved - spot)
        spot = moved
        remaining = inputs.years_to_expiry - step_years * (index + 1)
        if remaining <= 0.0:
            break
        _, delta, gamma = call_greeks(inputs, spot, remaining)
        width = max(band_for(policy, inputs, spot, gamma), MINIMUM_BAND)
        if abs(hedge - delta) > width:
            cost += inputs.proportional_cost * abs(delta - hedge) * spot
            hedge = delta
            rebalances += 1

    payoff = max(spot - inputs.strike, 0.0)
    cost += inputs.proportional_cost * abs(hedge) * spot
    return PathOutcome(
        terminal_profit=opening_price - payoff + hedge_profit - cost,
        transaction_cost=cost,
        rebalance_count=rebalances + 1,
    )


def hedging_statistics(
    inputs: HedgingInputs, policy: BandPolicy, initial_state: int, sequence: int, path_count: int
) -> HedgingStatistics:
    validate_inputs(inputs)
    validate_policy(policy)
    if path_count < MINIMUM_PATHS:
        raise InvalidHedgingInputsError(f"path_count must be at least {MINIMUM_PATHS}, got {path_count}")

    profits: list[float] = []
    total_cost = 0.0
    total_rebalances = 0
    source = seeded_source(initial_state, sequence)
    for _ in range(path_count):
        source, shocks = standard_normals(source, inputs.steps)
        outcome = hedge_one_path(inputs, policy, shocks)
        profits.append(outcome.terminal_profit)
        total_cost += outcome.transaction_cost
        total_rebalances += outcome.rebalance_count

    mean = 0.0
    for profit in profits:
        mean += profit
    mean /= path_count
    squared = 0.0
    for profit in profits:
        squared += (profit - mean) * (profit - mean)
    variance = squared / (path_count - 1)

    return HedgingStatistics(
        path_count=path_count,
        mean_profit=mean,
        profit_standard_deviation=math.sqrt(max(variance, 0.0)),
        mean_transaction_cost=total_cost / path_count,
        mean_rebalance_count=total_rebalances / path_count,
        certainty_equivalent=mean - 0.5 * inputs.risk_aversion * variance,
    )
