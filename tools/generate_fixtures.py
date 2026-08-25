#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import mpmath

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "tools"))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from fixture_cases import (  # noqa: E402
    AmericanCase,
    PricingCase,
    all_american_cases,
    all_pricing_cases,
    american_inversion_cases,
)
from oracle import oracle_implied_volatility, oracle_price_and_greeks  # noqa: E402
from volarb_py.american import (  # noqa: E402
    LatticeInputs,
    black_scholes_reference_price,
    richardson_extrapolated_price,
)
from volarb_py.cli import (  # noqa: E402
    calibrate_essvi_surface_record,
    calibrate_svi_slice_record,
    invert_american_implied_volatility_record,
    invert_implied_volatility_record,
    price_american_option_record,
    price_option_record,
    scan_svi_slice_record,
    scan_svi_surface_record,
    simulate_fills_record,
)
from volarb_py.documents import Document, write_document  # noqa: E402
from volarb_py.essvi import EssviParameters, slices_from_parameters  # noqa: E402
from volarb_py.svi import (  # noqa: E402
    SviParameters,
    durrleman_function,
    risk_neutral_density,
    scan_svi_slice,
)
from volarb_py.svi import total_variance as svi_total_variance  # noqa: E402
from volarb_py.svi_calibration import reference_log_moneyness  # noqa: E402
from volarb_py.svi_surface import (  # noqa: E402
    DEFAULT_TIME_STEPS_PER_INTERVAL,
    SviSurfaceSlice,
    scan_svi_surface,
)

FIXTURE_ROOT: Final[Path] = REPOSITORY_ROOT / "spec" / "fixtures"
DOUBLE_PRECISION_EPSILON: Final[float] = sys.float_info.epsilon
PRICE_ORACLE_ULP_BUDGET: Final[float] = 8.0
GREEK_ORACLE_RELATIVE_BUDGET: Final[float] = 1e-13
VOLATILITY_ORACLE_ABSOLUTE_BUDGET: Final[float] = 1e-9
FINE_LATTICE_BASE_STEPS: Final[int] = 512
LATTICE_ORACLE_RELATIVE_BUDGET: Final[float] = 1e-4
EUROPEAN_LATTICE_ORACLE_RELATIVE_BUDGET: Final[float] = 5e-5
AMERICAN_INVERSION_RELATIVE_BUDGET: Final[float] = 1e-4
SVI_FINE_SCAN_STEPS: Final[int] = 20000
SVI_SCAN_ORACLE_BUDGET: Final[float] = 1e-9
SURFACE_FINE_SCAN_STEPS: Final[int] = 4096
SURFACE_FINE_TIME_STEPS: Final[int] = 64
SURFACE_SCAN_ORACLE_BUDGET: Final[float] = 1e-9
SURFACE_ROUND_TRIP_BUDGET: Final[float] = 1e-5
ESSVI_RECOVERY_BUDGET: Final[float] = 1e-8


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


def build_american_inversion_fixture() -> None:
    request_records = []
    result_records = []
    for case in american_inversion_cases():
        priced = price_american_option_record(asdict(case))
        request = {
            "id": case.id,
            "spot_price": case.spot_price,
            "strike": case.strike,
            "years_to_expiry": case.years_to_expiry,
            "zero_rate": case.zero_rate,
            "carry_rate": case.carry_rate,
            "option_price": priced["price"],
            "option_type": case.option_type,
            "exercise_style": case.exercise_style,
        }
        result = invert_american_implied_volatility_record(request)
        if result["status"] == "converged":
            recovered = abs(float(result["volatility"]) - case.volatility) / case.volatility
            if recovered > AMERICAN_INVERSION_RELATIVE_BUDGET:
                raise OracleDisagreementError(
                    f"{case.id}: inversion did not recover its own volatility, off by {recovered}"
                )
        request_records.append(request)
        result_records.append(result)

    directory = FIXTURE_ROOT / "invert-american-implied-volatility"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(
        directory / "roundtrip.input.json", Document("american_inversion_request/v1", request_records)
    )
    write_document(
        directory / "roundtrip.expected.json", Document("american_inversion_result/v1", result_records)
    )
    statuses = sorted({str(record["status"]) for record in result_records})
    print(f"invert-american-implied-volatility/roundtrip: {len(result_records)} cases, statuses {statuses}")


