#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

enum class BandRule { Fixed, WhalleyWilmott };

inline constexpr double whalley_wilmott_factor = 1.5;
inline constexpr double minimum_band = 1e-12;
inline constexpr double minimum_risk_aversion = 1e-12;
inline constexpr int minimum_paths = 2;
inline constexpr int minimum_hedging_steps = 1;
inline constexpr double one_third = 1.0 / 3.0;

class InvalidHedgingInputsError : public std::invalid_argument {
  public:
    explicit InvalidHedgingInputsError(const std::string& message) : std::invalid_argument(message) {}
};

struct HedgingInputs {
    double spot;
    double strike;
    double years_to_expiry;
    double volatility;
    int steps;
    double proportional_cost;
    double risk_aversion;
};

struct BandPolicy {
    BandRule rule;
    double fixed_width;
};

struct PathOutcome {
    double terminal_profit;
    double transaction_cost;
    int rebalance_count;
};

struct HedgingStatistics {
    int path_count;
    double mean_profit;
    double profit_standard_deviation;
    double mean_transaction_cost;
    double mean_rebalance_count;
    double certainty_equivalent;
};

BandRule band_rule_from_name(const std::string& name);
std::string name_of_band_rule(BandRule rule);

double whalley_wilmott_band(double spot, double gamma, double proportional_cost,
                            double risk_aversion);
PathOutcome hedge_one_path(const HedgingInputs& inputs, const BandPolicy& policy,
                           const std::vector<double>& shocks);
HedgingStatistics hedging_statistics(const HedgingInputs& inputs, const BandPolicy& policy,
                                     const std::string& initial_state, const std::string& sequence,
                                     int path_count);

}
