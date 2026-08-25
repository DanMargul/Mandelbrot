#include "volarb/simplex.hpp"

namespace volarb {

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
    const std::size_t dimension = vertices[0].size();
    Coordinates centroid(dimension, 0.0);
    const std::size_t kept = order.size() - 1;
    for (std::size_t position = 0; position < kept; ++position) {
        for (std::size_t axis = 0; axis < dimension; ++axis) {
            centroid[axis] += vertices[order[position]][axis];
        }
    }
    for (double& value : centroid) {
        value /= static_cast<double>(kept);
    }
    return centroid;
}

Coordinates combine(const Coordinates& base, const Coordinates& direction, double scale) {
    Coordinates result(base.size());
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
    for (std::size_t axis = 0; axis < seed.size(); ++axis) {
        Coordinates shifted = seed;
        shifted[axis] += simplex_initial_step;
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

}
