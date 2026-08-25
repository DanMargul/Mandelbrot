from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from volarb_py.american import (
    RICHARDSON_BASE_STEPS,
    AmericanInversionInputs,
    ExerciseStyle,
    LatticeInputs,
    early_exercise_premium,
    european_counterpart,
    invert_american_implied_volatility,
    richardson_extrapolated_price,
)
from volarb_py.documents import (
    Document,
    DocumentError,
    JsonRecord,
    json_safe_float,
    optional_boolean,
    optional_float,
    read_document,
    required_float,
    required_integer,
    required_option_type,
    required_string,
    write_document,
)
from volarb_py.essvi import EssviSliceQuotes, calibrate_essvi_surface
from volarb_py.execution import OrderSide, PackageLeg, Quote, fill_package
from volarb_py.factors import (
    SurfacePoint,
    decompose_surface_factors,
    neutralise_against_loadings,
    score_residual,
)
from volarb_py.forward_curve import ForwardCurvePoint, imply_forward_curve
from volarb_py.implied_vol import ImpliedVolatilityInputs, invert_black_implied_volatility
from volarb_py.market_data import (
    AsOfChainReader,
    ChainDatasetError,
    ChainQuery,
    ContractQuote,
    KnowledgeHorizon,
    format_canonical_date,
    format_canonical_timestamp,
    open_chain_dataset,
    parse_canonical_timestamp,
)
from volarb_py.pricing import BlackScholesInputs, InvalidOptionInputsError, black_scholes_price_and_greeks
from volarb_py.rate_curve import (
    CurveNode,
    RateCurve,
    discount_factor,
    forward_discount_factor,
    forward_rate,
    integrated_rate,
    zero_rate,
)
from volarb_py.svi import (
    DEFAULT_SCAN_STEPS,
    SviParameters,
    scan_svi_slice,
)
from volarb_py.svi_calibration import (
    SliceObservation,
    calibrate_svi_slice,
)
from volarb_py.svi_surface import (
    DEFAULT_SURFACE_SCAN_STEPS,
    DEFAULT_TIME_STEPS_PER_INTERVAL,
    SviSurfaceSlice,
    scan_svi_surface,
)


@dataclass(frozen=True)
class Verb:
    name: str
    input_schema: str
    output_schema: str
    transform_records: Callable[[list[JsonRecord]], list[JsonRecord]]


def mapped_over_records(
    transform: Callable[[JsonRecord], JsonRecord],
) -> Callable[[list[JsonRecord]], list[JsonRecord]]:
    def apply_to_each(records: list[JsonRecord]) -> list[JsonRecord]:
        return [transform(record) for record in records]

    return apply_to_each


def price_option_record(record: JsonRecord) -> JsonRecord:
    greeks = black_scholes_price_and_greeks(
        BlackScholesInputs(
            forward=required_float(record, "forward"),
            strike=required_float(record, "strike"),
            years_to_expiry=required_float(record, "years_to_expiry"),
            volatility=required_float(record, "volatility"),
            discount_factor=required_float(record, "discount_factor"),
            option_type=required_option_type(record, "option_type"),
        )
    )
    return {
        "id": required_string(record, "id"),
        "price": greeks.price,
        "delta_with_respect_to_forward": greeks.delta_with_respect_to_forward,
        "gamma_with_respect_to_forward": greeks.gamma_with_respect_to_forward,
        "vega_with_respect_to_volatility": greeks.vega_with_respect_to_volatility,
        "theta_with_respect_to_time": greeks.theta_with_respect_to_time,
    }


def invert_implied_volatility_record(record: JsonRecord) -> JsonRecord:
    result = invert_black_implied_volatility(
        ImpliedVolatilityInputs(
            forward=required_float(record, "forward"),
            strike=required_float(record, "strike"),
            years_to_expiry=required_float(record, "years_to_expiry"),
            discount_factor=required_float(record, "discount_factor"),
            option_price=required_float(record, "option_price"),
            option_type=required_option_type(record, "option_type"),
        )
    )
    return {
        "id": required_string(record, "id"),
        "volatility": result.volatility,
        "status": result.status,
        "iterations": result.iterations,
        "absolute_price_error": result.absolute_price_error,
        "volatility_uncertainty": json_safe_float(result.volatility_uncertainty),
    }


