#include "volarb/factors.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <vector>

using Catch::Approx;
using volarb::correlation_of;
using volarb::decompose_surface_factors;
using volarb::effective_sample_size;
using volarb::FactorDecomposition;
using volarb::inner_product;
using volarb::InvalidFactorInputsError;
using volarb::lag_one_autocorrelation;
using volarb::neutralise_against_loadings;
using volarb::orthonormal_basis;
using volarb::raw_factor_vectors;
using volarb::score_residual;
using volarb::SurfacePoint;

namespace {

const std::vector<double> tenors = {0.0833, 0.25, 0.5, 1.0, 2.0};
const std::vector<double> strikes = {-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.4};

std::vector<SurfacePoint> full_grid() {
    std::vector<SurfacePoint> grid;
    for (const double tenor : tenors) {
        for (const double strike : strikes) {
            grid.push_back(SurfacePoint{strike, tenor});
        }
    }
    return grid;
}

std::vector<std::vector<double>> factor_driven_surfaces(int count) {
    std::vector<std::vector<double>> observations;
    for (int index = 0; index < count; ++index) {
        const double phase = static_cast<double>(index);
        const double level = 0.04 * std::exp(0.2 * std::sin(phase * 0.31));
        const double slope = 1.0 + 0.1 * std::cos(phase * 0.17);
        const double skew = -0.35 + 0.08 * std::sin(phase * 0.23);
        const double curvature = 0.9 + 0.15 * std::cos(phase * 0.11);
        std::vector<double> surface;
        for (const double tenor : tenors) {
            for (const double strike : strikes) {
                surface.push_back(level * std::pow(tenor, slope) *
                                  std::exp(skew * strike + curvature * strike * strike));
            }
        }
        observations.push_back(surface);
    }
    return observations;
}

}

TEST_CASE("the named basis is orthonormal on the grid", "[factors]") {
    const std::vector<std::vector<double>> basis = orthonormal_basis(raw_factor_vectors(full_grid()));
    REQUIRE(basis.size() == 4);
    for (std::size_t row = 0; row < basis.size(); ++row) {
        for (std::size_t column = 0; column < basis.size(); ++column) {
            const double expected = row == column ? 1.0 : 0.0;
            REQUIRE(inner_product(basis[row], basis[column]) == Approx(expected).margin(1e-12));
        }
    }
}

TEST_CASE("a surface built only from the factors leaves no residual", "[factors]") {
    const FactorDecomposition decomposition =
        decompose_surface_factors(full_grid(), factor_driven_surfaces(120));
    REQUIRE(decomposition.identified_factor_count == 4);
    REQUIRE(decomposition.variance_explained > 0.999999);
    for (const std::vector<double>& residual : decomposition.residuals) {
        for (const double value : residual) {
            REQUIRE(std::abs(value) < 1e-12);
        }
    }
}

TEST_CASE("residuals are orthogonal to the basis at every observation", "[factors]") {
    const std::vector<SurfacePoint> grid = full_grid();
    const FactorDecomposition decomposition =
        decompose_surface_factors(grid, factor_driven_surfaces(60));
    const std::vector<std::vector<double>> basis = orthonormal_basis(raw_factor_vectors(grid));
    for (const std::vector<double>& residual : decomposition.residuals) {
        for (const std::vector<double>& vector : basis) {
            REQUIRE(inner_product(residual, vector) == Approx(0.0).margin(1e-10));
        }
    }
}

TEST_CASE("a single expiry grid cannot identify a term slope", "[factors]") {
    std::vector<SurfacePoint> grid;
    for (const double strike : strikes) {
        grid.push_back(SurfacePoint{strike, 0.25});
    }
    std::vector<std::vector<double>> observations;
    for (int index = 0; index < 20; ++index) {
        std::vector<double> surface;
        for (const double strike : strikes) {
            surface.push_back(0.04 * std::exp(-0.3 * strike + 0.02 * static_cast<double>(index)));
        }
        observations.push_back(surface);
    }
    const FactorDecomposition decomposition = decompose_surface_factors(grid, observations);
    REQUIRE(decomposition.identified_factor_count == 3);
    for (const volarb::FactorLoadings& entry : decomposition.loadings) {
        REQUIRE(entry.curvature == Approx(0.0));
    }
}

