#include "volarb/portfolio.hpp"

#include "volarb/hedging.hpp"

#include <algorithm>
#include <cmath>

namespace volarb {

namespace {

using ConstraintRow = std::pair<std::vector<double>, double>;

std::size_t validate_candidates(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) {
        throw InvalidPortfolioInputsError("a portfolio needs at least one candidate");
    }
    const std::size_t factor_count = candidates.front().factor_exposures.size();
    for (const Candidate& candidate : candidates) {
        if (candidate.factor_exposures.size() != factor_count) {
            throw InvalidPortfolioInputsError(
                "a candidate carries " + std::to_string(candidate.factor_exposures.size()) +
                " factor exposures against " + std::to_string(factor_count));
        }
        if (candidate.maximum_size < 0.0) {
            throw InvalidPortfolioInputsError("maximum_size must not be negative, got " +
                                              std::to_string(candidate.maximum_size));
        }
        if (candidate.spread_cost < 0.0) {
            throw InvalidPortfolioInputsError("spread_cost must not be negative, got " +
                                              std::to_string(candidate.spread_cost));
        }
    }
    return factor_count;
}

void validate_limits(const PortfolioLimits& limits) {
    if (limits.vega_budget < 0.0 || limits.gamma_budget < 0.0 || limits.theta_budget < 0.0 ||
        limits.factor_tolerance < 0.0) {
        throw InvalidPortfolioInputsError("budgets and tolerances must not be negative");
    }
    if (limits.risk_aversion <= 0.0) {
        throw InvalidPortfolioInputsError("risk_aversion must be positive, got " +
                                          std::to_string(limits.risk_aversion));
    }
    if (limits.spot <= 0.0) {
        throw InvalidPortfolioInputsError("spot must be positive, got " + std::to_string(limits.spot));
    }
    if (limits.volatility <= 0.0) {
        throw InvalidPortfolioInputsError("volatility must be positive, got " +
                                          std::to_string(limits.volatility));
    }
    if (limits.years_to_expiry <= 0.0) {
        throw InvalidPortfolioInputsError("years_to_expiry must be positive, got " +
                                          std::to_string(limits.years_to_expiry));
    }
    if (limits.proportional_cost < 0.0) {
        throw InvalidPortfolioInputsError("proportional_cost must not be negative, got " +
                                          std::to_string(limits.proportional_cost));
    }
}

double weighted_total(const std::vector<double>& weights, const std::vector<double>& loadings) {
    double total = 0.0;
    for (std::size_t index = 0; index < weights.size(); ++index) {
        total += weights[index] * loadings[index];
    }
    return total;
}

std::vector<double> column_of(const std::vector<Candidate>& candidates, std::size_t index) {
    std::vector<double> values;
    values.reserve(candidates.size());
    for (const Candidate& candidate : candidates) {
        values.push_back(candidate.factor_exposures[index]);
    }
    return values;
}

std::vector<double> greek_column(const std::vector<Candidate>& candidates, int which) {
    std::vector<double> values;
    values.reserve(candidates.size());
    for (const Candidate& candidate : candidates) {
        const double picked = which == 0   ? candidate.vega
                              : which == 1 ? candidate.gamma
                              : which == 2 ? candidate.theta
                                           : candidate.expected_edge;
        values.push_back(picked);
    }
    return values;
}

std::vector<ConstraintRow> constraint_rows(const std::vector<Candidate>& candidates,
                                           const PortfolioLimits& limits, std::size_t factor_count) {
    std::vector<ConstraintRow> rows;
    rows.emplace_back(greek_column(candidates, 0), limits.vega_budget);
    rows.emplace_back(greek_column(candidates, 1), limits.gamma_budget);
    rows.emplace_back(greek_column(candidates, 2), limits.theta_budget);
    for (std::size_t index = 0; index < factor_count; ++index) {
        rows.emplace_back(column_of(candidates, index), limits.factor_tolerance);
    }
    return rows;
}

std::vector<double> clipped_to_size(const std::vector<double>& weights,
                                    const std::vector<Candidate>& candidates) {
    std::vector<double> result;
    result.reserve(weights.size());
    for (std::size_t index = 0; index < weights.size(); ++index) {
        const double limit = candidates[index].maximum_size;
        result.push_back(std::min(std::max(weights[index], -limit), limit));
    }
    return result;
}

std::vector<double> projected_onto_slab(const std::vector<double>& weights,
                                        const std::vector<double>& direction, double bound) {
    const double exposure = weighted_total(weights, direction);
    if (std::abs(exposure) <= bound) {
        return weights;
    }
    const double squared = weighted_total(direction, direction);
    if (squared < minimum_direction_norm) {
        return weights;
    }
    const double target = exposure > 0.0 ? bound : -bound;
    const double scale = (exposure - target) / squared;
    std::vector<double> result;
    result.reserve(weights.size());
    for (std::size_t index = 0; index < weights.size(); ++index) {
        result.push_back(weights[index] - scale * direction[index]);
    }
    return result;
}

std::vector<double> projected(const std::vector<double>& weights,
                              const std::vector<Candidate>& candidates,
                              const std::vector<ConstraintRow>& rows) {
    std::vector<double> current = clipped_to_size(weights, candidates);
    for (int pass = 0; pass < projection_passes; ++pass) {
        for (const ConstraintRow& row : rows) {
            current = projected_onto_slab(current, row.first, row.second);
        }
        current = clipped_to_size(current, candidates);
    }
    return current;
}

double hedging_cost_slope(double gamma, const PortfolioLimits& limits) {
    const double above = hedging_cost_of_gamma(gamma + gamma_derivative_step, limits);
    const double below = hedging_cost_of_gamma(gamma - gamma_derivative_step, limits);
    return (above - below) / (2.0 * gamma_derivative_step);
}

double subgradient_of(double raw, double weight, double spread_cost) {
    if (weight > 0.0) {
        return raw - spread_cost;
    }
    if (weight < 0.0) {
        return raw + spread_cost;
    }
    if (raw > spread_cost) {
        return raw - spread_cost;
    }
    if (raw < -spread_cost) {
        return raw + spread_cost;
    }
    return 0.0;
}

std::vector<double> ascent_direction(const std::vector<double>& weights,
                                     const std::vector<Candidate>& candidates,
                                     const PortfolioLimits& limits, bool charge_hedging) {
    double slope = 0.0;
    if (charge_hedging) {
        slope = hedging_cost_slope(weighted_total(weights, greek_column(candidates, 1)), limits);
    }
    std::vector<double> gradient;
    gradient.reserve(candidates.size());
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        const Candidate& candidate = candidates[index];
        const double raw = candidate.expected_edge - slope * candidate.gamma;
        gradient.push_back(subgradient_of(raw, weights[index], candidate.spread_cost));
    }
    return gradient;
}

