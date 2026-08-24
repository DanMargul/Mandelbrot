from __future__ import annotations

from dataclasses import replace

import pytest
from volarb_py.american import (
    RICHARDSON_BASE_STEPS,
    ExerciseStyle,
    InvalidLatticeInputsError,
    LatticeInputs,
    binomial_black_scholes_price,
    black_scholes_reference_price,
    cox_ross_rubinstein_price,
    early_exercise_premium,
    european_counterpart,
    richardson_extrapolated_price,
)

REFERENCE_SPOT = 100.0
REFERENCE_ZERO_RATE = 0.0425
STRIKES = (70.0, 90.0, 100.0, 110.0, 140.0)
VOLATILITIES = (0.12, 0.30, 0.65)
CARRY_RATES = (0.0, 0.025, 0.070)
EXPIRED_INTRINSIC = 10.0
FINE_LATTICE_BASE_STEPS = 512
FINE_LATTICE_RELATIVE_BUDGET = 1e-4

BASE = LatticeInputs(
    spot_price=REFERENCE_SPOT,
    strike=100.0,
    years_to_expiry=1.0,
    volatility=0.25,
    zero_rate=REFERENCE_ZERO_RATE,
    carry_rate=0.02,
    option_type="call",
    exercise_style="american",
)
EUROPEAN_BASE = replace(BASE, exercise_style="european")


def american_grid() -> list[LatticeInputs]:
    return [
        replace(BASE, strike=strike, volatility=volatility, carry_rate=carry, option_type=side)
        for strike in STRIKES
        for volatility in VOLATILITIES
        for carry in CARRY_RATES
        for side in ("call", "put")
    ]


def test_the_plain_lattice_converges_to_the_closed_form() -> None:
    inputs = replace(EUROPEAN_BASE, carry_rate=0.03)
    exact = black_scholes_reference_price(inputs)
    errors = [abs(cox_ross_rubinstein_price(inputs, steps) - exact) for steps in (64, 256, 1024)]
    assert errors == sorted(errors, reverse=True)


def test_the_terminal_correction_beats_a_far_finer_plain_lattice() -> None:
    inputs = replace(EUROPEAN_BASE, carry_rate=0.03)
    exact = black_scholes_reference_price(inputs)
    plain = abs(cox_ross_rubinstein_price(inputs, 1024) - exact)
    corrected = abs(richardson_extrapolated_price(inputs) - exact)
    assert corrected < plain


def test_the_terminal_correction_alone_beats_the_plain_lattice_at_equal_steps() -> None:
    inputs = replace(EUROPEAN_BASE, strike=140.0, years_to_expiry=2.0, volatility=0.65, carry_rate=0.0)
    exact = black_scholes_reference_price(inputs)
    plain = abs(cox_ross_rubinstein_price(inputs, RICHARDSON_BASE_STEPS) - exact)
    corrected = abs(binomial_black_scholes_price(inputs, RICHARDSON_BASE_STEPS) - exact)
    assert corrected < plain


@pytest.mark.parametrize("inputs", american_grid())
def test_an_american_price_is_never_below_its_european_counterpart(inputs: LatticeInputs) -> None:
    american = richardson_extrapolated_price(inputs)
    european = richardson_extrapolated_price(european_counterpart(inputs))
    assert american >= european - 1e-9


@pytest.mark.parametrize("inputs", american_grid())
def test_the_price_agrees_with_a_far_finer_lattice(inputs: LatticeInputs) -> None:
    coarse = richardson_extrapolated_price(inputs)
    fine = richardson_extrapolated_price(inputs, FINE_LATTICE_BASE_STEPS)
    assert abs(coarse - fine) / REFERENCE_SPOT < FINE_LATTICE_RELATIVE_BUDGET


@pytest.mark.parametrize("strike", STRIKES)
@pytest.mark.parametrize("volatility", VOLATILITIES)
def test_an_american_call_on_a_zero_carry_underlying_has_exactly_no_premium(
    strike: float, volatility: float
) -> None:
    inputs = replace(BASE, strike=strike, volatility=volatility, carry_rate=0.0)
    assert early_exercise_premium(inputs) == 0.0


def test_an_american_put_on_a_positive_rate_carries_a_premium() -> None:
    assert early_exercise_premium(replace(BASE, carry_rate=0.0, option_type="put")) > 0.0


def test_an_american_call_on_a_dividend_payer_carries_a_premium() -> None:
    assert early_exercise_premium(replace(BASE, carry_rate=0.06)) > 0.0


def test_a_european_contract_has_no_premium_by_construction() -> None:
    assert early_exercise_premium(replace(EUROPEAN_BASE, carry_rate=0.06)) == 0.0


@pytest.mark.parametrize("exercise_style", ["european", "american"])
def test_degenerate_inputs_return_intrinsic_value(exercise_style: ExerciseStyle) -> None:
    expired = replace(BASE, strike=90.0, years_to_expiry=0.0, exercise_style=exercise_style)
    assert richardson_extrapolated_price(expired) == pytest.approx(EXPIRED_INTRINSIC, rel=1e-15)
    motionless = replace(BASE, strike=90.0, volatility=0.0, exercise_style=exercise_style)
    assert richardson_extrapolated_price(motionless) == pytest.approx(EXPIRED_INTRINSIC, rel=1e-15)


@pytest.mark.parametrize(
    ("field", "value"),
    [("spot_price", 0.0), ("strike", -1.0), ("years_to_expiry", -1.0), ("volatility", -0.1)],
)
def test_invalid_lattice_inputs_are_rejected(field: str, value: float) -> None:
    broken = LatticeInputs(**{**vars(BASE), field: value})
    with pytest.raises(InvalidLatticeInputsError):
        cox_ross_rubinstein_price(broken, 64)


@pytest.mark.parametrize("steps", [1, 0, -4, 100000])
def test_an_out_of_range_step_count_is_rejected(steps: int) -> None:
    with pytest.raises(InvalidLatticeInputsError, match="steps"):
        cox_ross_rubinstein_price(BASE, steps)
