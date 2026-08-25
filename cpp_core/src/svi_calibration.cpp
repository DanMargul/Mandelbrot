#include "volarb/svi_calibration.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <numeric>
#include <optional>
#include <utility>

namespace volarb {

namespace {

const std::vector<double> seed_correlations = {-0.7, -0.3, 0.0, 0.3};
const std::vector<double> seed_width_multipliers = {0.5, 1.0, 2.0};

using Coordinates = std::vector<double>;
using Objective = std::function<double(const Coordinates&)>;

struct SimplexStep {
    Coordinates coordinates;
    double value;
};

struct ContractionContext {
    const Coordinates& centroid;
    const Coordinates& worst_vertex;
    double worst_value;
    const Coordinates& reflected;
    double reflected_value;
};

struct SimplexOutcome {
    Coordinates coordinates;
    double value;
    int iterations;
    bool settled;
};

double butterfly_penalty(const SviParameters& parameters, double lowest_log_moneyness,
                         double highest_log_moneyness) {
    const double span = highest_log_moneyness - lowest_log_moneyness;
    double total = 0.0;
    for (int index = 0; index <= penalty_grid_steps; ++index) {
        const double point =
            lowest_log_moneyness + span * static_cast<double>(index) / static_cast<double>(penalty_grid_steps);
        const double shortfall = -durrleman_function(parameters, point);
        if (shortfall > 0.0) {
            total += shortfall * shortfall;
        }
    }
    return butterfly_penalty_weight * total;
}

std::vector<Coordinates> seed_coordinates(const std::vector<SliceObservation>& observations) {
    double smallest = observations[0].total_variance;
    double largest = observations[0].total_variance;
    double at_minimum = observations[0].log_moneyness;
    double lowest_moneyness = observations[0].log_moneyness;
    double highest_moneyness = observations[0].log_moneyness;
    for (const SliceObservation& observation : observations) {
        if (observation.total_variance < smallest) {
            smallest = observation.total_variance;
            at_minimum = observation.log_moneyness;
        }
        largest = std::max(largest, observation.total_variance);
        lowest_moneyness = std::min(lowest_moneyness, observation.log_moneyness);
        highest_moneyness = std::max(highest_moneyness, observation.log_moneyness);
    }
    smallest = std::max(smallest, 1e-8);
    const double width = std::max(highest_moneyness - lowest_moneyness, 1e-3);
    const double slope = (largest - smallest) / width;

    std::vector<Coordinates> seeds;
    for (const double correlation : seed_correlations) {
        for (const double multiplier : seed_width_multipliers) {
            seeds.push_back(Coordinates{
                std::log(smallest),
                std::log(std::max(slope, 1e-6)),
                std::atanh(correlation),
                at_minimum,
                std::log(width * multiplier * 0.25),
            });
        }
    }
    return seeds;
}

std::vector<std::size_t> simplex_vertex_order(const std::vector<Coordinates>& vertices,
                                              const std::vector<double>& values) {
    std::vector<std::size_t> order(values.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right) {
        if (values[left] != values[right]) {
            return values[left] < values[right];
        }
        return vertices[left] < vertices[right];
    });
    return order;
}

Coordinates centroid_excluding_worst(const std::vector<Coordinates>& vertices,
                                     const std::vector<std::size_t>& order) {
    Coordinates centroid(static_cast<std::size_t>(parameter_count), 0.0);
    const std::size_t kept = order.size() - 1;
    for (std::size_t position = 0; position < kept; ++position) {
        for (int axis = 0; axis < parameter_count; ++axis) {
            centroid[static_cast<std::size_t>(axis)] += vertices[order[position]][static_cast<std::size_t>(axis)];
        }
    }
    for (double& value : centroid) {
        value /= static_cast<double>(kept);
    }
    return centroid;
}

Coordinates combine(const Coordinates& base, const Coordinates& direction, double scale) {
    Coordinates result(static_cast<std::size_t>(parameter_count));
    for (std::size_t axis = 0; axis < result.size(); ++axis) {
        result[axis] = base[axis] + scale * (direction[axis] - base[axis]);
    }
    return result;
}

double simplex_spread(const std::vector<Coordinates>& vertices, const std::vector<std::size_t>& order) {
    const Coordinates& best = vertices[order[0]];
    double spread = 0.0;
    for (std::size_t position = 1; position < order.size(); ++position) {
        for (std::size_t axis = 0; axis < best.size(); ++axis) {
            spread = std::max(spread, std::abs(vertices[order[position]][axis] - best[axis]));
        }
    }
    return spread;
}

std::optional<SimplexStep> contracted_replacement(const ContractionContext& context,
                                                  const Objective& evaluate) {
    if (context.reflected_value < context.worst_value) {
        const Coordinates outside = combine(context.centroid, context.reflected, contraction_coefficient);
        const double outside_value = evaluate(outside);
        if (outside_value <= context.reflected_value) {
            return SimplexStep{outside, outside_value};
        }
        return std::nullopt;
    }
    const Coordinates inside = combine(context.centroid, context.worst_vertex, contraction_coefficient);
    const double inside_value = evaluate(inside);
    if (inside_value < context.worst_value) {
        return SimplexStep{inside, inside_value};
    }
    return std::nullopt;
}

SimplexOutcome minimise_by_simplex(const Coordinates& seed, const Objective& evaluate) {
    std::vector<Coordinates> vertices{seed};
    for (int axis = 0; axis < parameter_count; ++axis) {
        Coordinates shifted = seed;
        shifted[static_cast<std::size_t>(axis)] += simplex_initial_step;
        vertices.push_back(shifted);
    }
    std::vector<double> values;
    values.reserve(vertices.size());
    for (const Coordinates& vertex : vertices) {
        values.push_back(evaluate(vertex));
    }

    for (int iteration = 1; iteration <= maximum_simplex_iterations; ++iteration) {
        const std::vector<std::size_t> order = simplex_vertex_order(vertices, values);
        if (simplex_spread(vertices, order) <= simplex_spread_tolerance) {
            return SimplexOutcome{vertices[order[0]], values[order[0]], iteration, true};
        }

        const std::size_t best = order[0];
        const std::size_t second_worst = order[order.size() - 2];
        const std::size_t worst = order.back();
        const Coordinates centroid = centroid_excluding_worst(vertices, order);

        const Coordinates reflected = combine(centroid, vertices[worst], -reflection_coefficient);
        const double reflected_value = evaluate(reflected);

        if (reflected_value < values[best]) {
            const Coordinates expanded = combine(centroid, reflected, expansion_coefficient);
            const double expanded_value = evaluate(expanded);
            if (expanded_value < reflected_value) {
                vertices[worst] = expanded;
                values[worst] = expanded_value;
            } else {
                vertices[worst] = reflected;
                values[worst] = reflected_value;
            }
            continue;
        }

        if (reflected_value < values[second_worst]) {
            vertices[worst] = reflected;
            values[worst] = reflected_value;
            continue;
        }

        const ContractionContext context{centroid, vertices[worst], values[worst], reflected,
                                         reflected_value};
        const std::optional<SimplexStep> contraction = contracted_replacement(context, evaluate);
        if (contraction.has_value()) {
            vertices[worst] = contraction->coordinates;
            values[worst] = contraction->value;
            continue;
        }

        const Coordinates anchor = vertices[best];
        for (std::size_t index = 0; index < vertices.size(); ++index) {
            if (index == best) {
                continue;
            }
            vertices[index] = combine(anchor, vertices[index], shrink_coefficient);
            values[index] = evaluate(vertices[index]);
        }
    }

    const std::vector<std::size_t> order = simplex_vertex_order(vertices, values);
    return SimplexOutcome{vertices[order[0]], values[order[0]], maximum_simplex_iterations, false};
}

double weighted_root_mean_square_residual(const SviParameters& parameters,
                                          const std::vector<SliceObservation>& observations) {
    double total_weight = 0.0;
    for (const SliceObservation& observation : observations) {
        total_weight += observation.weight;
    }
    if (total_weight <= 0.0) {
        return 0.0;
    }
    return std::sqrt(weighted_squared_residuals(parameters, observations) / total_weight);
}

}

