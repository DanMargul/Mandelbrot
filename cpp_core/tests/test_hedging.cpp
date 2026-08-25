#include "volarb/hedging.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::BandPolicy;
using volarb::BandRule;
using volarb::band_rule_from_name;
using volarb::HedgingInputs;
using volarb::HedgingStatistics;
using volarb::hedging_statistics;
using volarb::InvalidHedgingInputsError;
using volarb::name_of_band_rule;
using volarb::whalley_wilmott_band;

namespace {

HedgingInputs base_inputs() {
    return HedgingInputs{100.0, 100.0, 0.25, 0.20, 63, 0.0010, 0.10};
}

const int paths = 400;

HedgingStatistics run(const BandPolicy& policy, const std::string& sequence) {
    return hedging_statistics(base_inputs(), policy, "1", sequence, paths);
}

}

TEST_CASE("the band scales as the cube root of cost and gamma squared", "[hedging]") {
    const double base = whalley_wilmott_band(100.0, 0.04, 0.001, 0.1);
    REQUIRE(whalley_wilmott_band(100.0, 0.04, 0.008, 0.1) == Approx(2.0 * base).epsilon(1e-12));
    REQUIRE(whalley_wilmott_band(100.0, 0.32, 0.001, 0.1) == Approx(4.0 * base).epsilon(1e-12));
    REQUIRE(whalley_wilmott_band(100.0, 0.04, 0.001, 0.8) == Approx(0.5 * base).epsilon(1e-12));
    REQUIRE(whalley_wilmott_band(100.0, 0.0, 0.001, 0.1) == Approx(0.0));
}

TEST_CASE("a wider band trades less and pays less", "[hedging]") {
    double previous_cost = 1e9;
    double previous_rebalances = 1e9;
    for (const double width : {0.0, 0.05, 0.10, 0.20, 0.40}) {
        const HedgingStatistics stats = run(BandPolicy{BandRule::Fixed, width}, "1");
        REQUIRE(stats.mean_transaction_cost < previous_cost);
        REQUIRE(stats.mean_rebalance_count < previous_rebalances);
        previous_cost = stats.mean_transaction_cost;
        previous_rebalances = stats.mean_rebalance_count;
    }
}

TEST_CASE("a wider band carries more risk", "[hedging]") {
    double previous = 0.0;
    for (const double width : {0.0, 0.05, 0.10, 0.20, 0.40}) {
        const HedgingStatistics stats = run(BandPolicy{BandRule::Fixed, width}, "1");
        REQUIRE(stats.profit_standard_deviation > previous);
        previous = stats.profit_standard_deviation;
    }
}

TEST_CASE("hedging with no cost and no band replicates the option", "[hedging]") {
    HedgingInputs inputs = base_inputs();
    inputs.proportional_cost = 0.0;
    inputs.steps = 252;
    const HedgingStatistics stats =
        hedging_statistics(inputs, BandPolicy{BandRule::Fixed, 0.0}, "1", "1", paths);
    REQUIRE(stats.mean_transaction_cost == Approx(0.0));
    REQUIRE(std::abs(stats.mean_profit) < 0.1);
    REQUIRE(stats.profit_standard_deviation < 0.3);
}

TEST_CASE("the same seed reproduces the same statistics", "[hedging]") {
    const HedgingStatistics one = run(BandPolicy{BandRule::WhalleyWilmott, 0.0}, "1");
    const HedgingStatistics other = run(BandPolicy{BandRule::WhalleyWilmott, 0.0}, "1");
    REQUIRE(one.mean_profit == other.mean_profit);
    REQUIRE(one.certainty_equivalent == other.certainty_equivalent);

    const HedgingStatistics elsewhere = run(BandPolicy{BandRule::WhalleyWilmott, 0.0}, "2");
    REQUIRE(elsewhere.mean_profit != one.mean_profit);
}

TEST_CASE("the certainty equivalent is the mean penalised by variance", "[hedging]") {
    const HedgingStatistics stats = run(BandPolicy{BandRule::Fixed, 0.10}, "1");
    const double variance = stats.profit_standard_deviation * stats.profit_standard_deviation;
    REQUIRE(stats.certainty_equivalent ==
            Approx(stats.mean_profit - 0.5 * base_inputs().risk_aversion * variance).epsilon(1e-12));
    REQUIRE(stats.certainty_equivalent < stats.mean_profit);
}

TEST_CASE("band rules have names that round trip", "[hedging]") {
    REQUIRE(band_rule_from_name("fixed") == BandRule::Fixed);
    REQUIRE(band_rule_from_name("whalley_wilmott") == BandRule::WhalleyWilmott);
    REQUIRE(name_of_band_rule(BandRule::Fixed) == "fixed");
    REQUIRE(name_of_band_rule(BandRule::WhalleyWilmott) == "whalley_wilmott");
    REQUIRE_THROWS_AS(band_rule_from_name("never"), InvalidHedgingInputsError);
}

TEST_CASE("malformed hedging inputs are rejected", "[hedging]") {
    HedgingInputs inputs = base_inputs();
    const BandPolicy policy{BandRule::Fixed, 0.1};
    inputs.spot = -1.0;
    REQUIRE_THROWS_AS(hedging_statistics(inputs, policy, "1", "1", paths), InvalidHedgingInputsError);
    inputs = base_inputs();
    inputs.risk_aversion = 0.0;
    REQUIRE_THROWS_AS(hedging_statistics(inputs, policy, "1", "1", paths), InvalidHedgingInputsError);
    inputs = base_inputs();
    REQUIRE_THROWS_AS(hedging_statistics(inputs, BandPolicy{BandRule::Fixed, -1.0}, "1", "1", paths),
                      InvalidHedgingInputsError);
    REQUIRE_THROWS_AS(hedging_statistics(inputs, policy, "1", "1", 1), InvalidHedgingInputsError);
    REQUIRE_THROWS_AS(hedging_statistics(inputs, policy, "x", "1", paths), InvalidHedgingInputsError);
}
