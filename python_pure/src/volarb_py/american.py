from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

from volarb_py.pricing import BlackScholesInputs, OptionType, black_scholes_price

ExerciseStyle = Literal["european", "american"]

RICHARDSON_BASE_STEPS: Final[int] = 128
MINIMUM_LATTICE_STEPS: Final[int] = 2
MAXIMUM_LATTICE_STEPS: Final[int] = 4096


class InvalidLatticeInputsError(ValueError):
    pass


@dataclass(frozen=True)
class LatticeInputs:
    spot_price: float
    strike: float
    years_to_expiry: float
    volatility: float
    zero_rate: float
    carry_rate: float
    option_type: OptionType
    exercise_style: ExerciseStyle


def validate_lattice_inputs(inputs: LatticeInputs, steps: int) -> None:
    if not inputs.spot_price > 0.0:
        raise InvalidLatticeInputsError(f"spot_price must be positive, got {inputs.spot_price}")
    if not inputs.strike > 0.0:
        raise InvalidLatticeInputsError(f"strike must be positive, got {inputs.strike}")
    if inputs.years_to_expiry < 0.0:
        raise InvalidLatticeInputsError(f"years_to_expiry must not be negative, got {inputs.years_to_expiry}")
    if inputs.volatility < 0.0:
        raise InvalidLatticeInputsError(f"volatility must not be negative, got {inputs.volatility}")
    if not MINIMUM_LATTICE_STEPS <= steps <= MAXIMUM_LATTICE_STEPS:
        raise InvalidLatticeInputsError(
            f"steps must lie in [{MINIMUM_LATTICE_STEPS}, {MAXIMUM_LATTICE_STEPS}], got {steps}"
        )


def intrinsic_value(spot_price: float, strike: float, option_type: OptionType) -> float:
    if option_type == "call":
        return max(spot_price - strike, 0.0)
    return max(strike - spot_price, 0.0)


def spot_ladder(spot_price: float, log_up: float, steps: int) -> list[float]:
    return [spot_price * math.exp(log_up * (index - steps)) for index in range(2 * steps + 1)]


def cox_ross_rubinstein_price(inputs: LatticeInputs, steps: int) -> float:
    validate_lattice_inputs(inputs, steps)
    if inputs.years_to_expiry <= 0.0 or inputs.volatility <= 0.0:
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type)

    time_step = inputs.years_to_expiry / float(steps)
    log_up = inputs.volatility * math.sqrt(time_step)
    up_move = math.exp(log_up)
    down_move = math.exp(-log_up)
    growth = math.exp((inputs.zero_rate - inputs.carry_rate) * time_step)
    discount = math.exp(-inputs.zero_rate * time_step)
    up_probability = (growth - down_move) / (up_move - down_move)
    down_probability = 1.0 - up_probability

    ladder = spot_ladder(inputs.spot_price, log_up, steps)
    values = [
        intrinsic_value(ladder[2 * node], inputs.strike, inputs.option_type) for node in range(steps + 1)
    ]

    is_american = inputs.exercise_style == "american"
    for level in range(steps - 1, -1, -1):
        offset = steps - level
        for node in range(level + 1):
            continuation = discount * (up_probability * values[node + 1] + down_probability * values[node])
            if is_american:
                exercise = intrinsic_value(ladder[offset + 2 * node], inputs.strike, inputs.option_type)
                values[node] = max(continuation, exercise)
            else:
                values[node] = continuation
    return values[0]


def one_step_black_scholes_value(inputs: LatticeInputs, spot_price: float, time_step: float) -> float:
    carry = inputs.zero_rate - inputs.carry_rate
    return black_scholes_price(
        BlackScholesInputs(
            forward=spot_price * math.exp(carry * time_step),
            strike=inputs.strike,
            years_to_expiry=time_step,
            volatility=inputs.volatility,
            discount_factor=math.exp(-inputs.zero_rate * time_step),
            option_type=inputs.option_type,
        )
    )


def binomial_black_scholes_price(inputs: LatticeInputs, steps: int) -> float:
    validate_lattice_inputs(inputs, steps)
    if inputs.years_to_expiry <= 0.0 or inputs.volatility <= 0.0:
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type)

    time_step = inputs.years_to_expiry / float(steps)
    log_up = inputs.volatility * math.sqrt(time_step)
    up_move = math.exp(log_up)
    down_move = math.exp(-log_up)
    growth = math.exp((inputs.zero_rate - inputs.carry_rate) * time_step)
    discount = math.exp(-inputs.zero_rate * time_step)
    up_probability = (growth - down_move) / (up_move - down_move)
    down_probability = 1.0 - up_probability

    ladder = spot_ladder(inputs.spot_price, log_up, steps)
    is_american = inputs.exercise_style == "american"

    values = [0.0] * (steps + 1)
    for node in range(steps):
        spot_at_node = ladder[1 + 2 * node]
        smoothed = one_step_black_scholes_value(inputs, spot_at_node, time_step)
        if is_american:
            smoothed = max(smoothed, intrinsic_value(spot_at_node, inputs.strike, inputs.option_type))
        values[node] = smoothed

    for level in range(steps - 2, -1, -1):
        offset = steps - level
        for node in range(level + 1):
            continuation = discount * (up_probability * values[node + 1] + down_probability * values[node])
            if is_american:
                exercise = intrinsic_value(ladder[offset + 2 * node], inputs.strike, inputs.option_type)
                values[node] = max(continuation, exercise)
            else:
                values[node] = continuation
    return values[0]


def richardson_extrapolated_price(inputs: LatticeInputs, base_steps: int = RICHARDSON_BASE_STEPS) -> float:
    coarse = binomial_black_scholes_price(inputs, base_steps)
    fine = binomial_black_scholes_price(inputs, 2 * base_steps)
    return 2.0 * fine - coarse


def european_counterpart(inputs: LatticeInputs) -> LatticeInputs:
    return LatticeInputs(
        spot_price=inputs.spot_price,
        strike=inputs.strike,
        years_to_expiry=inputs.years_to_expiry,
        volatility=inputs.volatility,
        zero_rate=inputs.zero_rate,
        carry_rate=inputs.carry_rate,
        option_type=inputs.option_type,
        exercise_style="european",
    )


def early_exercise_premium(inputs: LatticeInputs, base_steps: int = RICHARDSON_BASE_STEPS) -> float:
    if inputs.exercise_style == "european":
        return 0.0
    american = richardson_extrapolated_price(inputs, base_steps)
    european = richardson_extrapolated_price(european_counterpart(inputs), base_steps)
    return max(american - european, 0.0)


def black_scholes_reference_price(inputs: LatticeInputs) -> float:
    if inputs.years_to_expiry <= 0.0 or inputs.volatility <= 0.0:
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type)
    carry = inputs.zero_rate - inputs.carry_rate
    return black_scholes_price(
        BlackScholesInputs(
            forward=inputs.spot_price * math.exp(carry * inputs.years_to_expiry),
            strike=inputs.strike,
            years_to_expiry=inputs.years_to_expiry,
            volatility=inputs.volatility,
            discount_factor=math.exp(-inputs.zero_rate * inputs.years_to_expiry),
            option_type=inputs.option_type,
        )
    )