std::string name_of_svi_calibration_status(SviCalibrationStatus status) {
    switch (status) {
    case SviCalibrationStatus::Converged:
        return "converged";
    case SviCalibrationStatus::TooFewObservations:
        return "too_few_observations";
    case SviCalibrationStatus::SimplexBudgetExhausted:
        return "simplex_budget_exhausted";
    }
    return "simplex_budget_exhausted";
}

double bounded_exponential(double coordinate) {
    return std::exp(std::min(std::max(coordinate, -maximum_log_parameter), maximum_log_parameter));
}

std::vector<double> reference_log_moneyness() {
    const double span = reference_log_moneyness_highest - reference_log_moneyness_lowest;
    std::vector<double> points;
    points.reserve(static_cast<std::size_t>(reference_log_moneyness_steps + 1));
    for (int index = 0; index <= reference_log_moneyness_steps; ++index) {
        points.push_back(reference_log_moneyness_lowest +
                         span * static_cast<double>(index) /
                             static_cast<double>(reference_log_moneyness_steps));
    }
    return points;
}

std::vector<double> fitted_curve(const SviParameters& parameters) {
    std::vector<double> curve;
    for (const double point : reference_log_moneyness()) {
        curve.push_back(total_variance(parameters, point));
    }
    return curve;
}

