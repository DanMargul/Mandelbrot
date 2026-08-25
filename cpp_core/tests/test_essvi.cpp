#include "volarb/essvi.hpp"

#include "volarb/svi_surface.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::calibrate_essvi_surface;
using volarb::EssviCalibration;
using volarb::EssviParameters;
using volarb::EssviSliceQuotes;
using volarb::EssviStatus;
using volarb::InvalidEssviInputsError;
using volarb::name_of_essvi_status;
using volarb::slices_from_parameters;
using volarb::SliceObservation;
using volarb::SviParameters;
using volarb::SviSurfaceSlice;
using volarb::total_variance;

namespace {

const std::vector<double> expiries = {0.0833, 0.25, 0.5, 1.0};

EssviParameters truth() {
    return EssviParameters{{0.0033, 0.0100, 0.0200, 0.0400}, 0.35, 0.45, -0.85, 0.30};
}

std::vector<EssviSliceQuotes> quotes_from(const std::vector<SviParameters>& slices) {
    std::vector<EssviSliceQuotes> quotes;
    for (std::size_t index = 0; index < slices.size(); ++index) {
        std::vector<SliceObservation> observations;
        for (int step = 0; step <= 20; ++step) {
            const double point = -0.4 + 0.8 * static_cast<double>(step) / 20.0;
            observations.push_back(
                SliceObservation{point, total_variance(slices[index], point), 1.0});
        }
        quotes.push_back(EssviSliceQuotes{expiries[index], observations});
    }
    return quotes;
}

std::vector<SviParameters> healthy_slices() {
    return {
        SviParameters{0.0015, 0.030, -0.70, 0.010, 0.10},
        SviParameters{0.0060, 0.055, -0.65, 0.015, 0.15},
        SviParameters{0.0140, 0.075, -0.60, 0.020, 0.22},
        SviParameters{0.0300, 0.100, -0.55, 0.030, 0.32},
    };
}

}

TEST_CASE("an eSSVI surface is recovered from its own samples", "[essvi]") {
    const EssviCalibration fit = calibrate_essvi_surface(quotes_from(slices_from_parameters(truth())),
                                                         -0.6, 0.6);
    REQUIRE(fit.status == EssviStatus::Converged);
    REQUIRE(fit.weighted_root_mean_square_residual < 1e-10);
    REQUIRE(fit.parameters.curvature_scale == Approx(0.35).epsilon(1e-6));
    REQUIRE(fit.parameters.power_law_exponent == Approx(0.45).epsilon(1e-6));
    REQUIRE(fit.parameters.correlation_intercept == Approx(-0.85).epsilon(1e-6));
    REQUIRE(fit.parameters.correlation_slope == Approx(0.30).epsilon(1e-6));
}

TEST_CASE("the fitted surface passes the acceptance test", "[essvi]") {
    const EssviCalibration fit = calibrate_essvi_surface(quotes_from(healthy_slices()), -0.6, 0.6);
    REQUIRE(fit.status == EssviStatus::Converged);
    REQUIRE(fit.surface_minimum_durrleman_value > 0.0);
    REQUIRE(fit.surface_minimum_total_variance_time_slope > 0.0);
    REQUIRE(fit.slices.size() == expiries.size());
}

TEST_CASE("a calendar violation in the data is repaired by the fit", "[essvi]") {
    std::vector<SviParameters> slices = healthy_slices();
    slices[2] = SviParameters{0.0040, 0.055, -0.60, 0.020, 0.22};
    const EssviCalibration fit = calibrate_essvi_surface(quotes_from(slices), -0.6, 0.6);
    REQUIRE(fit.status == EssviStatus::Converged);
    REQUIRE(fit.surface_minimum_total_variance_time_slope > 0.0);
}

TEST_CASE("every reachable coordinate maps to a valid SVI slice", "[essvi]") {
    for (const double level : {1e-6, 1e-3, 0.04, 1.0, 10.0}) {
        for (const double correlation : {-0.9999, -0.5, 0.0, 0.5, 0.9999}) {
            for (const double curvature : {1e-4, 0.35, 50.0}) {
                const SviParameters slice =
                    volarb::svi_slice_from_essvi(level, curvature, correlation);
                REQUIRE_NOTHROW(volarb::validate_svi_parameters(slice));
                REQUIRE(total_variance(slice, 0.0) == Approx(level).epsilon(1e-12));
            }
        }
    }
}

TEST_CASE("a surface with too few slices or observations is reported rather than fitted", "[essvi]") {
    const std::vector<EssviSliceQuotes> full = quotes_from(healthy_slices());
    REQUIRE(calibrate_essvi_surface({full[0]}, -0.6, 0.6).status == EssviStatus::TooFewSlices);

    std::vector<EssviSliceQuotes> sparse = {full[0], full[1]};
    sparse[1].observations.resize(3);
    REQUIRE(calibrate_essvi_surface(sparse, -0.6, 0.6).status == EssviStatus::TooFewObservations);
}

TEST_CASE("expiries out of order are rejected", "[essvi]") {
    const std::vector<EssviSliceQuotes> full = quotes_from(healthy_slices());
    REQUIRE_THROWS_AS(calibrate_essvi_surface({full[1], full[0]}, -0.6, 0.6), InvalidEssviInputsError);
    REQUIRE_THROWS_AS(calibrate_essvi_surface({full[0], full[1]}, 0.6, -0.6), InvalidEssviInputsError);
}

TEST_CASE("a fit that cannot eliminate arbitrage says so", "[essvi]") {
    std::vector<SviParameters> slices = healthy_slices();
    slices[2] = SviParameters{0.0002, 0.350, -0.85, 0.000, 0.02};
    const EssviCalibration fit = calibrate_essvi_surface(quotes_from(slices), -0.6, 0.6);
    REQUIRE(fit.status == EssviStatus::ArbitrageNotEliminated);
    REQUIRE((fit.surface_minimum_durrleman_value < 0.0 ||
             fit.surface_minimum_total_variance_time_slope < 0.0));
}

TEST_CASE("every reachable coordinate maps to a valid surface", "[essvi]") {
    for (const double extreme : {-1e4, -40.0, -1.0, 0.0, 1.0, 40.0, 1e4}) {
        const std::vector<double> coordinates(8, extreme);
        const EssviParameters parameters = volarb::parameters_from_coordinates(coordinates, 4);
        REQUIRE(parameters.curvature_scale > 0.0);
        for (std::size_t index = 1; index < parameters.atm_total_variance.size(); ++index) {
            REQUIRE(parameters.atm_total_variance[index] >
                    parameters.atm_total_variance[index - 1]);
        }
        for (const SviParameters& slice : slices_from_parameters(parameters)) {
            REQUIRE_NOTHROW(volarb::validate_svi_parameters(slice));
        }
    }
}

TEST_CASE("every eSSVI status has a name", "[essvi]") {
    REQUIRE(name_of_essvi_status(EssviStatus::Converged) == "converged");
    REQUIRE(name_of_essvi_status(EssviStatus::TooFewSlices) == "too_few_slices");
    REQUIRE(name_of_essvi_status(EssviStatus::TooFewObservations) == "too_few_observations");
    REQUIRE(name_of_essvi_status(EssviStatus::SimplexBudgetExhausted) == "simplex_budget_exhausted");
    REQUIRE(name_of_essvi_status(EssviStatus::ArbitrageNotEliminated) == "arbitrage_not_eliminated");
}
