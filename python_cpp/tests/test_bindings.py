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
    points = core.imply_forward_curve(quotes, "2026-08-21T17:00:00.000000Z", None)
    assert len(points) == SPX_EXPIRY_COUNT
    for point in points:
        assert point.status == "converged"
        assert point.forward > 0.0
        assert 0.0 < point.discount_factor <= 1.0
        assert point.forward_standard_error is not None
        assert point.active_pair_count < point.parity_pair_count


def test_american_quotes_are_refused_without_a_rate() -> None:
    reader = core.open_chain_dataset("spec/fixtures/datasets/synthetic_chain", "2026-08-21T17:00:00.000000Z")
    quotes = reader.chain_as_of(
        underlying_symbol="AAPL",
        observation_time="2026-08-21T17:00:00.000000Z",
        include_adjusted_contracts=False,
    )
    refused = core.imply_forward_curve(quotes, "2026-08-21T17:00:00.000000Z", None)
    assert len(refused) == 1
    assert refused[0].status == "american_quotes_not_stripped"
    assert refused[0].forward_standard_error is None

    stripped = core.imply_forward_curve(quotes, "2026-08-21T17:00:00.000000Z", 0.0425)
    assert stripped[0].status == "converged"
    assert stripped[0].early_exercise_premium_stripped
    assert 0.0 < stripped[0].discount_factor < 1.0


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


BENIGN_SVI = {"a": 0.0002, "b": 0.018, "rho": -0.65, "m": 0.01, "sigma": 0.10}
VIOLATING_SVI = {"a": 0.0002, "b": 0.350, "rho": -0.85, "m": 0.00, "sigma": 0.02}


def svi_scan(**overrides: object) -> object:
    arguments = {
        **BENIGN_SVI,
        "lowest_log_moneyness": -0.6,
        "highest_log_moneyness": 0.6,
        "scan_steps": core.DEFAULT_SCAN_STEPS,
    }
    arguments.update(overrides)
    return core.scan_svi_slice(**arguments)


def test_a_well_shaped_slice_scans_clean_through_the_bindings() -> None:
    scan = svi_scan()
    assert scan.status == "arbitrage_free_on_grid"
    assert scan.minimum_durrleman_value > 0.0
    assert scan.minimum_risk_neutral_density > 0.0


def test_a_violating_slice_is_caught_through_the_bindings() -> None:
    scan = svi_scan(**VIOLATING_SVI)
    assert scan.status == "butterfly_arbitrage_found"
    assert scan.minimum_durrleman_value < 0.0
    assert scan.minimum_risk_neutral_density < 0.0


def test_invalid_svi_parameters_raise_a_value_error() -> None:
    with pytest.raises(ValueError, match="rho"):
        svi_scan(rho=1.0)


HEALTHY_SURFACE = {
    "years_to_expiry": [0.0833, 0.2500, 0.5000, 1.0000],
    "a": [0.0015, 0.0060, 0.0140, 0.0300],
    "b": [0.030, 0.055, 0.075, 0.100],
    "rho": [-0.70, -0.65, -0.60, -0.55],
    "m": [0.010, 0.015, 0.020, 0.030],
    "sigma": [0.10, 0.15, 0.22, 0.32],
}
SURFACE_ROUND_TRIP_BUDGET = 1e-5


def svi_surface_scan(**overrides: object) -> object:
    arguments: dict[str, object] = {
        **HEALTHY_SURFACE,
        "lowest_log_moneyness": -1.5,
        "highest_log_moneyness": 1.5,
        "scan_steps": core.DEFAULT_SURFACE_SCAN_STEPS,
        "time_steps_per_interval": core.DEFAULT_TIME_STEPS_PER_INTERVAL,
    }
    arguments.update(overrides)
    return core.scan_svi_surface(**arguments)


def test_a_monotone_surface_scans_clean_through_the_bindings() -> None:
    scan = svi_surface_scan()
    assert scan.status == "arbitrage_free_on_grid"
    assert scan.slice_count == len(HEALTHY_SURFACE["years_to_expiry"])
    assert scan.minimum_durrleman_value > 0.0
    assert scan.minimum_risk_neutral_density > 0.0
    assert scan.minimum_total_variance_time_slope > 0.0
    assert scan.minimum_local_variance > 0.0


