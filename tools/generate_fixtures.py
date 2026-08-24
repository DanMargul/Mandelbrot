#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import mpmath

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "tools"))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from fixture_cases import AmericanCase, PricingCase, all_american_cases, all_pricing_cases  # noqa: E402
from oracle import oracle_implied_volatility, oracle_price_and_greeks  # noqa: E402
from volarb_py.american import (  # noqa: E402
    LatticeInputs,
    black_scholes_reference_price,
    richardson_extrapolated_price,
)
from volarb_py.cli import (  # noqa: E402
    invert_implied_volatility_record,
    price_american_option_record,
    price_option_record,
)
from volarb_py.documents import Document, write_document  # noqa: E402

FIXTURE_ROOT: Final[Path] = REPOSITORY_ROOT / "spec" / "fixtures"
DOUBLE_PRECISION_EPSILON: Final[float] = sys.float_info.epsilon
PRICE_ORACLE_ULP_BUDGET: Final[float] = 8.0
GREEK_ORACLE_RELATIVE_BUDGET: Final[float] = 1e-13
VOLATILITY_ORACLE_ABSOLUTE_BUDGET: Final[float] = 1e-9
FINE_LATTICE_BASE_STEPS: Final[int] = 512
LATTICE_ORACLE_RELATIVE_BUDGET: Final[float] = 1e-4
EUROPEAN_LATTICE_ORACLE_RELATIVE_BUDGET: Final[float] = 1e-4


class OracleDisagreementError(AssertionError):
    pass


def pricing_request_record(case: PricingCase) -> dict[str, Any]:
    return asdict(case)


def verify_price_against_oracle(case: PricingCase, result: dict[str, Any]) -> None:
    oracle = oracle_price_and_greeks(
        forward=case.forward,
        strike=case.strike,
        years_to_expiry=case.years_to_expiry,
        volatility=case.volatility,
        discount_factor=case.discount_factor,
        option_type=case.option_type,
    )
    price_budget = (
        PRICE_ORACLE_ULP_BUDGET
        * DOUBLE_PRECISION_EPSILON
        * max(case.forward, case.strike)
        * case.discount_factor
    )
    price_difference = abs(mpmath.mpf(result["price"]) - oracle.price)
    if price_difference > price_budget:
        raise OracleDisagreementError(
            f"{case.id}: price differs from oracle by {price_difference} > {price_budget}"
        )

    for field in (
        "delta_with_respect_to_forward",
        "gamma_with_respect_to_forward",
        "vega_with_respect_to_volatility",
        "theta_with_respect_to_time",
    ):
        expected = getattr(oracle, field)
        actual = mpmath.mpf(result[field])
        scale = max(abs(expected), mpmath.mpf("1e-300"))
        if abs(actual - expected) / scale > GREEK_ORACLE_RELATIVE_BUDGET:
            raise OracleDisagreementError(
                f"{case.id}: {field} differs from oracle by {abs(actual - expected)}"
            )


def build_pricing_fixture(family: str, cases: list[PricingCase]) -> None:
    request_records = [pricing_request_record(case) for case in cases]
    result_records = []
    for case, record in zip(cases, request_records, strict=True):
        result = price_option_record(record)
        verify_price_against_oracle(case, result)
        result_records.append(result)

    directory = FIXTURE_ROOT / "price-options"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(directory / f"{family}.input.json", Document("pricing_request/v1", request_records))
    write_document(directory / f"{family}.expected.json", Document("pricing_result/v1", result_records))
    print(f"price-options/{family}: {len(cases)} cases verified against the oracle")


def implied_volatility_request_record(case: PricingCase, priced: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case.id,
        "forward": case.forward,
        "strike": case.strike,
        "years_to_expiry": case.years_to_expiry,
        "discount_factor": case.discount_factor,
        "option_price": priced["price"],
        "option_type": case.option_type,
    }


def verify_volatility_against_oracle(
    case: PricingCase, request: dict[str, Any], result: dict[str, Any]
) -> None:
    if result["status"] != "converged":
        return
    oracle_volatility = oracle_implied_volatility(
        forward=request["forward"],
        strike=request["strike"],
        years_to_expiry=request["years_to_expiry"],
        discount_factor=request["discount_factor"],
        option_price=request["option_price"],
        option_type=request["option_type"],
    )
    if oracle_volatility is None:
        return
    reported_uncertainty = result["volatility_uncertainty"]
    budget = VOLATILITY_ORACLE_ABSOLUTE_BUDGET
    if reported_uncertainty is not None:
        budget = max(budget, 4.0 * reported_uncertainty)
    difference = abs(mpmath.mpf(result["volatility"]) - oracle_volatility)
    if difference > budget:
        raise OracleDisagreementError(f"{case.id}: volatility differs from oracle by {difference} > {budget}")