SVI_SCAN_CASES: Final[tuple[dict[str, Any], ...]] = (
    {"id": "short_dated_index_smile", "a": 0.0002, "b": 0.018, "rho": -0.65, "m": 0.01, "sigma": 0.10},
    {"id": "long_dated_index_smile", "a": 0.0100, "b": 0.090, "rho": -0.55, "m": 0.05, "sigma": 0.35},
    {"id": "almost_flat_smile", "a": 0.0400, "b": 0.002, "rho": -0.10, "m": 0.00, "sigma": 0.50},
    {"id": "steep_negative_skew", "a": 0.0050, "b": 0.060, "rho": -0.90, "m": 0.02, "sigma": 0.20},
    {"id": "positive_skew", "a": 0.0050, "b": 0.050, "rho": 0.50, "m": -0.02, "sigma": 0.22},
    {"id": "zero_convexity", "a": 0.0400, "b": 0.000, "rho": -0.30, "m": 0.00, "sigma": 0.30},
    {"id": "high_level_wide_smile", "a": 0.2000, "b": 0.300, "rho": -0.40, "m": 0.00, "sigma": 0.60},
    {
        "id": "butterfly_violation_narrow_wing",
        "a": 0.0002,
        "b": 0.350,
        "rho": -0.85,
        "m": 0.00,
        "sigma": 0.02,
    },
    {
        "id": "butterfly_violation_steep_slope",
        "a": 0.0100,
        "b": 0.400,
        "rho": -0.95,
        "m": 0.00,
        "sigma": 0.05,
    },
    {"id": "butterfly_violation_off_centre", "a": 0.0050, "b": 0.250, "rho": 0.80, "m": 0.15, "sigma": 0.03},
)

SVI_SCAN_RANGES: Final[tuple[tuple[str, float, float, int], ...]] = (
    ("standard", -0.60, 0.60, 512),
    ("narrow", -0.15, 0.15, 128),
    ("wide", -1.50, 1.50, 1024),
    ("coarse", -0.60, 0.60, 16),
)


def verify_svi_scan(request: dict[str, Any], result: dict[str, Any]) -> None:
    parameters = SviParameters(
        a=float(request["a"]),
        b=float(request["b"]),
        rho=float(request["rho"]),
        m=float(request["m"]),
        sigma=float(request["sigma"]),
    )
    minimum_point = float(result["log_moneyness_at_minimum"])
    durrleman = durrleman_function(parameters, minimum_point)
    density = risk_neutral_density(parameters, minimum_point)
    if (durrleman < 0.0) != (density < 0.0):
        raise OracleDisagreementError(f"{request['id']}: density and Durrleman disagree on sign")

    fine = scan_svi_slice(
        parameters,
        float(request["lowest_log_moneyness"]),
        float(request["highest_log_moneyness"]),
        SVI_FINE_SCAN_STEPS,
    )
    slack = float(result["minimum_durrleman_value"]) - fine.minimum_durrleman_value
    if slack > SVI_SCAN_ORACLE_BUDGET:
        raise OracleDisagreementError(
            f"{request['id']}: a {SVI_FINE_SCAN_STEPS} step scan found {slack} more depth"
        )