def required_exercise_style(record: JsonRecord, field: str) -> ExerciseStyle:
    value = required_string(record, field)
    if value == "european":
        return "european"
    if value == "american":
        return "american"
    raise DocumentError(f"field {field!r} must be 'european' or 'american', found {value!r}")


def price_american_option_record(record: JsonRecord) -> JsonRecord:
    inputs = LatticeInputs(
        spot_price=required_float(record, "spot_price"),
        strike=required_float(record, "strike"),
        years_to_expiry=required_float(record, "years_to_expiry"),
        volatility=required_float(record, "volatility"),
        zero_rate=required_float(record, "zero_rate"),
        carry_rate=required_float(record, "carry_rate"),
        option_type=required_option_type(record, "option_type"),
        exercise_style=required_exercise_style(record, "exercise_style"),
    )
    return {
        "id": required_string(record, "id"),
        "price": richardson_extrapolated_price(inputs, RICHARDSON_BASE_STEPS),
        "european_price": richardson_extrapolated_price(european_counterpart(inputs), RICHARDSON_BASE_STEPS),
        "early_exercise_premium": early_exercise_premium(inputs, RICHARDSON_BASE_STEPS),
        "lattice_steps": RICHARDSON_BASE_STEPS,
    }


def invert_american_implied_volatility_record(record: JsonRecord) -> JsonRecord:
    result = invert_american_implied_volatility(
        AmericanInversionInputs(
            spot_price=required_float(record, "spot_price"),
            strike=required_float(record, "strike"),
            years_to_expiry=required_float(record, "years_to_expiry"),
            zero_rate=required_float(record, "zero_rate"),
            carry_rate=required_float(record, "carry_rate"),
            option_price=required_float(record, "option_price"),
            option_type=required_option_type(record, "option_type"),
            exercise_style=required_exercise_style(record, "exercise_style"),
        )
    )
    return {
        "id": required_string(record, "id"),
        "volatility": result.volatility,
        "status": result.status,
        "iterations": result.iterations,
        "absolute_price_error": result.absolute_price_error,
    }


def scan_svi_slice_record(record: JsonRecord) -> JsonRecord:
    parameters = SviParameters(
        a=required_float(record, "a"),
        b=required_float(record, "b"),
        rho=required_float(record, "rho"),
        m=required_float(record, "m"),
        sigma=required_float(record, "sigma"),
    )
    steps = record.get("scan_steps", DEFAULT_SCAN_STEPS)
    scan = scan_svi_slice(
        parameters,
        required_float(record, "lowest_log_moneyness"),
        required_float(record, "highest_log_moneyness"),
        int(steps) if isinstance(steps, int) else DEFAULT_SCAN_STEPS,
    )
    return {
        "id": required_string(record, "id"),
        "minimum_durrleman_value": scan.minimum_durrleman_value,
        "log_moneyness_at_minimum": scan.log_moneyness_at_minimum,
        "minimum_total_variance": scan.minimum_total_variance,
        "minimum_risk_neutral_density": scan.minimum_risk_neutral_density,
        "scan_steps": scan.scan_steps,
        "status": scan.status,
    }


def surface_grid_from(record: JsonRecord) -> list[SurfacePoint]:
    raw = record.get("grid")
    if not isinstance(raw, list):
        raise DocumentError("field 'grid' must be an array")
    grid: list[SurfacePoint] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'grid' must be an object")
        grid.append(
            SurfacePoint(
                log_moneyness=required_float(entry, "log_moneyness"),
                years_to_expiry=required_float(entry, "years_to_expiry"),
            )
        )
    return grid