def test_the_dupire_round_trip_holds_through_the_bindings() -> None:
    scan = svi_surface_scan()
    assert scan.round_trip_point_count > 0
    assert scan.worst_local_variance_round_trip_error < SURFACE_ROUND_TRIP_BUDGET


def test_a_falling_term_structure_is_caught_through_the_bindings() -> None:
    scan = svi_surface_scan(a=[0.0015, 0.0060, 0.0040, 0.0300], b=[0.030, 0.055, 0.055, 0.100])
    assert scan.status == "calendar_arbitrage_found"
    assert scan.minimum_total_variance_time_slope < 0.0


def test_ragged_surface_columns_raise_a_value_error() -> None:
    with pytest.raises(ValueError, match="length"):
        svi_surface_scan(sigma=[0.10, 0.15])


def test_a_surface_with_one_slice_raises_a_value_error() -> None:
    single = {name: [value[0]] for name, value in HEALTHY_SURFACE.items()}
    with pytest.raises(ValueError, match="at least"):
        svi_surface_scan(**single)


ESSVI_EXPIRIES = [0.0833, 0.25, 0.5, 1.0]
ESSVI_SLICES = [
    (0.0015, 0.030, -0.70, 0.010, 0.10),
    (0.0060, 0.055, -0.65, 0.015, 0.15),
    (0.0140, 0.075, -0.60, 0.020, 0.22),
    (0.0300, 0.100, -0.55, 0.030, 0.32),
]


def total_variance_of(slice_parameters: tuple[float, ...], point: float) -> float:
    a, b, rho, m, sigma = slice_parameters
    centred = point - m
    return a + b * (rho * centred + math.sqrt(centred * centred + sigma * sigma))


def essvi_columns(slices: list[tuple[float, ...]]) -> dict[str, object]:
    points = [-0.4 + 0.8 * index / 20 for index in range(21)]
    return {
        "years_to_expiry": ESSVI_EXPIRIES,
        "log_moneyness": [list(points) for _ in slices],
        "total_variances": [[total_variance_of(entry, point) for point in points] for entry in slices],
        "weights": [[1.0] * len(points) for _ in slices],
    }


def essvi_fit(slices: list[tuple[float, ...]]) -> object:
    return core.calibrate_essvi_surface(
        **essvi_columns(slices), lowest_log_moneyness=-0.6, highest_log_moneyness=0.6
    )


def test_an_essvi_surface_fits_clean_through_the_bindings() -> None:
    fit = essvi_fit(ESSVI_SLICES)
    assert fit.status == "converged"
    assert fit.slice_count == len(ESSVI_EXPIRIES)
    assert fit.surface_minimum_durrleman_value > 0.0
    assert fit.surface_minimum_total_variance_time_slope > 0.0
    assert len(fit.slice_a) == len(ESSVI_EXPIRIES)
    assert len(fit.atm_total_variance) == len(ESSVI_EXPIRIES)


def test_a_fit_that_cannot_eliminate_arbitrage_says_so_through_the_bindings() -> None:
    slices = list(ESSVI_SLICES)
    slices[2] = (0.0002, 0.350, -0.85, 0.000, 0.02)
    fit = essvi_fit(slices)
    assert fit.status == "arbitrage_not_eliminated"


def test_ragged_essvi_columns_raise_a_value_error() -> None:
    columns = essvi_columns(ESSVI_SLICES)
    columns["weights"] = columns["weights"][:2]
    with pytest.raises(ValueError, match="length"):
        core.calibrate_essvi_surface(**columns, lowest_log_moneyness=-0.6, highest_log_moneyness=0.6)


LIQUID_LEG = {
    "bid_price": [10.00],
    "ask_price": [10.20],
    "bid_size": [50],
    "ask_size": [40],
    "side": ["buy"],
    "quantity": [10],
    "contract_multiplier": [100],
    "vega_with_respect_to_volatility": [0.20],
}
EXPECTED_HALF_SPREAD = 0.10
FILL_LOT = 10
FILL_MULTIPLIER = 100


