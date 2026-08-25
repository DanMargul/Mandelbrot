from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.factors import FactorLoadings  # noqa: E402
from volarb_py.pricing import (  # noqa: E402
    BlackScholesInputs,
    OptionType,
    black_scholes_price_and_greeks,
)

MINIMUM_ABSOLUTE_PNL: Final[float] = 1e-12
MINIMUM_VOLATILITY: Final[float] = 1e-12
HALF: Final[float] = 0.5


class InvalidAttributionInputsError(ValueError):
    pass


@dataclass(frozen=True)
class MarketState:
    forward: float
    volatility: float
    years_to_expiry: float
    discount_factor: float


@dataclass(frozen=True)
class PositionLeg:
    strike: float
    option_type: OptionType
    quantity: int
    contract_multiplier: int


@dataclass(frozen=True)
class GreekAttribution:
    total_pnl: float
    delta_pnl: float
    gamma_pnl: float
    vega_pnl: float
    theta_pnl: float
    discount_pnl: float
    explained_pnl: float
    unexplained_pnl: float
    unexplained_share: float


@dataclass(frozen=True)
class VegaSplit:
    factor_pnl: list[float]
    residual_pnl: float
    explained_vega_pnl: float
    residual_share: float


def validate_state(state: MarketState) -> None:
    if state.forward <= 0.0:
        raise InvalidAttributionInputsError(f"forward must be positive, got {state.forward}")
    if state.volatility <= 0.0:
        raise InvalidAttributionInputsError(f"volatility must be positive, got {state.volatility}")
    if state.years_to_expiry <= 0.0:
        raise InvalidAttributionInputsError(f"years_to_expiry must be positive, got {state.years_to_expiry}")
    if state.discount_factor <= 0.0:
        raise InvalidAttributionInputsError(f"discount_factor must be positive, got {state.discount_factor}")


def validate_transition(earlier: MarketState, later: MarketState) -> None:
    validate_state(earlier)
    validate_state(later)
    if later.years_to_expiry > earlier.years_to_expiry:
        raise InvalidAttributionInputsError("time cannot run backwards between two states")


def inputs_for(leg: PositionLeg, state: MarketState) -> BlackScholesInputs:
    return BlackScholesInputs(
        forward=state.forward,
        strike=leg.strike,
        years_to_expiry=state.years_to_expiry,
        volatility=state.volatility,
        discount_factor=state.discount_factor,
        option_type=leg.option_type,
    )


def signed_size(leg: PositionLeg) -> float:
    return float(leg.quantity) * float(leg.contract_multiplier)


def attribute_position(legs: list[PositionLeg], earlier: MarketState, later: MarketState) -> GreekAttribution:
    if not legs:
        raise InvalidAttributionInputsError("a position needs at least one leg")
    validate_transition(earlier, later)

    forward_move = later.forward - earlier.forward
    volatility_move = later.volatility - earlier.volatility
    elapsed = earlier.years_to_expiry - later.years_to_expiry
    discount_move = later.discount_factor - earlier.discount_factor

    total = 0.0
    delta_pnl = 0.0
    gamma_pnl = 0.0
    vega_pnl = 0.0
    theta_pnl = 0.0
    discount_pnl = 0.0
    for leg in legs:
        size = signed_size(leg)
        opening = black_scholes_price_and_greeks(inputs_for(leg, earlier))
        closing = black_scholes_price_and_greeks(inputs_for(leg, later))
        total += size * (closing.price - opening.price)
        delta_pnl += size * opening.delta_with_respect_to_forward * forward_move
        gamma_pnl += size * HALF * opening.gamma_with_respect_to_forward * forward_move * forward_move
        vega_pnl += size * opening.vega_with_respect_to_volatility * volatility_move
        theta_pnl += size * opening.theta_with_respect_to_time * elapsed
        discount_pnl += size * (opening.price / earlier.discount_factor) * discount_move

    explained = delta_pnl + gamma_pnl + vega_pnl + theta_pnl + discount_pnl
    unexplained = total - explained
    scale = max(abs(total), MINIMUM_ABSOLUTE_PNL)
    return GreekAttribution(
        total_pnl=total,
        delta_pnl=delta_pnl,
        gamma_pnl=gamma_pnl,
        vega_pnl=vega_pnl,
        theta_pnl=theta_pnl,
        discount_pnl=discount_pnl,
        explained_pnl=explained,
        unexplained_pnl=unexplained,
        unexplained_share=abs(unexplained) / scale,
    )


def loading_values(loadings: FactorLoadings) -> list[float]:
    return [loadings.level, loadings.term_slope, loadings.skew, loadings.curvature]


def log_variance_changes(
    basis: list[list[float]],
    earlier: FactorLoadings,
    later: FactorLoadings,
    grid_index: int,
) -> list[float]:
    if grid_index < 0 or grid_index >= len(basis[0]):
        raise InvalidAttributionInputsError(f"grid_index {grid_index} is outside the basis")
    before = loading_values(earlier)
    after = loading_values(later)
    return [(after[which] - before[which]) * vector[grid_index] for which, vector in enumerate(basis)]


def split_vega_by_factor(
    vega_pnl: float,
    volatility: float,
    factor_log_variance_changes: list[float],
    residual_log_variance_change: float,
) -> VegaSplit:
    if volatility <= 0.0:
        raise InvalidAttributionInputsError(f"volatility must be positive, got {volatility}")
    total_change = sum(factor_log_variance_changes) + residual_log_variance_change
    if abs(total_change) < MINIMUM_VOLATILITY:
        return VegaSplit(
            factor_pnl=[0.0] * len(factor_log_variance_changes),
            residual_pnl=0.0,
            explained_vega_pnl=0.0,
            residual_share=0.0,
        )

    per_unit = vega_pnl / total_change
    factor_pnl = [per_unit * change for change in factor_log_variance_changes]
    residual_pnl = per_unit * residual_log_variance_change
    explained = sum(factor_pnl) + residual_pnl
    gross = sum(abs(value) for value in factor_pnl) + abs(residual_pnl)
    return VegaSplit(
        factor_pnl=factor_pnl,
        residual_pnl=residual_pnl,
        explained_vega_pnl=explained,
        residual_share=abs(residual_pnl) / max(gross, MINIMUM_ABSOLUTE_PNL),
    )
