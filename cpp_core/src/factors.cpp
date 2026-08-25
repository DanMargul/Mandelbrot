#include "volarb/factors.hpp"

#include <algorithm>
#include <cmath>

namespace volarb {

namespace {

void validate_grid(const std::vector<SurfacePoint>& grid) {
    if (grid.size() < minimum_grid_points) {
        throw InvalidFactorInputsError("a grid needs at least " + std::to_string(minimum_grid_points) +
                                       " points, got " + std::to_string(grid.size()));
    }
    for (const SurfacePoint& point : grid) {
        if (point.years_to_expiry <= 0.0) {
            throw InvalidFactorInputsError("years_to_expiry must be positive, got " +
                                           std::to_string(point.years_to_expiry));
        }
    }
}

void validate_observations(const std::vector<SurfacePoint>& grid,
                           const std::vector<std::vector<double>>& observations) {
    if (observations.size() < minimum_factor_observations) {
        throw InvalidFactorInputsError("a decomposition needs at least " +
                                       std::to_string(minimum_factor_observations) +
                                       " observations, got " + std::to_string(observations.size()));
    }
    for (const std::vector<double>& observation : observations) {
        if (observation.size() != grid.size()) {
            throw InvalidFactorInputsError("an observation has " + std::to_string(observation.size()) +
                                           " values against " + std::to_string(grid.size()) +
                                           " grid points");
        }
        for (const double value : observation) {
            if (value <= 0.0) {
                throw InvalidFactorInputsError("total variance must be positive, got " +
                                               std::to_string(value));
            }
        }
    }
}

std::vector<double> log_total_variance(const std::vector<double>& observation) {
    std::vector<double> values;
    values.reserve(observation.size());
    for (const double value : observation) {
        values.push_back(std::log(std::max(value, minimum_factor_total_variance)));
    }
    return values;
}

std::vector<double> subtract_projection(const std::vector<double>& vector,
                                        const std::vector<double>& basis) {
    const double overlap = inner_product(vector, basis);
    std::vector<double> result;
    result.reserve(vector.size());
    for (std::size_t index = 0; index < vector.size(); ++index) {
        result.push_back(vector[index] - overlap * basis[index]);
    }
    return result;
}

std::vector<double> project_onto(const std::vector<std::vector<double>>& basis,
                                 const std::vector<double>& values) {
    std::vector<double> coefficients;
    coefficients.reserve(basis.size());
    for (const std::vector<double>& vector : basis) {
        coefficients.push_back(inner_product(values, vector));
    }
    return coefficients;
}

std::vector<double> reconstruct_from(const std::vector<std::vector<double>>& basis,
                                     const std::vector<double>& coefficients) {
    std::vector<double> fitted(basis[0].size(), 0.0);
    for (std::size_t index = 0; index < fitted.size(); ++index) {
        double total = 0.0;
        for (std::size_t which = 0; which < basis.size(); ++which) {
            total += coefficients[which] * basis[which][index];
        }
        fitted[index] = total;
    }
    return fitted;
}

FactorLoadings loadings_from(const std::vector<double>& coefficients) {
    std::vector<double> padded = coefficients;
    padded.resize(static_cast<std::size_t>(factor_count), 0.0);
    return FactorLoadings{padded[0], padded[1], padded[2], padded[3]};
}

std::vector<std::vector<double>> loading_columns(const std::vector<FactorLoadings>& loadings,
                                                 int identified) {
    std::vector<std::vector<double>> columns;
    for (int which = 0; which < identified && which < factor_count; ++which) {
        std::vector<double> column;
        column.reserve(loadings.size());
        for (const FactorLoadings& entry : loadings) {
            const double picked = which == 0   ? entry.level
                                  : which == 1 ? entry.term_slope
                                  : which == 2 ? entry.skew
                                               : entry.curvature;
            column.push_back(picked);
        }
        columns.push_back(column);
    }
    return columns;
}

double worst_correlation_against(const std::vector<double>& series,
                                 const std::vector<std::vector<double>>& columns) {
    double worst = 0.0;
    for (const std::vector<double>& column : columns) {
        worst = std::max(worst, std::abs(correlation_of(series, column)));
    }
    return worst;
}

double worst_correlation_with_factors(const std::vector<std::vector<double>>& residuals,
                                      const std::vector<FactorLoadings>& loadings, int identified) {
    const std::vector<std::vector<double>> columns = loading_columns(loadings, identified);
    double worst = 0.0;
    for (std::size_t index = 0; index < residuals[0].size(); ++index) {
        std::vector<double> series;
        series.reserve(residuals.size());
        for (const std::vector<double>& residual : residuals) {
            series.push_back(residual[index]);
        }
        worst = std::max(worst, worst_correlation_against(series, columns));
    }
    return worst;
}

}

double inner_product(const std::vector<double>& left, const std::vector<double>& right) {
    double total = 0.0;
    for (std::size_t index = 0; index < left.size(); ++index) {
        total += left[index] * right[index];
    }
    return total;
}

double norm_of(const std::vector<double>& vector) {
    return std::sqrt(std::max(inner_product(vector, vector), 0.0));
}

std::vector<double> centred(const std::vector<double>& values) {
    double total = 0.0;
    for (const double value : values) {
        total += value;
    }
    const double mean = total / static_cast<double>(values.size());
    std::vector<double> result;
    result.reserve(values.size());
    for (const double value : values) {
        result.push_back(value - mean);
    }
    return result;
}

double correlation_of(const std::vector<double>& left, const std::vector<double>& right) {
    const std::vector<double> one = centred(left);
    const std::vector<double> other = centred(right);
    const double scale = norm_of(one) * norm_of(other);
    if (scale < minimum_basis_norm) {
        return 0.0;
    }
    return inner_product(one, other) / scale;
}

std::vector<std::vector<double>> raw_factor_vectors(const std::vector<SurfacePoint>& grid) {
    std::vector<double> level;
    std::vector<double> term;
    std::vector<double> skew;
    std::vector<double> curvature;
    for (const SurfacePoint& point : grid) {
        level.push_back(1.0);
        term.push_back(std::log(point.years_to_expiry));
        skew.push_back(point.log_moneyness);
        curvature.push_back(point.log_moneyness * point.log_moneyness);
    }
    return {level, term, skew, curvature};
}

std::vector<std::vector<double>> orthonormal_basis(const std::vector<std::vector<double>>& vectors) {
    std::vector<std::vector<double>> basis;
    for (const std::vector<double>& vector : vectors) {
        std::vector<double> candidate = vector;
        for (int pass = 0; pass < gram_schmidt_passes; ++pass) {
            for (const std::vector<double>& existing : basis) {
                candidate = subtract_projection(candidate, existing);
            }
        }
        const double length = norm_of(candidate);
        if (length < minimum_basis_norm) {
            continue;
        }
        for (double& value : candidate) {
            value /= length;
        }
        basis.push_back(candidate);
    }
    return basis;
}

FactorDecomposition decompose_surface_factors(const std::vector<SurfacePoint>& grid,
                                              const std::vector<std::vector<double>>& observations) {
    validate_grid(grid);
    validate_observations(grid, observations);

    const std::vector<std::vector<double>> basis = orthonormal_basis(raw_factor_vectors(grid));
    if (basis.empty()) {
        throw InvalidFactorInputsError("no factor direction is identifiable on this grid");
    }

    std::vector<FactorLoadings> loadings;
    std::vector<std::vector<double>> residuals;
    double total_energy = 0.0;
    double residual_energy = 0.0;
    for (const std::vector<double>& observation : observations) {
        const std::vector<double> values = log_total_variance(observation);
        const std::vector<double> coefficients = project_onto(basis, values);
        const std::vector<double> fitted = reconstruct_from(basis, coefficients);
        std::vector<double> residual;
        residual.reserve(values.size());
        for (std::size_t index = 0; index < values.size(); ++index) {
            residual.push_back(values[index] - fitted[index]);
        }
        loadings.push_back(loadings_from(coefficients));
        total_energy += inner_product(values, values);
        residual_energy += inner_product(residual, residual);
        residuals.push_back(residual);
    }

    const double share = total_energy > 0.0 ? residual_energy / total_energy : 0.0;
    return FactorDecomposition{
        static_cast<int>(observations.size()),
        static_cast<int>(grid.size()),
        static_cast<int>(basis.size()),
        loadings,
        residuals,
        1.0 - share,
        share,
        worst_correlation_with_factors(residuals, loadings, static_cast<int>(basis.size())),
    };
}

NeutralisedResidual neutralise_against_loadings(const std::vector<double>& series,
                                                const std::vector<FactorLoadings>& loadings,
                                                int identified) {
    if (series.size() != loadings.size()) {
        throw InvalidFactorInputsError("the series has " + std::to_string(series.size()) +
                                       " points against " + std::to_string(loadings.size()) +
                                       " observations");
    }
    const std::vector<std::vector<double>> columns = loading_columns(loadings, identified);
    std::vector<std::vector<double>> design{std::vector<double>(series.size(), 1.0)};
    for (const std::vector<double>& column : columns) {
        design.push_back(column);
    }
    const std::vector<std::vector<double>> basis = orthonormal_basis(design);
    const std::vector<double> fitted = reconstruct_from(basis, project_onto(basis, series));
    std::vector<double> neutralised;
    neutralised.reserve(series.size());
    for (std::size_t index = 0; index < series.size(); ++index) {
        neutralised.push_back(series[index] - fitted[index]);
    }
    return NeutralisedResidual{neutralised, worst_correlation_against(neutralised, columns),
                               worst_correlation_against(series, columns)};
}

double lag_one_autocorrelation(const std::vector<double>& series) {
    if (series.size() < minimum_factor_observations) {
        throw InvalidFactorInputsError("an autocorrelation needs at least " +
                                       std::to_string(minimum_factor_observations) + " points, got " +
                                       std::to_string(series.size()));
    }
    const std::vector<double> deviations = centred(series);
    const double variance = inner_product(deviations, deviations);
    if (variance < minimum_basis_norm) {
        return 0.0;
    }
    double covariance = 0.0;
    for (std::size_t index = 1; index < deviations.size(); ++index) {
        covariance += deviations[index - 1] * deviations[index];
    }
    return std::min(std::max(covariance / variance, -maximum_autocorrelation), maximum_autocorrelation);
}

double effective_sample_size(int count, double autocorrelation) {
    return static_cast<double>(count) * (1.0 - autocorrelation) / (1.0 + autocorrelation);
}

ResidualScore score_residual(const std::vector<double>& series) {
    if (series.size() < minimum_factor_observations) {
        throw InvalidFactorInputsError("a score needs at least " +
                                       std::to_string(minimum_factor_observations) + " points, got " +
                                       std::to_string(series.size()));
    }
    const int count = static_cast<int>(series.size());
    double total = 0.0;
    for (const double value : series) {
        total += value;
    }
    const double mean = total / static_cast<double>(count);
    const std::vector<double> deviations = centred(series);
    const double variance = inner_product(deviations, deviations) / static_cast<double>(count - 1);
    const double deviation = std::sqrt(std::max(variance, 0.0));
    if (deviation < minimum_residual_standard_deviation) {
        return ResidualScore{count, mean, deviation, 0.0, static_cast<double>(count),
                             0.0,   0.0,  1.0,       true};
    }

    const double autocorrelation = lag_one_autocorrelation(series);
    const double effective = std::max(effective_sample_size(count, autocorrelation), 1.0);
    const double inflation = std::sqrt(static_cast<double>(count) / effective);
    const double naive = (series.back() - mean) / deviation;
    return ResidualScore{count,     mean,  deviation,         autocorrelation,
                         effective, naive, naive / inflation, inflation,
                         false};
}

}
