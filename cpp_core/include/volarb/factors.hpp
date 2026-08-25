#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

inline constexpr int factor_count = 4;
inline constexpr std::size_t minimum_factor_observations = 2;
inline constexpr std::size_t minimum_grid_points = 4;
inline constexpr double minimum_basis_norm = 1e-10;
inline constexpr double minimum_factor_total_variance = 1e-12;
inline constexpr double minimum_residual_standard_deviation = 1e-12;
inline constexpr double maximum_autocorrelation = 0.99;
inline constexpr int gram_schmidt_passes = 2;

class InvalidFactorInputsError : public std::invalid_argument {
  public:
    explicit InvalidFactorInputsError(const std::string& message) : std::invalid_argument(message) {}
};

struct SurfacePoint {
    double log_moneyness;
    double years_to_expiry;
};

struct FactorLoadings {
    double level;
    double term_slope;
    double skew;
    double curvature;
};

struct FactorDecomposition {
    int observation_count;
    int grid_point_count;
    int identified_factor_count;
    std::vector<FactorLoadings> loadings;
    std::vector<std::vector<double>> residuals;
    double variance_explained;
    double residual_share;
    double worst_residual_factor_correlation;
};

struct NeutralisedResidual {
    std::vector<double> values;
    double worst_factor_correlation;
    double worst_factor_correlation_before;
};

struct ResidualScore {
    int observation_count;
    double mean;
    double standard_deviation;
    double lag_one_autocorrelation;
    double effective_sample_size;
    double naive_z_score;
    double adjusted_z_score;
    double naive_overstatement;
    bool residual_is_degenerate;
};

double inner_product(const std::vector<double>& left, const std::vector<double>& right);
double norm_of(const std::vector<double>& vector);
std::vector<double> centred(const std::vector<double>& values);
double correlation_of(const std::vector<double>& left, const std::vector<double>& right);
std::vector<std::vector<double>> raw_factor_vectors(const std::vector<SurfacePoint>& grid);
std::vector<std::vector<double>> orthonormal_basis(const std::vector<std::vector<double>>& vectors);

FactorDecomposition decompose_surface_factors(const std::vector<SurfacePoint>& grid,
                                              const std::vector<std::vector<double>>& observations);
NeutralisedResidual neutralise_against_loadings(const std::vector<double>& series,
                                                const std::vector<FactorLoadings>& loadings,
                                                int identified);
double lag_one_autocorrelation(const std::vector<double>& series);
double effective_sample_size(int count, double autocorrelation);
ResidualScore score_residual(const std::vector<double>& series);

}
