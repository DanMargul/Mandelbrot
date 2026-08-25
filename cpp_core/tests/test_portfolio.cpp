#include "volarb/portfolio.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::allocate;
using volarb::Allocation;
using volarb::Candidate;
using volarb::hedging_cost_of_gamma;
using volarb::InvalidPortfolioInputsError;
using volarb::PortfolioLimits;
using volarb::report;

namespace {

std::vector<Candidate> candidates() {
    return {
        Candidate{1.00, 0.20, 0.010, -0.05, {0.9, 0.2}, 10.0, 0.10},
        Candidate{1.05, 0.22, 0.070, -0.30, {0.8, -0.3}, 10.0, 0.12},
        Candidate{0.95, 0.18, 0.008, -0.04, {-0.7, 0.5}, 10.0, 0.09},
        Candidate{1.10, 0.25, 0.090, -0.40, {-0.9, -0.1}, 10.0, 0.15},
        Candidate{0.90, 0.15, 0.006, -0.03, {0.4, 0.8}, 10.0, 0.08},
        Candidate{1.02, 0.21, 0.055, -0.25, {0.1, -0.9}, 10.0, 0.11},
        Candidate{0.98, 0.19, 0.012, -0.06, {-0.2, 0.7}, 10.0, 0.10},
        Candidate{1.08, 0.24, 0.080, -0.35, {0.6, 0.4}, 10.0, 0.14},
    };
}

PortfolioLimits limits() {
    return PortfolioLimits{1.0, 0.50, 2.0, 0.5, 0.10, 0.0010, 100.0, 0.20, 0.25};
}

const double tolerance = 1e-9;

}

TEST_CASE("every budget and tolerance is respected", "[portfolio]") {
    const Allocation solved = allocate(candidates(), limits(), true);
    REQUIRE(std::abs(solved.net_vega) <= limits().vega_budget + tolerance);
    REQUIRE(std::abs(solved.net_gamma) <= limits().gamma_budget + tolerance);
    REQUIRE(std::abs(solved.net_theta) <= limits().theta_budget + tolerance);
    REQUIRE(solved.worst_factor_exposure <= limits().factor_tolerance + tolerance);
    for (std::size_t index = 0; index < solved.weights.size(); ++index) {
        REQUIRE(std::abs(solved.weights[index]) <= candidates()[index].maximum_size + tolerance);
    }
}

TEST_CASE("solving jointly beats solving separately", "[portfolio]") {
    const Allocation joint = allocate(candidates(), limits(), true);
    const Allocation naive = allocate(candidates(), limits(), false);
    const Allocation charged = report(naive.weights, candidates(), limits(), true);
    REQUIRE(joint.objective > charged.objective);
    REQUIRE(std::abs(joint.net_gamma) < std::abs(charged.net_gamma));
    REQUIRE(joint.hedging_cost < charged.hedging_cost);
}

TEST_CASE("the hedging cost grows with the square of gamma over its band", "[portfolio]") {
    const PortfolioLimits with = limits();
    REQUIRE(hedging_cost_of_gamma(0.0, with) == Approx(0.0));
    REQUIRE(hedging_cost_of_gamma(0.05, with) > hedging_cost_of_gamma(0.02, with));
    REQUIRE(hedging_cost_of_gamma(-0.05, with) == Approx(hedging_cost_of_gamma(0.05, with)));

    PortfolioLimits free_market = limits();
    free_market.proportional_cost = 0.0;
    REQUIRE(hedging_cost_of_gamma(0.05, free_market) == Approx(0.0));
}

TEST_CASE("a free market allocates the same either way", "[portfolio]") {
    PortfolioLimits free_market = limits();
    free_market.proportional_cost = 0.0;
    const Allocation joint = allocate(candidates(), free_market, true);
    const Allocation naive = allocate(candidates(), free_market, false);
    REQUIRE(joint.objective == Approx(naive.objective).epsilon(1e-12));
}

TEST_CASE("a zero budget forces the exposure to zero", "[portfolio]") {
    PortfolioLimits tight = limits();
    tight.vega_budget = 0.0;
    const Allocation solved = allocate(candidates(), tight, true);
    REQUIRE(std::abs(solved.net_vega) < tolerance);
}

TEST_CASE("candidates with no edge are not traded", "[portfolio]") {
    std::vector<Candidate> flat = candidates();
    for (Candidate& candidate : flat) {
        candidate.expected_edge = 0.0;
    }
    const Allocation solved = allocate(flat, limits(), true);
    for (const double weight : solved.weights) {
        REQUIRE(std::abs(weight) < tolerance);
    }
    REQUIRE(solved.objective == Approx(0.0).margin(tolerance));
}

TEST_CASE("the allocation is deterministic", "[portfolio]") {
    const Allocation one = allocate(candidates(), limits(), true);
    const Allocation other = allocate(candidates(), limits(), true);
    REQUIRE(one.weights == other.weights);
    REQUIRE(one.objective == other.objective);
}

TEST_CASE("malformed portfolio inputs are rejected", "[portfolio]") {
    REQUIRE_THROWS_AS(allocate({}, limits(), true), InvalidPortfolioInputsError);

    std::vector<Candidate> ragged = candidates();
    ragged[1].factor_exposures = {0.1};
    REQUIRE_THROWS_AS(allocate(ragged, limits(), true), InvalidPortfolioInputsError);

    std::vector<Candidate> negative = candidates();
    negative[0].maximum_size = -1.0;
    REQUIRE_THROWS_AS(allocate(negative, limits(), true), InvalidPortfolioInputsError);

    PortfolioLimits broken = limits();
    broken.risk_aversion = 0.0;
    REQUIRE_THROWS_AS(allocate(candidates(), broken, true), InvalidPortfolioInputsError);
    broken = limits();
    broken.vega_budget = -1.0;
    REQUIRE_THROWS_AS(allocate(candidates(), broken, true), InvalidPortfolioInputsError);
}
