#include "volarb/essvi.hpp"

#include "volarb/simplex.hpp"
#include "volarb/svi_surface.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>

namespace volarb {

namespace {

const std::vector<double> essvi_seed_correlations = {-0.7, -0.3, 0.0};
const std::vector<double> essvi_seed_curvature_fractions = {0.1, 0.3, 0.6};

double bounded_correlation(double argument) {
    return std::min(std::max(std::tanh(argument), -maximum_correlation), maximum_correlation);
}

std::vector<double> atm_total_variance_from_coordinates(const std::vector<double>& coordinates,
                                                        std::size_t slice_count) {
    std::vector<double> levels;
    levels.reserve(slice_count);
    double running = 0.0;
    for (std::size_t index = 0; index < slice_count; ++index) {
        running += bounded_exponential(coordinates[index]);
        levels.push_back(running);
    }
    return levels;
}

double power_law_exponent_from_coordinate(double coordinate) {
    return maximum_power_law_exponent * 0.5 * (1.0 + std::tanh(coordinate));
}

double normalized_position(const std::vector<double>& levels, std::size_t index) {
    const double span = levels.back() - levels.front();
    if (span <= 0.0) {
        return 0.0;
    }
    return (levels[index] - levels.front()) / span;
}

double bounded_power(double base, double exponent) {
    return bounded_exponential(exponent * std::log(base));
}

double curvature_fraction_from_coordinate(double coordinate) {
    const double fraction = 0.5 * (1.0 + std::tanh(coordinate));
    return std::min(std::max(fraction, minimum_curvature_fraction), maximum_curvature_fraction);
}

std::vector<double> penalty_grid(double lowest_log_moneyness, double highest_log_moneyness) {
    const double span = highest_log_moneyness - lowest_log_moneyness;
    std::vector<double> grid;
    grid.reserve(static_cast<std::size_t>(essvi_penalty_grid_steps + 1));
    for (int index = 0; index <= essvi_penalty_grid_steps; ++index) {
        grid.push_back(lowest_log_moneyness +
                       span * static_cast<double>(index) / static_cast<double>(essvi_penalty_grid_steps));
    }
    return grid;
}

double butterfly_penalty(const std::vector<SviParameters>& slices, const std::vector<double>& grid) {
    double total = 0.0;
    for (const SviParameters& parameters : slices) {
        for (const double point : grid) {
            const double shortfall = -durrleman_function(parameters, point);
            if (shortfall > 0.0) {
                total += shortfall * shortfall;
            }
        }
    }
    return essvi_butterfly_penalty_weight * total;
}

double calendar_penalty(const std::vector<SviParameters>& slices, const std::vector<double>& grid) {
    double total = 0.0;
    for (std::size_t index = 1; index < slices.size(); ++index) {
        for (const double point : grid) {
            const double shortfall =
                total_variance(slices[index - 1], point) - total_variance(slices[index], point);
            if (shortfall > 0.0) {
                total += shortfall * shortfall;
            }
        }
    }
    return essvi_calendar_penalty_weight * total;
}

double weighted_squared_residuals(const std::vector<SviParameters>& slices,
                                  const std::vector<EssviSliceQuotes>& quotes) {
    double total = 0.0;
    for (std::size_t index = 0; index < quotes.size(); ++index) {
        for (const SliceObservation& observation : quotes[index].observations) {
            const double residual =
                total_variance(slices[index], observation.log_moneyness) - observation.total_variance;
            total += observation.weight * residual * residual;
        }
    }
    return total;
}

double calibration_objective(const std::vector<double>& coordinates,
                             const std::vector<EssviSliceQuotes>& quotes,
                             const std::vector<double>& grid) {
    const EssviParameters parameters = parameters_from_coordinates(coordinates, quotes.size());
    const std::vector<SviParameters> slices = slices_from_parameters(parameters);
    return weighted_squared_residuals(slices, quotes) + butterfly_penalty(slices, grid) +
           calendar_penalty(slices, grid);
}

double at_the_money_variance(const EssviSliceQuotes& entry) {
    const SliceObservation* closest = &entry.observations.front();
    for (const SliceObservation& observation : entry.observations) {
        const double distance = std::abs(observation.log_moneyness);
        const double best = std::abs(closest->log_moneyness);
        if (distance < best || (distance == best && observation.log_moneyness < closest->log_moneyness)) {
            closest = &observation;
        }
    }
    return std::max(closest->total_variance, minimum_seed_variance);
}

std::vector<double> level_increment_coordinates(const std::vector<EssviSliceQuotes>& quotes) {
    std::vector<double> levels;
    levels.reserve(quotes.size());
    for (const EssviSliceQuotes& entry : quotes) {
        levels.push_back(at_the_money_variance(entry));
    }
    std::vector<double> coordinates{std::log(levels.front())};
    for (std::size_t index = 1; index < levels.size(); ++index) {
        coordinates.push_back(std::log(std::max(levels[index] - levels[index - 1], minimum_seed_increment)));
    }
    return coordinates;
}

std::vector<Coordinates> seed_coordinates(const std::vector<EssviSliceQuotes>& quotes) {
    const std::vector<double> increments = level_increment_coordinates(quotes);
    std::vector<Coordinates> seeds;
    for (const double correlation : essvi_seed_correlations) {
        for (const double fraction : essvi_seed_curvature_fractions) {
            Coordinates seed = increments;
            seed.push_back(std::atanh(2.0 * fraction - 1.0));
            seed.push_back(0.0);
            seed.push_back(std::atanh(correlation));
            seed.push_back(0.0);
            seeds.push_back(seed);
        }
    }
    return seeds;
}

std::vector<double> fitted_surface(const std::vector<SviParameters>& slices) {
    const std::vector<double> points = reference_log_moneyness();
    std::vector<double> surface;
    surface.reserve(slices.size() * points.size());
    for (const SviParameters& parameters : slices) {
        for (const double point : points) {
            surface.push_back(total_variance(parameters, point));
        }
    }
    return surface;
}

int total_observation_count(const std::vector<EssviSliceQuotes>& quotes) {
    std::size_t total = 0;
    for (const EssviSliceQuotes& entry : quotes) {
        total += entry.observations.size();
    }
    return static_cast<int>(total);
}

EssviCalibration unfitted_result(const std::vector<EssviSliceQuotes>& quotes, EssviStatus status) {
    return EssviCalibration{EssviParameters{{}, 0.0, 0.0, 0.0, 0.0},
                            {},
                            0.0,
                            0.0,
                            0,
                            static_cast<int>(quotes.size()),
                            total_observation_count(quotes),
                            {},
                            0.0,
                            0.0,
                            status};
}

double weighted_root_mean_square_residual(const std::vector<SviParameters>& slices,
                                          const std::vector<EssviSliceQuotes>& quotes) {
    double total_weight = 0.0;
    for (const EssviSliceQuotes& entry : quotes) {
        for (const SliceObservation& observation : entry.observations) {
            total_weight += observation.weight;
        }
    }
    if (total_weight <= 0.0) {
        return 0.0;
    }
    return std::sqrt(weighted_squared_residuals(slices, quotes) / total_weight);
}

void validate_quotes(const std::vector<EssviSliceQuotes>& quotes) {
    for (const EssviSliceQuotes& entry : quotes) {
        if (entry.years_to_expiry <= 0.0) {
            throw InvalidEssviInputsError("years_to_expiry must be positive, got " +
                                          std::to_string(entry.years_to_expiry));
        }
    }
    for (std::size_t index = 1; index < quotes.size(); ++index) {
        if (quotes[index].years_to_expiry <= quotes[index - 1].years_to_expiry) {
            throw InvalidEssviInputsError("slices must be strictly increasing in years_to_expiry");
        }
    }
}

EssviStatus calibration_status(bool settled, SviSurfaceStatus surface_status) {
    if (surface_status != SviSurfaceStatus::ArbitrageFreeOnGrid) {
        return EssviStatus::ArbitrageNotEliminated;
    }
    if (!settled) {
        return EssviStatus::SimplexBudgetExhausted;
    }
    return EssviStatus::Converged;
}

}

std::string name_of_essvi_status(EssviStatus status) {
    switch (status) {
    case EssviStatus::Converged:
        return "converged";
    case EssviStatus::TooFewSlices:
        return "too_few_slices";
    case EssviStatus::TooFewObservations:
        return "too_few_observations";
    case EssviStatus::SimplexBudgetExhausted:
        return "simplex_budget_exhausted";
    case EssviStatus::ArbitrageNotEliminated:
        return "arbitrage_not_eliminated";
    }
    return "arbitrage_not_eliminated";
}

double maximum_curvature_scale(const std::vector<double>& levels,
                               const std::vector<double>& correlations, double exponent) {
    double bound = std::numeric_limits<double>::infinity();
    for (std::size_t index = 0; index < levels.size(); ++index) {
        const double weight = 1.0 + std::abs(correlations[index]);
        const double slope_bound =
            durrleman_sufficient_bound / (bounded_power(levels[index], 1.0 - exponent) * weight);
        const double curvature_bound = std::sqrt(
            durrleman_sufficient_bound / (bounded_power(levels[index], 1.0 - 2.0 * exponent) * weight));
        bound = std::min(bound, std::min(slope_bound, curvature_bound));
    }
    return bound;
}

EssviParameters parameters_from_coordinates(const std::vector<double>& coordinates,
                                            std::size_t slice_count) {
    const std::vector<double> levels = atm_total_variance_from_coordinates(coordinates, slice_count);
    const double exponent = power_law_exponent_from_coordinate(coordinates[slice_count + 1]);
    const double intercept = coordinates[slice_count + 2];
    const double slope = coordinates[slice_count + 3];
    std::vector<double> correlations;
    correlations.reserve(slice_count);
    for (std::size_t index = 0; index < slice_count; ++index) {
        correlations.push_back(bounded_correlation(intercept + slope * normalized_position(levels, index)));
    }
    const double fraction = curvature_fraction_from_coordinate(coordinates[slice_count]);
    return EssviParameters{levels, fraction * maximum_curvature_scale(levels, correlations, exponent),
                           exponent, intercept, slope};
}

double curvature_at(const EssviParameters& parameters, std::size_t index) {
    const double level = parameters.atm_total_variance[index];
    const double exponent =
        std::log(parameters.curvature_scale) - parameters.power_law_exponent * std::log(level);
    return bounded_exponential(exponent);
}

double correlation_at(const EssviParameters& parameters, std::size_t index) {
    const double position = normalized_position(parameters.atm_total_variance, index);
    return bounded_correlation(parameters.correlation_intercept +
                               parameters.correlation_slope * position);
}

SviParameters svi_slice_from_essvi(double level, double curvature, double correlation) {
    const double complement = std::sqrt(1.0 - correlation * correlation);
    return SviParameters{0.5 * level * (1.0 - correlation * correlation), 0.5 * level * curvature,
                         correlation, -correlation / curvature, complement / curvature};
}

std::vector<SviParameters> slices_from_parameters(const EssviParameters& parameters) {
    std::vector<SviParameters> slices;
    slices.reserve(parameters.atm_total_variance.size());
    for (std::size_t index = 0; index < parameters.atm_total_variance.size(); ++index) {
        slices.push_back(svi_slice_from_essvi(parameters.atm_total_variance[index],
                                              curvature_at(parameters, index),
                                              correlation_at(parameters, index)));
    }
    return slices;
}

EssviCalibration calibrate_essvi_surface(const std::vector<EssviSliceQuotes>& quotes,
                                         double lowest_log_moneyness, double highest_log_moneyness) {
    if (quotes.size() < minimum_essvi_slices) {
        return unfitted_result(quotes, EssviStatus::TooFewSlices);
    }
    validate_quotes(quotes);
    for (const EssviSliceQuotes& entry : quotes) {
        if (entry.observations.size() < static_cast<std::size_t>(minimum_observations)) {
            return unfitted_result(quotes, EssviStatus::TooFewObservations);
        }
    }
    if (!(highest_log_moneyness > lowest_log_moneyness)) {
        throw InvalidEssviInputsError("the penalty range must be non-empty and increasing");
    }

    const std::vector<double> grid = penalty_grid(lowest_log_moneyness, highest_log_moneyness);
    const Objective evaluate = [&](const Coordinates& coordinates) {
        return calibration_objective(coordinates, quotes, grid);
    };

    std::optional<SimplexOutcome> best_outcome;
    int total_iterations = 0;
    for (const Coordinates& seed : seed_coordinates(quotes)) {
        const SimplexOutcome outcome = minimise_by_simplex(seed, evaluate);
        total_iterations += outcome.iterations;
        if (!best_outcome.has_value() || outcome.value < best_outcome->value) {
            best_outcome = outcome;
        }
    }

    const EssviParameters parameters = parameters_from_coordinates(best_outcome->coordinates, quotes.size());
    const std::vector<SviParameters> slices = slices_from_parameters(parameters);

    std::vector<SviSurfaceSlice> surface;
    surface.reserve(quotes.size());
    for (std::size_t index = 0; index < quotes.size(); ++index) {
        surface.push_back(SviSurfaceSlice{quotes[index].years_to_expiry, slices[index]});
    }
    const SviSurfaceScan scan =
        scan_svi_surface(surface, lowest_log_moneyness, highest_log_moneyness,
                         default_surface_scan_steps, default_time_steps_per_interval);

    return EssviCalibration{parameters,
                            slices,
                            best_outcome->value,
                            weighted_root_mean_square_residual(slices, quotes),
                            total_iterations,
                            static_cast<int>(quotes.size()),
                            total_observation_count(quotes),
                            fitted_surface(slices),
                            scan.minimum_durrleman_value,
                            scan.minimum_total_variance_time_slope,
                            calibration_status(best_outcome->settled, scan.status)};
}

}
