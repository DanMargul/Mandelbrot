#pragma once

#include "volarb/pricing.hpp"

#include <string>

namespace volarb {

enum class InversionStatus {
    Converged,
    BelowIntrinsic,
    AboveNoArbitrageBound,
    BelowVolatilityFloor,
    AboveVolatilityCeiling,
    NotConverged,
    DegenerateExpiry,
};

inline constexpr double minimum_volatility = 1e-9;
inline constexpr double maximum_volatility = 10.0;
inline constexpr int maximum_iterations = 100;
inline constexpr double volatility_convergence_tolerance = 1e-12;
inline constexpr double minimum_usable_vega = 1e-12;

struct ImpliedVolatilityInputs {
    double forward;
    double strike;
    double years_to_expiry;
    double discount_factor;
    double option_price;
    OptionType option_type;
};

struct ImpliedVolatilityResult {
    double volatility;
    InversionStatus status;
    int iterations;
    double absolute_price_error;
    double volatility_uncertainty;
};

std::string name_of_inversion_status(InversionStatus status);

OptionType out_of_the_money_option_type(double forward, double strike);
double undiscounted_out_of_the_money_target_price(const ImpliedVolatilityInputs& inputs);
double undiscounted_no_arbitrage_price_ceiling(double forward, double strike, OptionType option_type);
double volatility_uncertainty_from_price_resolution(
    double largest_price_term, double quoted_undiscounted_price, double vega);

ImpliedVolatilityResult invert_black_implied_volatility(const ImpliedVolatilityInputs& inputs);

}
