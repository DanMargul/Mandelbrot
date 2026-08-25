from __future__ import annotations

import math
from itertools import pairwise

import pytest
from volarb_py.rate_curve import (
    CurveNode,
    InvalidRateCurveError,
    RateCurve,
    discount_factor,
    forward_discount_factor,
    forward_rate,
    zero_rate,
)

UPWARD = RateCurve(
    [
        CurveNode(0.0833, 0.01),
        CurveNode(0.2500, 0.04),
        CurveNode(1.0000, 0.045),
        CurveNode(2.0000, 0.043),
    ]
)
NEGATIVE = RateCurve([CurveNode(0.5, -0.006), CurveNode(2.0, -0.002), CurveNode(5.0, 0.004)])
FLAT = RateCurve([CurveNode(1.0, 0.03)])
FIRST_SEGMENT_FORWARD_SAMPLES = 21
NEGATIVE_MIDDLE_FORWARD = -0.0006666666666666666
LINEAR_ZERO_FORWARD_SWING = 3.0


def test_the_curve_reproduces_its_own_nodes_exactly() -> None:
    for node in UPWARD.nodes:
        assert zero_rate(UPWARD, node.years_to_maturity) == pytest.approx(
            node.continuously_compounded_zero_rate, rel=1e-15
        )
        assert discount_factor(UPWARD, node.years_to_maturity) == pytest.approx(
            math.exp(-node.continuously_compounded_zero_rate * node.years_to_maturity), rel=1e-15
        )


def test_the_forward_rate_is_constant_inside_a_segment() -> None:
    reference = forward_rate(UPWARD, 0.0833, 0.25)
    step = (0.25 - 0.0833) / FIRST_SEGMENT_FORWARD_SAMPLES
    for index in range(FIRST_SEGMENT_FORWARD_SAMPLES):
        lower = 0.0833 + step * index
        assert forward_rate(UPWARD, lower, lower + step) == pytest.approx(reference, rel=1e-12)


def test_interpolating_the_zero_rate_instead_would_not_be_constant() -> None:
    def zero_rate_linearly(years: float) -> float:
        nodes = UPWARD.nodes
        for earlier, later in pairwise(nodes):
            if earlier.years_to_maturity <= years <= later.years_to_maturity:
                span = later.years_to_maturity - earlier.years_to_maturity
                fraction = (years - earlier.years_to_maturity) / span
                return (1.0 - fraction) * earlier.continuously_compounded_zero_rate + (
                    fraction * later.continuously_compounded_zero_rate
                )
        raise AssertionError(years)

    def forward_under_linear_zero(years: float) -> float:
        step = 1e-6
        return (
            zero_rate_linearly(years + step) * (years + step)
            - zero_rate_linearly(years - step) * (years - step)
        ) / (2.0 * step)

    inside = [0.0833 + (0.25 - 0.0833) * index / 100 for index in range(1, 100)]
    forwards = [forward_under_linear_zero(years) for years in inside]
    assert max(forwards) / min(forwards) > LINEAR_ZERO_FORWARD_SWING
    assert forward_rate(UPWARD, 0.0833, 0.25) == pytest.approx(forward_rate(UPWARD, 0.10, 0.20), rel=1e-12)


def test_discount_factors_compose_across_a_forward_period() -> None:
    assert discount_factor(UPWARD, 1.5) == pytest.approx(
        discount_factor(UPWARD, 0.4) * forward_discount_factor(UPWARD, 0.4, 1.5), rel=1e-14
    )


def test_the_short_end_is_flat_at_the_first_node() -> None:
    for years in (1e-6, 0.01, 0.05, 0.0833):
        assert zero_rate(UPWARD, years) == pytest.approx(0.01, rel=1e-12)
    assert discount_factor(UPWARD, 0.0) == 1.0


def test_beyond_the_last_node_the_final_forward_continues() -> None:
    tail = forward_rate(UPWARD, 1.0, 2.0)
    assert forward_rate(UPWARD, 2.0, 5.0) == pytest.approx(tail, rel=1e-12)
    assert forward_rate(UPWARD, 3.0, 30.0) == pytest.approx(tail, rel=1e-12)


def test_a_single_node_curve_is_flat_everywhere() -> None:
    for years in (0.01, 1.0, 7.0):
        assert zero_rate(FLAT, years) == pytest.approx(0.03, rel=1e-12)
    assert forward_rate(FLAT, 2.0, 9.0) == pytest.approx(0.03, rel=1e-12)


def test_negative_rates_are_a_market_condition_and_not_an_error() -> None:
    assert discount_factor(NEGATIVE, 0.5) > 1.0
    assert zero_rate(NEGATIVE, 0.5) == pytest.approx(-0.006, rel=1e-14)
    assert zero_rate(NEGATIVE, 5.0) == pytest.approx(0.004, rel=1e-14)


def test_rising_zero_rates_do_not_imply_a_positive_forward() -> None:
    assert NEGATIVE.nodes[1].continuously_compounded_zero_rate > (
        NEGATIVE.nodes[0].continuously_compounded_zero_rate
    )
    assert forward_rate(NEGATIVE, 0.5, 2.0) == pytest.approx(NEGATIVE_MIDDLE_FORWARD, rel=1e-12)
    assert discount_factor(NEGATIVE, 2.0) > discount_factor(NEGATIVE, 0.5)


def test_a_malformed_curve_is_rejected() -> None:
    with pytest.raises(InvalidRateCurveError):
        discount_factor(RateCurve([]), 1.0)
    with pytest.raises(InvalidRateCurveError):
        discount_factor(RateCurve([CurveNode(0.0, 0.01)]), 1.0)
    with pytest.raises(InvalidRateCurveError):
        discount_factor(RateCurve([CurveNode(1.0, 0.01), CurveNode(0.5, 0.02)]), 1.0)
    with pytest.raises(InvalidRateCurveError):
        discount_factor(UPWARD, -1.0)
    with pytest.raises(InvalidRateCurveError):
        forward_rate(UPWARD, 1.0, 1.0)
