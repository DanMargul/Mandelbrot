from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from volarb_cpp import _volarb_core
from volarb_cpp.documents import (
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
    greeks = _volarb_core.black_scholes_price_and_greeks(
        _volarb_core.BlackScholesInputs(
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
    result = _volarb_core.invert_black_implied_volatility(
        _volarb_core.ImpliedVolatilityInputs(
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


def required_exercise_style(record: JsonRecord, field: str) -> _volarb_core.ExerciseStyle:
    value = required_string(record, field)
    if value == "european":
        return "european"
    if value == "american":
        return "american"
    raise DocumentError(f"field {field!r} must be 'european' or 'american', found {value!r}")


def price_american_option_record(record: JsonRecord) -> JsonRecord:
    inputs = _volarb_core.LatticeInputs(
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
        "price": _volarb_core.richardson_extrapolated_price(inputs),
        "european_price": _volarb_core.european_price(inputs),
        "early_exercise_premium": _volarb_core.early_exercise_premium(inputs),
        "lattice_steps": _volarb_core.RICHARDSON_BASE_STEPS,
    }


def invert_american_implied_volatility_record(record: JsonRecord) -> JsonRecord:
    result = _volarb_core.invert_american_implied_volatility(
        spot_price=required_float(record, "spot_price"),
        strike=required_float(record, "strike"),
        years_to_expiry=required_float(record, "years_to_expiry"),
        zero_rate=required_float(record, "zero_rate"),
        carry_rate=required_float(record, "carry_rate"),
        option_price=required_float(record, "option_price"),
        option_type=required_option_type(record, "option_type"),
        exercise_style=required_exercise_style(record, "exercise_style"),
    )
    return {
        "id": required_string(record, "id"),
        "volatility": result.volatility,
        "status": result.status,
        "iterations": result.iterations,
        "absolute_price_error": result.absolute_price_error,
    }


def required_wide_integer(record: JsonRecord, field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.isdigit():
        raise DocumentError(f"field {field!r} must be a decimal integer string, found {value!r}")
    return value


def draw_random_sample_record(record: JsonRecord) -> JsonRecord:
    sample = _volarb_core.draw_random_sample(
        initial_state=required_wide_integer(record, "initial_state"),
        sequence=required_wide_integer(record, "sequence"),
        count=required_integer(record, "count"),
    )
    return {
        "id": required_string(record, "id"),
        "count": required_integer(record, "count"),
        "bits": sample.bits,
        "uniforms": sample.uniforms,
        "standard_normals": sample.standard_normals,
    }


def surface_grid_columns(record: JsonRecord) -> dict[str, list[float]]:
    raw = record.get("grid")
    if not isinstance(raw, list):
        raise DocumentError("field 'grid' must be an array")
    columns: dict[str, list[float]] = {"log_moneyness": [], "years_to_expiry": []}
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'grid' must be an object")
        for name, column in columns.items():
            column.append(required_float(entry, name))
    return columns


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
    index = record.get("scored_grid_index", 0)
    scored = index if isinstance(index, int) else 0
    report = _volarb_core.decompose_surface_factors(
        **surface_grid_columns(record),
        observations=surface_observations_from(record),
        scored_grid_index=scored,
    )
    return {
        "id": required_string(record, "id"),
        "observation_count": report.observation_count,
        "grid_point_count": report.grid_point_count,
        "identified_factor_count": report.identified_factor_count,
        "variance_explained": report.variance_explained,
        "residual_share": report.residual_share,
        "worst_residual_factor_correlation": report.worst_residual_factor_correlation,
        "level_loading": report.level_loading,
        "term_slope_loading": report.term_slope_loading,
        "skew_loading": report.skew_loading,
        "curvature_loading": report.curvature_loading,
        "scored_grid_index": report.scored_grid_index,
        "scored_worst_factor_correlation_before": report.scored_worst_factor_correlation_before,
        "scored_worst_factor_correlation_after": report.scored_worst_factor_correlation_after,
        "scored_lag_one_autocorrelation": report.scored_lag_one_autocorrelation,
        "scored_effective_sample_size": report.scored_effective_sample_size,
        "scored_naive_z_score": report.scored_naive_z_score,
        "scored_adjusted_z_score": report.scored_adjusted_z_score,
        "scored_naive_overstatement": report.scored_naive_overstatement,
        "scored_residual_is_degenerate": report.scored_residual_is_degenerate,
    }


def rate_curve_columns(record: JsonRecord) -> dict[str, list[float]]:
    raw = record.get("nodes")
    if not isinstance(raw, list):
        raise DocumentError("field 'nodes' must be an array")
    columns: dict[str, list[float]] = {
        "years_to_maturity": [],
        "continuously_compounded_zero_rate": [],
    }
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'nodes' must be an object")
        for name, column in columns.items():
            column.append(required_float(entry, name))
    return columns


def evaluate_rate_curve_record(record: JsonRecord) -> JsonRecord:
    columns = rate_curve_columns(record)
    years = required_float(record, "years_to_maturity")
    start = optional_float(record, "forward_start_years")
    end = optional_float(record, "forward_end_years")
    if start is None or end is None:
        start, end = years, years + 1.0
    return {
        "id": required_string(record, "id"),
        "years_to_maturity": years,
        "discount_factor": _volarb_core.rate_curve_discount_factor(**columns, years=years),
        "zero_rate": _volarb_core.rate_curve_zero_rate(**columns, years=years),
        "integrated_rate": _volarb_core.rate_curve_integrated_rate(**columns, years=years),
        "forward_rate": _volarb_core.rate_curve_forward_rate(**columns, start_years=start, end_years=end),
        "forward_discount_factor": _volarb_core.rate_curve_forward_discount_factor(
            **columns, start_years=start, end_years=end
        ),
    }


def required_order_side(record: JsonRecord, field: str) -> str:
    value = record.get(field)
    if value in ("buy", "sell"):
        return str(value)
    raise DocumentError(f"field {field!r} must be 'buy' or 'sell', found {value!r}")


def package_leg_columns(record: JsonRecord) -> dict[str, list[Any]]:
    raw = record.get("legs")
    if not isinstance(raw, list):
        raise DocumentError("field 'legs' must be an array")
    numeric = ("bid_price", "ask_price", "vega_with_respect_to_volatility")
    integral = ("bid_size", "ask_size", "quantity", "contract_multiplier")
    columns: dict[str, list[Any]] = {name: [] for name in (*numeric, *integral, "side")}
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'legs' must be an object")
        for name in numeric:
            columns[name].append(required_float(entry, name))
        for name in integral:
            columns[name].append(required_integer(entry, name))
        columns["side"].append(required_order_side(entry, "side"))
    return columns


def simulate_fills_record(record: JsonRecord) -> JsonRecord:
    fill = _volarb_core.fill_package(**package_leg_columns(record))
    return {
        "id": required_string(record, "id"),
        "status": fill.status,
        "requested_quantity": fill.requested_quantity,
        "filled_quantity": fill.filled_quantity,
        "total_cost_against_mid": fill.total_cost_against_mid,
        "net_vega": fill.net_vega,
        "net_vega_is_negligible": fill.net_vega_is_negligible,
        "round_trip_cost_in_volatility_points": fill.round_trip_cost_in_volatility_points,
        "leg_filled_quantity": fill.leg_filled_quantity,
        "leg_touch_price": fill.leg_touch_price,
        "leg_mid_price": fill.leg_mid_price,
        "leg_half_spread": fill.leg_half_spread,
        "leg_cost_against_mid": fill.leg_cost_against_mid,
        "leg_status": fill.leg_status,
    }


def essvi_slice_columns(record: JsonRecord) -> dict[str, list[Any]]:
    raw = record.get("slices")
    if not isinstance(raw, list):
        raise DocumentError("field 'slices' must be an array")
    years: list[Any] = []
    moneyness: list[Any] = []
    variances: list[Any] = []
    weights: list[Any] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'slices' must be an object")
        years.append(required_float(entry, "years_to_expiry"))
        observations = entry.get("observations")
        if not isinstance(observations, list):
            raise DocumentError("field 'observations' must be an array")
        moneyness.append([required_float(item, "log_moneyness") for item in observations])
        variances.append([required_float(item, "total_variance") for item in observations])
        weights.append([required_float(item, "weight") for item in observations])
    return {
        "years_to_expiry": years,
        "log_moneyness": moneyness,
        "total_variances": variances,
        "weights": weights,
    }


def calibrate_essvi_surface_record(record: JsonRecord) -> JsonRecord:
    columns = essvi_slice_columns(record)
    calibration = _volarb_core.calibrate_essvi_surface(
        years_to_expiry=columns["years_to_expiry"],
        log_moneyness=columns["log_moneyness"],
        total_variances=columns["total_variances"],
        weights=columns["weights"],
        lowest_log_moneyness=required_float(record, "lowest_log_moneyness"),
        highest_log_moneyness=required_float(record, "highest_log_moneyness"),
    )
    return {
        "id": required_string(record, "id"),
        "status": calibration.status,
        "slice_count": calibration.slice_count,
        "observation_count": calibration.observation_count,
        "simplex_iterations": calibration.simplex_iterations,
        "objective": calibration.objective,
        "weighted_root_mean_square_residual": calibration.weighted_root_mean_square_residual,
        "atm_total_variance": calibration.atm_total_variance,
        "curvature_scale": calibration.curvature_scale,
        "power_law_exponent": calibration.power_law_exponent,
        "correlation_intercept": calibration.correlation_intercept,
        "correlation_slope": calibration.correlation_slope,
        "slice_a": calibration.slice_a,
        "slice_b": calibration.slice_b,
        "slice_rho": calibration.slice_rho,
        "slice_m": calibration.slice_m,
        "slice_sigma": calibration.slice_sigma,
        "fitted_surface": calibration.fitted_surface,
        "surface_minimum_durrleman_value": calibration.surface_minimum_durrleman_value,
        "surface_minimum_total_variance_time_slope": (calibration.surface_minimum_total_variance_time_slope),
    }


def surface_slice_columns(record: JsonRecord) -> dict[str, list[float]]:
    raw = record.get("slices")
    if not isinstance(raw, list):
        raise DocumentError("field 'slices' must be an array")
    columns: dict[str, list[float]] = {
        name: [] for name in ("years_to_expiry", "a", "b", "rho", "m", "sigma")
    }
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every entry of 'slices' must be an object")
        for name, column in columns.items():
            column.append(required_float(entry, name))
    return columns


def optional_step_count(record: JsonRecord, field: str, fallback: int) -> int:
    value = record.get(field, fallback)
    return value if isinstance(value, int) else fallback


def scan_svi_surface_record(record: JsonRecord) -> JsonRecord:
    columns = surface_slice_columns(record)
    scan = _volarb_core.scan_svi_surface(
        years_to_expiry=columns["years_to_expiry"],
        a=columns["a"],
        b=columns["b"],
        rho=columns["rho"],
        m=columns["m"],
        sigma=columns["sigma"],
        lowest_log_moneyness=required_float(record, "lowest_log_moneyness"),
        highest_log_moneyness=required_float(record, "highest_log_moneyness"),
        scan_steps=optional_step_count(record, "scan_steps", _volarb_core.DEFAULT_SURFACE_SCAN_STEPS),
        time_steps_per_interval=optional_step_count(
            record, "time_steps_per_interval", _volarb_core.DEFAULT_TIME_STEPS_PER_INTERVAL
        ),
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


def scan_svi_slice_record(record: JsonRecord) -> JsonRecord:
    steps = record.get("scan_steps", _volarb_core.DEFAULT_SCAN_STEPS)
    scan = _volarb_core.scan_svi_slice(
        a=required_float(record, "a"),
        b=required_float(record, "b"),
        rho=required_float(record, "rho"),
        m=required_float(record, "m"),
        sigma=required_float(record, "sigma"),
        lowest_log_moneyness=required_float(record, "lowest_log_moneyness"),
        highest_log_moneyness=required_float(record, "highest_log_moneyness"),
        scan_steps=int(steps) if isinstance(steps, int) else _volarb_core.DEFAULT_SCAN_STEPS,
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


def calibrate_svi_slice_record(record: JsonRecord) -> JsonRecord:
    raw = record.get("observations")
    if not isinstance(raw, list):
        raise DocumentError("field 'observations' must be an array")
    log_moneyness: list[float] = []
    total_variances: list[float] = []
    weights: list[float] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise DocumentError("every observation must be an object")
        log_moneyness.append(required_float(entry, "log_moneyness"))
        total_variances.append(required_float(entry, "total_variance"))
        weights.append(required_float(entry, "weight"))

    calibration = _volarb_core.calibrate_svi_slice(
        log_moneyness=log_moneyness,
        total_variances=total_variances,
        weights=weights,
        lowest_log_moneyness=required_float(record, "lowest_log_moneyness"),
        highest_log_moneyness=required_float(record, "highest_log_moneyness"),
    )
    return {
        "id": required_string(record, "id"),
        "a": calibration.a,
        "b": calibration.b,
        "rho": calibration.rho,
        "m": calibration.m,
        "sigma": calibration.sigma,
        "objective": calibration.objective,
        "weighted_root_mean_square_residual": calibration.weighted_root_mean_square_residual,
        "simplex_iterations": calibration.simplex_iterations,
        "observation_count": calibration.observation_count,
        "fitted_curve": calibration.fitted_curve,
        "status": calibration.status,
    }


def chain_snapshot_record(query_id: str, quote: _volarb_core.ContractQuote) -> JsonRecord:
    return {
        "id": f"{query_id}|{quote.contract_symbol}",
        "query_id": query_id,
        "contract_symbol": quote.contract_symbol,
        "expiry_date": quote.expiry_date,
        "strike": quote.strike,
        "option_type": quote.option_type,
        "contract_multiplier": quote.contract_multiplier,
        "is_standard_deliverable": quote.is_standard_deliverable,
        "exercise_style": quote.exercise_style,
        "event_time": quote.event_time,
        "knowledge_time": quote.knowledge_time,
        "ingest_sequence": quote.ingest_sequence,
        "underlying_price": quote.underlying_price,
        "bid_price": quote.bid_price,
        "ask_price": quote.ask_price,
        "bid_size": quote.bid_size,
        "ask_size": quote.ask_size,
    }


def read_chain_as_of_records(records: list[JsonRecord]) -> list[JsonRecord]:
    readers: dict[tuple[str, str], _volarb_core.AsOfChainReader] = {}
    snapshots: list[JsonRecord] = []
    for record in records:
        dataset_root = required_string(record, "dataset_root")
        horizon_text = required_string(record, "knowledge_horizon")
        cache_key = (dataset_root, horizon_text)
        if cache_key not in readers:
            readers[cache_key] = _volarb_core.open_chain_dataset(dataset_root, horizon_text)
        quotes = readers[cache_key].chain_as_of(
            underlying_symbol=required_string(record, "underlying_symbol"),
            observation_time=required_string(record, "observation_time"),
            include_adjusted_contracts=optional_boolean(record, "include_adjusted_contracts", False),
        )
        query_id = required_string(record, "id")
        snapshots.extend(chain_snapshot_record(query_id, quote) for quote in quotes)
    return snapshots


def forward_curve_record(
    query_id: str, underlying_symbol: str, point: _volarb_core.ForwardCurvePoint
) -> JsonRecord:
    return {
        "id": f"{query_id}|{point.expiry_date}",
        "query_id": query_id,
        "underlying_symbol": underlying_symbol,
        "expiry_date": point.expiry_date,
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
    readers: dict[tuple[str, str], _volarb_core.AsOfChainReader] = {}
    curve: list[JsonRecord] = []
    for record in records:
        dataset_root = required_string(record, "dataset_root")
        horizon_text = required_string(record, "knowledge_horizon")
        cache_key = (dataset_root, horizon_text)
        if cache_key not in readers:
            readers[cache_key] = _volarb_core.open_chain_dataset(dataset_root, horizon_text)
        observation_time = required_string(record, "observation_time")
        underlying_symbol = required_string(record, "underlying_symbol")
        quotes = readers[cache_key].chain_as_of(
            underlying_symbol=underlying_symbol,
            observation_time=observation_time,
            include_adjusted_contracts=optional_boolean(record, "include_adjusted_contracts", False),
        )
        query_id = required_string(record, "id")
        curve.extend(
            forward_curve_record(query_id, underlying_symbol, point)
            for point in _volarb_core.imply_forward_curve(
                quotes, observation_time, optional_float(record, "zero_rate")
            )
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
    "draw-random-sample": Verb(
        name="draw-random-sample",
        input_schema="random_sample_request/v1",
        output_schema="random_sample/v1",
        transform_records=mapped_over_records(draw_random_sample_record),
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
    parser = argparse.ArgumentParser(prog="volarb-cpp")
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
    except (DocumentError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def entry_point() -> None:
    raise SystemExit(main(sys.argv[1:]))
