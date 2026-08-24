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
    required_option_type,
    required_string,
    write_document,
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
