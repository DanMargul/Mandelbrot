#pragma once

#include "volarb/svi.hpp"

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

enum class SviSurfaceStatus {
    ArbitrageFreeOnGrid,
    ButterflyArbitrageFound,
    CalendarArbitrageFound,
    InvalidSurface
};

inline constexpr int default_surface_scan_steps = 256;
inline constexpr int minimum_surface_scan_steps = 2;
inline constexpr std::size_t minimum_surface_slices = 2;
inline constexpr int default_time_steps_per_interval = 8;
inline constexpr int minimum_time_steps_per_interval = 1;
inline constexpr double calendar_tolerance = -1e-12;
inline constexpr double minimum_durrleman_denominator = 1e-12;
inline constexpr double round_trip_moneyness_step = 1e-4;
inline constexpr double round_trip_time_step = 1e-5;
inline constexpr double round_trip_local_variance_floor = 1e-6;

class InvalidSviSurfaceError : public std::invalid_argument {
  public:
    explicit InvalidSviSurfaceError(const std::string& message) : std::invalid_argument(message) {}
};

struct SviSurfaceSlice {
    double years_to_expiry;
    SviParameters parameters;
};

struct SurfaceInterval {
    SviSurfaceSlice earlier;
    SviSurfaceSlice later;
};

struct InterpolatedSlice {
    SviParameters earlier;
    SviParameters later;
    double fraction;
    double time_span;
};

struct SviSurfaceScan {
    int slice_count;
    int scan_steps;
    int time_steps_per_interval;
    double minimum_durrleman_value;
    double log_moneyness_at_minimum_durrleman_value;
    double years_to_expiry_at_minimum_durrleman_value;
    double minimum_risk_neutral_density;
    double minimum_total_variance_time_slope;
    double log_moneyness_at_minimum_time_slope;
    double years_to_expiry_at_minimum_time_slope;
    double minimum_local_variance;
    double log_moneyness_at_minimum_local_variance;
    double years_to_expiry_at_minimum_local_variance;
    double worst_local_variance_round_trip_error;
    double log_moneyness_at_worst_round_trip_error;
    int round_trip_point_count;
    SviSurfaceStatus status;
};

std::string name_of_svi_surface_status(SviSurfaceStatus status);

void validate_svi_surface(const std::vector<SviSurfaceSlice>& slices);

InterpolatedSlice interpolated_slice_between(const SviSurfaceSlice& earlier, const SviSurfaceSlice& later,
                                             double fraction);

double interpolated_total_variance(const InterpolatedSlice& interpolated, double log_moneyness);
double interpolated_first_derivative(const InterpolatedSlice& interpolated, double log_moneyness);
double interpolated_second_derivative(const InterpolatedSlice& interpolated, double log_moneyness);
double interpolated_time_slope(const InterpolatedSlice& interpolated, double log_moneyness);
double interpolated_durrleman_value(const InterpolatedSlice& interpolated, double log_moneyness);
double interpolated_risk_neutral_density(const InterpolatedSlice& interpolated, double log_moneyness);
double interpolated_local_variance(const InterpolatedSlice& interpolated, double log_moneyness);
double price_space_curvature(const InterpolatedSlice& interpolated, double log_moneyness);
double local_variance_from_prices(const InterpolatedSlice& interpolated, double log_moneyness);

SviSurfaceScan scan_svi_surface(const std::vector<SviSurfaceSlice>& slices, double lowest_log_moneyness,
                                double highest_log_moneyness,
                                int scan_steps = default_surface_scan_steps,
                                int time_steps_per_interval = default_time_steps_per_interval);

}
