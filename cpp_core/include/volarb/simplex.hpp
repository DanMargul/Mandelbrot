#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <functional>
#include <numeric>
#include <optional>
#include <vector>

namespace volarb {

inline constexpr int maximum_simplex_iterations = 4000;
inline constexpr double simplex_spread_tolerance = 1e-12;
inline constexpr double simplex_initial_step = 0.5;
inline constexpr double reflection_coefficient = 1.0;
inline constexpr double expansion_coefficient = 2.0;
inline constexpr double contraction_coefficient = 0.5;
inline constexpr double shrink_coefficient = 0.5;

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

std::vector<std::size_t> simplex_vertex_order(const std::vector<Coordinates>& vertices,
                                              const std::vector<double>& values);
Coordinates centroid_excluding_worst(const std::vector<Coordinates>& vertices,
                                     const std::vector<std::size_t>& order);
Coordinates combine(const Coordinates& base, const Coordinates& direction, double scale);
double simplex_spread(const std::vector<Coordinates>& vertices, const std::vector<std::size_t>& order);
std::optional<SimplexStep> contracted_replacement(const ContractionContext& context,
                                                  const Objective& evaluate);

SimplexOutcome minimise_by_simplex(const Coordinates& seed, const Objective& evaluate);

}
