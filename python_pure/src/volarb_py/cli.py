from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from volarb_py.documents import (
    Document,
    DocumentError,
    JsonRecord,
    json_safe_float,
    read_document,
    required_float,
    required_option_type,
    required_string,
    write_document,
)
from volarb_py.implied_vol import ImpliedVolatilityInputs, invert_black_implied_volatility
from volarb_py.pricing import BlackScholesInputs, InvalidOptionInputsError, black_scholes_price_and_greeks


@dataclass(frozen=True)
class Verb:
    name: str
    input_schema: str
    output_schema: str
    transform_record: Callable[[JsonRecord], JsonRecord]


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


VERBS: Final[dict[str, Verb]] = {
    "price-options": Verb(
        name="price-options",
        input_schema="pricing_request/v1",
        output_schema="pricing_result/v1",
        transform_record=price_option_record,
    ),
    "invert-implied-volatility": Verb(
        name="invert-implied-volatility",
        input_schema="implied_volatility_request/v1",
        output_schema="implied_volatility_result/v1",
        transform_record=invert_implied_volatility_record,
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
    records = [verb.transform_record(record) for record in document.records]
    write_document(output_path, Document(schema=verb.output_schema, records=records))


def main(argv: Sequence[str]) -> int:
    arguments = parse_arguments(argv)
    try:
        run_verb(VERBS[arguments.verb], arguments.input, arguments.output)
    except (DocumentError, InvalidOptionInputsError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def entry_point() -> None:
    raise SystemExit(main(sys.argv[1:]))
