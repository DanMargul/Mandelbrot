#pragma once

#include "volarb/simplex.hpp"
#include "volarb/svi.hpp"

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

enum class SviCalibrationStatus { Converged, TooFewObservations, SimplexBudgetExhausted };

inline constexpr int parameter_count = 5;
inline constexpr int minimum_observations = 5;
inline constexpr double butterfly_penalty_weight = 1e4;
inline constexpr int penalty_grid_steps = 64;
inline constexpr double maximum_log_parameter = 30.0;
inline constexpr double maximum_correlation = 0.9999;
inline constexpr double reference_log_moneyness_lowest = -0.4;
inline constexpr double reference_log_moneyness_highest = 0.4;
inline constexpr int reference_log_moneyness_steps = 16;

class InvalidCalibrationInputsError : public std::invalid_argument {
  public:
    explicit InvalidCalibrationInputsError(const std::string& message) : std::invalid_argument(message) {}
};

struct SliceObservation {
    double log_moneyness;
    double total_variance;
    double weight;
};

struct SviCalibration {
    SviParameters parameters;
    double objective;
    double weighted_root_mean_square_residual;
    int simplex_iterations;
    int observation_count;
    std::vector<double> fitted_curve;
    SviCalibrationStatus status;
};

std::string name_of_svi_calibration_status(SviCalibrationStatus status);

double bounded_exponential(double coordinate);
SviParameters parameters_from_coordinates(const std::vector<double>& coordinates);
std::vector<double> reference_log_moneyness();
std::vector<double> fitted_curve(const SviParameters& parameters);
double weighted_squared_residuals(const SviParameters& parameters,
                                  const std::vector<SliceObservation>& observations);

SviCalibration calibrate_svi_slice(const std::vector<SliceObservation>& observations,
                                   double lowest_log_moneyness, double highest_log_moneyness);

}
