from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest
from conftest import REPOSITORY_ROOT
from volarb_py.forward_curve import (
    ForwardCurvePoint,
    ParityPair,
    imply_forward_curve,
    median_of,
    parity_pairs_from_chain,
    years_to_expiry_from,
)
from volarb_py.market_data import ChainQuery, KnowledgeHorizon, open_chain_dataset

DATASET_ROOT = REPOSITORY_ROOT / "spec" / "fixtures" / "datasets" / "synthetic_chain"
GROUND_TRUTH = json.loads((DATASET_ROOT / "ground_truth.json").read_text(encoding="utf-8"))
RISK_FREE_RATE = GROUND_TRUTH["risk_free_rate"]
CARRY_RATES = {name: entry["carry_rate"] for name, entry in GROUND_TRUTH["underlyings"].items()}
OBSERVATION_HOURS = (15, 16, 17)
MINIMUM_PARITY_PAIRS = 4
CARRY_RATE_RECOVERY_TOLERANCE = 0.05
ODD_COUNT_MEDIAN = 2.0
EVEN_COUNT_MEDIAN = 2.5
SINGLE_VALUE_MEDIAN = 7.0


def moment(hour: int) -> datetime:
    return datetime(2026, 8, 21, hour, tzinfo=UTC)


def curve_for(underlying: str, hour: int) -> list[ForwardCurvePoint]:
    observation = moment(hour)
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(observation))
    return imply_forward_curve(reader.chain_as_of(ChainQuery(underlying, observation)), observation)


def true_discount_factor(years: float) -> float:
    return math.exp(-RISK_FREE_RATE * years)


def true_forward(spot_price: float, underlying: str, years: float) -> float:
    return spot_price * math.exp((RISK_FREE_RATE - CARRY_RATES[underlying]) * years)


def every_converged_point() -> list[ForwardCurvePoint]:
    return [point for _, point in converged_points()]


def converged_points() -> list[tuple[str, ForwardCurvePoint]]:
    return [
        (underlying, point)
        for underlying in ("SPX", "AAPL")
        for hour in OBSERVATION_HOURS
        for point in curve_for(underlying, hour)
        if point.status == "converged"
    ]


def test_the_median_is_defined_for_odd_and_even_counts() -> None:
    assert median_of([3.0, 1.0, 2.0]) == ODD_COUNT_MEDIAN
    assert median_of([4.0, 1.0, 3.0, 2.0]) == EVEN_COUNT_MEDIAN
    assert median_of([7.0]) == SINGLE_VALUE_MEDIAN


def test_the_year_fraction_is_measured_to_the_settlement_hour() -> None:
    settlement_hour = GROUND_TRUTH["expiry_settlement_hour_utc"]
    observation = datetime(2026, 8, 21, settlement_hour, tzinfo=UTC)
    assert years_to_expiry_from(observation, datetime(2026, 8, 21).date()) == 0.0
    assert years_to_expiry_from(observation, datetime(2027, 8, 21).date()) == pytest.approx(1.0, rel=1e-12)


@pytest.mark.parametrize(("underlying", "point"), converged_points())
def test_the_forward_recovers_ground_truth_within_its_standard_error(
    underlying: str, point: ForwardCurvePoint
) -> None:
    assert point.forward_standard_error is not None
    expected = true_forward(point.spot_price, underlying, point.years_to_expiry)
    assert abs(point.forward - expected) <= point.forward_standard_error


@pytest.mark.parametrize("point", every_converged_point())
def test_the_discount_factor_recovers_ground_truth_within_its_standard_error(
    point: ForwardCurvePoint,
) -> None:
    assert point.discount_factor_standard_error is not None
    expected = true_discount_factor(point.years_to_expiry)
    assert abs(point.discount_factor - expected) <= point.discount_factor_standard_error


@pytest.mark.parametrize("point", every_converged_point())
def test_the_forward_is_determined_far_better_than_the_discount_factor(point: ForwardCurvePoint) -> None:
    assert point.forward_standard_error is not None
    assert point.discount_factor_standard_error is not None
    relative_forward_error = point.forward_standard_error / point.forward
    relative_discount_error = point.discount_factor_standard_error / point.discount_factor
    assert relative_forward_error < relative_discount_error


@pytest.mark.parametrize("point", every_converged_point())
def test_a_stale_quote_is_trimmed(point: ForwardCurvePoint) -> None:
    assert point.active_pair_count < point.parity_pair_count
    assert point.active_pair_count >= MINIMUM_PARITY_PAIRS


@pytest.mark.parametrize("point", every_converged_point())
def test_the_discount_factor_term_structure_is_monotone(point: ForwardCurvePoint) -> None:
    assert point.discount_factor_is_monotone_in_expiry


def test_a_thin_chain_reports_too_few_pairs_rather_than_guessing() -> None:
    points = curve_for("THIN", 17)
    assert len(points) == 1
    assert points[0].status == "too_few_pairs"
    assert points[0].forward == 0.0
    assert points[0].discount_factor == 0.0
    assert points[0].forward_standard_error is None
    assert points[0].implied_zero_rate is None
    assert points[0].chi_square_per_degree_of_freedom is None


def test_an_absent_underlying_produces_no_curve_points() -> None:
    assert curve_for("NVDA", 17) == []


def test_only_strikes_with_both_a_call_and_a_put_become_pairs() -> None:
    observation = moment(17)
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(observation))
    quotes = reader.chain_as_of(ChainQuery("SPX", observation))
    pairs = parity_pairs_from_chain(quotes)
    calls = sum(1 for quote in quotes if quote.option_type == "call")
    paired = sum(len(group) for group in pairs.values())
    assert paired < calls


def test_the_weight_is_the_inverse_variance_of_the_measured_difference() -> None:
    observation = moment(17)
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(observation))
    pairs = parity_pairs_from_chain(reader.chain_as_of(ChainQuery("SPX", observation)))
    every_pair: list[ParityPair] = [pair for group in pairs.values() for pair in group]
    assert every_pair
    assert all(pair.weight > 0.0 for pair in every_pair)
    assert all(math.isfinite(pair.weight) for pair in every_pair)


def test_the_implied_carry_rate_recovers_the_synthetic_dividend_yield() -> None:
    for underlying, point in converged_points():
        assert point.implied_carry_rate is not None
        assert abs(point.implied_carry_rate - CARRY_RATES[underlying]) < CARRY_RATE_RECOVERY_TOLERANCE