def build_svi_scan_fixture() -> None:
    request_records = []
    result_records = []
    for label, lowest, highest, steps in SVI_SCAN_RANGES:
        for case in SVI_SCAN_CASES:
            request = {
                **case,
                "id": f"{case['id']}_{label}",
                "lowest_log_moneyness": lowest,
                "highest_log_moneyness": highest,
                "scan_steps": steps,
            }
            result = scan_svi_slice_record(request)
            verify_svi_scan(request, result)
            request_records.append(request)
            result_records.append(result)

    directory = FIXTURE_ROOT / "scan-svi-slice"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(directory / "slices.input.json", Document("svi_scan_request/v1", request_records))
    write_document(directory / "slices.expected.json", Document("svi_scan_result/v1", result_records))
    statuses = sorted({str(record["status"]) for record in result_records})
    print(f"scan-svi-slice/slices: {len(result_records)} cases, statuses {statuses}")


SVI_SURFACE_CASES: Final[
    tuple[tuple[str, tuple[tuple[float, float, float, float, float, float], ...]], ...]
] = (
    (
        "healthy_index_term_structure",
        (
            (0.0833, 0.0015, 0.030, -0.70, 0.010, 0.10),
            (0.2500, 0.0060, 0.055, -0.65, 0.015, 0.15),
            (0.5000, 0.0140, 0.075, -0.60, 0.020, 0.22),
            (1.0000, 0.0300, 0.100, -0.55, 0.030, 0.32),
        ),
    ),
    (
        "two_slice_minimal",
        (
            (0.2500, 0.0060, 0.055, -0.65, 0.015, 0.15),
            (1.0000, 0.0300, 0.100, -0.55, 0.030, 0.32),
        ),
    ),
    (
        "flat_term_structure",
        (
            (0.2500, 0.0060, 0.055, -0.65, 0.015, 0.15),
            (0.7500, 0.0060, 0.055, -0.65, 0.015, 0.15),
        ),
    ),
    (
        "steep_skew_term_structure",
        (
            (0.0833, 0.0020, 0.040, -0.90, 0.000, 0.08),
            (0.3333, 0.0090, 0.070, -0.85, 0.010, 0.14),
            (1.0000, 0.0350, 0.120, -0.80, 0.020, 0.28),
        ),
    ),
    (
        "positive_skew_term_structure",
        (
            (0.1667, 0.0040, 0.045, 0.40, -0.020, 0.12),
            (0.5000, 0.0150, 0.080, 0.35, -0.010, 0.20),
            (1.5000, 0.0450, 0.130, 0.30, 0.000, 0.34),
        ),
    ),
    (
        "calendar_violation_level_falls",
        (
            (0.0833, 0.0015, 0.030, -0.70, 0.010, 0.10),
            (0.2500, 0.0060, 0.055, -0.65, 0.015, 0.15),
            (0.5000, 0.0040, 0.055, -0.60, 0.020, 0.22),
            (1.0000, 0.0300, 0.100, -0.55, 0.030, 0.32),
        ),
    ),
    (
        "calendar_violation_in_the_wing_only",
        (
            (0.2500, 0.0300, 0.030, -0.10, 0.000, 0.20),
            (0.7500, 0.0320, 0.150, -0.80, 0.000, 0.30),
        ),
    ),
    (
        "butterfly_violation_between_two_clean_knots",
        (
            (0.2500, -0.127, 0.379, -0.598, 0.088, 0.419),
            (1.0000, 0.077, 0.396, -0.617, 0.191, 0.079),
        ),
    ),
    (
        "butterfly_violation_in_a_knot",
        (
            (0.2500, 0.0060, 0.055, -0.65, 0.015, 0.15),
            (0.7500, 0.0002, 0.350, -0.85, 0.000, 0.02),
        ),
    ),
)

SVI_SURFACE_RANGES: Final[tuple[tuple[str, float, float, int, int], ...]] = (
    ("standard", -0.60, 0.60, 256, 8),
    ("unit", -1.00, 1.00, 256, 8),
    ("wide", -1.50, 1.50, 512, 4),
    ("coarse", -0.60, 0.60, 16, 1),
)


