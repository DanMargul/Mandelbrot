#include "volarb/hedging.hpp"

#include "volarb/pricing.hpp"
#include "volarb/random_source.hpp"

#include <algorithm>
#include <cmath>

namespace volarb {

namespace {

struct CallGreeks {
    double price;
    double delta;
    double gamma;
};

void validate_inputs(const HedgingInputs& inputs) {
    if (inputs.spot <= 0.0) {
        throw InvalidHedgingInputsError("spot must be positive, got " + std::to_string(inputs.spot));
    }
    if (inputs.strike <= 0.0) {
        throw InvalidHedgingInputsError("strike must be positive, got " + std::to_string(inputs.strike));
    }
    if (inputs.years_to_expiry <= 0.0) {
        throw InvalidHedgingInputsError("years_to_expiry must be positive, got " +
                                        std::to_string(inputs.years_to_expiry));
    }
    if (inputs.volatility <= 0.0) {
        throw InvalidHedgingInputsError("volatility must be positive, got " +
                                        std::to_string(inputs.volatility));
    }
    if (inputs.steps < minimum_hedging_steps) {
        throw InvalidHedgingInputsError("steps must be at least " +
                                        std::to_string(minimum_hedging_steps) + ", got " +
                                        std::to_string(inputs.steps));
    }
    if (inputs.proportional_cost < 0.0) {
        throw InvalidHedgingInputsError("proportional_cost must not be negative, got " +
                                        std::to_string(inputs.proportional_cost));
    }
    if (inputs.risk_aversion <= minimum_risk_aversion) {
        throw InvalidHedgingInputsError("risk_aversion must be positive, got " +
                                        std::to_string(inputs.risk_aversion));
    }
}

void validate_policy(const BandPolicy& policy) {
    if (policy.rule == BandRule::Fixed && policy.fixed_width < 0.0) {
        throw InvalidHedgingInputsError("fixed_width must not be negative, got " +
                                        std::to_string(policy.fixed_width));
    }
}

CallGreeks call_greeks(const HedgingInputs& inputs, double spot, double remaining) {
    const BlackScholesGreeks priced = black_scholes_price_and_greeks(BlackScholesInputs{
        spot, inputs.strike, remaining, inputs.volatility, 1.0, OptionType::Call});
    return CallGreeks{priced.price, priced.delta_with_respect_to_forward,
                      priced.gamma_with_respect_to_forward};
}

double band_for(const BandPolicy& policy, const HedgingInputs& inputs, double spot, double gamma) {
    if (policy.rule == BandRule::Fixed) {
        return policy.fixed_width;
    }
    return whalley_wilmott_band(spot, gamma, inputs.proportional_cost, inputs.risk_aversion);
}

UnsignedWide wide_from_decimal(const std::string& text) {
    if (text.empty()) {
        throw InvalidHedgingInputsError("a seed must be a decimal integer string");
    }
    UnsignedWide value = 0;
    for (const char digit : text) {
        if (digit < '0' || digit > '9') {
            throw InvalidHedgingInputsError("a seed must be a decimal integer string, got " + text);
        }
        value = value * 10 + static_cast<UnsignedWide>(digit - '0');
    }
    return value;
}

}

BandRule band_rule_from_name(const std::string& name) {
    if (name == "fixed") {
        return BandRule::Fixed;
    }
    if (name == "whalley_wilmott") {
        return BandRule::WhalleyWilmott;
    }
    throw InvalidHedgingInputsError("rule must be 'fixed' or 'whalley_wilmott', got " + name);
}

std::string name_of_band_rule(BandRule rule) {
    return rule == BandRule::Fixed ? "fixed" : "whalley_wilmott";
}

double whalley_wilmott_band(double spot, double gamma, double proportional_cost,
                            double risk_aversion) {
    if (risk_aversion <= minimum_risk_aversion) {
        throw InvalidHedgingInputsError("risk_aversion must be positive, got " +
                                        std::to_string(risk_aversion));
    }
    const double numerator = whalley_wilmott_factor * proportional_cost * spot * gamma * gamma;
    return std::pow(numerator / risk_aversion, one_third);
}

PathOutcome hedge_one_path(const HedgingInputs& inputs, const BandPolicy& policy,
                           const std::vector<double>& shocks) {
    const double step_years = inputs.years_to_expiry / static_cast<double>(inputs.steps);
    const double drift = -0.5 * inputs.volatility * inputs.volatility * step_years;
    const double diffusion = inputs.volatility * std::sqrt(step_years);

    double spot = inputs.spot;
    const CallGreeks opening = call_greeks(inputs, spot, inputs.years_to_expiry);
    double hedge = opening.delta;
    double cost = inputs.proportional_cost * std::abs(hedge) * spot;
    int rebalances = 1;
    double hedge_profit = 0.0;

    for (int index = 0; index < inputs.steps; ++index) {
        const double moved = spot * std::exp(drift + diffusion * shocks[static_cast<std::size_t>(index)]);
        hedge_profit += hedge * (moved - spot);
        spot = moved;
        const double remaining = inputs.years_to_expiry - step_years * static_cast<double>(index + 1);
        if (remaining <= 0.0) {
            break;
        }
        const CallGreeks current = call_greeks(inputs, spot, remaining);
        const double width = std::max(band_for(policy, inputs, spot, current.gamma), minimum_band);
        if (std::abs(hedge - current.delta) > width) {
            cost += inputs.proportional_cost * std::abs(current.delta - hedge) * spot;
            hedge = current.delta;
            rebalances += 1;
        }
    }

    const double payoff = std::max(spot - inputs.strike, 0.0);
    cost += inputs.proportional_cost * std::abs(hedge) * spot;
    return PathOutcome{opening.price - payoff + hedge_profit - cost, cost, rebalances + 1};
}

HedgingStatistics hedging_statistics(const HedgingInputs& inputs, const BandPolicy& policy,
                                     const std::string& initial_state, const std::string& sequence,
                                     int path_count) {
    validate_inputs(inputs);
    validate_policy(policy);
    if (path_count < minimum_paths) {
        throw InvalidHedgingInputsError("path_count must be at least " + std::to_string(minimum_paths) +
                                        ", got " + std::to_string(path_count));
    }

    std::vector<double> profits;
    profits.reserve(static_cast<std::size_t>(path_count));
    double total_cost = 0.0;
    long long total_rebalances = 0;
    PcgState source = seeded_source(wide_from_decimal(initial_state), wide_from_decimal(sequence));
    for (int index = 0; index < path_count; ++index) {
        std::vector<double> shocks;
        shocks.reserve(static_cast<std::size_t>(inputs.steps));
        for (int step = 0; step < inputs.steps; step += 2) {
            const NormalPair pair = next_standard_normal_pair(source);
            source = pair.state;
            shocks.push_back(pair.first);
            if (static_cast<int>(shocks.size()) < inputs.steps) {
                shocks.push_back(pair.second);
            }
        }
        const PathOutcome outcome = hedge_one_path(inputs, policy, shocks);
        profits.push_back(outcome.terminal_profit);
        total_cost += outcome.transaction_cost;
        total_rebalances += outcome.rebalance_count;
    }

    double mean = 0.0;
    for (const double profit : profits) {
        mean += profit;
    }
    mean /= static_cast<double>(path_count);
    double squared = 0.0;
    for (const double profit : profits) {
        squared += (profit - mean) * (profit - mean);
    }
    const double variance = squared / static_cast<double>(path_count - 1);

    return HedgingStatistics{path_count,
                             mean,
                             std::sqrt(std::max(variance, 0.0)),
                             total_cost / static_cast<double>(path_count),
                             static_cast<double>(total_rebalances) / static_cast<double>(path_count),
                             mean - 0.5 * inputs.risk_aversion * variance};
}

}
