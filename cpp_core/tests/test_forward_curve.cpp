#include "volarb/forward_curve.hpp"
#include "volarb/market_data.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <string>
#include <vector>

using Catch::Approx;
using volarb::ChainQuery;
using volarb::ContractQuote;
using volarb::ForwardCurvePoint;
using volarb::ForwardCurveStatus;
using volarb::imply_forward_curve;
using volarb::KnowledgeHorizon;
using volarb::median_of;
using volarb::name_of_forward_curve_status;
using volarb::open_chain_dataset;
using volarb::parity_pairs_from_chain;
using volarb::parse_canonical_timestamp;
using volarb::years_to_expiry_from;

namespace {

const std::filesystem::path dataset_root = VOLARB_DATASET_ROOT;

std::vector<ForwardCurvePoint> curve_for(const std::string& underlying, const std::string& observation) {
    const auto moment = parse_canonical_timestamp(observation);
    const auto reader = open_chain_dataset(dataset_root, KnowledgeHorizon{moment});
    return imply_forward_curve(reader.chain_as_of(ChainQuery{underlying, moment, false}), moment);
}

}

TEST_CASE("the median is defined for odd and even counts", "[forward_curve]") {
    REQUIRE(median_of({3.0, 1.0, 2.0}) == 2.0);
    REQUIRE(median_of({4.0, 1.0, 3.0, 2.0}) == 2.5);
    REQUIRE(median_of({7.0}) == 7.0);
}

TEST_CASE("the year fraction is measured to the settlement hour", "[forward_curve]") {
    const auto observation = parse_canonical_timestamp("2026-08-21T21:00:00.000000Z");
    REQUIRE(years_to_expiry_from(observation, 20686) == Approx(0.0).margin(1e-15));
    REQUIRE(years_to_expiry_from(observation, 20686 + 365) == Approx(1.0).epsilon(1e-12));
}

TEST_CASE("the forward curve converges on a liquid chain", "[forward_curve]") {
    const auto points = curve_for("SPX", "2026-08-21T17:00:00.000000Z");
    REQUIRE(points.size() == 2);
    for (const ForwardCurvePoint& point : points) {
        REQUIRE(point.status == ForwardCurveStatus::Converged);
        REQUIRE(point.forward > 0.0);
        REQUIRE(point.discount_factor > 0.0);
        REQUIRE(point.discount_factor <= 1.0);
        REQUIRE(point.forward_standard_error.has_value());
        REQUIRE(*point.forward_standard_error > 0.0);
    }
}

TEST_CASE("a stale quote is trimmed from the active set", "[forward_curve]") {
    for (const ForwardCurvePoint& point : curve_for("SPX", "2026-08-21T17:00:00.000000Z")) {
        REQUIRE(point.active_pair_count < point.parity_pair_count);
        REQUIRE(point.active_pair_count >= 4);
    }
}

TEST_CASE("the discount factor term structure is monotone", "[forward_curve]") {
    for (const ForwardCurvePoint& point : curve_for("SPX", "2026-08-21T17:00:00.000000Z")) {
        REQUIRE(point.discount_factor_is_monotone_in_expiry);
    }
}

TEST_CASE("a thin chain reports too few pairs rather than guessing", "[forward_curve]") {
    const auto points = curve_for("THIN", "2026-08-21T17:00:00.000000Z");
    REQUIRE(points.size() == 1);
    REQUIRE(points[0].status == ForwardCurveStatus::TooFewPairs);
    REQUIRE(points[0].forward == 0.0);
    REQUIRE(points[0].discount_factor == 0.0);
    REQUIRE_FALSE(points[0].forward_standard_error.has_value());
    REQUIRE_FALSE(points[0].implied_zero_rate.has_value());
}

TEST_CASE("american quotes are refused rather than silently biased", "[forward_curve]") {
    const auto points = curve_for("AAPL", "2026-08-21T17:00:00.000000Z");
    REQUIRE(points.size() == 1);
    REQUIRE(points[0].status == ForwardCurveStatus::AmericanQuotesNotStripped);
    REQUIRE(points[0].forward == 0.0);
    REQUIRE_FALSE(points[0].forward_standard_error.has_value());
}

TEST_CASE("an empty chain produces no curve points", "[forward_curve]") {
    REQUIRE(curve_for("NVDA", "2026-08-21T17:00:00.000000Z").empty());
}

TEST_CASE("only strikes with both a call and a put become pairs", "[forward_curve]") {
    const auto moment = parse_canonical_timestamp("2026-08-21T17:00:00.000000Z");
    const auto reader = open_chain_dataset(dataset_root, KnowledgeHorizon{moment});
    const auto quotes = reader.chain_as_of(ChainQuery{"SPX", moment, false});
    const auto pairs = parity_pairs_from_chain(quotes);
    std::size_t paired = 0;
    for (const auto& [expiry, list] : pairs) {
        paired += list.size();
    }
    REQUIRE(paired * 2 < quotes.size() + pairs.size() * 2);
}

TEST_CASE("status names round trip", "[forward_curve]") {
    REQUIRE(name_of_forward_curve_status(ForwardCurveStatus::Converged) == "converged");
    REQUIRE(name_of_forward_curve_status(ForwardCurveStatus::TooFewPairs) == "too_few_pairs");
}
