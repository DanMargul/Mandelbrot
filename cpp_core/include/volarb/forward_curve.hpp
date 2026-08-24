#pragma once

#include "volarb/american.hpp"
#include "volarb/market_data.hpp"

#include <map>
#include <optional>
#include <utility>
#include <string>
#include <vector>

namespace volarb {

enum class ForwardCurveStatus {
    Converged,
    TooFewPairs,
    DegenerateStrikeRange,
    NonPositiveDiscountFactor,
    AmericanQuotesNotStripped,
};

inline constexpr int minimum_parity_pairs = 4;
inline constexpr int maximum_trimming_passes = 5;
inline constexpr double outlier_rejection_sigmas = 4.0;
inline constexpr double median_absolute_deviation_scale = 1.4826;
inline constexpr double minimum_half_spread = 1e-8;
inline constexpr double minimum_covariance_inflation = 1.0;
inline constexpr int expiry_settlement_hour_utc = 21;
inline constexpr double days_per_year = 365.0;
inline constexpr double seconds_per_day = 86400.0;
inline constexpr int maximum_stripping_passes = 4;
inline constexpr double forward_stripping_tolerance = 1e-6;

struct ParityPair {
    double strike;
    double call_minus_put_mid;
    double weight;
};

struct ForwardCurvePoint {
    DaysSinceEpoch expiry_date;
    double years_to_expiry;
    double spot_price;
    double forward;
    std::optional<double> forward_standard_error;
    double discount_factor;
    std::optional<double> discount_factor_standard_error;
    std::optional<double> implied_zero_rate;
    std::optional<double> implied_carry_rate;
    int parity_pair_count;
    int active_pair_count;
    std::optional<double> chi_square_per_degree_of_freedom;
    bool early_exercise_premium_stripped;
    bool discount_factor_is_monotone_in_expiry;
    ForwardCurveStatus status;
};

std::string name_of_forward_curve_status(ForwardCurveStatus status);

double median_of(std::vector<double> values);
double years_to_expiry_from(EpochMicroseconds observation_time, DaysSinceEpoch expiry_date);

std::map<DaysSinceEpoch, std::vector<ParityPair>> parity_pairs_from_chain(
    const std::vector<ContractQuote>& quotes);

using QuotePair = std::pair<ContractQuote, ContractQuote>;

std::map<DaysSinceEpoch, std::vector<QuotePair>> paired_quotes_from_chain(
    const std::vector<ContractQuote>& quotes);

std::vector<ForwardCurvePoint> imply_forward_curve(const std::vector<ContractQuote>& quotes,
                                                   EpochMicroseconds observation_time,
                                                   std::optional<double> zero_rate = std::nullopt);

}