def surface_observations_from(record: JsonRecord) -> list[list[float]]:
    raw = record.get("observations")
    if not isinstance(raw, list):
        raise DocumentError("field 'observations' must be an array")
    observations: list[list[float]] = []
    for entry in raw:
        if not isinstance(entry, list):
            raise DocumentError("every entry of 'observations' must be an array")
        observations.append([float(value) for value in entry])
    return observations


def decompose_surface_factors_record(record: JsonRecord) -> JsonRecord:
    decomposition = decompose_surface_factors(surface_grid_from(record), surface_observations_from(record))
    index = record.get("scored_grid_index", 0)
    scored = index if isinstance(index, int) else 0
    series = [residual[scored] for residual in decomposition.residuals]
    neutralised = neutralise_against_loadings(
        series, decomposition.loadings, decomposition.identified_factor_count
    )
    score = score_residual(neutralised.values)
    return {
        "id": required_string(record, "id"),
        "observation_count": decomposition.observation_count,
        "grid_point_count": decomposition.grid_point_count,
        "identified_factor_count": decomposition.identified_factor_count,
        "variance_explained": decomposition.variance_explained,
        "residual_share": decomposition.residual_share,
        "worst_residual_factor_correlation": decomposition.worst_residual_factor_correlation,
        "level_loading": [entry.level for entry in decomposition.loadings],
        "term_slope_loading": [entry.term_slope for entry in decomposition.loadings],
        "skew_loading": [entry.skew for entry in decomposition.loadings],
        "curvature_loading": [entry.curvature for entry in decomposition.loadings],
        "scored_grid_index": scored,
        "scored_worst_factor_correlation_before": neutralised.worst_factor_correlation_before,
        "scored_worst_factor_correlation_after": neutralised.worst_factor_correlation,
        "scored_lag_one_autocorrelation": score.lag_one_autocorrelation,
        "scored_effective_sample_size": score.effective_sample_size,
        "scored_naive_z_score": score.naive_z_score,
        "scored_adjusted_z_score": score.adjusted_z_score,
        "scored_naive_overstatement": score.naive_overstatement,
        "scored_residual_is_degenerate": score.residual_is_degenerate,
    }


def rate_curve_from(record: JsonRecord) -> RateCurve:
    raw = record.get("nodes")
    if not isinstance(raw, list):
        raise DocumentError("field 'nodes' must be an array")
    nodes: list[CurveNode] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'nodes' must be an object")
        nodes.append(
            CurveNode(
                years_to_maturity=required_float(entry, "years_to_maturity"),
                continuously_compounded_zero_rate=required_float(entry, "continuously_compounded_zero_rate"),
            )
        )
    return RateCurve(nodes)


def evaluate_rate_curve_record(record: JsonRecord) -> JsonRecord:
    curve = rate_curve_from(record)
    years = required_float(record, "years_to_maturity")
    start = optional_float(record, "forward_start_years")
    end = optional_float(record, "forward_end_years")
    if start is None or end is None:
        start, end = years, years + 1.0
    return {
        "id": required_string(record, "id"),
        "years_to_maturity": years,
        "discount_factor": discount_factor(curve, years),
        "zero_rate": zero_rate(curve, years),
        "integrated_rate": integrated_rate(curve, years),
        "forward_rate": forward_rate(curve, start, end),
        "forward_discount_factor": forward_discount_factor(curve, start, end),
    }


def required_order_side(record: JsonRecord, field: str) -> OrderSide:
    value = record.get(field)
    if value == "buy":
        return "buy"
    if value == "sell":
        return "sell"
    raise DocumentError(f"field {field!r} must be 'buy' or 'sell', found {value!r}")


