#include "volarb/forward_curve.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <utility>

namespace volarb {

namespace {

struct WeightedLineFit {
    double slope;
    double weighted_mean_strike;
    double weighted_mean_value;
    double slope_variance;
    double mean_value_variance;
    double chi_square_per_degree_of_freedom;

    double value_at(double strike) const {
        return weighted_mean_value + slope * (strike - weighted_mean_strike);
    }
};

bool is_two_sided(const ContractQuote& quote) {
    return quote.ask_price >= quote.bid_price && quote.ask_price > 0.0;
}

double half_spread_of(const ContractQuote& quote) {
    return std::max(0.5 * (quote.ask_price - quote.bid_price), minimum_half_spread);
}

double mid_price_of(const ContractQuote& quote) {
    return 0.5 * (quote.bid_price + quote.ask_price);
}

ParityPair parity_pair_from(const ContractQuote& call, const ContractQuote& put) {
    const double call_half_spread = half_spread_of(call);
    const double put_half_spread = half_spread_of(put);
    const double variance = call_half_spread * call_half_spread + put_half_spread * put_half_spread;
    return ParityPair{call.strike, mid_price_of(call) - mid_price_of(put), 1.0 / variance};
}

std::optional<WeightedLineFit> fit_weighted_line(const std::vector<ParityPair>& pairs) {
    double total_weight = 0.0;
    double weighted_strike = 0.0;
    double weighted_value = 0.0;
    for (const ParityPair& pair : pairs) {
        total_weight += pair.weight;
        weighted_strike += pair.weight * pair.strike;
        weighted_value += pair.weight * pair.call_minus_put_mid;
    }
    if (total_weight <= 0.0) {
        return std::nullopt;
    }
    const double mean_strike = weighted_strike / total_weight;
    const double mean_value = weighted_value / total_weight;

    double centred_strike_squared = 0.0;
    for (const ParityPair& pair : pairs) {
        const double centred = pair.strike - mean_strike;
        centred_strike_squared += pair.weight * centred * centred;
    }
    if (centred_strike_squared <= 0.0) {
        return std::nullopt;
    }

    double centred_cross_product = 0.0;
    for (const ParityPair& pair : pairs) {
        centred_cross_product +=
            pair.weight * (pair.strike - mean_strike) * (pair.call_minus_put_mid - mean_value);
    }
    const double slope = centred_cross_product / centred_strike_squared;

    double weighted_residual_sum = 0.0;
    for (const ParityPair& pair : pairs) {
        const double residual =
            pair.call_minus_put_mid - (mean_value + slope * (pair.strike - mean_strike));
        weighted_residual_sum += pair.weight * residual * residual;
    }
    const double chi_square = weighted_residual_sum / static_cast<double>(pairs.size() - 2);
    const double inflation = std::max(chi_square, minimum_covariance_inflation);

    return WeightedLineFit{
        slope,
        mean_strike,
        mean_value,
        inflation / centred_strike_squared,
        inflation / total_weight,
        chi_square,
    };
}

std::vector<ParityPair> trimmed_pairs(const std::vector<ParityPair>& pairs) {
    std::vector<ParityPair> active = pairs;
    for (int pass = 0; pass < maximum_trimming_passes; ++pass) {
        const std::optional<WeightedLineFit> fit = fit_weighted_line(active);
        if (!fit.has_value()) {
            return active;
        }
        std::vector<double> residuals;
        residuals.reserve(active.size());
        for (const ParityPair& pair : active) {
            residuals.push_back(pair.call_minus_put_mid - fit->value_at(pair.strike));
        }
        const double centre = median_of(residuals);
        std::vector<double> deviations;
        deviations.reserve(residuals.size());
        for (const double residual : residuals) {
            deviations.push_back(std::abs(residual - centre));
        }
        const double scale = median_absolute_deviation_scale * median_of(deviations);
        if (scale <= 0.0) {
            return active;
        }

        std::vector<ParityPair> kept;
        for (std::size_t index = 0; index < active.size(); ++index) {
            if (std::abs(residuals[index] - centre) <= outlier_rejection_sigmas * scale) {
                kept.push_back(active[index]);
            }
        }
        if (static_cast<int>(kept.size()) < minimum_parity_pairs || kept.size() == active.size()) {
            return active;
        }
        active = std::move(kept);
    }
    return active;
}

double forward_from(const WeightedLineFit& fit) {
    return fit.weighted_mean_strike - fit.weighted_mean_value / fit.slope;
}

double forward_variance_from(const WeightedLineFit& fit) {
    const double slope_squared = fit.slope * fit.slope;
    return fit.mean_value_variance / slope_squared +
           fit.weighted_mean_value * fit.weighted_mean_value * fit.slope_variance /
               (slope_squared * slope_squared);
}

ForwardCurvePoint failed_point(DaysSinceEpoch expiry_date, double years, double spot_price,
                               int pair_count, ForwardCurveStatus status) {
    return ForwardCurvePoint{
        expiry_date, years, spot_price, 0.0,      std::nullopt, 0.0,   std::nullopt,
        std::nullopt, std::nullopt,     pair_count, 0,          std::nullopt, false, status,
    };
}

ForwardCurvePoint curve_point_for_expiry(DaysSinceEpoch expiry_date, const std::vector<ParityPair>& pairs,
                                         double years, double spot_price) {
    const int pair_count = static_cast<int>(pairs.size());
    if (pair_count < minimum_parity_pairs) {
        return failed_point(expiry_date, years, spot_price, pair_count, ForwardCurveStatus::TooFewPairs);
    }

    const std::vector<ParityPair> active = trimmed_pairs(pairs);
    const std::optional<WeightedLineFit> fit = fit_weighted_line(active);
    if (!fit.has_value()) {
        return failed_point(expiry_date, years, spot_price, pair_count,
                            ForwardCurveStatus::DegenerateStrikeRange);
    }
    if (fit->slope >= 0.0) {
        return failed_point(expiry_date, years, spot_price, pair_count,
                            ForwardCurveStatus::NonPositiveDiscountFactor);
    }

    const double discount_factor = -fit->slope;
    const double forward = forward_from(*fit);
    const double zero_rate = -std::log(discount_factor) / years;

    return ForwardCurvePoint{
        expiry_date,
        years,
        spot_price,
        forward,
        std::sqrt(std::max(forward_variance_from(*fit), 0.0)),
        discount_factor,
        std::sqrt(std::max(fit->slope_variance, 0.0)),
        zero_rate,
        zero_rate - std::log(forward / spot_price) / years,
        pair_count,
        static_cast<int>(active.size()),
        fit->chi_square_per_degree_of_freedom,
        false,
        ForwardCurveStatus::Converged,
    };
}

bool discount_factors_are_monotone(const std::vector<ForwardCurvePoint>& points) {
    std::vector<const ForwardCurvePoint*> converged;
    for (const ForwardCurvePoint& point : points) {
        if (point.status == ForwardCurveStatus::Converged) {
            converged.push_back(&point);
        }
    }
    std::stable_sort(converged.begin(), converged.end(),
                     [](const ForwardCurvePoint* left, const ForwardCurvePoint* right) {
                         return left->expiry_date < right->expiry_date;
                     });
    for (std::size_t index = 1; index < converged.size(); ++index) {
        if (converged[index]->discount_factor > converged[index - 1]->discount_factor) {
            return false;
        }
    }
    return true;
}

double spot_price_for(const std::vector<ContractQuote>& quotes, DaysSinceEpoch expiry_date) {
    for (const ContractQuote& quote : quotes) {
        if (quote.expiry_date == expiry_date) {
            return quote.underlying_price;
        }
    }
    return 0.0;
}

}

std::string name_of_forward_curve_status(ForwardCurveStatus status) {
    switch (status) {
    case ForwardCurveStatus::Converged:
        return "converged";
    case ForwardCurveStatus::TooFewPairs:
        return "too_few_pairs";
    case ForwardCurveStatus::DegenerateStrikeRange:
        return "degenerate_strike_range";
    case ForwardCurveStatus::NonPositiveDiscountFactor:
        return "non_positive_discount_factor";
    }
    return "too_few_pairs";
}

double median_of(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    const std::size_t count = values.size();
    const std::size_t middle = count / 2;
    if (count % 2 == 1) {
        return values[middle];
    }
    return 0.5 * (values[middle - 1] + values[middle]);
}

double years_to_expiry_from(EpochMicroseconds observation_time, DaysSinceEpoch expiry_date) {
    const EpochMicroseconds settlement =
        (static_cast<EpochMicroseconds>(expiry_date) * 86400LL +
         static_cast<EpochMicroseconds>(expiry_settlement_hour_utc) * 3600LL) *
        1000000LL;
    return static_cast<double>(settlement - observation_time) / 1000000.0 / (days_per_year * seconds_per_day);
}

std::map<DaysSinceEpoch, std::vector<ParityPair>> parity_pairs_from_chain(
    const std::vector<ContractQuote>& quotes) {
    std::map<std::pair<DaysSinceEpoch, double>, ContractQuote> calls;
    std::map<std::pair<DaysSinceEpoch, double>, ContractQuote> puts;
    for (const ContractQuote& quote : quotes) {
        if (!is_two_sided(quote)) {
            continue;
        }
        const std::pair<DaysSinceEpoch, double> key{quote.expiry_date, quote.strike};
        if (quote.option_type == OptionType::Call) {
            calls.insert_or_assign(key, quote);
        } else {
            puts.insert_or_assign(key, quote);
        }
    }

    std::map<DaysSinceEpoch, std::vector<ParityPair>> pairs_by_expiry;
    for (const auto& [key, call] : calls) {
        const auto put = puts.find(key);
        if (put == puts.end()) {
            continue;
        }
        pairs_by_expiry[key.first].push_back(parity_pair_from(call, put->second));
    }
    return pairs_by_expiry;
}

std::vector<ForwardCurvePoint> imply_forward_curve(const std::vector<ContractQuote>& quotes,
                                                   EpochMicroseconds observation_time) {
    std::vector<ForwardCurvePoint> points;
    for (const auto& [expiry_date, pairs] : parity_pairs_from_chain(quotes)) {
        const double years = years_to_expiry_from(observation_time, expiry_date);
        if (years <= 0.0) {
            continue;
        }
        points.push_back(curve_point_for_expiry(expiry_date, pairs, years, spot_price_for(quotes, expiry_date)));
    }

    const bool monotone = discount_factors_are_monotone(points);
    for (ForwardCurvePoint& point : points) {
        point.discount_factor_is_monotone_in_expiry = monotone;
    }
    return points;
}

}
