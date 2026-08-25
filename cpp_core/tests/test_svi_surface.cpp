#include "volarb/svi_surface.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <utility>
#include <vector>

using Catch::Approx;
using volarb::interpolated_durrleman_value;
using volarb::interpolated_local_variance;
using volarb::interpolated_slice_between;
using volarb::interpolated_time_slope;
using volarb::InterpolatedSlice;
using volarb::InvalidSviSurfaceError;
using volarb::local_variance_from_prices;
using volarb::name_of_svi_surface_status;
using volarb::scan_svi_slice;
using volarb::scan_svi_surface;
using volarb::SviParameters;
using volarb::SviSurfaceScan;
using volarb::SviSurfaceSlice;
using volarb::SviSurfaceStatus;

namespace {

std::vector<SviSurfaceSlice> healthy_surface() {
    return {
        SviSurfaceSlice{0.0833, SviParameters{0.0015, 0.030, -0.70, 0.010, 0.10}},
        SviSurfaceSlice{0.2500, SviParameters{0.0060, 0.055, -0.65, 0.015, 0.15}},
        SviSurfaceSlice{0.5000, SviParameters{0.0140, 0.075, -0.60, 0.020, 0.22}},
        SviSurfaceSlice{1.0000, SviParameters{0.0300, 0.100, -0.55, 0.030, 0.32}},
    };
}

std::vector<SviSurfaceSlice> calendar_violating_surface() {
    std::vector<SviSurfaceSlice> slices = healthy_surface();
    slices[2] = SviSurfaceSlice{0.5000, SviParameters{0.0040, 0.055, -0.60, 0.020, 0.22}};
    return slices;
}

std::vector<SviSurfaceSlice> clean_knots_that_interpolate_badly() {
    return {
        SviSurfaceSlice{0.25, SviParameters{-0.127, 0.379, -0.598, 0.088, 0.419}},
        SviSurfaceSlice{1.00, SviParameters{0.077, 0.396, -0.617, 0.191, 0.079}},
    };
}

}

TEST_CASE("a monotone term structure of clean slices is arbitrage free on the grid", "[svi_surface]") {
    const SviSurfaceScan scan = scan_svi_surface(healthy_surface(), -1.5, 1.5);
    REQUIRE(scan.status == SviSurfaceStatus::ArbitrageFreeOnGrid);
    REQUIRE(scan.minimum_durrleman_value > 0.0);
    REQUIRE(scan.minimum_risk_neutral_density > 0.0);
    REQUIRE(scan.minimum_total_variance_time_slope > 0.0);
    REQUIRE(scan.minimum_local_variance > 0.0);
    REQUIRE(scan.slice_count == 4);
}

TEST_CASE("a slice that falls in total variance is a calendar violation", "[svi_surface]") {
    const std::vector<SviSurfaceSlice> slices = calendar_violating_surface();
    for (const SviSurfaceSlice& entry : slices) {
        REQUIRE(scan_svi_slice(entry.parameters, -1.5, 1.5).status ==
                volarb::SviStatus::ArbitrageFreeOnGrid);
    }

    const SviSurfaceScan scan = scan_svi_surface(slices, -1.5, 1.5);
    REQUIRE(scan.status == SviSurfaceStatus::CalendarArbitrageFound);
    REQUIRE(scan.minimum_total_variance_time_slope < 0.0);
    REQUIRE(scan.minimum_local_variance < 0.0);
}

TEST_CASE("the Dupire round trip reproduces the analytic local variance", "[svi_surface]") {
    const SviSurfaceScan scan = scan_svi_surface(healthy_surface(), -1.5, 1.5);
    REQUIRE(scan.round_trip_point_count > 0);
    REQUIRE(scan.worst_local_variance_round_trip_error < 1e-5);
}

TEST_CASE("local variance is the time slope over the Durrleman function", "[svi_surface]") {
    const std::vector<SviSurfaceSlice> slices = healthy_surface();
    const InterpolatedSlice midpoint = interpolated_slice_between(slices[1], slices[2], 0.5);
    for (int index = 0; index <= 40; ++index) {
        const double point = -1.0 + 2.0 * static_cast<double>(index) / 40.0;
        const double expected =
            interpolated_time_slope(midpoint, point) / interpolated_durrleman_value(midpoint, point);
        REQUIRE(interpolated_local_variance(midpoint, point) == Approx(expected).epsilon(1e-12));
    }
}

