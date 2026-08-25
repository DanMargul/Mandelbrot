from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

MINIMUM_CURVE_NODES: Final[int] = 1
MINIMUM_YEAR_FRACTION: Final[float] = 1e-12


class InvalidRateCurveError(ValueError):
    pass


@dataclass(frozen=True)
class CurveNode:
    years_to_maturity: float
    continuously_compounded_zero_rate: float


@dataclass(frozen=True)
class RateCurve:
    nodes: list[CurveNode]


def validate_rate_curve(curve: RateCurve) -> None:
    if len(curve.nodes) < MINIMUM_CURVE_NODES:
        raise InvalidRateCurveError(
            f"a curve needs at least {MINIMUM_CURVE_NODES} node, got {len(curve.nodes)}"
        )
    if curve.nodes[0].years_to_maturity <= 0.0:
        raise InvalidRateCurveError(
            f"every node must sit at a positive maturity, got {curve.nodes[0].years_to_maturity}"
        )
    for earlier, later in pairwise(curve.nodes):
        if later.years_to_maturity <= earlier.years_to_maturity:
            raise InvalidRateCurveError("nodes must be strictly increasing in years_to_maturity")


def integrated_rate_at_node(node: CurveNode) -> float:
    return node.continuously_compounded_zero_rate * node.years_to_maturity


def terminal_forward_rate(curve: RateCurve) -> float:
    last = curve.nodes[-1]
    if len(curve.nodes) == MINIMUM_CURVE_NODES:
        return last.continuously_compounded_zero_rate
    previous = curve.nodes[-2]
    span = last.years_to_maturity - previous.years_to_maturity
    return (integrated_rate_at_node(last) - integrated_rate_at_node(previous)) / span


def integrated_rate(curve: RateCurve, years: float) -> float:
    validate_rate_curve(curve)
    if years < 0.0:
        raise InvalidRateCurveError(f"years must not be negative, got {years}")
    if years == 0.0:
        return 0.0

    first = curve.nodes[0]
    if years <= first.years_to_maturity:
        return integrated_rate_at_node(first) * (years / first.years_to_maturity)

    last = curve.nodes[-1]
    if years >= last.years_to_maturity:
        return integrated_rate_at_node(last) + terminal_forward_rate(curve) * (years - last.years_to_maturity)

    for earlier, later in pairwise(curve.nodes):
        if earlier.years_to_maturity <= years <= later.years_to_maturity:
            span = later.years_to_maturity - earlier.years_to_maturity
            fraction = (years - earlier.years_to_maturity) / span
            return (1.0 - fraction) * integrated_rate_at_node(earlier) + fraction * (
                integrated_rate_at_node(later)
            )
    raise InvalidRateCurveError(f"no curve segment contains {years}")


def discount_factor(curve: RateCurve, years: float) -> float:
    return math.exp(-integrated_rate(curve, years))


def zero_rate(curve: RateCurve, years: float) -> float:
    if years <= MINIMUM_YEAR_FRACTION:
        return instantaneous_forward_rate(curve)
    return integrated_rate(curve, years) / years


def instantaneous_forward_rate(curve: RateCurve) -> float:
    validate_rate_curve(curve)
    return curve.nodes[0].continuously_compounded_zero_rate


def forward_rate(curve: RateCurve, start_years: float, end_years: float) -> float:
    if not end_years > start_years:
        raise InvalidRateCurveError(f"the forward period must be positive, got {start_years} to {end_years}")
    span = end_years - start_years
    return (integrated_rate(curve, end_years) - integrated_rate(curve, start_years)) / span


def forward_discount_factor(curve: RateCurve, start_years: float, end_years: float) -> float:
    return math.exp(-forward_rate(curve, start_years, end_years) * (end_years - start_years))
