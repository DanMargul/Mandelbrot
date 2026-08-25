#include "volarb/svi.hpp"
#include "volarb/svi_calibration.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::calibrate_svi_slice;
using volarb::name_of_svi_calibration_status;
using volarb::scan_svi_slice;
using volarb::SliceObservation;
using volarb::SviCalibration;
using volarb::SviCalibrationStatus;
using volarb::SviParameters;
using volarb::SviStatus;
using volarb::total_variance;

namespace {

const SviParameters truth{0.0002, 0.018, -0.65, 0.01, 0.10};

std::vector<SliceObservation> sample(const SviParameters& parameters, double lowest, double highest,
                                     int count) {
    std::vector<SliceObservation> observations;
    for (int index = 0; index < count; ++index) {
        const double point =
            lowest + (highest - lowest) * static_cast<double>(index) / static_cast<double>(count - 1);
        observations.push_back(SliceObservation{point, total_variance(parameters, point), 1.0});
    }
    return observations;
}

}

TEST_CASE("calibration recovers a slice it was sampled from", "[svi_calibration]") {
    const auto observations = sample(truth, -0.30, 0.30, 21);
    const SviCalibration calibration = calibrate_svi_slice(observations, -0.6, 0.6);
    REQUIRE(calibration.status == SviCalibrationStatus::Converged);
    REQUIRE(calibration.observation_count == 21);
    for (const SliceObservation& observation : observations) {
        const double fitted = total_variance(calibration.parameters, observation.log_moneyness);
        REQUIRE(fitted == Approx(observation.total_variance).epsilon(1e-6));
    }
}

TEST_CASE("a calibrated slice passes the arbitrage scan", "[svi_calibration]") {
    const SviCalibration calibration = calibrate_svi_slice(sample(truth, -0.30, 0.30, 21), -0.6, 0.6);
    REQUIRE(scan_svi_slice(calibration.parameters, -0.6, 0.6).status == SviStatus::ArbitrageFreeOnGrid);
}

TEST_CASE("the fitted parameters are inside the valid region", "[svi_calibration]") {
    const SviCalibration calibration = calibrate_svi_slice(sample(truth, -0.30, 0.30, 21), -0.6, 0.6);
    REQUIRE(calibration.parameters.b >= 0.0);
    REQUIRE(std::abs(calibration.parameters.rho) < 1.0);
    REQUIRE(calibration.parameters.sigma > 0.0);
    const double floor = calibration.parameters.a + calibration.parameters.b * calibration.parameters.sigma *
                                                        std::sqrt(1.0 - calibration.parameters.rho *
                                                                            calibration.parameters.rho);
    REQUIRE(floor >= 0.0);
}

TEST_CASE("too few observations is reported rather than fitted", "[svi_calibration]") {
    const SviCalibration calibration = calibrate_svi_slice(sample(truth, -0.1, 0.1, 3), -0.6, 0.6);
    REQUIRE(calibration.status == SviCalibrationStatus::TooFewObservations);
    REQUIRE(calibration.simplex_iterations == 0);
    REQUIRE(calibration.observation_count == 3);
}

TEST_CASE("an inverted penalty range is rejected", "[svi_calibration]") {
    REQUIRE_THROWS_AS(calibrate_svi_slice(sample(truth, -0.30, 0.30, 21), 0.6, -0.6),
                      volarb::InvalidCalibrationInputsError);
}

TEST_CASE("calibration status names round trip", "[svi_calibration]") {
    REQUIRE(name_of_svi_calibration_status(SviCalibrationStatus::Converged) == "converged");
    REQUIRE(name_of_svi_calibration_status(SviCalibrationStatus::TooFewObservations) ==
            "too_few_observations");
}
