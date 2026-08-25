#include "volarb/svi.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <utility>
#include <vector>

namespace volarb {

namespace {

struct MinimumLocation {
    double log_moneyness;
    double value;
};

MinimumLocation refined_minimum(const SviParameters& parameters, double lower, double upper) {
    double left = upper - golden_section_ratio * (upper - lower);
    double right = lower + golden_section_ratio * (upper - lower);
    double left_value = durrleman_function(parameters, left);
    double right_value = durrleman_function(parameters, right);

    for (int pass = 0; pass < refinement_passes; ++pass) {
        if (left_value < right_value) {
            upper = right;
            right = left;
            right_value = left_value;
            left = upper - golden_section_ratio * (upper - lower);
            left_value = durrleman_function(parameters, left);
        } else {
            lower = left;
            left = right;
            left_value = right_value;
            right = lower + golden_section_ratio * (upper - lower);
            right_value = durrleman_function(parameters, right);
        }
    }

    if (left_value <= right_value) {
        return MinimumLocation{left, left_value};
    }
    return MinimumLocation{right, right_value};
}

}

std::string name_of_svi_status(SviStatus status) {
    switch (status) {
    case SviStatus::ArbitrageFreeOnGrid:
        return "arbitrage_free_on_grid";
    case SviStatus::ButterflyArbitrageFound:
        return "butterfly_arbitrage_found";
    case SviStatus::InvalidParameters:
        return "invalid_parameters";
    }
    return "invalid_parameters";
}

void validate_svi_parameters(const SviParameters& parameters) {
    if (parameters.b < 0.0) {
        throw InvalidSviParametersError("b must not be negative, got " + std::to_string(parameters.b));
    }
    if (!(parameters.rho > -1.0 && parameters.rho < 1.0)) {
        throw InvalidSviParametersError("rho must lie strictly inside (-1, 1), got " +
                                        std::to_string(parameters.rho));
    }
    if (parameters.sigma <= 0.0) {
        throw InvalidSviParametersError("sigma must be positive, got " + std::to_string(parameters.sigma));
    }
    const double floor =
        parameters.a + parameters.b * parameters.sigma * std::sqrt(1.0 - parameters.rho * parameters.rho);
    if (floor < 0.0) {
        throw InvalidSviParametersError("minimum total variance must not be negative, got " +
                                        std::to_string(floor));
    }
}

double total_variance(const SviParameters& parameters, double log_moneyness) {
    const double centred = log_moneyness - parameters.m;
    const double root = std::sqrt(centred * centred + parameters.sigma * parameters.sigma);
    return parameters.a + parameters.b * (parameters.rho * centred + root);
}

double total_variance_first_derivative(const SviParameters& parameters, double log_moneyness) {
    const double centred = log_moneyness - parameters.m;
    const double root = std::sqrt(centred * centred + parameters.sigma * parameters.sigma);
    return parameters.b * (parameters.rho + centred / root);
}

double total_variance_second_derivative(const SviParameters& parameters, double log_moneyness) {
    const double centred = log_moneyness - parameters.m;
    const double root = std::sqrt(centred * centred + parameters.sigma * parameters.sigma);
    return parameters.b * parameters.sigma * parameters.sigma / (root * root * root);
}

double implied_volatility(const SviParameters& parameters, double log_moneyness, double years_to_expiry) {
    return std::sqrt(std::max(total_variance(parameters, log_moneyness), 0.0) / years_to_expiry);
}

double durrleman_value(double log_moneyness, double variance, double slope, double curvature) {
    const double balance = 1.0 - log_moneyness * slope / (2.0 * variance);
    return balance * balance - 0.25 * slope * slope * (1.0 / variance + 0.25) + 0.5 * curvature;
}

double density_weight(double log_moneyness, double variance) {
    const double root = std::sqrt(variance);
    const double standardized = -log_moneyness / root - 0.5 * root;
    return std::exp(-0.5 * standardized * standardized) / std::sqrt(2.0 * std::numbers::pi * variance);
}

double durrleman_function(const SviParameters& parameters, double log_moneyness) {
    const double variance = std::max(total_variance(parameters, log_moneyness), minimum_total_variance);
    const double slope = total_variance_first_derivative(parameters, log_moneyness);
    const double curvature = total_variance_second_derivative(parameters, log_moneyness);
    return durrleman_value(log_moneyness, variance, slope, curvature);
}

double risk_neutral_density(const SviParameters& parameters, double log_moneyness) {
    const double variance = std::max(total_variance(parameters, log_moneyness), minimum_total_variance);
    return durrleman_function(parameters, log_moneyness) * density_weight(log_moneyness, variance);
}

SviSliceScan scan_svi_slice(const SviParameters& parameters, double lowest_log_moneyness,
                            double highest_log_moneyness, int scan_steps) {
    validate_svi_parameters(parameters);
    if (!(highest_log_moneyness > lowest_log_moneyness)) {
        throw InvalidSviParametersError("the scan range must be non-empty and increasing");
    }
    if (scan_steps < minimum_scan_steps) {
        throw InvalidSviParametersError("scan_steps must be at least " +
                                        std::to_string(minimum_scan_steps) + ", got " +
                                        std::to_string(scan_steps));
    }

    const double span = highest_log_moneyness - lowest_log_moneyness;
    std::vector<double> grid;
    std::vector<double> values;
    grid.reserve(static_cast<std::size_t>(scan_steps + 1));
    values.reserve(static_cast<std::size_t>(scan_steps + 1));
    for (int index = 0; index <= scan_steps; ++index) {
        const double point =
            lowest_log_moneyness + span * static_cast<double>(index) / static_cast<double>(scan_steps);
        grid.push_back(point);
        values.push_back(durrleman_function(parameters, point));
    }

    std::size_t best_index = 0;
    for (std::size_t index = 1; index < values.size(); ++index) {
        if (values[index] < values[best_index]) {
            best_index = index;
        }
    }

    const double neighbourhood_lower = grid[best_index == 0 ? 0 : best_index - 1];
    const double neighbourhood_upper =
        grid[std::min(best_index + 1, static_cast<std::size_t>(scan_steps))];
    const MinimumLocation refined = refined_minimum(parameters, neighbourhood_lower, neighbourhood_upper);

    double worst_point = grid[best_index];
    double worst_value = values[best_index];
    if (refined.value <= worst_value) {
        worst_point = refined.log_moneyness;
        worst_value = refined.value;
    }

    double smallest_total_variance = total_variance(parameters, grid[0]);
    for (const double point : grid) {
        smallest_total_variance = std::min(smallest_total_variance, total_variance(parameters, point));
    }

    return SviSliceScan{
        worst_value,
        worst_point,
        smallest_total_variance,
        risk_neutral_density(parameters, worst_point),
        scan_steps,
        worst_value >= butterfly_tolerance ? SviStatus::ArbitrageFreeOnGrid
                                           : SviStatus::ButterflyArbitrageFound,
    };
}

}