def package_legs_from(record: JsonRecord) -> list[PackageLeg]:
    raw = record.get("legs")
    if not isinstance(raw, list):
        raise DocumentError("field 'legs' must be an array")
    legs: list[PackageLeg] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'legs' must be an object")
        legs.append(
            PackageLeg(
                quote=Quote(
                    bid_price=required_float(entry, "bid_price"),
                    ask_price=required_float(entry, "ask_price"),
                    bid_size=required_integer(entry, "bid_size"),
                    ask_size=required_integer(entry, "ask_size"),
                ),
                side=required_order_side(entry, "side"),
                quantity=required_integer(entry, "quantity"),
                contract_multiplier=required_integer(entry, "contract_multiplier"),
                vega_with_respect_to_volatility=required_float(entry, "vega_with_respect_to_volatility"),
            )
        )
    return legs


def simulate_fills_record(record: JsonRecord) -> JsonRecord:
    fill = fill_package(package_legs_from(record))
    return {
        "id": required_string(record, "id"),
        "status": fill.status,
        "requested_quantity": fill.requested_quantity,
        "filled_quantity": fill.filled_quantity,
        "total_cost_against_mid": fill.total_cost_against_mid,
        "net_vega": fill.net_vega,
        "net_vega_is_negligible": fill.net_vega_is_negligible,
        "round_trip_cost_in_volatility_points": fill.round_trip_cost_in_volatility_points,
        "leg_filled_quantity": [leg.filled_quantity for leg in fill.leg_fills],
        "leg_touch_price": [leg.touch_price for leg in fill.leg_fills],
        "leg_mid_price": [leg.mid_price for leg in fill.leg_fills],
        "leg_half_spread": [leg.half_spread for leg in fill.leg_fills],
        "leg_cost_against_mid": [leg.cost_against_mid for leg in fill.leg_fills],
        "leg_status": [leg.status for leg in fill.leg_fills],
    }


def essvi_slice_quotes_from(record: JsonRecord) -> list[EssviSliceQuotes]:
    raw = record.get("slices")
    if not isinstance(raw, list):
        raise DocumentError("field 'slices' must be an array")
    quotes: list[EssviSliceQuotes] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'slices' must be an object")
        quotes.append(
            EssviSliceQuotes(
                years_to_expiry=required_float(entry, "years_to_expiry"),
                observations=slice_observations_from(entry),
            )
        )
    return quotes


def calibrate_essvi_surface_record(record: JsonRecord) -> JsonRecord:
    calibration = calibrate_essvi_surface(
        essvi_slice_quotes_from(record),
        required_float(record, "lowest_log_moneyness"),
        required_float(record, "highest_log_moneyness"),
    )
    return {
        "id": required_string(record, "id"),
        "status": calibration.status,
        "slice_count": calibration.slice_count,
        "observation_count": calibration.observation_count,
        "simplex_iterations": calibration.simplex_iterations,
        "objective": calibration.objective,
        "weighted_root_mean_square_residual": calibration.weighted_root_mean_square_residual,
        "atm_total_variance": calibration.parameters.atm_total_variance,
        "curvature_scale": calibration.parameters.curvature_scale,
        "power_law_exponent": calibration.parameters.power_law_exponent,
        "correlation_intercept": calibration.parameters.correlation_intercept,
        "correlation_slope": calibration.parameters.correlation_slope,
        "slice_a": [entry.a for entry in calibration.slices],
        "slice_b": [entry.b for entry in calibration.slices],
        "slice_rho": [entry.rho for entry in calibration.slices],
        "slice_m": [entry.m for entry in calibration.slices],
        "slice_sigma": [entry.sigma for entry in calibration.slices],
        "fitted_surface": calibration.fitted_surface,
        "surface_minimum_durrleman_value": calibration.surface_minimum_durrleman_value,
        "surface_minimum_total_variance_time_slope": (calibration.surface_minimum_total_variance_time_slope),
    }


def surface_slices_from(record: JsonRecord) -> list[SviSurfaceSlice]:
    raw = record.get("slices")
    if not isinstance(raw, list):
        raise DocumentError("field 'slices' must be an array")
    slices: list[SviSurfaceSlice] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'slices' must be an object")
        slices.append(
            SviSurfaceSlice(
                years_to_expiry=required_float(entry, "years_to_expiry"),
                parameters=SviParameters(
                    a=required_float(entry, "a"),
                    b=required_float(entry, "b"),
                    rho=required_float(entry, "rho"),
                    m=required_float(entry, "m"),
                    sigma=required_float(entry, "sigma"),
                ),
            )
        )
    return slices