def surface_slices_of(
    case: tuple[tuple[float, float, float, float, float, float], ...],
) -> list[SviSurfaceSlice]:
    return [
        SviSurfaceSlice(
            years_to_expiry=years,
            parameters=SviParameters(a=a, b=b, rho=rho, m=m, sigma=sigma),
        )
        for years, a, b, rho, m, sigma in case
    ]


def verify_svi_surface_scan(
    case: tuple[tuple[float, float, float, float, float, float], ...],
    request: dict[str, Any],
    result: dict[str, Any],
) -> None:
    slices = surface_slices_of(case)
    lowest = float(request["lowest_log_moneyness"])
    highest = float(request["highest_log_moneyness"])
    time_steps = int(request["time_steps_per_interval"])

    fine = scan_svi_surface(slices, lowest, highest, SURFACE_FINE_SCAN_STEPS, time_steps)
    slack = float(result["minimum_durrleman_value"]) - fine.minimum_durrleman_value
    if slack > SURFACE_SCAN_ORACLE_BUDGET:
        raise OracleDisagreementError(
            f"{request['id']}: a {SURFACE_FINE_SCAN_STEPS} step scan in log moneyness "
            f"found {slack} more butterfly depth"
        )
    calendar_slack = (
        float(result["minimum_total_variance_time_slope"]) - fine.minimum_total_variance_time_slope
    )
    if calendar_slack > SURFACE_SCAN_ORACLE_BUDGET:
        raise OracleDisagreementError(
            f"{request['id']}: a finer scan found {calendar_slack} more calendar depth"
        )

    if time_steps >= DEFAULT_TIME_STEPS_PER_INTERVAL:
        finest = scan_svi_surface(slices, lowest, highest, SURFACE_FINE_SCAN_STEPS, SURFACE_FINE_TIME_STEPS)
        slack = float(result["minimum_durrleman_value"]) - finest.minimum_durrleman_value
        if slack > SURFACE_SCAN_ORACLE_BUDGET:
            raise OracleDisagreementError(
                f"{request['id']}: a {SURFACE_FINE_SCAN_STEPS} by {SURFACE_FINE_TIME_STEPS} scan "
                f"found {slack} more butterfly depth"
            )
    if result["status"] != "arbitrage_free_on_grid":
        return
    error = float(result["worst_local_variance_round_trip_error"])
    if error > SURFACE_ROUND_TRIP_BUDGET:
        raise OracleDisagreementError(
            f"{request['id']}: the Dupire round trip disagreed by {error} > {SURFACE_ROUND_TRIP_BUDGET}"
        )


def build_svi_surface_fixture() -> None:
    request_records = []
    result_records = []
    for label, lowest, highest, steps, time_steps in SVI_SURFACE_RANGES:
        for name, case in SVI_SURFACE_CASES:
            request = {
                "id": f"{name}_{label}",
                "slices": [
                    {
                        "years_to_expiry": years,
                        "a": a,
                        "b": b,
                        "rho": rho,
                        "m": m,
                        "sigma": sigma,
                    }
                    for years, a, b, rho, m, sigma in case
                ],
                "lowest_log_moneyness": lowest,
                "highest_log_moneyness": highest,
                "scan_steps": steps,
                "time_steps_per_interval": time_steps,
            }
            result = scan_svi_surface_record(request)
            verify_svi_surface_scan(case, request, result)
            request_records.append(request)
            result_records.append(result)

    directory = FIXTURE_ROOT / "scan-svi-surface"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(
        directory / "surfaces.input.json", Document("svi_surface_scan_request/v1", request_records)
    )
    write_document(
        directory / "surfaces.expected.json", Document("svi_surface_scan_result/v1", result_records)
    )
    statuses = sorted({str(record["status"]) for record in result_records})
    worst = max(float(record["worst_local_variance_round_trip_error"]) for record in result_records)
    print(
        f"scan-svi-surface/surfaces: {len(result_records)} cases, statuses {statuses}, "
        f"worst round trip {worst:.3e}"
    )