TEST_CASE("the price space route agrees with the total variance route away from the wings",
          "[svi_surface]") {
    const std::vector<SviSurfaceSlice> slices = healthy_surface();
    const InterpolatedSlice midpoint = interpolated_slice_between(slices[2], slices[3], 0.5);
    for (int index = 0; index <= 20; ++index) {
        const double point = -1.0 + 2.0 * static_cast<double>(index) / 20.0;
        const double analytic = interpolated_local_variance(midpoint, point);
        const double from_prices = local_variance_from_prices(midpoint, point);
        REQUIRE(std::abs(from_prices - analytic) / analytic < 1e-5);
    }
}

TEST_CASE("a surface needs at least two strictly increasing expiries", "[svi_surface]") {
    const std::vector<SviSurfaceSlice> slices = healthy_surface();
    REQUIRE_THROWS_AS(scan_svi_surface({slices[0]}, -1.0, 1.0), InvalidSviSurfaceError);
    REQUIRE_THROWS_AS(scan_svi_surface({slices[1], slices[0]}, -1.0, 1.0), InvalidSviSurfaceError);
    REQUIRE_THROWS_AS(scan_svi_surface({slices[0], slices[0]}, -1.0, 1.0), InvalidSviSurfaceError);
}

TEST_CASE("an inverted or degenerate scan range is rejected", "[svi_surface]") {
    REQUIRE_THROWS_AS(scan_svi_surface(healthy_surface(), 1.0, -1.0), InvalidSviSurfaceError);
    REQUIRE_THROWS_AS(scan_svi_surface(healthy_surface(), -1.0, 1.0, 1), InvalidSviSurfaceError);
    REQUIRE_THROWS_AS(scan_svi_surface(healthy_surface(), -1.0, 1.0, 256, 0), InvalidSviSurfaceError);
}

TEST_CASE("every surface status has a name", "[svi_surface]") {
    REQUIRE(name_of_svi_surface_status(SviSurfaceStatus::ArbitrageFreeOnGrid) == "arbitrage_free_on_grid");
    REQUIRE(name_of_svi_surface_status(SviSurfaceStatus::ButterflyArbitrageFound) ==
            "butterfly_arbitrage_found");
    REQUIRE(name_of_svi_surface_status(SviSurfaceStatus::CalendarArbitrageFound) ==
            "calendar_arbitrage_found");
    REQUIRE(name_of_svi_surface_status(SviSurfaceStatus::InvalidSurface) == "invalid_surface");
}

TEST_CASE("two arbitrage free knots can interpolate into a violation", "[svi_surface]") {
    const std::vector<SviSurfaceSlice> slices = clean_knots_that_interpolate_badly();
    for (const SviSurfaceSlice& entry : slices) {
        const auto alone = scan_svi_slice(entry.parameters, -1.0, 1.0, 20000);
        REQUIRE(alone.status == volarb::SviStatus::ArbitrageFreeOnGrid);
        REQUIRE(alone.minimum_durrleman_value > 0.02);
    }

    const SviSurfaceScan scan = scan_svi_surface(slices, -1.0, 1.0, 256, 8);
    REQUIRE(scan.status == SviSurfaceStatus::ButterflyArbitrageFound);
    REQUIRE(scan.minimum_durrleman_value < 0.0);
    REQUIRE(scan.minimum_risk_neutral_density < 0.0);
    REQUIRE(scan.minimum_total_variance_time_slope > 0.0);
    REQUIRE(scan.years_to_expiry_at_minimum_durrleman_value > 0.25);
    REQUIRE(scan.years_to_expiry_at_minimum_durrleman_value < 1.00);
}

TEST_CASE("the reported depth does not depend on either grid resolution", "[svi_surface]") {
    const std::vector<SviSurfaceSlice> slices = clean_knots_that_interpolate_badly();
    for (const std::pair<double, double> range :
         {std::pair{-0.6, 0.6}, std::pair{-1.0, 1.0}}) {
        const SviSurfaceScan reference =
            scan_svi_surface(slices, range.first, range.second, 8192, 256);
        for (const int scan_steps : {16, 256, 512}) {
            for (const int time_steps : {1, 4, 8, 16}) {
                const SviSurfaceScan scan =
                    scan_svi_surface(slices, range.first, range.second, scan_steps, time_steps);
                REQUIRE(scan.minimum_durrleman_value ==
                        Approx(reference.minimum_durrleman_value).margin(1e-15));
            }
        }
    }
}
