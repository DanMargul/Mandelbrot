#pragma once

#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace volarb {

inline constexpr int ascent_passes = 400;
inline constexpr int projection_passes = 40;
inline constexpr double portfolio_step_size = 0.05;
inline constexpr double minimum_portfolio_gamma = 1e-12;
inline constexpr double minimum_direction_norm = 1e-18;
inline constexpr double gamma_derivative_step = 1e-6;

class InvalidPortfolioInputsError : public std::invalid_argument {
  public:
    explicit InvalidPortfolioInputsError(const std::string& message)
        : std::invalid_argument(message) {}
};

struct Candidate {
    double expected_edge;
    double vega;
    double gamma;
    double theta;
    std::vector<double> factor_exposures;
    double maximum_size;
    double spread_cost;
};

struct PortfolioLimits {
    double vega_budget;
    double gamma_budget;
    double theta_budget;
    double factor_tolerance;
    double risk_aversion;
    double proportional_cost;
    double spot;
    double volatility;
    double years_to_expiry;
};

struct Allocation {
    std::vector<double> weights;
    double expected_edge;
    double spread_cost;
    double hedging_cost;
    double objective;
    double net_vega;
    double net_gamma;
    double net_theta;
    double worst_factor_exposure;
    bool charged_for_hedging;
};

double hedging_cost_of_gamma(double gamma, const PortfolioLimits& limits);
Allocation report(const std::vector<double>& weights, const std::vector<Candidate>& candidates,
                  const PortfolioLimits& limits, bool charge_hedging);
Allocation allocate(const std::vector<Candidate>& candidates, const PortfolioLimits& limits,
                    bool charge_hedging);

}