FILL_QUOTES: Final[tuple[tuple[str, float, float, int, int, float], ...]] = (
    ("liquid_index", 10.00, 10.20, 250, 180, 0.2000),
    ("liquid_single_name", 2.40, 2.50, 90, 75, 0.0850),
    ("wide_single_name", 1.00, 1.40, 12, 9, 0.0500),
    ("very_wide", 0.30, 0.55, 5, 4, 0.0180),
    ("penny_wide", 0.05, 0.10, 400, 350, 0.0040),
    ("locked", 3.15, 3.15, 20, 20, 0.1100),
    ("no_offer", 4.00, 4.60, 30, 0, 0.1500),
)

FILL_QUANTITIES: Final[tuple[int, ...]] = (1, 10, 200)
FILL_MULTIPLIER: Final[int] = 100
FILL_SPREAD_BUDGET: Final[float] = 1e-12


def fill_leg(name: str, side: str, quantity: int) -> dict[str, Any]:
    for label, bid, ask, bid_size, ask_size, vega in FILL_QUOTES:
        if label == name:
            return {
                "bid_price": bid,
                "ask_price": ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "side": side,
                "quantity": quantity,
                "contract_multiplier": FILL_MULTIPLIER,
                "vega_with_respect_to_volatility": vega,
            }
    raise KeyError(name)


def single_leg_requests() -> list[dict[str, Any]]:
    records = []
    for label, _, _, _, _, _ in FILL_QUOTES:
        for side in ("buy", "sell"):
            for quantity in FILL_QUANTITIES:
                records.append(
                    {
                        "id": f"{label}_{side}_{quantity}",
                        "legs": [fill_leg(label, side, quantity)],
                    }
                )
    return records


def package_requests() -> list[dict[str, Any]]:
    return [
        {
            "id": "vertical_spread",
            "legs": [fill_leg("liquid_single_name", "buy", 10), fill_leg("wide_single_name", "sell", 10)],
        },
        {
            "id": "vega_neutral_pair",
            "legs": [fill_leg("liquid_index", "buy", 10), fill_leg("liquid_index", "sell", 10)],
        },
        {
            "id": "four_leg_condor",
            "legs": [
                fill_leg("liquid_single_name", "buy", 5),
                fill_leg("wide_single_name", "sell", 5),
                fill_leg("very_wide", "sell", 5),
                fill_leg("penny_wide", "buy", 5),
            ],
        },
        {
            "id": "package_with_a_missing_offer",
            "legs": [fill_leg("liquid_index", "buy", 10), fill_leg("no_offer", "buy", 10)],
        },
        {
            "id": "package_capped_by_displayed_size",
            "legs": [fill_leg("very_wide", "buy", 200), fill_leg("liquid_index", "sell", 200)],
        },
    ]


def verify_fill(request: dict[str, Any], result: dict[str, Any]) -> None:
    for leg, half_spread, filled in zip(
        request["legs"], result["leg_half_spread"], result["leg_filled_quantity"], strict=True
    ):
        expected = 0.5 * (leg["ask_price"] - leg["bid_price"])
        if abs(half_spread - expected) > FILL_SPREAD_BUDGET:
            raise OracleDisagreementError(f"{request['id']}: half spread {half_spread} against {expected}")
        available = leg["ask_size"] if leg["side"] == "buy" else leg["bid_size"]
        if filled != min(leg["quantity"], available):
            raise OracleDisagreementError(f"{request['id']}: filled {filled} against available {available}")
    if result["total_cost_against_mid"] < 0.0:
        raise OracleDisagreementError(f"{request['id']}: a taker cannot be paid to cross the spread")


def build_fill_fixture() -> None:
    request_records = [*single_leg_requests(), *package_requests()]
    result_records = []
    for request in request_records:
        result = simulate_fills_record(request)
        verify_fill(request, result)
        result_records.append(result)

    directory = FIXTURE_ROOT / "simulate-fills"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(directory / "orders.input.json", Document("fill_request/v1", request_records))
    write_document(directory / "orders.expected.json", Document("fill_result/v1", result_records))
    statuses = sorted({str(record["status"]) for record in result_records})
    print(f"simulate-fills/orders: {len(result_records)} cases, statuses {statuses}")