SviParameters parameters_from_coordinates(const std::vector<double>& coordinates) {
    const double minimum_variance = bounded_exponential(coordinates[0]);
    const double b = bounded_exponential(coordinates[1]);
    const double rho = std::min(std::max(std::tanh(coordinates[2]), -maximum_correlation), maximum_correlation);
    const double m = coordinates[3];
    const double sigma = bounded_exponential(coordinates[4]);
    const double a = minimum_variance - b * sigma * std::sqrt(1.0 - rho * rho);
    return SviParameters{a, b, rho, m, sigma};
}

double weighted_squared_residuals(const SviParameters& parameters,
                                  const std::vector<SliceObservation>& observations) {
    double total = 0.0;
    for (const SliceObservation& observation : observations) {
        const double residual =
            total_variance(parameters, observation.log_moneyness) - observation.total_variance;
        total += observation.weight * residual * residual;
    }
    return total;
}

SviCalibration calibrate_svi_slice(const std::vector<SliceObservation>& observations,
                                   double lowest_log_moneyness, double highest_log_moneyness) {
    if (static_cast<int>(observations.size()) < minimum_observations) {
        return SviCalibration{
            SviParameters{0.0, 0.0, 0.0, 0.0, 1.0},
            0.0,
            0.0,
            0,
            static_cast<int>(observations.size()),
            std::vector<double>(static_cast<std::size_t>(reference_log_moneyness_steps + 1), 0.0),
            SviCalibrationStatus::TooFewObservations};
    }
    if (!(highest_log_moneyness > lowest_log_moneyness)) {
        throw InvalidCalibrationInputsError("the penalty range must be non-empty and increasing");
    }

    const Objective evaluate = [&](const Coordinates& coordinates) {
        const SviParameters parameters = parameters_from_coordinates(coordinates);
        return weighted_squared_residuals(parameters, observations) +
               butterfly_penalty(parameters, lowest_log_moneyness, highest_log_moneyness);
    };

    std::optional<SimplexOutcome> best;
    int total_iterations = 0;
    for (const Coordinates& seed : seed_coordinates(observations)) {
        const SimplexOutcome outcome = minimise_by_simplex(seed, evaluate);
        total_iterations += outcome.iterations;
        if (!best.has_value() || outcome.value < best->value) {
            best = outcome;
        }
    }

    const SviParameters parameters = parameters_from_coordinates(best->coordinates);
    return SviCalibration{
        parameters,
        best->value,
        weighted_root_mean_square_residual(parameters, observations),
        total_iterations,
        static_cast<int>(observations.size()),
        fitted_curve(parameters),
        best->settled ? SviCalibrationStatus::Converged : SviCalibrationStatus::SimplexBudgetExhausted,
    };
}

}
