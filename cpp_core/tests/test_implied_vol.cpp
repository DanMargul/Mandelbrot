#include "volarb/implied_vol.hpp"
#include "volarb/pricing.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::black_scholes_price;
using volarb::BlackScholesInputs;
using volarb::ImpliedVolatilityInputs;
using volarb::ImpliedVolatilityResult;
using volarb::invert_black_implied_volatility;
using volarb::InversionStatus;
using volarb::name_of_inversion_status;
using volarb::OptionType;
using volarb::out_of_the_money_option_type;
using volarb::volatility_convergence_tolerance;

namespace {

constexpr double reference_forward = 100.0;
constexpr double reference_discount_factor = 0.9876543;
constexpr double uncertainty_safety_factor = 64.0;
constexpr double resolvable_relative_uncertainty = 1e-6;

const std::vector<double> strikes = {50.0, 70.0, 85.0, 95.0, 99.0, 100.0, 101.0, 110.0, 130.0, 180.0, 300.0};
const std::vector<double> expiries = {0.002740, 0.019178, 0.083333, 0.25, 1.0, 3.0};
const std::vector<double> volatilities = {0.05, 0.10, 0.20, 0.45, 1.0, 2.0};

ImpliedVolatilityResult invert_a_priced_option(
    double strike, double years, double volatility, OptionType option_type) {
    const double price = black_scholes_price(BlackScholesInputs{
        reference_forward, strike, years, volatility, reference_discount_factor, option_type});
    return invert_black_implied_volatility(ImpliedVolatilityInputs{
        reference_forward, strike, years, reference_discount_factor, price, option_type});
}

}

TEST_CASE("a resolvable out of the money quote round trips exactly", "[implied_vol]") {
    int checked = 0;
    for (const double strike : strikes) {
        const OptionType option_type = out_of_the_money_option_type(reference_forward, strike);
        for (const double years : expiries) {
            for (const double volatility : volatilities) {
                const ImpliedVolatilityResult result =
                    invert_a_priced_option(strike, years, volatility, option_type);
                if (result.status != InversionStatus::Converged) {
                    continue;
                }
                if (result.volatility_uncertainty > resolvable_relative_uncertainty * volatility) {
                    continue;
                }
                REQUIRE(result.volatility == Approx(volatility).epsilon(1.2e-12));
                ++checked;
            }
        }
    }
    REQUIRE(checked > 200);
}

TEST_CASE("realized error stays within the reported uncertainty and a safety factor", "[implied_vol]") {
    for (const double strike : strikes) {
        for (const double years : expiries) {
            for (const double volatility : volatilities) {
                for (const OptionType option_type : {OptionType::Call, OptionType::Put}) {
                    const ImpliedVolatilityResult result =
                        invert_a_priced_option(strike, years, volatility, option_type);
                    if (result.status != InversionStatus::Converged) {
                        continue;
                    }
                    const double solver_floor = volatility_convergence_tolerance * result.volatility;
                    const double budget =
                        uncertainty_safety_factor * (result.volatility_uncertainty + solver_floor);
                    REQUIRE(std::abs(result.volatility - volatility) <= budget);
                }
            }
        }
    }
}

TEST_CASE("every result is finite and typed", "[implied_vol]") {
    for (const double strike : strikes) {
        for (const double years : expiries) {
            for (const OptionType option_type : {OptionType::Call, OptionType::Put}) {
                const ImpliedVolatilityResult result = invert_a_priced_option(strike, years, 0.2, option_type);
                REQUIRE_FALSE(std::isnan(result.volatility));
                REQUIRE(result.volatility >= 0.0);
                REQUIRE(result.iterations >= 0);
                if (result.status != InversionStatus::Converged) {
                    REQUIRE(result.volatility == 0.0);
                }
            }
        }
    }
}

TEST_CASE("inversion always selects the out of the money side", "[implied_vol]") {
    REQUIRE(out_of_the_money_option_type(100.0, 90.0) == OptionType::Put);
    REQUIRE(out_of_the_money_option_type(100.0, 110.0) == OptionType::Call);
    REQUIRE(out_of_the_money_option_type(100.0, 100.0) == OptionType::Call);
}

TEST_CASE("an in the money quote reports far larger uncertainty", "[implied_vol]") {
    const ImpliedVolatilityResult from_out_of_the_money =
        invert_a_priced_option(80.0, 1.0, 0.05, OptionType::Put);
    const ImpliedVolatilityResult from_in_the_money =
        invert_a_priced_option(80.0, 1.0, 0.05, OptionType::Call);
    REQUIRE(from_out_of_the_money.volatility_uncertainty <
            from_in_the_money.volatility_uncertainty / 1000.0);
    REQUIRE(std::abs(from_out_of_the_money.volatility - 0.05) <
            std::abs(from_in_the_money.volatility - 0.05));
}

TEST_CASE("boundary conditions report their cause", "[implied_vol]") {
    struct BoundaryCase {
        double strike;
        double years;
        double price;
        OptionType option_type;
        InversionStatus expected_status;
    };

    const std::vector<BoundaryCase> cases = {
        {90.0, 1.0, 5.0, OptionType::Call, InversionStatus::BelowIntrinsic},
        {90.0, 1.0, 10.0, OptionType::Call, InversionStatus::BelowIntrinsic},
        {110.0, 1.0, 101.0, OptionType::Call, InversionStatus::AboveNoArbitrageBound},
        {90.0, 1.0, 91.0, OptionType::Put, InversionStatus::AboveNoArbitrageBound},
        {100.0, 0.0, 1.0, OptionType::Call, InversionStatus::DegenerateExpiry},
        {100.0, 1.0, 1e-12, OptionType::Call, InversionStatus::BelowVolatilityFloor},
        {100.0, 1.0, 99.9999995, OptionType::Call, InversionStatus::AboveVolatilityCeiling},
    };

    for (const BoundaryCase& boundary : cases) {
        const ImpliedVolatilityResult result = invert_black_implied_volatility(ImpliedVolatilityInputs{
            100.0, boundary.strike, boundary.years, 1.0, boundary.price, boundary.option_type});
        INFO("case " << name_of_inversion_status(boundary.expected_status));
        REQUIRE(result.status == boundary.expected_status);
        REQUIRE(result.volatility == 0.0);
        REQUIRE(std::isinf(result.volatility_uncertainty));
    }
}