def test_a_taker_pays_the_touch_through_the_bindings() -> None:
    fill = core.fill_package(**LIQUID_LEG)
    assert fill.status == "filled"
    assert fill.filled_quantity == FILL_LOT
    assert fill.total_cost_against_mid == pytest.approx(FILL_LOT * FILL_MULTIPLIER * EXPECTED_HALF_SPREAD)
    assert fill.leg_touch_price == [10.20]
    assert fill.leg_status == ["filled"]


def test_size_beyond_the_touch_is_capped_through_the_bindings() -> None:
    oversized = {**LIQUID_LEG, "quantity": [500]}
    fill = core.fill_package(**oversized)
    assert fill.status == "partially_filled"
    assert fill.filled_quantity == LIQUID_LEG["ask_size"][0]


def test_a_crossed_book_raises_through_the_bindings() -> None:
    crossed = {**LIQUID_LEG, "bid_price": [10.30], "ask_price": [10.20]}
    with pytest.raises(ValueError, match="crossed"):
        core.fill_package(**crossed)


def test_an_unknown_side_raises_through_the_bindings() -> None:
    with pytest.raises(ValueError, match="buy"):
        core.fill_package(**{**LIQUID_LEG, "side": ["hold"]})


def test_ragged_leg_columns_raise_through_the_bindings() -> None:
    with pytest.raises(ValueError, match="length"):
        core.fill_package(**{**LIQUID_LEG, "quantity": [10, 10]})


UPWARD_CURVE = {
    "years_to_maturity": [0.0833, 0.25, 1.0, 2.0],
    "continuously_compounded_zero_rate": [0.01, 0.04, 0.045, 0.043],
}
FIRST_NODE_YEARS = 0.0833
FIRST_NODE_RATE = 0.01


def test_the_curve_reproduces_a_node_through_the_bindings() -> None:
    assert core.rate_curve_zero_rate(**UPWARD_CURVE, years=FIRST_NODE_YEARS) == pytest.approx(
        FIRST_NODE_RATE, rel=1e-14
    )
    assert core.rate_curve_discount_factor(**UPWARD_CURVE, years=FIRST_NODE_YEARS) == pytest.approx(
        math.exp(-FIRST_NODE_RATE * FIRST_NODE_YEARS), rel=1e-14
    )


def test_the_forward_is_constant_inside_a_segment_through_the_bindings() -> None:
    whole = core.rate_curve_forward_rate(**UPWARD_CURVE, start_years=0.0833, end_years=0.25)
    part = core.rate_curve_forward_rate(**UPWARD_CURVE, start_years=0.12, end_years=0.20)
    assert whole == pytest.approx(part, rel=1e-12)


def test_a_malformed_curve_raises_through_the_bindings() -> None:
    with pytest.raises(ValueError, match="increasing"):
        core.rate_curve_zero_rate(
            years_to_maturity=[1.0, 0.5], continuously_compounded_zero_rate=[0.01, 0.02], years=1.0
        )
    with pytest.raises(ValueError, match="length"):
        core.rate_curve_zero_rate(
            years_to_maturity=[1.0, 2.0], continuously_compounded_zero_rate=[0.01], years=1.0
        )


FACTOR_TENORS = (0.0833, 0.25, 0.5, 1.0, 2.0)
FACTOR_STRIKES = (-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.4)
FACTOR_GRID_POINTS = len(FACTOR_TENORS) * len(FACTOR_STRIKES)
FACTOR_OBSERVATIONS = 60
EXPECTED_FACTORS = 4
NEUTRALITY_BUDGET = 1e-12
EXACT_RECONSTRUCTION = 0.999999


def factor_arguments() -> dict[str, object]:
    observations = []
    for index in range(FACTOR_OBSERVATIONS):
        level = 0.04 * math.exp(0.2 * math.sin(index * 0.31))
        slope = 1.0 + 0.1 * math.cos(index * 0.17)
        skew = -0.35 + 0.08 * math.sin(index * 0.23)
        observations.append(
            [
                level * tenor**slope * math.exp(skew * strike + 0.9 * strike * strike)
                for tenor in FACTOR_TENORS
                for strike in FACTOR_STRIKES
            ]
        )
    return {
        "log_moneyness": [strike for _ in FACTOR_TENORS for strike in FACTOR_STRIKES],
        "years_to_expiry": [tenor for tenor in FACTOR_TENORS for _ in FACTOR_STRIKES],
        "observations": observations,
        "scored_grid_index": 3,
    }


