#include "volarb/implied_correlation.hpp"

#include <cmath>

namespace volarb {

void validate_basket(const std::vector<BasketConstituent>& constituents) {
    if (constituents.size() < minimum_constituents) {
        throw InvalidBasketError("a basket needs at least " + std::to_string(minimum_constituents) +
                                 " constituents, got " + std::to_string(constituents.size()));
    }
    double total = 0.0;
    for (const BasketConstituent& constituent : constituents) {
        if (constituent.weight <= 0.0) {
            throw InvalidBasketError(constituent.symbol + " carries a weight of " +
                                     std::to_string(constituent.weight) + ", which is not positive");
        }
        if (constituent.volatility <= 0.0) {
            throw InvalidBasketError(constituent.symbol + " carries a volatility of " +
                                     std::to_string(constituent.volatility) + ", which is not positive");
        }
        total += constituent.weight;
    }
    if (std::abs(total - 1.0) > weight_total_tolerance) {
        throw InvalidBasketError("the constituent weights sum to " + std::to_string(total) +
                                 " rather than one");
    }
}

BasketMoments moments_of(const std::vector<BasketConstituent>& constituents) {
    double weighted = 0.0;
    double diagonal = 0.0;
    for (const BasketConstituent& constituent : constituents) {
        const double contribution = constituent.weight * constituent.volatility;
        weighted += contribution;
        diagonal += contribution * contribution;
    }
    const double off_diagonal = weighted * weighted - diagonal;
    return BasketMoments{weighted, diagonal, off_diagonal, diagonal / (weighted * weighted)};
}

double lowest_admissible_correlation(std::size_t constituent_count) {
    return -1.0 / static_cast<double>(constituent_count - 1);
}

double basket_volatility(const std::vector<BasketConstituent>& constituents, double correlation) {
    validate_basket(constituents);
    const double floor = lowest_admissible_correlation(constituents.size());
    if (correlation < floor || correlation > perfect_correlation) {
        throw InvalidBasketError("a correlation of " + std::to_string(correlation) +
                                 " is outside the admissible range [" + std::to_string(floor) + ", " +
                                 std::to_string(perfect_correlation) + "] for " +
                                 std::to_string(constituents.size()) + " constituents");
    }
    const BasketMoments moments = moments_of(constituents);
    const double variance = moments.diagonal_variance + correlation * moments.off_diagonal_variance;
    return std::sqrt(variance > 0.0 ? variance : 0.0);
}

CorrelationReport imply_correlation(const std::vector<BasketConstituent>& constituents,
                                    double index_volatility) {
    validate_basket(constituents);
    if (index_volatility <= 0.0) {
        throw InvalidBasketError("the index volatility must be positive, got " +
                                 std::to_string(index_volatility));
    }
    const BasketMoments moments = moments_of(constituents);
    if (moments.off_diagonal_variance < minimum_off_diagonal_variance) {
        throw InvalidBasketError(
            "the off diagonal variance is nothing, so no correlation can be implied from it");
    }
    const double index_variance = index_volatility * index_volatility;
    const double clean = (index_variance - moments.diagonal_variance) / moments.off_diagonal_variance;
    const double bias = moments.concentration * (perfect_correlation - clean);
    const double floor = lowest_admissible_correlation(constituents.size());
    return CorrelationReport{static_cast<int>(constituents.size()),
                             index_volatility,
                             moments.weighted_volatility,
                             moments.concentration,
                             clean,
                             bias,
                             clean + bias,
                             floor,
                             floor <= clean && clean <= perfect_correlation,
                             clean > perfect_correlation};
}

std::vector<double> index_sensitivities(const std::vector<BasketConstituent>& constituents,
                                        double correlation) {
    const double index_volatility = basket_volatility(constituents, correlation);
    const BasketMoments moments = moments_of(constituents);
    std::vector<double> sensitivities;
    sensitivities.reserve(constituents.size());
    for (const BasketConstituent& constituent : constituents) {
        const double contribution = constituent.weight * constituent.volatility;
        const double others = moments.weighted_volatility - contribution;
        sensitivities.push_back(constituent.weight * (contribution + correlation * others) /
                                index_volatility);
    }
    return sensitivities;
}

std::vector<double> dispersion_vega_weights(const std::vector<BasketConstituent>& constituents,
                                            double correlation, double index_vega) {
    std::vector<double> weights = index_sensitivities(constituents, correlation);
    for (double& weight : weights) {
        weight *= index_vega;
    }
    return weights;
}

}
