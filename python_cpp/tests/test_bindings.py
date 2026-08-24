from __future__ import annotations

import math

import pytest
from volarb_cpp import _volarb_core as core

FORWARD = 100.0
DISCOUNT_FACTOR = 0.9876543
STRIKES = (60.0, 90.0, 99.0, 100.0, 101.0, 130.0, 250.0)
EXPIRIES = (0.019178, 0.25, 1.0, 5.0)
VOLATILITIES = (0.05, 0.15, 0.35, 1.2)
SPX_EXPIRY_COUNT = 2
RICHARDSON_BASE_STEPS = 128


def pricing_inputs(strike: float, years: float, volatility: float, option_type: str) -> object:
    return core.BlackScholesInputs(
        forward=FORWARD,
        strike=strike,
        years_to_expiry=years,
        volatility=volatility,
        discount_factor=DISCOUNT_FACTOR,
        option_type=option_type,
    )


def every_ordinary_case() -> list[tuple[float, float, float]]:
    return [
        (strike, years, volatility) for strike in STRIKES for years in EXPIRIES for volatility in VOLATILITIES
    ]


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_put_call_parity_holds(strike: float, years: float, volatility: float) -> None:
    call = core.black_scholes_price(pricing_inputs(strike, years, volatility, "call"))
    put = core.black_scholes_price(pricing_inputs(strike, years, volatility, "put"))
    assert call - put == pytest.approx(DISCOUNT_FACTOR * (FORWARD - strike), rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_delta_parity_holds(strike: float, years: float, volatility: float) -> None:
    call = core.black_scholes_price_and_greeks(pricing_inputs(strike, years, volatility, "call"))
    put = core.black_scholes_price_and_greeks(pricing_inputs(strike, years, volatility, "put"))
    difference = call.delta_with_respect_to_forward - put.delta_with_respect_to_forward
    assert difference == pytest.approx(DISCOUNT_FACTOR, rel=1e-12)


@pytest.mark.parametrize(("strike", "years", "volatility"), every_ordinary_case())
def test_round_trip_through_the_native_solver(strike: float, years: float, volatility: float) -> None:
    option_type = core.out_of_the_money_option_type(FORWARD, strike)
    price = core.black_scholes_price(pricing_inputs(strike, years, volatility, option_type))
    result = core.invert_black_implied_volatility(
        core.ImpliedVolatilityInputs(
            forward=FORWARD,
            strike=strike,
            years_to_expiry=years,
            discount_factor=DISCOUNT_FACTOR,
            option_price=price,
            option_type=option_type,
        )
    )
    if result.status != "converged":
        pytest.skip(f"not invertible in double precision: {result.status}")
    if result.volatility_uncertainty > 1e-6 * volatility:
        pytest.skip("quote does not resolve the volatility")
    assert result.volatility == pytest.approx(volatility, rel=1.2e-12)


def test_the_batch_entry_points_match_the_scalar_ones() -> None:
    batch = [pricing_inputs(strike, 1.0, 0.2, "call") for strike in STRIKES]
    scalar = [core.black_scholes_price_and_greeks(inputs).price for inputs in batch]
    vectorised = [greeks.price for greeks in core.black_scholes_price_and_greeks_batch(batch)]
    assert scalar == vectorised


def test_an_invalid_input_raises_a_value_error() -> None:
    with pytest.raises(ValueError, match="forward must be positive"):
        core.black_scholes_price(
            pricing_inputs(100.0, 1.0, 0.2, "call").__class__(
                forward=-1.0,
                strike=100.0,
                years_to_expiry=1.0,
                volatility=0.2,
                discount_factor=1.0,
                option_type="call",
            )
        )


def test_an_unknown_option_type_raises_a_value_error() -> None:
    with pytest.raises(ValueError, match="option_type"):
        core.BlackScholesInputs(
            forward=100.0,
            strike=100.0,
            years_to_expiry=1.0,
            volatility=0.2,
            discount_factor=1.0,
            option_type="straddle",
        )


def test_failed_inversions_report_infinite_uncertainty() -> None:
    result = core.invert_black_implied_volatility(
        core.ImpliedVolatilityInputs(
            forward=100.0,
            strike=90.0,
            years_to_expiry=1.0,
            discount_factor=1.0,
            option_price=5.0,
            option_type="call",
        )
    )
    assert result.status == "below_intrinsic"
    assert result.volatility == 0.0
    assert math.isinf(result.volatility_uncertainty)


def test_the_forward_curve_is_reachable_through_the_bindings() -> None:
    reader = core.open_chain_dataset("spec/fixtures/datasets/synthetic_chain", "2026-08-21T17:00:00.000000Z")
    quotes = reader.chain_as_of(
        underlying_symbol="SPX",
        observation_time="2026-08-21T17:00:00.000000Z",
        include_adjusted_contracts=False,
    )
    points = core.imply_forward_curve(quotes, "2026-08-21T17:00:00.000000Z")
    assert len(points) == SPX_EXPIRY_COUNT
    for point in points:
        assert point.status == "converged"
        assert point.forward > 0.0
        assert 0.0 < point.discount_factor <= 1.0
        assert point.forward_standard_error is not None
        assert point.active_pair_count < point.parity_pair_count


def test_a_failed_curve_point_reports_none_rather_than_a_number() -> None:
    reader = core.open_chain_dataset("spec/fixtures/datasets/synthetic_chain", "2026-08-21T17:00:00.000000Z")
    quotes = reader.chain_as_of(
        underlying_symbol="THIN",
        observation_time="2026-08-21T17:00:00.000000Z",
        include_adjusted_contracts=False,
    )
    points = core.imply_forward_curve(quotes, "2026-08-21T17:00:00.000000Z")
    assert len(points) == 1
    assert points[0].status == "too_few_pairs"
    assert points[0].forward_standard_error is None
    assert points[0].implied_zero_rate is None


AMERICAN_BASE_ARGUMENTS = {
    "spot_price": 100.0,
    "strike": 100.0,
    "years_to_expiry": 1.0,
    "volatility": 0.25,
    "zero_rate": 0.0425,
    "carry_rate": 0.02,
    "option_type": "call",
    "exercise_style": "american",
}


def lattice_inputs(**overrides: object) -> object:
    return core.LatticeInputs(**{**AMERICAN_BASE_ARGUMENTS, **overrides})


def test_the_american_lattice_is_reachable_through_the_bindings() -> None:
    inputs = lattice_inputs(carry_rate=0.06)
    american = core.richardson_extrapolated_price(inputs)
    european = core.european_price(inputs)
    assert american > european
    assert core.early_exercise_premium(inputs) == pytest.approx(american - european, rel=1e-14)


def test_an_american_call_on_a_zero_carry_underlying_has_exactly_no_premium() -> None:
    assert core.early_exercise_premium(lattice_inputs(carry_rate=0.0)) == 0.0


def test_a_european_contract_reports_no_premium() -> None:
    assert core.early_exercise_premium(lattice_inputs(exercise_style="european")) == 0.0


def test_an_unknown_exercise_style_raises_a_value_error() -> None:
    with pytest.raises(ValueError, match="exercise_style"):
        lattice_inputs(exercise_style="bermudan")


def test_the_lattice_step_count_is_exposed_as_a_contract_constant() -> None:
    assert core.RICHARDSON_BASE_STEPS == RICHARDSON_BASE_STEPS
