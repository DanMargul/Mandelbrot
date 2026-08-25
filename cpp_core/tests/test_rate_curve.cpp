#include "volarb/rate_curve.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::CurveNode;
using volarb::discount_factor;
using volarb::forward_discount_factor;
using volarb::forward_rate;
using volarb::InvalidRateCurveError;
using volarb::RateCurve;
using volarb::zero_rate;

namespace {

RateCurve upward() {
    return RateCurve{{CurveNode{0.0833, 0.01}, CurveNode{0.25, 0.04}, CurveNode{1.0, 0.045},
                      CurveNode{2.0, 0.043}}};
}

}

TEST_CASE("the curve reproduces its own nodes exactly", "[rate_curve]") {
    const RateCurve curve = upward();
    for (const CurveNode& node : curve.nodes) {
        REQUIRE(zero_rate(curve, node.years_to_maturity) ==
                Approx(node.continuously_compounded_zero_rate).epsilon(1e-15));
        REQUIRE(discount_factor(curve, node.years_to_maturity) ==
                Approx(std::exp(-node.continuously_compounded_zero_rate * node.years_to_maturity))
                    .epsilon(1e-15));
    }
}

TEST_CASE("the forward rate is constant inside a segment", "[rate_curve]") {
    const RateCurve curve = upward();
    const double reference = forward_rate(curve, 0.0833, 0.25);
    for (int index = 0; index <= 20; ++index) {
        const double lower = 0.0833 + (0.25 - 0.0833) * static_cast<double>(index) / 21.0;
        const double upper = lower + (0.25 - 0.0833) / 21.0;
        REQUIRE(forward_rate(curve, lower, upper) == Approx(reference).epsilon(1e-12));
    }
}

TEST_CASE("discount factors compose across a forward period", "[rate_curve]") {
    const RateCurve curve = upward();
    REQUIRE(discount_factor(curve, 1.5) ==
            Approx(discount_factor(curve, 0.4) * forward_discount_factor(curve, 0.4, 1.5))
                .epsilon(1e-14));
}

TEST_CASE("discounting is monotone when every forward is positive", "[rate_curve]") {
    const RateCurve curve = upward();
    double previous = 1.0;
    for (int index = 1; index <= 60; ++index) {
        const double years = 3.0 * static_cast<double>(index) / 60.0;
        const double factor = discount_factor(curve, years);
        REQUIRE(factor < previous);
        previous = factor;
    }
}

TEST_CASE("the short end is flat at the first node's rate", "[rate_curve]") {
    const RateCurve curve = upward();
    for (const double years : {1e-6, 0.01, 0.05, 0.0833}) {
        REQUIRE(zero_rate(curve, years) == Approx(0.01).epsilon(1e-12));
    }
    REQUIRE(discount_factor(curve, 0.0) == Approx(1.0));
}

TEST_CASE("beyond the last node the final forward continues", "[rate_curve]") {
    const RateCurve curve = upward();
    const double tail = forward_rate(curve, 1.0, 2.0);
    REQUIRE(forward_rate(curve, 2.0, 5.0) == Approx(tail).epsilon(1e-12));
    REQUIRE(forward_rate(curve, 3.0, 30.0) == Approx(tail).epsilon(1e-12));
}

TEST_CASE("a single node curve is flat everywhere", "[rate_curve]") {
    const RateCurve curve{{CurveNode{1.0, 0.03}}};
    for (const double years : {0.01, 1.0, 7.0}) {
        REQUIRE(zero_rate(curve, years) == Approx(0.03).epsilon(1e-12));
    }
    REQUIRE(forward_rate(curve, 2.0, 9.0) == Approx(0.03).epsilon(1e-12));
}

TEST_CASE("negative rates are a market condition and not an error", "[rate_curve]") {
    const RateCurve curve{{CurveNode{0.5, -0.006}, CurveNode{2.0, -0.002}, CurveNode{5.0, 0.004}}};
    REQUIRE(discount_factor(curve, 0.5) > 1.0);
    REQUIRE(zero_rate(curve, 0.5) == Approx(-0.006).epsilon(1e-14));
    REQUIRE(zero_rate(curve, 5.0) == Approx(0.004).epsilon(1e-14));
    REQUIRE(forward_rate(curve, 0.5, 2.0) == Approx(-0.0006666666666666666).epsilon(1e-12));
    REQUIRE(forward_rate(curve, 2.0, 5.0) > 0.0);
    REQUIRE(discount_factor(curve, 2.0) > discount_factor(curve, 0.5));
}

TEST_CASE("a malformed curve is rejected", "[rate_curve]") {
    REQUIRE_THROWS_AS(discount_factor(RateCurve{{}}, 1.0), InvalidRateCurveError);
    REQUIRE_THROWS_AS(discount_factor(RateCurve{{CurveNode{0.0, 0.01}}}, 1.0), InvalidRateCurveError);
    REQUIRE_THROWS_AS(discount_factor(RateCurve{{CurveNode{1.0, 0.01}, CurveNode{0.5, 0.02}}}, 1.0),
                      InvalidRateCurveError);
    REQUIRE_THROWS_AS(discount_factor(upward(), -1.0), InvalidRateCurveError);
    REQUIRE_THROWS_AS(forward_rate(upward(), 1.0, 1.0), InvalidRateCurveError);
    REQUIRE_THROWS_AS(forward_rate(upward(), 2.0, 1.0), InvalidRateCurveError);
}
