from __future__ import annotations

import pytest
from volarb_py.portfolio import (
    Allocation,
    Candidate,
    InvalidPortfolioInputsError,
    PortfolioLimits,
    allocate,
    hedging_cost_of_gamma,
    report,
)

CANDIDATES = [
    Candidate(edge, vega, gamma, theta, [first, second], 10.0, spread)
    for edge, vega, gamma, theta, first, second, spread in (
        (1.00, 0.20, 0.010, -0.05, 0.9, 0.2, 0.10),
        (1.05, 0.22, 0.070, -0.30, 0.8, -0.3, 0.12),
        (0.95, 0.18, 0.008, -0.04, -0.7, 0.5, 0.09),
        (1.10, 0.25, 0.090, -0.40, -0.9, -0.1, 0.15),
        (0.90, 0.15, 0.006, -0.03, 0.4, 0.8, 0.08),
        (1.02, 0.21, 0.055, -0.25, 0.1, -0.9, 0.11),
        (0.98, 0.19, 0.012, -0.06, -0.2, 0.7, 0.10),
        (1.08, 0.24, 0.080, -0.35, 0.6, 0.4, 0.14),
    )
]
LIMITS = PortfolioLimits(1.0, 0.50, 2.0, 0.5, 0.10, 0.0010, 100.0, 0.20, 0.25)
TOLERANCE = 1e-9


def solved(charge_hedging: bool) -> Allocation:
    return allocate(CANDIDATES, LIMITS, charge_hedging)


def test_every_budget_and_tolerance_is_respected() -> None:
    allocation = solved(True)
    assert abs(allocation.net_vega) <= LIMITS.vega_budget + TOLERANCE
    assert abs(allocation.net_gamma) <= LIMITS.gamma_budget + TOLERANCE
    assert abs(allocation.net_theta) <= LIMITS.theta_budget + TOLERANCE
    assert allocation.worst_factor_exposure <= LIMITS.factor_tolerance + TOLERANCE
    for weight, candidate in zip(allocation.weights, CANDIDATES, strict=True):
        assert abs(weight) <= candidate.maximum_size + TOLERANCE


def test_solving_jointly_beats_solving_separately() -> None:
    joint = solved(True)
    charged = report(solved(False).weights, CANDIDATES, LIMITS, True)
    assert joint.objective > charged.objective
    assert abs(joint.net_gamma) < abs(charged.net_gamma)
    assert joint.hedging_cost < charged.hedging_cost


def test_the_gamma_budget_is_not_what_controls_gamma() -> None:
    joint = solved(True)
    charged = report(solved(False).weights, CANDIDATES, LIMITS, True)
    assert abs(charged.net_gamma) < LIMITS.gamma_budget
    assert abs(joint.net_gamma) < abs(charged.net_gamma)


def test_the_hedging_cost_is_even_in_gamma_and_grows_with_it() -> None:
    assert hedging_cost_of_gamma(0.0, LIMITS) == 0.0
    assert hedging_cost_of_gamma(0.05, LIMITS) > hedging_cost_of_gamma(0.02, LIMITS)
    assert hedging_cost_of_gamma(-0.05, LIMITS) == pytest.approx(hedging_cost_of_gamma(0.05, LIMITS))


def test_a_free_market_allocates_the_same_either_way() -> None:
    free_market = PortfolioLimits(1.0, 0.50, 2.0, 0.5, 0.10, 0.0, 100.0, 0.20, 0.25)
    assert hedging_cost_of_gamma(0.05, free_market) == 0.0
    joint = allocate(CANDIDATES, free_market, True)
    naive = allocate(CANDIDATES, free_market, False)
    assert joint.objective == pytest.approx(naive.objective, rel=1e-12)


def test_a_zero_budget_forces_the_exposure_to_zero() -> None:
    tight = PortfolioLimits(0.0, 0.50, 2.0, 0.5, 0.10, 0.0010, 100.0, 0.20, 0.25)
    assert abs(allocate(CANDIDATES, tight, True).net_vega) < TOLERANCE


def test_candidates_with_no_edge_are_not_traded() -> None:
    flat = [
        Candidate(0.0, c.vega, c.gamma, c.theta, c.factor_exposures, c.maximum_size, c.spread_cost)
        for c in CANDIDATES
    ]
    allocation = allocate(flat, LIMITS, True)
    assert max(abs(weight) for weight in allocation.weights) < TOLERANCE
    assert allocation.objective == pytest.approx(0.0, abs=TOLERANCE)


def test_an_edge_below_its_own_spread_is_not_traded() -> None:
    marginal = [Candidate(0.05, 0.20, 0.010, -0.05, [0.0, 0.0], 10.0, 0.10)]
    assert abs(allocate(marginal, LIMITS, True).weights[0]) < TOLERANCE

    worthwhile = [Candidate(0.50, 0.20, 0.010, -0.05, [0.0, 0.0], 10.0, 0.10)]
    assert abs(allocate(worthwhile, LIMITS, True).weights[0]) > TOLERANCE


def test_the_allocation_is_deterministic() -> None:
    assert solved(True) == solved(True)


def test_malformed_portfolio_inputs_are_rejected() -> None:
    with pytest.raises(InvalidPortfolioInputsError):
        allocate([], LIMITS, True)

    ragged = [*CANDIDATES[:1], Candidate(1.0, 0.2, 0.01, -0.05, [0.1], 10.0, 0.1)]
    with pytest.raises(InvalidPortfolioInputsError):
        allocate(ragged, LIMITS, True)

    negative = [Candidate(1.0, 0.2, 0.01, -0.05, [0.1, 0.2], -1.0, 0.1)]
    with pytest.raises(InvalidPortfolioInputsError):
        allocate(negative, LIMITS, True)

    for broken in (
        PortfolioLimits(-1.0, 0.5, 2.0, 0.5, 0.10, 0.001, 100.0, 0.20, 0.25),
        PortfolioLimits(1.0, 0.5, 2.0, 0.5, 0.0, 0.001, 100.0, 0.20, 0.25),
        PortfolioLimits(1.0, 0.5, 2.0, 0.5, 0.10, 0.001, 0.0, 0.20, 0.25),
        PortfolioLimits(1.0, 0.5, 2.0, 0.5, 0.10, 0.001, 100.0, 0.0, 0.25),
        PortfolioLimits(1.0, 0.5, 2.0, 0.5, 0.10, 0.001, 100.0, 0.20, 0.0),
        PortfolioLimits(1.0, 0.5, 2.0, 0.5, 0.10, -0.001, 100.0, 0.20, 0.25),
    ):
        with pytest.raises(InvalidPortfolioInputsError):
            allocate(CANDIDATES, broken, True)
