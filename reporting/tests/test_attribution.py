from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from attribution import (
    InvalidAttributionInputsError,
    MarketState,
    PositionLeg,
    attribute_position,
    log_variance_changes,
    split_vega_by_factor,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python_pure" / "src"))

from volarb_py.factors import FactorLoadings, orthonormal_basis

BASE = MarketState(forward=100.0, volatility=0.20, years_to_expiry=0.25, discount_factor=0.99)
LOTS = 10
MULTIPLIER = 100
CALL = [PositionLeg(strike=100.0, option_type="call", quantity=LOTS, contract_multiplier=MULTIPLIER)]
TRADING_DAY = 1.0 / 252
EXACT_LINEARITY = 1e-10
SMALL_MOVE_SHARE = 0.01
LARGE_MOVE_SHARE = 0.10


def test_price_is_exactly_linear_in_the_discount_factor() -> None:
    later = MarketState(BASE.forward, BASE.volatility, BASE.years_to_expiry, 0.9902)
    attribution = attribute_position(CALL, BASE, later)
    assert attribution.discount_pnl == pytest.approx(attribution.total_pnl, abs=EXACT_LINEARITY)
    assert abs(attribution.unexplained_pnl) < EXACT_LINEARITY


def test_each_greek_explains_its_own_variable() -> None:
    forward_only = attribute_position(CALL, BASE, MarketState(100.5, 0.20, 0.25, 0.99))
    assert forward_only.total_pnl == pytest.approx(forward_only.delta_pnl + forward_only.gamma_pnl, rel=1e-4)

    volatility_only = attribute_position(CALL, BASE, MarketState(100.0, 0.21, 0.25, 0.99))
    assert volatility_only.total_pnl == pytest.approx(volatility_only.vega_pnl, rel=1e-3)

    time_only = attribute_position(CALL, BASE, MarketState(100.0, 0.20, 0.25 - TRADING_DAY, 0.99))
    assert time_only.total_pnl == pytest.approx(time_only.theta_pnl, rel=1e-2)


def test_the_residual_grows_with_the_size_of_the_move() -> None:
    shares = []
    for move in (0.01, 0.05, 0.20):
        later = MarketState(100.0 * (1.0 + move), 0.21, 0.25 - TRADING_DAY, 0.9902)
        shares.append(attribute_position(CALL, BASE, later).unexplained_share)
    assert shares[0] < SMALL_MOVE_SHARE
    assert shares[-1] > LARGE_MOVE_SHARE
    assert shares == sorted(shares)


def test_the_residual_of_a_combined_move_is_mostly_cross_terms() -> None:
    later = MarketState(100.5, 0.21, 0.25 - TRADING_DAY, 0.9902)
    combined = attribute_position(CALL, BASE, later).unexplained_pnl
    isolated = sum(
        attribute_position(CALL, BASE, state).unexplained_pnl
        for state in (
            MarketState(100.5, 0.20, 0.25, 0.99),
            MarketState(100.0, 0.21, 0.25, 0.99),
            MarketState(100.0, 0.20, 0.25 - TRADING_DAY, 0.99),
            MarketState(100.0, 0.20, 0.25, 0.9902),
        )
    )
    assert abs(combined - isolated) > abs(isolated)


def test_a_position_with_no_move_has_no_profit_and_no_residual() -> None:
    attribution = attribute_position(CALL, BASE, BASE)
    assert attribution.total_pnl == 0.0
    assert attribution.explained_pnl == 0.0
    assert attribution.unexplained_pnl == 0.0


def test_reversing_the_position_reverses_every_term() -> None:
    later = MarketState(100.5, 0.21, 0.25 - TRADING_DAY, 0.99)
    long_side = attribute_position(CALL, BASE, later)
    short_side = attribute_position([PositionLeg(100.0, "call", -LOTS, MULTIPLIER)], BASE, later)
    assert short_side.total_pnl == pytest.approx(-long_side.total_pnl)
    assert short_side.vega_pnl == pytest.approx(-long_side.vega_pnl)
    assert short_side.theta_pnl == pytest.approx(-long_side.theta_pnl)


def test_the_vega_split_accounts_for_the_whole_vega_profit() -> None:
    split = split_vega_by_factor(-82.05, 0.1942, [-0.3, -0.04, 0.0, 0.001], 0.16)
    assert split.explained_vega_pnl == pytest.approx(-82.05, rel=1e-12)
    assert 0.0 <= split.residual_share <= 1.0


def test_a_residual_bet_can_be_right_and_still_lose_to_the_factors() -> None:
    split = split_vega_by_factor(-82.05, 0.1942, [-0.3, -0.04, 0.0, 0.001], 0.16)
    assert split.residual_pnl > 0.0
    assert split.factor_pnl[0] < 0.0
    assert split.explained_vega_pnl < 0.0


def test_a_surface_that_did_not_move_splits_into_nothing() -> None:
    split = split_vega_by_factor(0.0, 0.20, [0.0, 0.0, 0.0, 0.0], 0.0)
    assert split.residual_pnl == 0.0
    assert split.residual_share == 0.0
    assert split.factor_pnl == [0.0, 0.0, 0.0, 0.0]


def test_log_variance_changes_follow_the_loadings() -> None:
    basis = orthonormal_basis([[1.0, 1.0, 1.0, 1.0], [0.0, 1.0, 2.0, 3.0]])
    earlier = FactorLoadings(level=1.0, term_slope=2.0, skew=0.0, curvature=0.0)
    later = FactorLoadings(level=1.5, term_slope=2.0, skew=0.0, curvature=0.0)
    changes = log_variance_changes(basis, earlier, later, 0)
    assert changes[0] == pytest.approx(0.5 * basis[0][0])
    assert changes[1] == pytest.approx(0.0)


def test_malformed_attribution_inputs_are_rejected() -> None:
    with pytest.raises(InvalidAttributionInputsError):
        attribute_position([], BASE, BASE)
    with pytest.raises(InvalidAttributionInputsError):
        attribute_position(CALL, BASE, MarketState(100.0, 0.2, 0.30, 0.99))
    with pytest.raises(InvalidAttributionInputsError):
        attribute_position(CALL, MarketState(-1.0, 0.2, 0.25, 0.99), BASE)
    with pytest.raises(InvalidAttributionInputsError):
        split_vega_by_factor(1.0, 0.0, [0.1], 0.1)
    with pytest.raises(InvalidAttributionInputsError):
        log_variance_changes([[1.0, 1.0]], FactorLoadings(1, 0, 0, 0), FactorLoadings(2, 0, 0, 0), 9)


def test_the_attribution_uses_the_documented_theta_sign() -> None:
    later = MarketState(100.0, 0.20, 0.25 - TRADING_DAY, 0.99)
    attribution = attribute_position(CALL, BASE, later)
    assert attribution.theta_pnl < 0.0
    assert attribution.total_pnl < 0.0
    assert math.isclose(attribution.theta_pnl, attribution.total_pnl, rel_tol=1e-2)