def optional_step_count(record: JsonRecord, field: str, fallback: int) -> int:
    value = record.get(field, fallback)
    return value if isinstance(value, int) else fallback


def scan_svi_surface_record(record: JsonRecord) -> JsonRecord:
    scan = scan_svi_surface(
        surface_slices_from(record),
        required_float(record, "lowest_log_moneyness"),
        required_float(record, "highest_log_moneyness"),
        optional_step_count(record, "scan_steps", DEFAULT_SURFACE_SCAN_STEPS),
        optional_step_count(record, "time_steps_per_interval", DEFAULT_TIME_STEPS_PER_INTERVAL),
    )
    return {
        "id": required_string(record, "id"),
        "slice_count": scan.slice_count,
        "scan_steps": scan.scan_steps,
        "time_steps_per_interval": scan.time_steps_per_interval,
        "minimum_durrleman_value": scan.minimum_durrleman_value,
        "log_moneyness_at_minimum_durrleman_value": scan.log_moneyness_at_minimum_durrleman_value,
        "years_to_expiry_at_minimum_durrleman_value": scan.years_to_expiry_at_minimum_durrleman_value,
        "minimum_risk_neutral_density": scan.minimum_risk_neutral_density,
        "minimum_total_variance_time_slope": scan.minimum_total_variance_time_slope,
        "log_moneyness_at_minimum_time_slope": scan.log_moneyness_at_minimum_time_slope,
        "years_to_expiry_at_minimum_time_slope": scan.years_to_expiry_at_minimum_time_slope,
        "minimum_local_variance": scan.minimum_local_variance,
        "log_moneyness_at_minimum_local_variance": scan.log_moneyness_at_minimum_local_variance,
        "years_to_expiry_at_minimum_local_variance": scan.years_to_expiry_at_minimum_local_variance,
        "worst_local_variance_round_trip_error": scan.worst_local_variance_round_trip_error,
        "log_moneyness_at_worst_round_trip_error": scan.log_moneyness_at_worst_round_trip_error,
        "round_trip_point_count": scan.round_trip_point_count,
        "status": scan.status,
    }