double scale_of(const std::vector<Candidate>& candidates) {
    double largest = 0.0;
    for (const Candidate& candidate : candidates) {
        largest = std::max(largest, candidate.maximum_size);
    }
    return largest > 0.0 ? largest : 1.0;
}

}

double hedging_cost_of_gamma(double gamma, const PortfolioLimits& limits) {
    const double magnitude = std::abs(gamma);
    if (magnitude < minimum_portfolio_gamma || limits.proportional_cost <= 0.0) {
        return 0.0;
    }
    const double band =
        whalley_wilmott_band(limits.spot, magnitude, limits.proportional_cost, limits.risk_aversion);
    const double delta_volatility = magnitude * limits.volatility * limits.spot;
    return limits.proportional_cost * limits.spot * delta_volatility * delta_volatility / band *
           limits.years_to_expiry;
}

Allocation report(const std::vector<double>& weights, const std::vector<Candidate>& candidates,
                  const PortfolioLimits& limits, bool charge_hedging) {
    const double edge = weighted_total(weights, greek_column(candidates, 3));
    double spread = 0.0;
    for (std::size_t index = 0; index < weights.size(); ++index) {
        spread += std::abs(weights[index]) * candidates[index].spread_cost;
    }
    const double net_gamma = weighted_total(weights, greek_column(candidates, 1));
    const double hedging = hedging_cost_of_gamma(net_gamma, limits);
    double worst = 0.0;
    for (std::size_t index = 0; index < candidates.front().factor_exposures.size(); ++index) {
        worst = std::max(worst, std::abs(weighted_total(weights, column_of(candidates, index))));
    }
    return Allocation{weights,
                      edge,
                      spread,
                      hedging,
                      edge - spread - hedging,
                      weighted_total(weights, greek_column(candidates, 0)),
                      net_gamma,
                      weighted_total(weights, greek_column(candidates, 2)),
                      worst,
                      charge_hedging};
}

Allocation allocate(const std::vector<Candidate>& candidates, const PortfolioLimits& limits,
                    bool charge_hedging) {
    const std::size_t factor_count = validate_candidates(candidates);
    validate_limits(limits);

    const std::vector<ConstraintRow> rows = constraint_rows(candidates, limits, factor_count);
    const double step = portfolio_step_size * scale_of(candidates);
    std::vector<double> weights = projected(std::vector<double>(candidates.size(), 0.0), candidates, rows);
    for (int pass = 0; pass < ascent_passes; ++pass) {
        const std::vector<double> gradient =
            ascent_direction(weights, candidates, limits, charge_hedging);
        const double norm = std::sqrt(std::max(weighted_total(gradient, gradient), 0.0));
        if (norm < minimum_direction_norm) {
            break;
        }
        std::vector<double> moved;
        moved.reserve(weights.size());
        for (std::size_t index = 0; index < weights.size(); ++index) {
            moved.push_back(weights[index] + step * gradient[index] / norm);
        }
        weights = projected(moved, candidates, rows);
    }
    return report(weights, candidates, limits, charge_hedging);
}

}
