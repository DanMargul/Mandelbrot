#include "volarb/pricing.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::BlackScholesGreeks;
using volarb::BlackScholesInputs;
using volarb::black_scholes_price;
using volarb::black_scholes_price_and_greeks;
using volarb::InvalidOptionInputsError;
using volarb::OptionType;
using volarb::standard_normal_cumulative_distribution;
using volarb::standard_normal_probability_density;

namespace {

constexpr double reference_forward = 100.0;
constexpr double reference_discount_factor = 0.9876543;

const std::vector<double> strikes = {60.0, 90.0, 99.0, 100.0, 101.0, 130.0, 250.0};
const std::vector<double> expiries = {0.019178, 0.25, 1.0, 5.0};
const std::vector<double> volatilities = {0.05, 0.15, 0.35, 1.2};

BlackScholesInputs inputs_for(double strike, double years, double volatility, OptionType option_type) {
    return BlackScholesInputs{
        reference_forward, strike, years, volatility, reference_discount_factor, option_type};
}

}

TEST_CASE("put call parity holds across the grid", "[pricing]") {
    for (const double strike : strikes) {
        for (const double years : expiries) {
            for (const double volatility : volatilities) {
                const double call = black_scholes_price(inputs_for(strike, years, volatility, OptionType::Call));
                const double put = black_scholes_price(inputs_for(strike, years, volatility, OptionType::Put));
                const double expected = reference_discount_factor * (reference_forward - strike);
                REQUIRE(call - put == Approx(expected).epsilon(1e-12).margin(1e-12));
            }
        }
    }
}

TEST_CASE("delta parity holds across the grid", "[pricing]") {
    for (const double strike : strikes) {
        for (const double years : expiries) {
            for (const double volatility : volatilities) {
                const BlackScholesGreeks call =
                    black_scholes_price_and_greeks(inputs_for(strike, years, volatility, OptionType::Call));
                const BlackScholesGreeks put =
                    black_scholes_price_and_greeks(inputs_for(strike, years, volatility, OptionType::Put));
                const double difference =
                    call.delta_with_respect_to_forward - put.delta_with_respect_to_forward;
                REQUIRE(difference == Approx(reference_discount_factor).epsilon(1e-12));
            }
        }
    }
}

TEST_CASE("second order greeks do not depend on the option type", "[pricing]") {
    for (const double strike : strikes) {
        for (const double volatility : volatilities) {
            const BlackScholesGreeks call =
                black_scholes_price_and_greeks(inputs_for(strike, 1.0, volatility, OptionType::Call));
            const BlackScholesGreeks put =
                black_scholes_price_and_greeks(inputs_for(strike, 1.0, volatility, OptionType::Put));
            REQUIRE(call.gamma_with_respect_to_forward ==
                    Approx(put.gamma_with_respect_to_forward).epsilon(1e-14));
            REQUIRE(call.vega_with_respect_to_volatility ==
                    Approx(put.vega_with_respect_to_volatility).epsilon(1e-14));
            REQUIRE(call.theta_with_respect_to_time == Approx(put.theta_with_respect_to_time).epsilon(1e-14));
        }
    }
}

TEST_CASE("price is monotone in volatility", "[pricing]") {
    for (const double strike : strikes) {
        double previous = -1.0;
        for (const double volatility : volatilities) {
            const double price = black_scholes_price(inputs_for(strike, 1.0, volatility, OptionType::Call));
            REQUIRE(price >= previous);
            previous = price;
        }
    }
}

TEST_CASE("an expired option is worth its forward intrinsic value", "[pricing]") {
    const BlackScholesGreeks greeks =
        black_scholes_price_and_greeks(inputs_for(90.0, 0.0, 0.2, OptionType::Call));
    REQUIRE(greeks.price == Approx(reference_discount_factor * 10.0).epsilon(1e-15));
    REQUIRE(greeks.gamma_with_respect_to_forward == 0.0);
    REQUIRE(greeks.vega_with_respect_to_volatility == 0.0);
    REQUIRE(greeks.theta_with_respect_to_time == 0.0);
}

TEST_CASE("delta parity holds at the expiry kink", "[pricing]") {
    const BlackScholesGreeks call =
        black_scholes_price_and_greeks(inputs_for(reference_forward, 0.0, 0.2, OptionType::Call));
    const BlackScholesGreeks put =
        black_scholes_price_and_greeks(inputs_for(reference_forward, 0.0, 0.2, OptionType::Put));
    REQUIRE(call.delta_with_respect_to_forward == 0.0);
    REQUIRE(put.delta_with_respect_to_forward == -reference_discount_factor);
}

TEST_CASE("the deep wing put delta keeps its sign rather than cancelling to zero", "[pricing]") {
    const BlackScholesGreeks greeks =
        black_scholes_price_and_greeks(inputs_for(60.0, 0.019178, 0.25, OptionType::Put));
    REQUIRE(greeks.delta_with_respect_to_forward < 0.0);
}

TEST_CASE("invalid inputs are rejected", "[pricing]") {
    REQUIRE_THROWS_AS(black_scholes_price(BlackScholesInputs{0.0, 100.0, 1.0, 0.2, 1.0, OptionType::Call}),
                      InvalidOptionInputsError);
    REQUIRE_THROWS_AS(black_scholes_price(BlackScholesInputs{100.0, 0.0, 1.0, 0.2, 1.0, OptionType::Call}),
                      InvalidOptionInputsError);
    REQUIRE_THROWS_AS(black_scholes_price(BlackScholesInputs{100.0, 100.0, -1.0, 0.2, 1.0, OptionType::Call}),
                      InvalidOptionInputsError);
    REQUIRE_THROWS_AS(black_scholes_price(BlackScholesInputs{100.0, 100.0, 1.0, -0.2, 1.0, OptionType::Call}),
                      InvalidOptionInputsError);
}

TEST_CASE("the normal distribution matches known values", "[pricing]") {
    REQUIRE(standard_normal_cumulative_distribution(0.0) == 0.5);
    REQUIRE(standard_normal_probability_density(0.0) == Approx(0.3989422804014327).epsilon(1e-15));
    REQUIRE(standard_normal_cumulative_distribution(-1.0) == Approx(0.15865525393145705).epsilon(1e-15));
    REQUIRE(standard_normal_cumulative_distribution(1.0) == Approx(0.8413447460685429).epsilon(1e-15));
}

TEST_CASE("the normal left tail stays positive until it underflows", "[pricing]") {
    REQUIRE(standard_normal_cumulative_distribution(-37.0) == Approx(5.72557e-300).epsilon(1e-4));
    REQUIRE(standard_normal_cumulative_distribution(-38.4) > 0.0);
    REQUIRE(standard_normal_cumulative_distribution(-38.5) == 0.0);
    REQUIRE(standard_normal_cumulative_distribution(40.0) == 1.0);
}