def test_the_factor_basis_explains_a_factor_driven_surface_through_the_bindings() -> None:
    report = core.decompose_surface_factors(**factor_arguments())
    assert report.identified_factor_count == EXPECTED_FACTORS
    assert report.grid_point_count == FACTOR_GRID_POINTS
    assert report.variance_explained > EXACT_RECONSTRUCTION
    assert len(report.level_loading) == FACTOR_OBSERVATIONS


def test_the_neutralised_residual_carries_no_factor_loading_through_the_bindings() -> None:
    report = core.decompose_surface_factors(**factor_arguments())
    assert report.scored_worst_factor_correlation_after < NEUTRALITY_BUDGET


def test_a_degenerate_residual_is_flagged_rather_than_scored() -> None:
    report = core.decompose_surface_factors(**factor_arguments())
    assert report.scored_residual_is_degenerate
    assert report.scored_naive_z_score == 0.0


def test_a_grid_out_of_range_index_raises_through_the_bindings() -> None:
    with pytest.raises(ValueError, match="outside the grid"):
        core.decompose_surface_factors(**{**factor_arguments(), "scored_grid_index": 999})


REFERENCE_STREAM = [
    "9705778491962043240",
    "1370407407632858425",
    "11774395822783136600",
]
SAMPLE_DRAWS = 256


def test_the_seeded_stream_matches_the_reference_through_the_bindings() -> None:
    sample = core.draw_random_sample(initial_state="42", sequence="54", count=len(REFERENCE_STREAM))
    assert sample.bits == REFERENCE_STREAM


def test_uniforms_and_normals_come_back_through_the_bindings() -> None:
    sample = core.draw_random_sample(initial_state="1", sequence="1", count=SAMPLE_DRAWS)
    assert len(sample.uniforms) == SAMPLE_DRAWS
    assert len(sample.standard_normals) == SAMPLE_DRAWS
    assert all(0.0 <= value < 1.0 for value in sample.uniforms)


def test_a_wide_seed_survives_the_string_round_trip() -> None:
    widest = str((1 << 128) - 1)
    sample = core.draw_random_sample(initial_state=widest, sequence="1", count=4)
    other = core.draw_random_sample(initial_state="0", sequence="1", count=4)
    assert sample.bits != other.bits


def test_a_malformed_seed_raises_through_the_bindings() -> None:
    with pytest.raises(ValueError, match="decimal"):
        core.draw_random_sample(initial_state="not-a-number", sequence="1", count=1)
    with pytest.raises(ValueError, match="negative"):
        core.draw_random_sample(initial_state="1", sequence="1", count=-1)


HEDGING_ARGUMENTS = {
    "spot": 100.0,
    "strike": 100.0,
    "years_to_expiry": 0.25,
    "volatility": 0.20,
    "steps": 63,
    "proportional_cost": 0.0010,
    "risk_aversion": 0.10,
    "initial_state": "1",
    "sequence": "1",
    "path_count": 200,
}
HEDGING_PATHS = 200


def test_a_wider_band_pays_less_through_the_bindings() -> None:
    narrow = core.simulate_hedging(**HEDGING_ARGUMENTS, rule="fixed", fixed_width=0.0)
    wide = core.simulate_hedging(**HEDGING_ARGUMENTS, rule="fixed", fixed_width=0.40)
    assert wide.mean_transaction_cost < narrow.mean_transaction_cost
    assert wide.profit_standard_deviation > narrow.profit_standard_deviation
    assert narrow.path_count == HEDGING_PATHS


def test_the_derived_band_runs_through_the_bindings() -> None:
    stats = core.simulate_hedging(**HEDGING_ARGUMENTS, rule="whalley_wilmott", fixed_width=0.0)
    assert stats.mean_rebalance_count > 1.0
    assert stats.certainty_equivalent < stats.mean_profit


def test_an_unknown_band_rule_raises_through_the_bindings() -> None:
    with pytest.raises(ValueError, match="whalley_wilmott"):
        core.simulate_hedging(**HEDGING_ARGUMENTS, rule="guesswork", fixed_width=0.0)