ESSVI_EXPIRIES: Final[tuple[float, ...]] = (0.0833, 0.25, 0.5, 1.0)

ESSVI_TRUTHS: Final[tuple[tuple[str, tuple[float, ...], float, float, float, float], ...]] = (
    ("index_term_structure", (0.0033, 0.0100, 0.0200, 0.0400), 0.35, 0.45, -0.85, 0.30),
    ("flat_correlation", (0.0040, 0.0120, 0.0240, 0.0480), 0.50, 0.50, -0.60, 0.00),
    ("shallow_skew", (0.0025, 0.0080, 0.0160, 0.0320), 0.25, 0.35, -0.30, 0.10),
    ("steep_and_rotating", (0.0050, 0.0150, 0.0300, 0.0600), 0.60, 0.55, -0.90, 0.50),
)

ESSVI_SAMPLED_SURFACES: Final[tuple[tuple[str, tuple[SviParameters, ...]], ...]] = (
    (
        "ordinary_index_smiles",
        (
            SviParameters(0.0015, 0.030, -0.70, 0.010, 0.10),
            SviParameters(0.0060, 0.055, -0.65, 0.015, 0.15),
            SviParameters(0.0140, 0.075, -0.60, 0.020, 0.22),
            SviParameters(0.0300, 0.100, -0.55, 0.030, 0.32),
        ),
    ),
    (
        "calendar_violating_data",
        (
            SviParameters(0.0015, 0.030, -0.70, 0.010, 0.10),
            SviParameters(0.0060, 0.055, -0.65, 0.015, 0.15),
            SviParameters(0.0040, 0.055, -0.60, 0.020, 0.22),
            SviParameters(0.0300, 0.100, -0.55, 0.030, 0.32),
        ),
    ),
)

ESSVI_PENALTY_LOWEST: Final[float] = -0.6
ESSVI_PENALTY_HIGHEST: Final[float] = 0.6
ESSVI_SAMPLE_LOWEST: Final[float] = -0.4
ESSVI_SAMPLE_HIGHEST: Final[float] = 0.4
ESSVI_SAMPLE_COUNT: Final[int] = 21


def essvi_request_from_slices(
    name: str, slices: tuple[SviParameters, ...], noise: float, seed: int
) -> dict[str, Any]:
    generator = random.Random(seed)
    span = ESSVI_SAMPLE_HIGHEST - ESSVI_SAMPLE_LOWEST
    records = []
    for years, parameters in zip(ESSVI_EXPIRIES, slices, strict=True):
        observations = []
        for index in range(ESSVI_SAMPLE_COUNT):
            point = ESSVI_SAMPLE_LOWEST + span * index / (ESSVI_SAMPLE_COUNT - 1)
            disturbance = 1.0 + noise * generator.uniform(-1.0, 1.0)
            observations.append(
                {
                    "log_moneyness": point,
                    "total_variance": svi_total_variance(parameters, point) * disturbance,
                    "weight": 1.0,
                }
            )
        records.append({"years_to_expiry": years, "observations": observations})
    return {
        "id": name,
        "slices": records,
        "lowest_log_moneyness": ESSVI_PENALTY_LOWEST,
        "highest_log_moneyness": ESSVI_PENALTY_HIGHEST,
    }


def essvi_truth_slices(
    truth: tuple[float, ...], scale: float, exponent: float, intercept: float, slope: float
) -> tuple[SviParameters, ...]:
    return tuple(slices_from_parameters(EssviParameters(list(truth), scale, exponent, intercept, slope)))


