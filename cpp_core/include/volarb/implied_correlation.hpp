#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

inline constexpr std::size_t minimum_constituents = 2;
inline constexpr double minimum_off_diagonal_variance = 1e-18;
inline constexpr double perfect_correlation = 1.0;
inline constexpr double weight_total_tolerance = 1e-9;

class InvalidBasketError : public std::invalid_argument {
  public:
    explicit InvalidBasketError(const std::string& message) : std::invalid_argument(message) {}
};

struct BasketConstituent {
    std::string symbol;
    double weight;
    double volatility;
};

struct BasketMoments {
    double weighted_volatility;
    double diagonal_variance;
    double off_diagonal_variance;
    double concentration;
};

struct CorrelationReport {
    int constituent_count;
    double index_volatility;
    double weighted_volatility;
    double concentration;
    double clean_correlation;
    double diagonal_bias;
    double dirty_correlation;
    double lowest_admissible_correlation;
    bool is_admissible;
    bool exceeds_perfect_correlation;
};

void validate_basket(const std::vector<BasketConstituent>& constituents);

BasketMoments moments_of(const std::vector<BasketConstituent>& constituents);

double lowest_admissible_correlation(std::size_t constituent_count);

double basket_volatility(const std::vector<BasketConstituent>& constituents, double correlation);

CorrelationReport imply_correlation(const std::vector<BasketConstituent>& constituents,
                                    double index_volatility);

std::vector<double> index_sensitivities(const std::vector<BasketConstituent>& constituents,
                                        double correlation);

std::vector<double> dispersion_vega_weights(const std::vector<BasketConstituent>& constituents,
                                            double correlation, double index_vega);

}