TEST_CASE("time domain neutralisation removes what the cross section leaves", "[factors]") {
    const std::vector<SurfacePoint> grid = full_grid();
    std::vector<std::vector<double>> observations = factor_driven_surfaces(200);
    for (std::size_t index = 0; index < observations.size(); ++index) {
        observations[index][3] *= 1.0 + 0.02 * std::sin(static_cast<double>(index) * 0.31);
    }
    const FactorDecomposition decomposition = decompose_surface_factors(grid, observations);

    std::vector<double> series;
    for (const std::vector<double>& residual : decomposition.residuals) {
        series.push_back(residual[3]);
    }
    const volarb::NeutralisedResidual neutralised =
        neutralise_against_loadings(series, decomposition.loadings,
                                    decomposition.identified_factor_count);
    REQUIRE(neutralised.worst_factor_correlation < 1e-12);
    REQUIRE(neutralised.worst_factor_correlation < neutralised.worst_factor_correlation_before);
}

TEST_CASE("autocorrelation inflates the standard error of a z score", "[factors]") {
    for (const double rho : {0.0, 0.5, 0.8, 0.9}) {
        std::vector<double> series;
        double value = 0.0;
        double state = 1.0;
        for (int index = 0; index < 400; ++index) {
            state = std::fmod(state * 48271.0, 2147483647.0);
            const double shock = (state / 2147483647.0 - 0.5) * std::sqrt(12.0);
            value = rho * value + std::sqrt(1.0 - rho * rho) * shock;
            series.push_back(value);
        }
        const volarb::ResidualScore score = score_residual(series);
        const bool persistent = score.lag_one_autocorrelation > 0.0;
        REQUIRE((score.naive_overstatement > 1.0) == persistent);
        REQUIRE((score.effective_sample_size < static_cast<double>(series.size())) == persistent);
        if (persistent) {
            REQUIRE(std::abs(score.adjusted_z_score) < std::abs(score.naive_z_score));
        }
        if (rho > 0.5) {
            REQUIRE(score.lag_one_autocorrelation > 0.0);
            REQUIRE(score.naive_overstatement > 1.0);
        }
    }
}

TEST_CASE("the effective sample size follows the autocorrelation", "[factors]") {
    REQUIRE(effective_sample_size(100, 0.0) == Approx(100.0));
    REQUIRE(effective_sample_size(100, 0.9) == Approx(100.0 * 0.1 / 1.9));
    const std::vector<double> constant(50, 3.0);
    REQUIRE(lag_one_autocorrelation(constant) == Approx(0.0));
}

TEST_CASE("malformed factor inputs are rejected", "[factors]") {
    const std::vector<SurfacePoint> grid = full_grid();
    REQUIRE_THROWS_AS(decompose_surface_factors({SurfacePoint{0.0, 1.0}}, {{1.0}}),
                      InvalidFactorInputsError);
    REQUIRE_THROWS_AS(decompose_surface_factors(grid, {}), InvalidFactorInputsError);
    REQUIRE_THROWS_AS(decompose_surface_factors(grid, {std::vector<double>(grid.size(), 0.04),
                                                      std::vector<double>(3, 0.04)}),
                      InvalidFactorInputsError);
    REQUIRE_THROWS_AS(decompose_surface_factors(grid, {std::vector<double>(grid.size(), -0.04),
                                                      std::vector<double>(grid.size(), 0.04)}),
                      InvalidFactorInputsError);
    REQUIRE_THROWS_AS(score_residual({1.0}), InvalidFactorInputsError);
}

TEST_CASE("a residual uncorrelated with the loadings is unchanged in correlation", "[factors]") {
    const FactorDecomposition decomposition =
        decompose_surface_factors(full_grid(), factor_driven_surfaces(80));
    std::vector<double> series(decomposition.loadings.size(), 0.0);
    for (std::size_t index = 0; index < series.size(); ++index) {
        series[index] = std::sin(static_cast<double>(index) * 1.7);
    }
    const volarb::NeutralisedResidual neutralised = neutralise_against_loadings(
        series, decomposition.loadings, decomposition.identified_factor_count);
    REQUIRE(neutralised.worst_factor_correlation < 1e-12);
    REQUIRE(correlation_of(neutralised.values, series) > 0.5);
}