def verify_essvi_fit(request: dict[str, Any], result: dict[str, Any]) -> None:
    if result["status"] != "converged":
        raise OracleDisagreementError(
            f"{request['id']}: reported {result['status']} where a converged fit was expected"
        )
    if result["surface_minimum_durrleman_value"] < 0.0:
        raise OracleDisagreementError(f"{request['id']}: reported a fit whose density is negative")
    if result["surface_minimum_total_variance_time_slope"] < 0.0:
        raise OracleDisagreementError(f"{request['id']}: reported a fit that falls in total variance")


def verify_essvi_recovery(
    request: dict[str, Any], result: dict[str, Any], truth: tuple[SviParameters, ...]
) -> None:
    points = reference_log_moneyness()
    expected = [svi_total_variance(parameters, point) for parameters in truth for point in points]
    worst = max(
        abs(actual - target) / max(abs(target), 1e-300)
        for actual, target in zip(result["fitted_surface"], expected, strict=True)
    )
    if worst > ESSVI_RECOVERY_BUDGET:
        raise OracleDisagreementError(f"{request['id']}: refit departs from its own truth by {worst}")


def build_essvi_fixture() -> None:
    request_records = []
    result_records = []

    for name, levels, scale, exponent, intercept, slope in ESSVI_TRUTHS:
        truth = essvi_truth_slices(levels, scale, exponent, intercept, slope)
        request = essvi_request_from_slices(f"essvi_truth_{name}", truth, 0.0, 0)
        result = calibrate_essvi_surface_record(request)
        verify_essvi_fit(request, result)
        verify_essvi_recovery(request, result, truth)
        request_records.append(request)
        result_records.append(result)

    for index, (name, slices) in enumerate(ESSVI_SAMPLED_SURFACES):
        for label, noise in (("clean", 0.0), ("noisy", 0.02)):
            request = essvi_request_from_slices(f"{name}_{label}", slices, noise, 5000 + index)
            result = calibrate_essvi_surface_record(request)
            verify_essvi_fit(request, result)
            request_records.append(request)
            result_records.append(result)

    directory = FIXTURE_ROOT / "calibrate-essvi-surface"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(
        directory / "surfaces.input.json", Document("essvi_calibration_request/v1", request_records)
    )
    write_document(
        directory / "surfaces.expected.json",
        Document("essvi_calibration_result/v1", result_records),
    )
    statuses = sorted({str(record["status"]) for record in result_records})
    print(f"calibrate-essvi-surface/surfaces: {len(result_records)} cases, statuses {statuses}")


SVI_CALIBRATION_TRUTHS: Final[tuple[tuple[str, SviParameters], ...]] = (
    ("short_dated_index", SviParameters(0.0002, 0.018, -0.65, 0.01, 0.10)),
    ("long_dated_index", SviParameters(0.0100, 0.090, -0.55, 0.05, 0.35)),
    ("steep_negative_skew", SviParameters(0.0050, 0.060, -0.90, 0.02, 0.20)),
    ("positive_skew", SviParameters(0.0050, 0.050, 0.50, -0.02, 0.22)),
    ("almost_flat", SviParameters(0.0400, 0.002, -0.10, 0.00, 0.50)),
)

SVI_CALIBRATION_SAMPLINGS: Final[tuple[tuple[str, float, float, int, float], ...]] = (
    ("clean_wide", -0.30, 0.30, 21, 0.0),
    ("noisy_wide", -0.30, 0.30, 21, 5e-4),
    ("noisy_narrow", -0.12, 0.12, 11, 5e-4),
)

CALIBRATION_NOISE_SEED: Final[int] = 917
CALIBRATION_CURVE_BUDGET: Final[float] = 3e-3


def slice_observations(
    truth: SviParameters,
    generator: random.Random,
    *,
    lowest: float,
    highest: float,
    count: int,
    noise_fraction: float,
) -> list[dict[str, float]]:
    observations = []
    for index in range(count):
        point = lowest + (highest - lowest) * index / (count - 1)
        variance = svi_total_variance(truth, point)
        disturbed = variance * (1.0 + noise_fraction * generator.uniform(-1.0, 1.0))
        scale = max(noise_fraction, 1e-6) * variance
        observations.append(
            {"log_moneyness": point, "total_variance": disturbed, "weight": 1.0 / (scale * scale)}
        )
    return observations


