#include "volarb/american.hpp"
#include "volarb/pricing.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::black_scholes_reference_price;
using volarb::cox_ross_rubinstein_price;
using volarb::early_exercise_premium;
using volarb::european_counterpart;
using volarb::exercise_style_from_name;
using volarb::ExerciseStyle;
using volarb::InvalidLatticeInputsError;
using volarb::LatticeInputs;
using volarb::name_of_exercise_style;
using volarb::OptionType;
using volarb::richardson_extrapolated_price;

namespace {

constexpr double reference_spot = 100.0;
constexpr double reference_zero_rate = 0.0425;

LatticeInputs lattice(double strike, double years, double volatility, double carry_rate,
                      OptionType option_type, ExerciseStyle exercise_style) {
    return LatticeInputs{reference_spot, strike,     years,       volatility,
                         reference_zero_rate, carry_rate, option_type, exercise_style};
}

}

TEST_CASE("a European lattice converges to the closed form", "[american]") {
    const auto inputs = lattice(100.0, 1.0, 0.25, 0.03, OptionType::Call, ExerciseStyle::European);
    const double exact = black_scholes_reference_price(inputs);
    double previous = std::abs(cox_ross_rubinstein_price(inputs, 64) - exact);
    for (const int steps : {256, 1024}) {
        const double error = std::abs(cox_ross_rubinstein_price(inputs, steps) - exact);
        REQUIRE(error < previous);
        previous = error;
    }
}

TEST_CASE("the terminal correction with Richardson beats a far finer plain lattice", "[american]") {
    const auto inputs = lattice(100.0, 1.0, 0.25, 0.03, OptionType::Call, ExerciseStyle::European);
    const double exact = black_scholes_reference_price(inputs);
    const double plain = std::abs(cox_ross_rubinstein_price(inputs, 1024) - exact);
    const double corrected = std::abs(richardson_extrapolated_price(inputs) - exact);
    REQUIRE(corrected < plain);
}

TEST_CASE("an American price is never below its European counterpart", "[american]") {
    for (const double strike : {70.0, 100.0, 140.0}) {
        for (const double volatility : {0.12, 0.30, 0.65}) {
            for (const double carry_rate : {0.0, 0.025, 0.070}) {
                for (const OptionType option_type : {OptionType::Call, OptionType::Put}) {
                    const auto american =
                        lattice(strike, 1.0, volatility, carry_rate, option_type, ExerciseStyle::American);
                    REQUIRE(richardson_extrapolated_price(american) >=
                            richardson_extrapolated_price(european_counterpart(american)) - 1e-9);
                }
            }
        }
    }
}

TEST_CASE("an American call on a zero carry underlying has exactly no premium", "[american]") {
    for (const double strike : {70.0, 100.0, 140.0}) {
        for (const double volatility : {0.12, 0.30, 0.65}) {
            const auto inputs = lattice(strike, 1.0, volatility, 0.0, OptionType::Call, ExerciseStyle::American);
            REQUIRE(early_exercise_premium(inputs) == 0.0);
        }
    }
}

TEST_CASE("an American put on a positive rate carries a premium", "[american]") {
    const auto inputs = lattice(100.0, 1.0, 0.25, 0.0, OptionType::Put, ExerciseStyle::American);
    REQUIRE(early_exercise_premium(inputs) > 0.0);
}

TEST_CASE("an American call on a dividend payer carries a premium", "[american]") {
    const auto inputs = lattice(100.0, 1.0, 0.25, 0.06, OptionType::Call, ExerciseStyle::American);
    REQUIRE(early_exercise_premium(inputs) > 0.0);
}

TEST_CASE("a European contract has no premium by construction", "[american]") {
    const auto inputs = lattice(100.0, 1.0, 0.25, 0.06, OptionType::Call, ExerciseStyle::European);
    REQUIRE(early_exercise_premium(inputs) == 0.0);
}

TEST_CASE("degenerate inputs return intrinsic value", "[american]") {
    const auto expired = lattice(90.0, 0.0, 0.3, 0.02, OptionType::Call, ExerciseStyle::American);
    REQUIRE(richardson_extrapolated_price(expired) == Approx(10.0).epsilon(1e-15));
    const auto motionless = lattice(90.0, 1.0, 0.0, 0.02, OptionType::Call, ExerciseStyle::American);
    REQUIRE(richardson_extrapolated_price(motionless) == Approx(10.0).epsilon(1e-15));
}

TEST_CASE("invalid lattice inputs are rejected", "[american]") {
    const auto valid = lattice(100.0, 1.0, 0.25, 0.02, OptionType::Call, ExerciseStyle::American);
    auto broken = valid;
    broken.spot_price = 0.0;
    REQUIRE_THROWS_AS(cox_ross_rubinstein_price(broken, 64), InvalidLatticeInputsError);
    broken = valid;
    broken.strike = -1.0;
    REQUIRE_THROWS_AS(cox_ross_rubinstein_price(broken, 64), InvalidLatticeInputsError);
    REQUIRE_THROWS_AS(cox_ross_rubinstein_price(valid, 1), InvalidLatticeInputsError);
    REQUIRE_THROWS_AS(cox_ross_rubinstein_price(valid, 100000), InvalidLatticeInputsError);
}

TEST_CASE("exercise style names round trip", "[american]") {
    REQUIRE(exercise_style_from_name("american") == ExerciseStyle::American);
    REQUIRE(exercise_style_from_name("european") == ExerciseStyle::European);
    REQUIRE(name_of_exercise_style(ExerciseStyle::American) == "american");
    REQUIRE_THROWS_AS(exercise_style_from_name("bermudan"), InvalidLatticeInputsError);
}
