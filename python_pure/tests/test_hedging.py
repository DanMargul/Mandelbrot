from __future__ import annotations

import pytest
from volarb_py.hedging import (
    BandPolicy,
    HedgingInputs,
    InvalidHedgingInputsError,
    hedging_statistics,
    whalley_wilmott_band,
)

BASE = HedgingInputs(
    spot=100.0,
    strike=100.0,
    years_to_expiry=0.25,
    volatility=0.20,
    steps=63,
    proportional_cost=0.0010,
    risk_aversion=0.10,
)
PATHS = 400
WIDTHS = (0.0, 0.05, 0.10, 0.20, 0.40)
TUNING_GRID = (0.0, 0.05, 0.10, 0.20, 0.30, 0.50)
HELD_OUT_SEQUENCES = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
SURVIVING_EDGE_FRACTION = 5.0
REPLICATION_PROFIT = 0.1
REPLICATION_SPREAD = 0.3


def run(policy: BandPolicy, sequence: int) -> object:
    return hedging_statistics(BASE, policy, 1, sequence, PATHS)


def test_the_band_scales_as_the_cube_root_of_cost_and_gamma_squared() -> None:
    base = whalley_wilmott_band(100.0, 0.04, 0.001, 0.1)
    assert whalley_wilmott_band(100.0, 0.04, 0.008, 0.1) == pytest.approx(2.0 * base, rel=1e-12)
    assert whalley_wilmott_band(100.0, 0.32, 0.001, 0.1) == pytest.approx(4.0 * base, rel=1e-12)
    assert whalley_wilmott_band(100.0, 0.04, 0.001, 0.8) == pytest.approx(0.5 * base, rel=1e-12)
    assert whalley_wilmott_band(100.0, 0.0, 0.001, 0.1) == 0.0


def test_a_wider_band_trades_less_and_pays_less() -> None:
    costs = [run(BandPolicy("fixed", width), 1).mean_transaction_cost for width in WIDTHS]
    counts = [run(BandPolicy("fixed", width), 1).mean_rebalance_count for width in WIDTHS]
    assert costs == sorted(costs, reverse=True)
    assert counts == sorted(counts, reverse=True)


def test_a_wider_band_carries_more_risk() -> None:
    spreads = [run(BandPolicy("fixed", width), 1).profit_standard_deviation for width in WIDTHS]
    assert spreads == sorted(spreads)


def test_hedging_with_no_cost_and_no_band_replicates_the_option() -> None:
    inputs = HedgingInputs(100.0, 100.0, 0.25, 0.20, 252, 0.0, 0.10)
    stats = hedging_statistics(inputs, BandPolicy("fixed", 0.0), 1, 1, PATHS)
    assert stats.mean_transaction_cost == 0.0
    assert abs(stats.mean_profit) < REPLICATION_PROFIT
    assert stats.profit_standard_deviation < REPLICATION_SPREAD


def test_the_same_seed_reproduces_the_same_statistics() -> None:
    one = run(BandPolicy("whalley_wilmott", 0.0), 1)
    other = run(BandPolicy("whalley_wilmott", 0.0), 1)
    assert one == other
    assert run(BandPolicy("whalley_wilmott", 0.0), 2) != one


def test_the_certainty_equivalent_is_the_mean_penalised_by_variance() -> None:
    stats = run(BandPolicy("fixed", 0.10), 1)
    variance = stats.profit_standard_deviation**2
    assert stats.certainty_equivalent == pytest.approx(
        stats.mean_profit - 0.5 * BASE.risk_aversion * variance, rel=1e-12
    )
    assert stats.certainty_equivalent < stats.mean_profit


def tuned_fixed_width() -> float:
    return max(TUNING_GRID, key=lambda width: run(BandPolicy("fixed", width), 1).certainty_equivalent)


def test_a_tuned_fixed_band_wins_in_sample() -> None:
    tuned = tuned_fixed_width()
    assert (
        run(BandPolicy("fixed", tuned), 1).certainty_equivalent
        > run(BandPolicy("whalley_wilmott", 0.0), 1).certainty_equivalent
    )


def test_a_tuned_fixed_band_degrades_on_every_held_out_set() -> None:
    tuned = tuned_fixed_width()
    in_sample = run(BandPolicy("fixed", tuned), 1).certainty_equivalent
    for sequence in HELD_OUT_SEQUENCES:
        assert run(BandPolicy("fixed", tuned), sequence).certainty_equivalent < in_sample


def test_the_tuned_advantage_does_not_survive_out_of_sample() -> None:
    tuned = tuned_fixed_width()
    in_sample_edge = (
        run(BandPolicy("fixed", tuned), 1).certainty_equivalent
        - run(BandPolicy("whalley_wilmott", 0.0), 1).certainty_equivalent
    )
    held_out_edges = [
        run(BandPolicy("fixed", tuned), sequence).certainty_equivalent
        - run(BandPolicy("whalley_wilmott", 0.0), sequence).certainty_equivalent
        for sequence in HELD_OUT_SEQUENCES
    ]
    mean_edge = sum(held_out_edges) / len(held_out_edges)
    assert in_sample_edge > 0.0
    assert mean_edge < in_sample_edge / SURVIVING_EDGE_FRACTION


def test_malformed_hedging_inputs_are_rejected() -> None:
    policy = BandPolicy("fixed", 0.1)
    for broken in (
        HedgingInputs(-1.0, 100.0, 0.25, 0.20, 63, 0.001, 0.10),
        HedgingInputs(100.0, 0.0, 0.25, 0.20, 63, 0.001, 0.10),
        HedgingInputs(100.0, 100.0, 0.0, 0.20, 63, 0.001, 0.10),
        HedgingInputs(100.0, 100.0, 0.25, 0.0, 63, 0.001, 0.10),
        HedgingInputs(100.0, 100.0, 0.25, 0.20, 0, 0.001, 0.10),
        HedgingInputs(100.0, 100.0, 0.25, 0.20, 63, -0.001, 0.10),
        HedgingInputs(100.0, 100.0, 0.25, 0.20, 63, 0.001, 0.0),
    ):
        with pytest.raises(InvalidHedgingInputsError):
            hedging_statistics(broken, policy, 1, 1, PATHS)

    with pytest.raises(InvalidHedgingInputsError):
        hedging_statistics(BASE, BandPolicy("fixed", -1.0), 1, 1, PATHS)
    with pytest.raises(InvalidHedgingInputsError):
        hedging_statistics(BASE, policy, 1, 1, 1)
