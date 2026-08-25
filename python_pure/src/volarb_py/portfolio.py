from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from volarb_py.hedging import whalley_wilmott_band

ASCENT_PASSES: Final[int] = 400
PROJECTION_PASSES: Final[int] = 40
STEP_SIZE: Final[float] = 0.05
MINIMUM_GAMMA: Final[float] = 1e-12
MINIMUM_DIRECTION_NORM: Final[float] = 1e-18
GAMMA_DERIVATIVE_STEP: Final[float] = 1e-6


class InvalidPortfolioInputsError(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    expected_edge: float
    vega: float
    gamma: float
    theta: float
    factor_exposures: list[float]
    maximum_size: float
    spread_cost: float


@dataclass(frozen=True)
class PortfolioLimits:
    vega_budget: float
    gamma_budget: float
    theta_budget: float
    factor_tolerance: float
    risk_aversion: float
    proportional_cost: float
    spot: float
    volatility: float
    years_to_expiry: float


@dataclass(frozen=True)
class Allocation:
    weights: list[float]
    expected_edge: float
    spread_cost: float
    hedging_cost: float
    objective: float
    net_vega: float
    net_gamma: float
    net_theta: float
    worst_factor_exposure: float
    charged_for_hedging: bool


def validate_candidates(candidates: list[Candidate]) -> int:
    if not candidates:
        raise InvalidPortfolioInputsError("a portfolio needs at least one candidate")
    factor_count = len(candidates[0].factor_exposures)
    for candidate in candidates:
        if len(candidate.factor_exposures) != factor_count:
            raise InvalidPortfolioInputsError(
                f"a candidate carries {len(candidate.factor_exposures)} factor exposures "
                f"against {factor_count}"
            )
        if candidate.maximum_size < 0.0:
            raise InvalidPortfolioInputsError(
                f"maximum_size must not be negative, got {candidate.maximum_size}"
            )
        if candidate.spread_cost < 0.0:
            raise InvalidPortfolioInputsError(
                f"spread_cost must not be negative, got {candidate.spread_cost}"
            )
    return factor_count


def validate_limits(limits: PortfolioLimits) -> None:
    for name, value in (
        ("vega_budget", limits.vega_budget),
        ("gamma_budget", limits.gamma_budget),
        ("theta_budget", limits.theta_budget),
        ("factor_tolerance", limits.factor_tolerance),
    ):
        if value < 0.0:
            raise InvalidPortfolioInputsError(f"{name} must not be negative, got {value}")
    if limits.risk_aversion <= 0.0:
        raise InvalidPortfolioInputsError(f"risk_aversion must be positive, got {limits.risk_aversion}")
    if limits.spot <= 0.0:
        raise InvalidPortfolioInputsError(f"spot must be positive, got {limits.spot}")
    if limits.volatility <= 0.0:
        raise InvalidPortfolioInputsError(f"volatility must be positive, got {limits.volatility}")
    if limits.years_to_expiry <= 0.0:
        raise InvalidPortfolioInputsError(f"years_to_expiry must be positive, got {limits.years_to_expiry}")
    if limits.proportional_cost < 0.0:
        raise InvalidPortfolioInputsError(
            f"proportional_cost must not be negative, got {limits.proportional_cost}"
        )


def hedging_cost_of_gamma(gamma: float, limits: PortfolioLimits) -> float:
    magnitude = abs(gamma)
    if magnitude < MINIMUM_GAMMA or limits.proportional_cost <= 0.0:
        return 0.0
    band = whalley_wilmott_band(limits.spot, magnitude, limits.proportional_cost, limits.risk_aversion)
    delta_volatility = magnitude * limits.volatility * limits.spot
    return (
        limits.proportional_cost
        * limits.spot
        * delta_volatility
        * delta_volatility
        / band
        * limits.years_to_expiry
    )


def weighted_total(weights: list[float], loadings: list[float]) -> float:
    total = 0.0
    for weight, loading in zip(weights, loadings, strict=True):
        total += weight * loading
    return total


def column_of(candidates: list[Candidate], index: int) -> list[float]:
    return [candidate.factor_exposures[index] for candidate in candidates]


def constraint_rows(
    candidates: list[Candidate], limits: PortfolioLimits, factor_count: int
) -> list[tuple[list[float], float]]:
    rows = [
        ([candidate.vega for candidate in candidates], limits.vega_budget),
        ([candidate.gamma for candidate in candidates], limits.gamma_budget),
        ([candidate.theta for candidate in candidates], limits.theta_budget),
    ]
    for index in range(factor_count):
        rows.append((column_of(candidates, index), limits.factor_tolerance))
    return rows


def clipped_to_size(weights: list[float], candidates: list[Candidate]) -> list[float]:
    return [
        min(max(weight, -candidate.maximum_size), candidate.maximum_size)
        for weight, candidate in zip(weights, candidates, strict=True)
    ]


def projected_onto_slab(weights: list[float], direction: list[float], bound: float) -> list[float]:
    exposure = weighted_total(weights, direction)
    if abs(exposure) <= bound:
        return weights
    squared = weighted_total(direction, direction)
    if squared < MINIMUM_DIRECTION_NORM:
        return weights
    target = bound if exposure > 0.0 else -bound
    scale = (exposure - target) / squared
    return [weight - scale * component for weight, component in zip(weights, direction, strict=True)]


def projected(
    weights: list[float], candidates: list[Candidate], rows: list[tuple[list[float], float]]
) -> list[float]:
    current = clipped_to_size(weights, candidates)
    for _ in range(PROJECTION_PASSES):
        for direction, bound in rows:
            current = projected_onto_slab(current, direction, bound)
        current = clipped_to_size(current, candidates)
    return current


def hedging_cost_slope(gamma: float, limits: PortfolioLimits) -> float:
    step = GAMMA_DERIVATIVE_STEP
    above = hedging_cost_of_gamma(gamma + step, limits)
    below = hedging_cost_of_gamma(gamma - step, limits)
    return (above - below) / (2.0 * step)


def subgradient_of(raw: float, weight: float, spread_cost: float) -> float:
    if weight > 0.0:
        return raw - spread_cost
    if weight < 0.0:
        return raw + spread_cost
    if raw > spread_cost:
        return raw - spread_cost
    if raw < -spread_cost:
        return raw + spread_cost
    return 0.0


def ascent_direction(
    weights: list[float], candidates: list[Candidate], limits: PortfolioLimits, charge_hedging: bool
) -> list[float]:
    slope = 0.0
    if charge_hedging:
        net_gamma = weighted_total(weights, [candidate.gamma for candidate in candidates])
        slope = hedging_cost_slope(net_gamma, limits)
    gradient = []
    for weight, candidate in zip(weights, candidates, strict=True):
        raw = candidate.expected_edge - slope * candidate.gamma
        gradient.append(subgradient_of(raw, weight, candidate.spread_cost))
    return gradient


def scale_of(candidates: list[Candidate]) -> float:
    largest = 0.0
    for candidate in candidates:
        largest = max(largest, candidate.maximum_size)
    return largest if largest > 0.0 else 1.0


def report(
    weights: list[float], candidates: list[Candidate], limits: PortfolioLimits, charge_hedging: bool
) -> Allocation:
    edge = weighted_total(weights, [candidate.expected_edge for candidate in candidates])
    spread = 0.0
    for weight, candidate in zip(weights, candidates, strict=True):
        spread += abs(weight) * candidate.spread_cost
    net_gamma = weighted_total(weights, [candidate.gamma for candidate in candidates])
    hedging = hedging_cost_of_gamma(net_gamma, limits)
    worst = 0.0
    for index in range(len(candidates[0].factor_exposures)):
        worst = max(worst, abs(weighted_total(weights, column_of(candidates, index))))
    return Allocation(
        weights=weights,
        expected_edge=edge,
        spread_cost=spread,
        hedging_cost=hedging,
        objective=edge - spread - hedging,
        net_vega=weighted_total(weights, [candidate.vega for candidate in candidates]),
        net_gamma=net_gamma,
        net_theta=weighted_total(weights, [candidate.theta for candidate in candidates]),
        worst_factor_exposure=worst,
        charged_for_hedging=charge_hedging,
    )


def allocate(candidates: list[Candidate], limits: PortfolioLimits, charge_hedging: bool = True) -> Allocation:
    factor_count = validate_candidates(candidates)
    validate_limits(limits)

    rows = constraint_rows(candidates, limits, factor_count)
    step = STEP_SIZE * scale_of(candidates)
    weights = projected([0.0] * len(candidates), candidates, rows)
    for _ in range(ASCENT_PASSES):
        gradient = ascent_direction(weights, candidates, limits, charge_hedging)
        norm = math.sqrt(max(weighted_total(gradient, gradient), 0.0))
        if norm < MINIMUM_DIRECTION_NORM:
            break
        moved = [
            weight + step * component / norm for weight, component in zip(weights, gradient, strict=True)
        ]
        weights = projected(moved, candidates, rows)
    return report(weights, candidates, limits, charge_hedging)
