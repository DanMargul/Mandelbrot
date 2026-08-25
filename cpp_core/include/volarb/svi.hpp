#pragma once

#include <stdexcept>
#include <string>

namespace volarb {

enum class SviStatus { ArbitrageFreeOnGrid, ButterflyArbitrageFound, InvalidParameters };

inline constexpr double minimum_total_variance = 1e-12;
inline constexpr int default_scan_steps = 512;
inline constexpr int minimum_scan_steps = 2;
inline constexpr int refinement_passes = 60;
inline constexpr double golden_section_ratio = 0.6180339887498949;
inline constexpr double butterfly_tolerance = -1e-12;

class InvalidSviParametersError : public std::invalid_argument {
  public:
    explicit InvalidSviParametersError(const std::string& message) : std::invalid_argument(message) {}
};

struct SviParameters {
    double a;
    double b;
    double rho;
    double m;
    double sigma;
};

struct SviSliceScan {
    double minimum_durrleman_value;
    double log_moneyness_at_minimum;
    double minimum_total_variance;
    double minimum_risk_neutral_density;
    int scan_steps;
    SviStatus status;
};

std::string name_of_svi_status(SviStatus status);

void validate_svi_parameters(const SviParameters& parameters);
double total_variance(const SviParameters& parameters, double log_moneyness);
double total_variance_first_derivative(const SviParameters& parameters, double log_moneyness);
double total_variance_second_derivative(const SviParameters& parameters, double log_moneyness);
double implied_volatility(const SviParameters& parameters, double log_moneyness, double years_to_expiry);
double durrleman_value(double log_moneyness, double variance, double slope, double curvature);
double density_weight(double log_moneyness, double variance);
double durrleman_function(const SviParameters& parameters, double log_moneyness);
double risk_neutral_density(const SviParameters& parameters, double log_moneyness);

SviSliceScan scan_svi_slice(const SviParameters& parameters, double lowest_log_moneyness,
                            double highest_log_moneyness, int scan_steps = default_scan_steps);

}
