#include "volarb/implied_correlation.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::basket_volatility;
using volarb::BasketConstituent;
using volarb::CorrelationReport;
using volarb::dispersion_vega_weights;
using volarb::imply_correlation;
using volarb::index_sensitivities;
using volarb::InvalidBasketError;
using volarb::lowest_admissible_correlation;
using volarb::moments_of;
using volarb::perfect_correlation;

namespace {

constexpr double planted_correlation = 0.42;
constexpr double identity_tolerance = 1e-12;
constexpr double derivative_step = 1e-7;
constexpr double derivative_tolerance = 1e-7;
constexpr double index_vega = 250.0;
constexpr std::size_t volatility_tiers = 10;

std::vector<BasketConstituent> even_basket(std::size_t count) {
    std::vector<BasketConstituent> constituents;
    for (std::size_t index = 0; index < count; ++index) {
        constituents.push_back(BasketConstituent{
            "N" + std::to_string(index), 1.0 / static_cast<double>(count),
            0.18 + 0.01 * static_cast<double>(index % volatility_tiers)});
    }
    return constituents;
}

std::vector<BasketConstituent> concentrated_basket() {
    return {BasketConstituent{"HEAVY", 0.70, 0.30}, BasketConstituent{"LIGHT_A", 0.20, 0.25},
            BasketConstituent{"LIGHT_B", 0.10, 0.35}};
}

double naive_basket_volatility(const std::vector<BasketConstituent>& constituents, double correlation) {
    double total = 0.0;
    for (std::size_t row = 0; row < constituents.size(); ++row) {
        for (std::size_t column = 0; column < constituents.size(); ++column) {
            const double entry = row == column ? 1.0 : correlation;
            total += constituents[row].weight * constituents[column].weight *
                     constituents[row].volatility * constituents[column].volatility * entry;
        }
    }
    return std::sqrt(total);
}

}

TEST_CASE("the two sum form agrees with the full quadratic form") {
    for (const std::size_t count : {2u, 3u, 8u, 40u}) {
        const std::vector<BasketConstituent> basket = even_basket(count);
        REQUIRE(basket_volatility(basket, planted_correlation) ==
                Approx(naive_basket_volatility(basket, planted_correlation)).margin(identity_tolerance));
    }
}

TEST_CASE("a basket built at a correlation implies that correlation back") {
    const std::vector<BasketConstituent> basket = concentrated_basket();
    const double index = basket_volatility(basket, planted_correlation);
    REQUIRE(imply_correlation(basket, index).clean_correlation ==
            Approx(planted_correlation).margin(identity_tolerance));
}

TEST_CASE("dropping the diagonal overstates the correlation by exactly the concentration times its gap") {
    const std::vector<BasketConstituent> basket = concentrated_basket();
    const double index = basket_volatility(basket, planted_correlation);
    const CorrelationReport report = imply_correlation(basket, index);
    const double predicted =
        moments_of(basket).concentration * (perfect_correlation - report.clean_correlation);
    REQUIRE(report.diagonal_bias == Approx(predicted).margin(identity_tolerance));
    REQUIRE(report.dirty_correlation - report.clean_correlation ==
            Approx(predicted).margin(identity_tolerance));
    REQUIRE(report.dirty_correlation > report.clean_correlation);
}

TEST_CASE("the bias falls as the basket spreads out") {
    const double index_of_three = basket_volatility(even_basket(3), planted_correlation);
    const double index_of_forty = basket_volatility(even_basket(40), planted_correlation);
    REQUIRE(imply_correlation(even_basket(3), index_of_three).diagonal_bias >
            imply_correlation(even_basket(40), index_of_forty).diagonal_bias);
}

TEST_CASE("a perfectly correlated basket is worth its weighted volatility") {
    const std::vector<BasketConstituent> basket = concentrated_basket();
    const double weighted = moments_of(basket).weighted_volatility;
    REQUIRE(basket_volatility(basket, perfect_correlation) == Approx(weighted).margin(identity_tolerance));
    REQUIRE(imply_correlation(basket, weighted).clean_correlation ==
            Approx(perfect_correlation).margin(identity_tolerance));
}

