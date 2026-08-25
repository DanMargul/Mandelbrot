from __future__ import annotations

import math

import pytest
from volarb_py.implied_correlation import (
    PERFECT_CORRELATION,
    BasketConstituent,
    InvalidBasketError,
    basket_volatility,
    dispersion_vega_weights,
    imply_correlation,
    index_sensitivities,
    lowest_admissible_correlation,
    moments_of,
)

PLANTED_CORRELATION = 0.42
IDENTITY_TOLERANCE = 1e-12
DERIVATIVE_STEP = 1e-7
DERIVATIVE_TOLERANCE = 1e-7
INDEX_VEGA = 250.0
SMALL_BASKET = 3
LARGE_BASKET = 40
BASE_VOLATILITY = 0.18
VOLATILITY_SPREAD = 0.01
VOLATILITY_TIERS = 10
IMPOSSIBLE_MULTIPLE = 1.05
TWO_NAME_FLOOR = -1.0
THREE_NAME_FLOOR = -0.5
INDEX_LIKE_BASKET = 500
SWEEP_CORRELATIONS = (-0.2, 0.0, 0.25, 0.5, 0.75, 0.99)


def even_basket(count: int) -> list[BasketConstituent]:
    return [
        BasketConstituent(
            f"N{index}", 1.0 / count, BASE_VOLATILITY + VOLATILITY_SPREAD * (index % VOLATILITY_TIERS)
        )
        for index in range(count)
    ]


def concentrated_basket() -> list[BasketConstituent]:
    return [
        BasketConstituent("HEAVY", 0.70, 0.30),
        BasketConstituent("LIGHT_A", 0.20, 0.25),
        BasketConstituent("LIGHT_B", 0.10, 0.35),
    ]


def naive_basket_volatility(constituents: list[BasketConstituent], correlation: float) -> float:
    total = 0.0
    for row, first in enumerate(constituents):
        for column, second in enumerate(constituents):
            entry = PERFECT_CORRELATION if row == column else correlation
            total += first.weight * second.weight * first.volatility * second.volatility * entry
    return math.sqrt(total)


@pytest.mark.parametrize("count", [2, 3, 8, LARGE_BASKET])
def test_the_two_sum_form_agrees_with_the_full_quadratic_form(count: int) -> None:
    basket = even_basket(count)
    assert basket_volatility(basket, PLANTED_CORRELATION) == pytest.approx(
        naive_basket_volatility(basket, PLANTED_CORRELATION), abs=IDENTITY_TOLERANCE
    )


@pytest.mark.parametrize("correlation", SWEEP_CORRELATIONS)
def test_a_basket_built_at_a_correlation_implies_that_correlation_back(correlation: float) -> None:
    basket = concentrated_basket()
    index = basket_volatility(basket, correlation)
    assert imply_correlation(basket, index).clean_correlation == pytest.approx(
        correlation, abs=IDENTITY_TOLERANCE
    )


@pytest.mark.parametrize("correlation", SWEEP_CORRELATIONS)
def test_dropping_the_diagonal_overstates_by_exactly_the_concentration_times_the_gap(
    correlation: float,
) -> None:
    basket = concentrated_basket()
    report = imply_correlation(basket, basket_volatility(basket, correlation))
    predicted = moments_of(basket).concentration * (PERFECT_CORRELATION - report.clean_correlation)
    assert report.diagonal_bias == pytest.approx(predicted, abs=IDENTITY_TOLERANCE)
    assert report.dirty_correlation - report.clean_correlation == pytest.approx(
        predicted, abs=IDENTITY_TOLERANCE
    )


def test_the_diagonal_bias_is_always_upward_below_perfect_correlation() -> None:
    basket = concentrated_basket()
    for correlation in SWEEP_CORRELATIONS:
        report = imply_correlation(basket, basket_volatility(basket, correlation))
        assert report.dirty_correlation > report.clean_correlation


def test_the_bias_vanishes_only_at_perfect_correlation() -> None:
    basket = concentrated_basket()
    report = imply_correlation(basket, moments_of(basket).weighted_volatility)
    assert report.diagonal_bias == pytest.approx(0.0, abs=IDENTITY_TOLERANCE)


def test_the_bias_falls_as_the_basket_spreads_out() -> None:
    biases = []
    for count in (SMALL_BASKET, 8, LARGE_BASKET, INDEX_LIKE_BASKET):
        basket = even_basket(count)
        biases.append(imply_correlation(basket, basket_volatility(basket, PLANTED_CORRELATION)).diagonal_bias)
    assert biases == sorted(biases, reverse=True)


def test_concentration_is_what_drives_the_bias_not_the_name_count() -> None:
    spread = even_basket(SMALL_BASKET)
    concentrated = concentrated_basket()
    assert len(spread) == len(concentrated)
    assert moments_of(concentrated).concentration > moments_of(spread).concentration
    spread_report = imply_correlation(spread, basket_volatility(spread, PLANTED_CORRELATION))
    concentrated_report = imply_correlation(
        concentrated, basket_volatility(concentrated, PLANTED_CORRELATION)
    )
    assert concentrated_report.diagonal_bias > spread_report.diagonal_bias


