#pragma once

#include "volarb/svi.hpp"
#include "volarb/svi_calibration.hpp"

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

enum class EssviStatus {
    Converged,
    TooFewSlices,
    TooFewObservations,
    SimplexBudgetExhausted,
    ArbitrageNotEliminated
};

inline constexpr int global_parameter_count = 4;
inline constexpr std::size_t minimum_essvi_slices = 2;
inline constexpr double essvi_butterfly_penalty_weight = 1e4;
inline constexpr double essvi_calendar_penalty_weight = 1e4;
inline constexpr int essvi_penalty_grid_steps = 64;
inline constexpr double maximum_power_law_exponent = 1.0;
inline constexpr double maximum_curvature_fraction = 0.9999;
inline constexpr double minimum_curvature_fraction = 1e-12;
inline constexpr double durrleman_sufficient_bound = 4.0;
inline constexpr double minimum_seed_variance = 1e-8;
inline constexpr double minimum_seed_increment = 1e-10;

class InvalidEssviInputsError : public std::invalid_argument {
  public:
    explicit InvalidEssviInputsError(const std::string& message) : std::invalid_argument(message) {}
};

struct EssviSliceQuotes {
    double years_to_expiry;
    std::vector<SliceObservation> observations;
};

struct EssviParameters {
    std::vector<double> atm_total_variance;
    double curvature_scale;
    double power_law_exponent;
    double correlation_intercept;
    double correlation_slope;
};

struct EssviCalibration {
    EssviParameters parameters;
    std::vector<SviParameters> slices;
    double objective;
    double weighted_root_mean_square_residual;
    int simplex_iterations;
    int slice_count;
    int observation_count;
    std::vector<double> fitted_surface;
    double surface_minimum_durrleman_value;
    double surface_minimum_total_variance_time_slope;
    EssviStatus status;
};

std::string name_of_essvi_status(EssviStatus status);

EssviParameters parameters_from_coordinates(const std::vector<double>& coordinates,
                                            std::size_t slice_count);
SviParameters svi_slice_from_essvi(double level, double curvature, double correlation);
std::vector<SviParameters> slices_from_parameters(const EssviParameters& parameters);
double curvature_at(const EssviParameters& parameters, std::size_t index);
double correlation_at(const EssviParameters& parameters, std::size_t index);
double maximum_curvature_scale(const std::vector<double>& levels,
                               const std::vector<double>& correlations, double exponent);

EssviCalibration calibrate_essvi_surface(const std::vector<EssviSliceQuotes>& quotes,
                                         double lowest_log_moneyness, double highest_log_moneyness);

}