def build_implied_volatility_fixture(family: str, cases: list[PricingCase]) -> None:
    request_records = []
    result_records = []
    for case in cases:
        priced = price_option_record(pricing_request_record(case))
        request = implied_volatility_request_record(case, priced)
        result = invert_implied_volatility_record(request)
        verify_volatility_against_oracle(case, request, result)
        request_records.append(request)
        result_records.append(result)

    directory = FIXTURE_ROOT / "invert-implied-volatility"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(
        directory / f"{family}.input.json",
        Document("implied_volatility_request/v1", request_records),
    )
    write_document(
        directory / f"{family}.expected.json",
        Document("implied_volatility_result/v1", result_records),
    )
    print(f"invert-implied-volatility/{family}: {len(cases)} cases verified against the oracle")


def boundary_implied_volatility_fixture() -> None:
    specifications = (
        ("price_below_intrinsic", 100.0, 90.0, 1.0, 0.98, 5.0, "call"),
        ("price_exactly_intrinsic", 100.0, 90.0, 1.0, 1.0, 10.0, "call"),
        ("price_above_forward", 100.0, 110.0, 1.0, 1.0, 101.0, "call"),
        ("put_price_above_strike", 100.0, 90.0, 1.0, 1.0, 91.0, "put"),
        ("expired_option", 100.0, 100.0, 0.0, 1.0, 1.0, "call"),
        ("negligible_time_value", 100.0, 100.0, 1.0, 1.0, 1e-12, "call"),
        ("volatility_above_ceiling", 100.0, 100.0, 1.0, 1.0, 99.9999995, "call"),
        ("ordinary_at_the_money", 100.0, 100.0, 1.0, 0.98, 7.8, "call"),
    )
    request_records = [
        {
            "id": name,
            "forward": forward,
            "strike": strike,
            "years_to_expiry": years,
            "discount_factor": discount,
            "option_price": price,
            "option_type": option_type,
        }
        for name, forward, strike, years, discount, price, option_type in specifications
    ]
    result_records = [invert_implied_volatility_record(record) for record in request_records]
    directory = FIXTURE_ROOT / "invert-implied-volatility"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(
        directory / "boundary.input.json", Document("implied_volatility_request/v1", request_records)
    )
    write_document(
        directory / "boundary.expected.json", Document("implied_volatility_result/v1", result_records)
    )
    statuses = {record["id"]: record["status"] for record in result_records}
    print(f"invert-implied-volatility/boundary: {json.dumps(statuses, indent=2)}")


def lattice_inputs_from(case: AmericanCase) -> LatticeInputs:
    return LatticeInputs(
        spot_price=case.spot_price,
        strike=case.strike,
        years_to_expiry=case.years_to_expiry,
        volatility=case.volatility,
        zero_rate=case.zero_rate,
        carry_rate=case.carry_rate,
        option_type=case.option_type,
        exercise_style=case.exercise_style,
    )


def verify_lattice_against_oracle(case: AmericanCase, result: dict[str, Any]) -> float:
    inputs = lattice_inputs_from(case)
    reference: float = richardson_extrapolated_price(inputs, FINE_LATTICE_BASE_STEPS)
    scale = max(abs(reference), case.spot_price)
    discrepancy: float = abs(float(result["price"]) - reference) / scale
    if discrepancy > LATTICE_ORACLE_RELATIVE_BUDGET:
        raise OracleDisagreementError(
            f"{case.id}: lattice price differs from the fine lattice by {discrepancy}"
        )
    if case.exercise_style == "european":
        closed_form = black_scholes_reference_price(inputs)
        closed_form_discrepancy = abs(float(result["price"]) - closed_form) / scale
        if closed_form_discrepancy > EUROPEAN_LATTICE_ORACLE_RELATIVE_BUDGET:
            raise OracleDisagreementError(
                f"{case.id}: European lattice differs from Black-Scholes by {closed_form_discrepancy}"
            )
    if result["price"] < result["european_price"] - 1e-9:
        raise OracleDisagreementError(f"{case.id}: American price below its European counterpart")
    return discrepancy


def build_american_fixture(family: str, cases: list[AmericanCase]) -> None:
    request_records = [asdict(case) for case in cases]
    result_records = []
    worst = 0.0
    for case, record in zip(cases, request_records, strict=True):
        result = price_american_option_record(record)
        worst = max(worst, verify_lattice_against_oracle(case, result))
        result_records.append(result)

    directory = FIXTURE_ROOT / "price-american-options"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(
        directory / f"{family}.input.json", Document("american_pricing_request/v1", request_records)
    )
    write_document(
        directory / f"{family}.expected.json", Document("american_pricing_result/v1", result_records)
    )
    print(
        f"price-american-options/{family}: {len(cases)} cases verified, "
        f"worst relative discrepancy against the fine lattice {worst:.2e}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verb",
        choices=[
            "price-options",
            "invert-implied-volatility",
            "price-american-options",
            "all",
        ],
        default="all",
    )
    arguments = parser.parse_args()

    families = all_pricing_cases()
    if arguments.verb in ("price-options", "all"):
        for family, cases in families.items():
            build_pricing_fixture(family, cases)
    if arguments.verb in ("invert-implied-volatility", "all"):
        for family, cases in families.items():
            build_implied_volatility_fixture(family, cases)
        boundary_implied_volatility_fixture()
    if arguments.verb in ("price-american-options", "all"):
        for family, american_cases in all_american_cases().items():
            build_american_fixture(family, american_cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
