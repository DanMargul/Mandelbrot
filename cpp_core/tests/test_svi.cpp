#include "volarb/svi.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::durrleman_function;
using volarb::implied_volatility;
using volarb::InvalidSviParametersError;
using volarb::name_of_svi_status;
using volarb::risk_neutral_density;
using volarb::scan_svi_slice;
using volarb::SviParameters;
using volarb::SviSliceScan;
using volarb::SviStatus;
using volarb::total_variance;

namespace {

const SviParameters benign{0.0002, 0.018, -0.65, 0.01, 0.10};
const SviParameters violating{0.0002, 0.350, -0.85, 0.00, 0.02};

}

TEST_CASE("a well shaped slice is free of butterfly arbitrage on the grid", "[svi]") {
    const SviSliceScan scan = scan_svi_slice(benign, -0.6, 0.6);
    REQUIRE(scan.status == SviStatus::ArbitrageFreeOnGrid);
    REQUIRE(scan.minimum_durrleman_value > 0.0);
    REQUIRE(scan.minimum_risk_neutral_density > 0.0);
    REQUIRE(scan.minimum_total_variance > 0.0);
}

TEST_CASE("curvature too large for the level is caught", "[svi]") {
    const SviSliceScan scan = scan_svi_slice(violating, -0.6, 0.6);
    REQUIRE(scan.status == SviStatus::ButterflyArbitrageFound);
    REQUIRE(scan.minimum_durrleman_value < 0.0);
    REQUIRE(scan.minimum_risk_neutral_density < 0.0);
}

TEST_CASE("the density and the Durrleman function share a sign everywhere", "[svi]") {
    for (const SviParameters& parameters : {benign, violating}) {
        for (int index = 0; index <= 200; ++index) {
            const double point = -0.6 + 1.2 * static_cast<double>(index) / 200.0;
            const bool durrleman_negative = durrleman_function(parameters, point) < 0.0;
            const bool density_negative = risk_neutral_density(parameters, point) < 0.0;
            REQUIRE(durrleman_negative == density_negative);
        }
    }
}

TEST_CASE("refinement finds a deeper minimum than a coarse grid alone", "[svi]") {
    const SviSliceScan coarse = scan_svi_slice(violating, -0.6, 0.6, 16);
    double grid_minimum = durrleman_function(violating, -0.6);
    for (int index = 0; index <= 16; ++index) {
        grid_minimum = std::min(grid_minimum,
                                durrleman_function(violating, -0.6 + 1.2 * static_cast<double>(index) / 16.0));
    }
    REQUIRE(coarse.minimum_durrleman_value < grid_minimum);
}

TEST_CASE("the reported minimum never exceeds any grid value", "[svi]") {
    const SviSliceScan scan = scan_svi_slice(benign, -0.6, 0.6, 64);
    for (int index = 0; index <= 64; ++index) {
        const double point = -0.6 + 1.2 * static_cast<double>(index) / 64.0;
        REQUIRE(scan.minimum_durrleman_value <= durrleman_function(benign, point) + 1e-15);
    }
}

TEST_CASE("total variance and implied volatility agree through w = sigma squared times T", "[svi]") {
    const double years = 0.25;
    for (const double point : {-0.3, 0.0, 0.3}) {
        const double volatility = implied_volatility(benign, point, years);
        REQUIRE(volatility * volatility * years == Approx(total_variance(benign, point)).epsilon(1e-14));
    }
}

TEST_CASE("invalid parameters are rejected", "[svi]") {
    REQUIRE_THROWS_AS(scan_svi_slice(SviParameters{0.01, -1.0, 0.0, 0.0, 0.1}, -0.5, 0.5),
                      InvalidSviParametersError);
    REQUIRE_THROWS_AS(scan_svi_slice(SviParameters{0.01, 0.1, 1.0, 0.0, 0.1}, -0.5, 0.5),
                      InvalidSviParametersError);
    REQUIRE_THROWS_AS(scan_svi_slice(SviParameters{0.01, 0.1, 0.0, 0.0, 0.0}, -0.5, 0.5),
                      InvalidSviParametersError);
    REQUIRE_THROWS_AS(scan_svi_slice(SviParameters{-1.0, 0.1, 0.0, 0.0, 0.1}, -0.5, 0.5),
                      InvalidSviParametersError);
    REQUIRE_THROWS_AS(scan_svi_slice(benign, 0.5, -0.5), InvalidSviParametersError);
    REQUIRE_THROWS_AS(scan_svi_slice(benign, -0.5, 0.5, 1), InvalidSviParametersError);
}

TEST_CASE("status names round trip", "[svi]") {
    REQUIRE(name_of_svi_status(SviStatus::ArbitrageFreeOnGrid) == "arbitrage_free_on_grid");
    REQUIRE(name_of_svi_status(SviStatus::ButterflyArbitrageFound) == "butterfly_arbitrage_found");
}