def verify_calibration(truth: SviParameters, request: dict[str, Any], result: dict[str, Any]) -> float:
    fitted = SviParameters(
        a=float(result["a"]),
        b=float(result["b"]),
        rho=float(result["rho"]),
        m=float(result["m"]),
        sigma=float(result["sigma"]),
    )
    worst = 0.0
    for observation in request["observations"]:
        point = float(observation["log_moneyness"])
        expected = svi_total_variance(truth, point)
        worst = max(worst, abs(svi_total_variance(fitted, point) - expected) / expected)
    if worst > CALIBRATION_CURVE_BUDGET:
        raise OracleDisagreementError(f"{request['id']}: fitted curve departs from the truth by {worst}")
    scan = scan_svi_slice(
        fitted, float(request["lowest_log_moneyness"]), float(request["highest_log_moneyness"])
    )
    if scan.status != "arbitrage_free_on_grid":
        raise OracleDisagreementError(f"{request['id']}: the fitted slice admits butterfly arbitrage")
    return worst


def build_svi_calibration_fixture() -> None:
    generator = random.Random(CALIBRATION_NOISE_SEED)
    request_records = []
    result_records = []
    worst = 0.0
    for sampling, lowest, highest, count, noise in SVI_CALIBRATION_SAMPLINGS:
        for name, truth in SVI_CALIBRATION_TRUTHS:
            request = {
                "id": f"{name}_{sampling}",
                "lowest_log_moneyness": -0.6,
                "highest_log_moneyness": 0.6,
                "observations": slice_observations(
                    truth,
                    generator,
                    lowest=lowest,
                    highest=highest,
                    count=count,
                    noise_fraction=noise,
                ),
            }
            result = calibrate_svi_slice_record(request)
            worst = max(worst, verify_calibration(truth, request, result))
            request_records.append(request)
            result_records.append(result)

    request_records.append(
        {
            "id": "too_few_observations",
            "lowest_log_moneyness": -0.6,
            "highest_log_moneyness": 0.6,
            "observations": slice_observations(
                SVI_CALIBRATION_TRUTHS[0][1],
                generator,
                lowest=-0.1,
                highest=0.1,
                count=3,
                noise_fraction=0.0,
            ),
        }
    )
    result_records.append(calibrate_svi_slice_record(request_records[-1]))

    directory = FIXTURE_ROOT / "calibrate-svi-slice"
    directory.mkdir(parents=True, exist_ok=True)
    write_document(directory / "slices.input.json", Document("svi_calibration_request/v1", request_records))
    write_document(directory / "slices.expected.json", Document("svi_calibration_result/v1", result_records))
    statuses = sorted({str(record["status"]) for record in result_records})
    print(
        f"calibrate-svi-slice/slices: {len(result_records)} cases, statuses {statuses}, "
        f"worst curve departure from truth {worst:.2e}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verb",
        choices=[
            "price-options",
            "invert-implied-volatility",
            "price-american-options",
            "invert-american-implied-volatility",
            "scan-svi-slice",
            "scan-svi-surface",
            "calibrate-essvi-surface",
            "simulate-fills",
            "calibrate-svi-slice",
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
    if arguments.verb in ("invert-american-implied-volatility", "all"):
        build_american_inversion_fixture()
    if arguments.verb in ("scan-svi-slice", "all"):
        build_svi_scan_fixture()
    if arguments.verb in ("scan-svi-surface", "all"):
        build_svi_surface_fixture()
    if arguments.verb in ("simulate-fills", "all"):
        build_fill_fixture()
    if arguments.verb in ("calibrate-essvi-surface", "all"):
        build_essvi_fixture()
    if arguments.verb in ("calibrate-svi-slice", "all"):
        build_svi_calibration_fixture()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
