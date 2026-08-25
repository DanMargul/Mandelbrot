#include "volarb/svi_surface.hpp"

#include "volarb/pricing.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

namespace volarb {

namespace {

struct ScanGrid {
    std::vector<double> log_moneyness;
    int scan_steps;
    int time_steps_per_interval;
};

struct SurfaceExtremes {
    double durrleman_value = std::numeric_limits<double>::infinity();
    double durrleman_log_moneyness = 0.0;
    double durrleman_years = 0.0;
    double risk_neutral_density = 0.0;
    double time_slope = std::numeric_limits<double>::infinity();
    double time_slope_log_moneyness = 0.0;
    double time_slope_years = 0.0;
    double local_variance = std::numeric_limits<double>::infinity();
    double local_variance_log_moneyness = 0.0;
    double local_variance_years = 0.0;
    double round_trip_error = 0.0;
    double round_trip_log_moneyness = 0.0;
    int round_trip_points = 0;
};

struct MinimumLocation {
    double log_moneyness;
    double value;
};

template <typename Evaluate>
MinimumLocation refined_minimum_of(Evaluate evaluate, double lower, double upper) {
    double left = upper - golden_section_ratio * (upper - lower);
    double right = lower + golden_section_ratio * (upper - lower);
    double left_value = evaluate(left);
    double right_value = evaluate(right);

    for (int pass = 0; pass < refinement_passes; ++pass) {
        if (left_value < right_value) {
            upper = right;
            right = left;
            right_value = left_value;
            left = upper - golden_section_ratio * (upper - lower);
            left_value = evaluate(left);
        } else {
            lower = left;
            left = right;
            left_value = right_value;
            right = lower + golden_section_ratio * (upper - lower);
            right_value = evaluate(right);
        }
    }

    if (left_value <= right_value) {
        return MinimumLocation{left, left_value};
    }
    return MinimumLocation{right, right_value};
}

template <typename Evaluate>
MinimumLocation grid_minimum_with_refinement(Evaluate evaluate, const ScanGrid& grid) {
    const std::vector<double>& points = grid.log_moneyness;
    std::vector<double> values;
    values.reserve(points.size());
    for (const double point : points) {
        values.push_back(evaluate(point));
    }

    std::size_t best_index = 0;
    for (std::size_t index = 1; index < values.size(); ++index) {
        if (values[index] < values[best_index]) {
            best_index = index;
        }
    }

    const double lower = points[best_index == 0 ? 0 : best_index - 1];
    const double upper = points[std::min(best_index + 1, static_cast<std::size_t>(grid.scan_steps))];
    const MinimumLocation refined = refined_minimum_of(evaluate, lower, upper);
    if (refined.value > values[best_index]) {
        return MinimumLocation{points[best_index], values[best_index]};
    }
    return refined;
}

double out_of_the_money_price(const InterpolatedSlice& interpolated, double log_moneyness,
                              bool use_put_branch) {
    const double variance =
        std::max(interpolated_total_variance(interpolated, log_moneyness), minimum_total_variance);
    const double root = std::sqrt(variance);
    const double d1 = -log_moneyness / root + 0.5 * root;
    const double d2 = d1 - root;
    if (use_put_branch) {
        return std::exp(log_moneyness) * standard_normal_cumulative_distribution(-d2) -
               standard_normal_cumulative_distribution(-d1);
    }
    return standard_normal_cumulative_distribution(d1) -
           std::exp(log_moneyness) * standard_normal_cumulative_distribution(d2);
}

InterpolatedSlice shifted_in_time(const InterpolatedSlice& interpolated, double years_offset) {
    return InterpolatedSlice{interpolated.earlier, interpolated.later,
                             interpolated.fraction + years_offset / interpolated.time_span,
                             interpolated.time_span};
}

std::vector<double> moneyness_grid(double lowest, double highest, int scan_steps) {
    const double span = highest - lowest;
    std::vector<double> grid;
    grid.reserve(static_cast<std::size_t>(scan_steps + 1));
    for (int index = 0; index <= scan_steps; ++index) {
        grid.push_back(lowest + span * static_cast<double>(index) / static_cast<double>(scan_steps));
    }
    return grid;
}

std::vector<double> scan_times_for_interval(int time_steps_per_interval, bool include_lower_knot) {
    std::vector<double> fractions;
    for (int index = include_lower_knot ? 0 : 1; index <= time_steps_per_interval; ++index) {
        fractions.push_back(static_cast<double>(index) / static_cast<double>(time_steps_per_interval));
    }
    return fractions;
}

MinimumLocation record_durrleman(SurfaceExtremes& extremes, const InterpolatedSlice& interpolated,
                                 const ScanGrid& grid, double years) {
    const MinimumLocation found = grid_minimum_with_refinement(
        [&](double argument) { return interpolated_durrleman_value(interpolated, argument); }, grid);
    if (found.value < extremes.durrleman_value) {
        extremes.durrleman_value = found.value;
        extremes.durrleman_log_moneyness = found.log_moneyness;
        extremes.durrleman_years = years;
        extremes.risk_neutral_density =
            interpolated_risk_neutral_density(interpolated, found.log_moneyness);
    }
    return found;
}

void record_time_slope(SurfaceExtremes& extremes, const InterpolatedSlice& interpolated,
                       const ScanGrid& grid, double years) {
    const MinimumLocation found = grid_minimum_with_refinement(
        [&](double argument) { return interpolated_time_slope(interpolated, argument); }, grid);
    if (found.value < extremes.time_slope) {
        extremes.time_slope = found.value;
        extremes.time_slope_log_moneyness = found.log_moneyness;
        extremes.time_slope_years = years;
    }
}

void record_local_variance(SurfaceExtremes& extremes, const InterpolatedSlice& interpolated,
                           const ScanGrid& grid, double years) {
    const MinimumLocation found = grid_minimum_with_refinement(
        [&](double argument) { return interpolated_local_variance(interpolated, argument); }, grid);
    if (found.value < extremes.local_variance) {
        extremes.local_variance = found.value;
        extremes.local_variance_log_moneyness = found.log_moneyness;
        extremes.local_variance_years = years;
    }
}

void record_round_trip(SurfaceExtremes& extremes, const InterpolatedSlice& interpolated,
                       const std::vector<double>& grid) {
    for (const double point : grid) {
        const double analytic = interpolated_local_variance(interpolated, point);
        if (analytic < round_trip_local_variance_floor) {
            continue;
        }
        if (price_space_curvature(interpolated, point) <= 0.0) {
            continue;
        }
        const double error = std::abs(local_variance_from_prices(interpolated, point) - analytic) / analytic;
        extremes.round_trip_points += 1;
        if (error > extremes.round_trip_error) {
            extremes.round_trip_error = error;
            extremes.round_trip_log_moneyness = point;
        }
    }
}

SviSurfaceStatus surface_status(const SurfaceExtremes& extremes) {
    if (extremes.durrleman_value < butterfly_tolerance) {
        return SviSurfaceStatus::ButterflyArbitrageFound;
    }
    if (extremes.time_slope < calendar_tolerance) {
        return SviSurfaceStatus::CalendarArbitrageFound;
    }
    return SviSurfaceStatus::ArbitrageFreeOnGrid;
}

InterpolatedSlice slice_at_fraction(const SurfaceInterval& interval, double fraction) {
    return interpolated_slice_between(interval.earlier, interval.later, fraction);
}

double years_at_fraction(const SurfaceInterval& interval, double fraction) {
    const double span = interval.later.years_to_expiry - interval.earlier.years_to_expiry;
    return interval.earlier.years_to_expiry + fraction * span;
}

MinimumLocation record_at_fraction(SurfaceExtremes& extremes, const SurfaceInterval& interval,
                                   const ScanGrid& grid, double fraction) {
    const InterpolatedSlice interpolated = slice_at_fraction(interval, fraction);
    const double years = years_at_fraction(interval, fraction);
    const MinimumLocation found = record_durrleman(extremes, interpolated, grid, years);
    record_local_variance(extremes, interpolated, grid, years);
    return found;
}

double durrleman_profile(const SurfaceInterval& interval, const ScanGrid& grid, double fraction) {
    const InterpolatedSlice interpolated = slice_at_fraction(interval, fraction);
    return grid_minimum_with_refinement(
               [&](double argument) { return interpolated_durrleman_value(interpolated, argument); },
               grid)
        .value;
}

void refine_durrleman_in_time(SurfaceExtremes& extremes, const SurfaceInterval& interval,
                              const ScanGrid& grid, double fraction) {
    const double step = 1.0 / static_cast<double>(grid.time_steps_per_interval);
    const double lower = std::max(fraction - step, 0.0);
    const double upper = std::min(fraction + step, 1.0);
    if (!(upper > lower)) {
        return;
    }
    const MinimumLocation refined = refined_minimum_of(
        [&](double argument) { return durrleman_profile(interval, grid, argument); }, lower, upper);
    record_at_fraction(extremes, interval, grid, refined.log_moneyness);
}

void scan_surface_interval(SurfaceExtremes& extremes, const SurfaceInterval& interval,
                           const ScanGrid& grid, bool include_lower_knot) {
    double worst_fraction = 0.0;
    double worst_value = std::numeric_limits<double>::infinity();
    for (const double fraction :
         scan_times_for_interval(grid.time_steps_per_interval, include_lower_knot)) {
        const MinimumLocation found = record_at_fraction(extremes, interval, grid, fraction);
        if (found.value < worst_value) {
            worst_fraction = fraction;
            worst_value = found.value;
        }
    }

    refine_durrleman_in_time(extremes, interval, grid, worst_fraction);

    record_time_slope(extremes, slice_at_fraction(interval, 0.0), grid,
                      interval.later.years_to_expiry);
    record_round_trip(extremes, slice_at_fraction(interval, 0.5), grid.log_moneyness);
}

}

std::string name_of_svi_surface_status(SviSurfaceStatus status) {
    switch (status) {
    case SviSurfaceStatus::ArbitrageFreeOnGrid:
        return "arbitrage_free_on_grid";
    case SviSurfaceStatus::ButterflyArbitrageFound:
        return "butterfly_arbitrage_found";
    case SviSurfaceStatus::CalendarArbitrageFound:
        return "calendar_arbitrage_found";
    case SviSurfaceStatus::InvalidSurface:
        return "invalid_surface";
    }
    return "invalid_surface";
}

void validate_svi_surface(const std::vector<SviSurfaceSlice>& slices) {
    if (slices.size() < minimum_surface_slices) {
        throw InvalidSviSurfaceError("a surface needs at least " + std::to_string(minimum_surface_slices) +
                                     " slices, got " + std::to_string(slices.size()));
    }
    for (const SviSurfaceSlice& entry : slices) {
        if (entry.years_to_expiry <= 0.0) {
            throw InvalidSviSurfaceError("years_to_expiry must be positive, got " +
                                         std::to_string(entry.years_to_expiry));
        }
        validate_svi_parameters(entry.parameters);
    }
    for (std::size_t index = 1; index < slices.size(); ++index) {
        const double span = slices[index].years_to_expiry - slices[index - 1].years_to_expiry;
        if (span <= 0.0) {
            throw InvalidSviSurfaceError("slices must be strictly increasing in years_to_expiry");
        }
        if (span <= 2.0 * round_trip_time_step) {
            throw InvalidSviSurfaceError("adjacent expiries must be more than " +
                                         std::to_string(2.0 * round_trip_time_step) +
                                         " years apart, got " + std::to_string(span));
        }
    }
}

InterpolatedSlice interpolated_slice_between(const SviSurfaceSlice& earlier, const SviSurfaceSlice& later,
                                             double fraction) {
    return InterpolatedSlice{earlier.parameters, later.parameters, fraction,
                             later.years_to_expiry - earlier.years_to_expiry};
}

double interpolated_total_variance(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double earlier = total_variance(interpolated.earlier, log_moneyness);
    const double later = total_variance(interpolated.later, log_moneyness);
    return (1.0 - interpolated.fraction) * earlier + interpolated.fraction * later;
}

double interpolated_first_derivative(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double earlier = total_variance_first_derivative(interpolated.earlier, log_moneyness);
    const double later = total_variance_first_derivative(interpolated.later, log_moneyness);
    return (1.0 - interpolated.fraction) * earlier + interpolated.fraction * later;
}

double interpolated_second_derivative(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double earlier = total_variance_second_derivative(interpolated.earlier, log_moneyness);
    const double later = total_variance_second_derivative(interpolated.later, log_moneyness);
    return (1.0 - interpolated.fraction) * earlier + interpolated.fraction * later;
}

double interpolated_time_slope(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double earlier = total_variance(interpolated.earlier, log_moneyness);
    const double later = total_variance(interpolated.later, log_moneyness);
    return (later - earlier) / interpolated.time_span;
}

double interpolated_durrleman_value(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double variance =
        std::max(interpolated_total_variance(interpolated, log_moneyness), minimum_total_variance);
    const double slope = interpolated_first_derivative(interpolated, log_moneyness);
    const double curvature = interpolated_second_derivative(interpolated, log_moneyness);
    return durrleman_value(log_moneyness, variance, slope, curvature);
}

double interpolated_risk_neutral_density(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double variance =
        std::max(interpolated_total_variance(interpolated, log_moneyness), minimum_total_variance);
    return interpolated_durrleman_value(interpolated, log_moneyness) *
           density_weight(log_moneyness, variance);
}

double interpolated_local_variance(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double denominator = std::max(interpolated_durrleman_value(interpolated, log_moneyness),
                                        minimum_durrleman_denominator);
    return interpolated_time_slope(interpolated, log_moneyness) / denominator;
}

double price_space_curvature(const InterpolatedSlice& interpolated, double log_moneyness) {
    const bool use_put_branch = log_moneyness < 0.0;
    const double centre = out_of_the_money_price(interpolated, log_moneyness, use_put_branch);
    const double above =
        out_of_the_money_price(interpolated, log_moneyness + round_trip_moneyness_step, use_put_branch);
    const double below =
        out_of_the_money_price(interpolated, log_moneyness - round_trip_moneyness_step, use_put_branch);
    const double first = (above - below) / (2.0 * round_trip_moneyness_step);
    const double second =
        (above - 2.0 * centre + below) / (round_trip_moneyness_step * round_trip_moneyness_step);
    return 0.5 * (second - first);
}

double local_variance_from_prices(const InterpolatedSlice& interpolated, double log_moneyness) {
    const double curvature = price_space_curvature(interpolated, log_moneyness);
    if (curvature <= 0.0) {
        throw InvalidSviSurfaceError("the price space density is not positive at " +
                                     std::to_string(log_moneyness) + ", got " +
                                     std::to_string(curvature));
    }
    const bool use_put_branch = log_moneyness < 0.0;
    const InterpolatedSlice later = shifted_in_time(interpolated, round_trip_time_step);
    const InterpolatedSlice earlier = shifted_in_time(interpolated, -round_trip_time_step);
    const double time_derivative = (out_of_the_money_price(later, log_moneyness, use_put_branch) -
                                    out_of_the_money_price(earlier, log_moneyness, use_put_branch)) /
                                   (2.0 * round_trip_time_step);
    return time_derivative / curvature;
}

SviSurfaceScan scan_svi_surface(const std::vector<SviSurfaceSlice>& slices, double lowest_log_moneyness,
                                double highest_log_moneyness, int scan_steps,
                                int time_steps_per_interval) {
    validate_svi_surface(slices);
    if (!(highest_log_moneyness > lowest_log_moneyness)) {
        throw InvalidSviSurfaceError("the scan range must be non-empty and increasing");
    }
    if (scan_steps < minimum_surface_scan_steps) {
        throw InvalidSviSurfaceError("scan_steps must be at least " +
                                     std::to_string(minimum_surface_scan_steps) + ", got " +
                                     std::to_string(scan_steps));
    }
    if (time_steps_per_interval < minimum_time_steps_per_interval) {
        throw InvalidSviSurfaceError("time_steps_per_interval must be at least " +
                                     std::to_string(minimum_time_steps_per_interval) + ", got " +
                                     std::to_string(time_steps_per_interval));
    }

    const ScanGrid grid{moneyness_grid(lowest_log_moneyness, highest_log_moneyness, scan_steps), scan_steps,
                        time_steps_per_interval};
    SurfaceExtremes extremes;
    for (std::size_t index = 1; index < slices.size(); ++index) {
        scan_surface_interval(extremes, SurfaceInterval{slices[index - 1], slices[index]}, grid,
                              index == 1);
    }

    return SviSurfaceScan{
        static_cast<int>(slices.size()),
        scan_steps,
        time_steps_per_interval,
        extremes.durrleman_value,
        extremes.durrleman_log_moneyness,
        extremes.durrleman_years,
        extremes.risk_neutral_density,
        extremes.time_slope,
        extremes.time_slope_log_moneyness,
        extremes.time_slope_years,
        extremes.local_variance,
        extremes.local_variance_log_moneyness,
        extremes.local_variance_years,
        extremes.round_trip_error,
        extremes.round_trip_log_moneyness,
        extremes.round_trip_points,
        surface_status(extremes),
    };
}

}