def slice_observations_from(record: JsonRecord) -> list[SliceObservation]:
    raw = record.get("observations")
    if not isinstance(raw, list):
        raise DocumentError("field 'observations' must be an array")
    observations: list[SliceObservation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every observation must be an object")
        observations.append(
            SliceObservation(
                log_moneyness=required_float(entry, "log_moneyness"),
                total_variance=required_float(entry, "total_variance"),
                weight=required_float(entry, "weight"),
            )
        )
    return observations


def calibrate_svi_slice_record(record: JsonRecord) -> JsonRecord:
    calibration = calibrate_svi_slice(
        slice_observations_from(record),
        required_float(record, "lowest_log_moneyness"),
        required_float(record, "highest_log_moneyness"),
    )
    return {
        "id": required_string(record, "id"),
        "a": calibration.parameters.a,
        "b": calibration.parameters.b,
        "rho": calibration.parameters.rho,
        "m": calibration.parameters.m,
        "sigma": calibration.parameters.sigma,
        "objective": calibration.objective,
        "weighted_root_mean_square_residual": calibration.weighted_root_mean_square_residual,
        "simplex_iterations": calibration.simplex_iterations,
        "observation_count": calibration.observation_count,
        "fitted_curve": calibration.fitted_curve,
        "status": calibration.status,
    }


def chain_snapshot_record(query_id: str, quote: ContractQuote) -> JsonRecord:
    return {
        "id": f"{query_id}|{quote.contract_symbol}",
        "query_id": query_id,
        "contract_symbol": quote.contract_symbol,
        "expiry_date": format_canonical_date(quote.expiry_date),
        "strike": quote.strike,
        "option_type": quote.option_type,
        "contract_multiplier": quote.contract_multiplier,
        "is_standard_deliverable": quote.is_standard_deliverable,
        "exercise_style": quote.exercise_style,
        "event_time": format_canonical_timestamp(quote.event_time),
        "knowledge_time": format_canonical_timestamp(quote.knowledge_time),
        "ingest_sequence": quote.ingest_sequence,
        "underlying_price": quote.underlying_price,
        "bid_price": quote.bid_price,
        "ask_price": quote.ask_price,
        "bid_size": quote.bid_size,
        "ask_size": quote.ask_size,
    }


def read_chain_as_of_records(records: list[JsonRecord]) -> list[JsonRecord]:
    readers: dict[tuple[str, str], AsOfChainReader] = {}
    snapshots: list[JsonRecord] = []
    for record in records:
        dataset_root = required_string(record, "dataset_root")
        horizon_text = required_string(record, "knowledge_horizon")
        cache_key = (dataset_root, horizon_text)
        if cache_key not in readers:
            readers[cache_key] = open_chain_dataset(
                Path(dataset_root), KnowledgeHorizon(parse_canonical_timestamp(horizon_text))
            )
        query = ChainQuery(
            underlying_symbol=required_string(record, "underlying_symbol"),
            observation_time=parse_canonical_timestamp(required_string(record, "observation_time")),
            include_adjusted_contracts=optional_boolean(record, "include_adjusted_contracts", False),
        )
        query_id = required_string(record, "id")
        snapshots.extend(
            chain_snapshot_record(query_id, quote) for quote in readers[cache_key].chain_as_of(query)
        )
    return snapshots


def forward_curve_record(query_id: str, underlying_symbol: str, point: ForwardCurvePoint) -> JsonRecord:
    return {
        "id": f"{query_id}|{format_canonical_date(point.expiry_date)}",
        "query_id": query_id,
        "underlying_symbol": underlying_symbol,
        "expiry_date": format_canonical_date(point.expiry_date),
        "years_to_expiry": point.years_to_expiry,
        "spot_price": point.spot_price,
        "forward": point.forward,
        "forward_standard_error": point.forward_standard_error,
        "discount_factor": point.discount_factor,
        "discount_factor_standard_error": point.discount_factor_standard_error,
        "implied_zero_rate": point.implied_zero_rate,
        "implied_carry_rate": point.implied_carry_rate,
        "parity_pair_count": point.parity_pair_count,
        "active_pair_count": point.active_pair_count,
        "chi_square_per_degree_of_freedom": point.chi_square_per_degree_of_freedom,
        "early_exercise_premium_stripped": point.early_exercise_premium_stripped,
        "discount_factor_is_monotone_in_expiry": point.discount_factor_is_monotone_in_expiry,
        "status": point.status,
    }


def imply_forward_curve_records(records: list[JsonRecord]) -> list[JsonRecord]:
    readers: dict[tuple[str, str], AsOfChainReader] = {}
    curve: list[JsonRecord] = []
    for record in records:
        dataset_root = required_string(record, "dataset_root")
        horizon_text = required_string(record, "knowledge_horizon")
        cache_key = (dataset_root, horizon_text)
        if cache_key not in readers:
            readers[cache_key] = open_chain_dataset(
                Path(dataset_root), KnowledgeHorizon(parse_canonical_timestamp(horizon_text))
            )
        observation_time = parse_canonical_timestamp(required_string(record, "observation_time"))
        underlying_symbol = required_string(record, "underlying_symbol")
        quotes = readers[cache_key].chain_as_of(
            ChainQuery(
                underlying_symbol=underlying_symbol,
                observation_time=observation_time,
                include_adjusted_contracts=optional_boolean(record, "include_adjusted_contracts", False),
            )
        )
        query_id = required_string(record, "id")
        curve.extend(
            forward_curve_record(query_id, underlying_symbol, point)
            for point in imply_forward_curve(quotes, observation_time, optional_float(record, "zero_rate"))
        )
    return curve


VERBS: Final[dict[str, Verb]] = {
    "price-options": Verb(
        name="price-options",
        input_schema="pricing_request/v1",
        output_schema="pricing_result/v1",
        transform_records=mapped_over_records(price_option_record),
    ),
    "invert-implied-volatility": Verb(
        name="invert-implied-volatility",
        input_schema="implied_volatility_request/v1",
        output_schema="implied_volatility_result/v1",
        transform_records=mapped_over_records(invert_implied_volatility_record),
    ),
    "read-chain-as-of": Verb(
        name="read-chain-as-of",
        input_schema="chain_query/v1",
        output_schema="chain_snapshot/v2",
        transform_records=read_chain_as_of_records,
    ),
    "price-american-options": Verb(
        name="price-american-options",
        input_schema="american_pricing_request/v1",
        output_schema="american_pricing_result/v1",
        transform_records=mapped_over_records(price_american_option_record),
    ),
    "invert-american-implied-volatility": Verb(
        name="invert-american-implied-volatility",
        input_schema="american_inversion_request/v1",
        output_schema="american_inversion_result/v1",
        transform_records=mapped_over_records(invert_american_implied_volatility_record),
    ),
    "calibrate-svi-slice": Verb(
        name="calibrate-svi-slice",
        input_schema="svi_calibration_request/v1",
        output_schema="svi_calibration_result/v1",
        transform_records=mapped_over_records(calibrate_svi_slice_record),
    ),
    "decompose-surface-factors": Verb(
        name="decompose-surface-factors",
        input_schema="factor_request/v1",
        output_schema="factor_decomposition/v1",
        transform_records=mapped_over_records(decompose_surface_factors_record),
    ),
    "evaluate-rate-curve": Verb(
        name="evaluate-rate-curve",
        input_schema="rate_curve_query/v1",
        output_schema="rate_curve_point/v1",
        transform_records=mapped_over_records(evaluate_rate_curve_record),
    ),
    "simulate-fills": Verb(
        name="simulate-fills",
        input_schema="fill_request/v1",
        output_schema="fill_result/v1",
        transform_records=mapped_over_records(simulate_fills_record),
    ),
    "calibrate-essvi-surface": Verb(
        name="calibrate-essvi-surface",
        input_schema="essvi_calibration_request/v1",
        output_schema="essvi_calibration_result/v1",
        transform_records=mapped_over_records(calibrate_essvi_surface_record),
    ),
    "scan-svi-surface": Verb(
        name="scan-svi-surface",
        input_schema="svi_surface_scan_request/v1",
        output_schema="svi_surface_scan_result/v1",
        transform_records=mapped_over_records(scan_svi_surface_record),
    ),
    "scan-svi-slice": Verb(
        name="scan-svi-slice",
        input_schema="svi_scan_request/v1",
        output_schema="svi_scan_result/v1",
        transform_records=mapped_over_records(scan_svi_slice_record),
    ),
    "imply-forward-curve": Verb(
        name="imply-forward-curve",
        input_schema="forward_curve_query/v1",
        output_schema="forward_curve/v1",
        transform_records=imply_forward_curve_records,
    ),
}


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="volarb-py")
    parser.add_argument("verb", choices=sorted(VERBS))
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    return parser.parse_args(list(argv))


def run_verb(verb: Verb, input_path: Path, output_path: Path) -> None:
    document = read_document(input_path, verb.input_schema)
    records = verb.transform_records(document.records)
    write_document(output_path, Document(schema=verb.output_schema, records=records))


def main(argv: Sequence[str]) -> int:
    arguments = parse_arguments(argv)
    try:
        run_verb(VERBS[arguments.verb], arguments.input, arguments.output)
    except (
        DocumentError,
        InvalidOptionInputsError,
        ChainDatasetError,
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def entry_point() -> None:
    raise SystemExit(main(sys.argv[1:]))
