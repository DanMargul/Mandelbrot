from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.factors import ResidualScore, SurfacePoint, score_residual  # noqa: E402
from volarb_py.portfolio import (  # noqa: E402
    Allocation,
    Candidate,
    PortfolioLimits,
    allocate,
)
from volarb_py.pricing import (  # noqa: E402
    BlackScholesGreeks,
    BlackScholesInputs,
    OptionType,
    black_scholes_price_and_greeks,
)

REVERSION_HORIZON_STEPS: Final[int] = 10
LOG_VARIANCE_TO_LOG_VOLATILITY: Final[float] = 0.5
VEGA_BUDGET_FRACTION: Final[float] = 0.25
GAMMA_BUDGET_FRACTION: Final[float] = 0.25
THETA_BUDGET_FRACTION: Final[float] = 0.25
FACTOR_TOLERANCE_FRACTION: Final[float] = 0.02
RISK_AVERSION: Final[float] = 0.10
ROUND_TRIP_CROSSINGS: Final[float] = 2.0


@dataclass(frozen=True)
class ContractState:
    contract_symbol: str
    grid_point: SurfacePoint
    forward: float
    strike: float
    discount_factor: float
    option_type: OptionType
    volatility: float
    half_spread: float
    contract_multiplier: int


@dataclass(frozen=True)
class BookSettings:
    lot_size: int
    spot: float
    factor_exposures: dict[str, list[float]]


def expected_log_variance_capture(score: ResidualScore) -> float:
    decay = score.lag_one_autocorrelation**REVERSION_HORIZON_STEPS
    deviation_now = score.naive_z_score * score.standard_deviation
    return -deviation_now * (1.0 - decay)


def greeks_of(state: ContractState) -> BlackScholesGreeks:
    return black_scholes_price_and_greeks(
        BlackScholesInputs(
            state.forward,
            state.strike,
            state.grid_point.years_to_expiry,
            state.volatility,
            state.discount_factor,
            state.option_type,
        )
    )


def candidate_for(state: ContractState, score: ResidualScore, settings: BookSettings) -> Candidate:
    greeks = greeks_of(state)
    capture = expected_log_variance_capture(score)
    volatility_change = state.volatility * LOG_VARIANCE_TO_LOG_VOLATILITY * capture
    multiplier = float(state.contract_multiplier)
    return Candidate(
        expected_edge=greeks.vega_with_respect_to_volatility * volatility_change * multiplier,
        vega=greeks.vega_with_respect_to_volatility * multiplier,
        gamma=greeks.gamma_with_respect_to_forward * multiplier,
        theta=greeks.theta_with_respect_to_time * multiplier,
        factor_exposures=settings.factor_exposures[state.contract_symbol],
        maximum_size=float(settings.lot_size),
        spread_cost=ROUND_TRIP_CROSSINGS * state.half_spread * multiplier,
    )


def absolute_total(loadings: list[float]) -> float:
    total = 0.0
    for loading in loadings:
        total += abs(loading)
    return total


def limits_for(
    candidates: list[Candidate], settings: BookSettings, states: list[ContractState]
) -> PortfolioLimits:
    lots = float(settings.lot_size)
    volatility = 0.0
    years = 0.0
    for state in states:
        volatility += state.volatility
        years += state.grid_point.years_to_expiry
    count = float(len(states))
    return PortfolioLimits(
        vega_budget=lots
        * VEGA_BUDGET_FRACTION
        * absolute_total([candidate.vega for candidate in candidates]),
        gamma_budget=lots
        * GAMMA_BUDGET_FRACTION
        * absolute_total([candidate.gamma for candidate in candidates]),
        theta_budget=lots
        * THETA_BUDGET_FRACTION
        * absolute_total([candidate.theta for candidate in candidates]),
        factor_tolerance=FACTOR_TOLERANCE_FRACTION * lots * math.sqrt(count),
        risk_aversion=RISK_AVERSION,
        proportional_cost=0.0,
        spot=settings.spot,
        volatility=volatility / count,
        years_to_expiry=years / count,
    )


EMPTY_ALLOCATION: Final[Allocation] = Allocation(
    weights=[],
    expected_edge=0.0,
    spread_cost=0.0,
    hedging_cost=0.0,
    objective=0.0,
    net_vega=0.0,
    net_gamma=0.0,
    net_theta=0.0,
    worst_factor_exposure=0.0,
    charged_for_hedging=True,
)


def allocated_book(
    states: list[ContractState], histories: dict[str, list[float]], settings: BookSettings
) -> tuple[dict[str, int], Allocation]:
    usable: list[ContractState] = []
    candidates: list[Candidate] = []
    for state in states:
        series = histories.get(state.contract_symbol, [])
        if len(series) < REVERSION_HORIZON_STEPS:
            continue
        score = score_residual(series)
        if score.residual_is_degenerate:
            continue
        usable.append(state)
        candidates.append(candidate_for(state, score, settings))
    if not candidates:
        return {}, EMPTY_ALLOCATION
    allocation = allocate(candidates, limits_for(candidates, settings, usable))
    book = {
        state.contract_symbol: round(weight)
        for state, weight in zip(usable, allocation.weights, strict=True)
        if round(weight) != 0
    }
    return book, allocation