TEST_CASE("an index quoted above its weighted volatility implies more than perfect correlation") {
    const std::vector<BasketConstituent> basket = concentrated_basket();
    const double impossible = moments_of(basket).weighted_volatility * 1.05;
    const CorrelationReport report = imply_correlation(basket, impossible);
    REQUIRE(report.exceeds_perfect_correlation);
    REQUIRE_FALSE(report.is_admissible);
}

TEST_CASE("the admissible floor tightens towards zero as the basket grows") {
    REQUIRE(lowest_admissible_correlation(2) == Approx(-1.0));
    REQUIRE(lowest_admissible_correlation(3) == Approx(-0.5));
    REQUIRE(lowest_admissible_correlation(500) > lowest_admissible_correlation(3));
}

TEST_CASE("the sensitivities satisfy the Euler identity because the index is homogeneous") {
    const std::vector<BasketConstituent> basket = even_basket(9);
    const std::vector<double> sensitivities = index_sensitivities(basket, planted_correlation);
    double total = 0.0;
    for (std::size_t index = 0; index < basket.size(); ++index) {
        total += basket[index].volatility * sensitivities[index];
    }
    REQUIRE(total == Approx(basket_volatility(basket, planted_correlation)).margin(identity_tolerance));
}

TEST_CASE("each sensitivity is the derivative it claims to be") {
    std::vector<BasketConstituent> basket = concentrated_basket();
    const std::vector<double> sensitivities = index_sensitivities(basket, planted_correlation);
    for (std::size_t index = 0; index < basket.size(); ++index) {
        std::vector<BasketConstituent> raised = basket;
        std::vector<BasketConstituent> lowered = basket;
        raised[index].volatility += derivative_step;
        lowered[index].volatility -= derivative_step;
        const double numeric = (basket_volatility(raised, planted_correlation) -
                                basket_volatility(lowered, planted_correlation)) /
                               (2.0 * derivative_step);
        REQUIRE(sensitivities[index] == Approx(numeric).margin(derivative_tolerance));
    }
}

TEST_CASE("dispersion weights are the sensitivities scaled by the index vega") {
    const std::vector<BasketConstituent> basket = concentrated_basket();
    const std::vector<double> sensitivities = index_sensitivities(basket, planted_correlation);
    const std::vector<double> weights = dispersion_vega_weights(basket, planted_correlation, index_vega);
    for (std::size_t index = 0; index < basket.size(); ++index) {
        REQUIRE(weights[index] == Approx(index_vega * sensitivities[index]).margin(identity_tolerance));
    }
}

TEST_CASE("a basket that does not add to one is rejected") {
    REQUIRE_THROWS_AS(imply_correlation({BasketConstituent{"A", 0.4, 0.2},
                                         BasketConstituent{"B", 0.4, 0.2}},
                                        0.2),
                      InvalidBasketError);
}

TEST_CASE("a single name, a negative weight and a negative volatility are all rejected") {
    REQUIRE_THROWS_AS(imply_correlation({BasketConstituent{"A", 1.0, 0.2}}, 0.2), InvalidBasketError);
    REQUIRE_THROWS_AS(imply_correlation({BasketConstituent{"A", -0.5, 0.2},
                                         BasketConstituent{"B", 1.5, 0.2}},
                                        0.2),
                      InvalidBasketError);
    REQUIRE_THROWS_AS(imply_correlation({BasketConstituent{"A", 0.5, -0.2},
                                         BasketConstituent{"B", 0.5, 0.2}},
                                        0.2),
                      InvalidBasketError);
}

TEST_CASE("a correlation outside the admissible range cannot price a basket") {
    const std::vector<BasketConstituent> basket = concentrated_basket();
    REQUIRE_THROWS_AS(basket_volatility(basket, -0.9), InvalidBasketError);
    REQUIRE_THROWS_AS(basket_volatility(basket, 1.1), InvalidBasketError);
}

TEST_CASE("a zero index volatility is rejected rather than implied from") {
    REQUIRE_THROWS_AS(imply_correlation(concentrated_basket(), 0.0), InvalidBasketError);
}