def test_a_perfectly_correlated_basket_is_worth_its_weighted_volatility() -> None:
    basket = concentrated_basket()
    weighted = moments_of(basket).weighted_volatility
    assert basket_volatility(basket, PERFECT_CORRELATION) == pytest.approx(weighted, abs=IDENTITY_TOLERANCE)
    assert imply_correlation(basket, weighted).clean_correlation == pytest.approx(
        PERFECT_CORRELATION, abs=IDENTITY_TOLERANCE
    )


def test_an_index_above_its_weighted_volatility_implies_more_than_perfect_correlation() -> None:
    basket = concentrated_basket()
    report = imply_correlation(basket, moments_of(basket).weighted_volatility * IMPOSSIBLE_MULTIPLE)
    assert report.exceeds_perfect_correlation
    assert not report.is_admissible


def test_the_admissible_floor_tightens_towards_zero_as_the_basket_grows() -> None:
    assert lowest_admissible_correlation(2) == pytest.approx(TWO_NAME_FLOOR)
    assert lowest_admissible_correlation(SMALL_BASKET) == pytest.approx(THREE_NAME_FLOOR)
    assert lowest_admissible_correlation(INDEX_LIKE_BASKET) > lowest_admissible_correlation(SMALL_BASKET)


def test_the_sensitivities_satisfy_the_euler_identity() -> None:
    basket = even_basket(9)
    sensitivities = index_sensitivities(basket, PLANTED_CORRELATION)
    total = 0.0
    for constituent, sensitivity in zip(basket, sensitivities, strict=True):
        total += constituent.volatility * sensitivity
    assert total == pytest.approx(basket_volatility(basket, PLANTED_CORRELATION), abs=IDENTITY_TOLERANCE)


def test_each_sensitivity_is_the_derivative_it_claims_to_be() -> None:
    basket = concentrated_basket()
    sensitivities = index_sensitivities(basket, PLANTED_CORRELATION)
    for index, sensitivity in enumerate(sensitivities):
        raised = list(basket)
        lowered = list(basket)
        moved = basket[index]
        raised[index] = BasketConstituent(moved.symbol, moved.weight, moved.volatility + DERIVATIVE_STEP)
        lowered[index] = BasketConstituent(moved.symbol, moved.weight, moved.volatility - DERIVATIVE_STEP)
        numeric = (
            basket_volatility(raised, PLANTED_CORRELATION) - basket_volatility(lowered, PLANTED_CORRELATION)
        ) / (2.0 * DERIVATIVE_STEP)
        assert sensitivity == pytest.approx(numeric, abs=DERIVATIVE_TOLERANCE)


def test_every_sensitivity_is_positive_because_more_constituent_vol_is_more_index_vol() -> None:
    for sensitivity in index_sensitivities(concentrated_basket(), PLANTED_CORRELATION):
        assert sensitivity > 0.0


def test_dispersion_weights_are_the_sensitivities_scaled_by_the_index_vega() -> None:
    basket = concentrated_basket()
    sensitivities = index_sensitivities(basket, PLANTED_CORRELATION)
    weights = dispersion_vega_weights(basket, PLANTED_CORRELATION, INDEX_VEGA)
    for weight, sensitivity in zip(weights, sensitivities, strict=True):
        assert weight == pytest.approx(INDEX_VEGA * sensitivity, abs=IDENTITY_TOLERANCE)


def test_the_dispersion_book_carries_less_constituent_vega_than_the_index_leg() -> None:
    weights = dispersion_vega_weights(even_basket(LARGE_BASKET), PLANTED_CORRELATION, INDEX_VEGA)
    assert sum(weights) < INDEX_VEGA


def test_a_basket_that_does_not_add_to_one_is_rejected() -> None:
    with pytest.raises(InvalidBasketError):
        imply_correlation([BasketConstituent("A", 0.4, 0.2), BasketConstituent("B", 0.4, 0.2)], 0.2)


def test_a_single_name_basket_is_rejected() -> None:
    with pytest.raises(InvalidBasketError):
        imply_correlation([BasketConstituent("A", 1.0, 0.2)], 0.2)


@pytest.mark.parametrize(
    "broken",
    [
        [BasketConstituent("A", -0.5, 0.2), BasketConstituent("B", 1.5, 0.2)],
        [BasketConstituent("A", 0.5, -0.2), BasketConstituent("B", 0.5, 0.2)],
        [BasketConstituent("A", 0.5, 0.0), BasketConstituent("B", 0.5, 0.2)],
    ],
)
def test_a_malformed_constituent_is_rejected(broken: list[BasketConstituent]) -> None:
    with pytest.raises(InvalidBasketError):
        imply_correlation(broken, 0.2)


@pytest.mark.parametrize("correlation", [-0.9, 1.1])
def test_a_correlation_outside_the_admissible_range_cannot_price_a_basket(correlation: float) -> None:
    with pytest.raises(InvalidBasketError):
        basket_volatility(concentrated_basket(), correlation)


def test_a_zero_index_volatility_is_rejected_rather_than_implied_from() -> None:
    with pytest.raises(InvalidBasketError):
        imply_correlation(concentrated_basket(), 0.0)
