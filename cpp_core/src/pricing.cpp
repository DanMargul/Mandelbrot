#include "volarb/pricing.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>

namespace volarb {

namespace {

const double square_root_of_two = std::sqrt(2.0);
const double inverse_square_root_of_two_pi = 1.0 / std::sqrt(2.0 * std::numbers::pi);

struct StandardizedMoneynessPair {
    double d1;
    double d2;
};

StandardizedMoneynessPair standardized_moneyness_pair(const BlackScholesInputs& inputs) {
    const double standard_deviation = inputs.volatility * std::sqrt(inputs.years_to_expiry);
    const double d1 =
        (std::log(inputs.forward / inputs.strike) + 0.5 * standard_deviation * standard_deviation) /
        standard_deviation;
    return {d1, d1 - standard_deviation};
}

}

OptionType option_type_from_name(const std::string& name) {
    if (name == "call") {
        return OptionType::Call;
    }
    if (name == "put") {
        return OptionType::Put;
    }
    throw InvalidOptionInputsError("option_type must be 'call' or 'put', found '" + name + "'");
}

std::string name_of_option_type(OptionType option_type) {
    return option_type == OptionType::Call ? "call" : "put";
}

double standard_normal_cumulative_distribution(double x) {
    return 0.5 * std::erfc(-x / square_root_of_two);
}

double standard_normal_probability_density(double x) {
    return inverse_square_root_of_two_pi * std::exp(-0.5 * x * x);
}

void validate_black_scholes_inputs(const BlackScholesInputs& inputs) {
    if (!(inputs.forward > 0.0)) {
        throw InvalidOptionInputsError("forward must be positive, got " + std::to_string(inputs.forward));
    }
    if (!(inputs.strike > 0.0)) {
        throw InvalidOptionInputsError("strike must be positive, got " + std::to_string(inputs.strike));
    }
    if (!(inputs.discount_factor > 0.0)) {
        throw InvalidOptionInputsError(
            "discount_factor must be positive, got " + std::to_string(inputs.discount_factor));
    }
    if (inputs.years_to_expiry < 0.0) {
        throw InvalidOptionInputsError(
            "years_to_expiry must not be negative, got " + std::to_string(inputs.years_to_expiry));
    }
    if (inputs.volatility < 0.0) {
        throw InvalidOptionInputsError(
            "volatility must not be negative, got " + std::to_string(inputs.volatility));
    }
}

bool has_degenerate_expiry(const BlackScholesInputs& inputs) {
    return inputs.years_to_expiry <= 0.0 || inputs.volatility <= 0.0;
}

double forward_intrinsic_value(const BlackScholesInputs& inputs) {
    if (inputs.option_type == OptionType::Call) {
        return inputs.discount_factor * std::max(inputs.forward - inputs.strike, 0.0);
    }
    return inputs.discount_factor * std::max(inputs.strike - inputs.forward, 0.0);
}

double forward_intrinsic_delta(const BlackScholesInputs& inputs) {
    const bool is_above_strike = inputs.forward > inputs.strike;
    if (inputs.option_type == OptionType::Call) {
        return is_above_strike ? inputs.discount_factor : 0.0;
    }
    return is_above_strike ? 0.0 : -inputs.discount_factor;
}

double largest_price_term_magnitude(const BlackScholesInputs& inputs) {
    validate_black_scholes_inputs(inputs);
    if (has_degenerate_expiry(inputs)) {
        return inputs.discount_factor * std::max(inputs.forward, inputs.strike);
    }
    const auto [d1, d2] = standardized_moneyness_pair(inputs);
    if (inputs.option_type == OptionType::Call) {
        return inputs.discount_factor *
               std::max(inputs.forward * standard_normal_cumulative_distribution(d1),
                        inputs.strike * standard_normal_cumulative_distribution(d2));
    }
    return inputs.discount_factor *
           std::max(inputs.strike * standard_normal_cumulative_distribution(-d2),
                    inputs.forward * standard_normal_cumulative_distribution(-d1));
}

double black_scholes_price(const BlackScholesInputs& inputs) {
    validate_black_scholes_inputs(inputs);
    if (has_degenerate_expiry(inputs)) {
        return forward_intrinsic_value(inputs);
    }
    const auto [d1, d2] = standardized_moneyness_pair(inputs);
    if (inputs.option_type == OptionType::Call) {
        return inputs.discount_factor * (inputs.forward * standard_normal_cumulative_distribution(d1) -
                                         inputs.strike * standard_normal_cumulative_distribution(d2));
    }
    return inputs.discount_factor * (inputs.strike * standard_normal_cumulative_distribution(-d2) -
                                     inputs.forward * standard_normal_cumulative_distribution(-d1));
}

BlackScholesGreeks black_scholes_price_and_greeks(const BlackScholesInputs& inputs) {
    validate_black_scholes_inputs(inputs);
    if (has_degenerate_expiry(inputs)) {
        return BlackScholesGreeks{forward_intrinsic_value(inputs), forward_intrinsic_delta(inputs), 0.0, 0.0, 0.0};
    }

    const auto [d1, d2] = standardized_moneyness_pair(inputs);
    const double density_at_d1 = standard_normal_probability_density(d1);
    const double square_root_of_years = std::sqrt(inputs.years_to_expiry);

    double price = 0.0;
    double delta = 0.0;
    if (inputs.option_type == OptionType::Call) {
        price = inputs.discount_factor * (inputs.forward * standard_normal_cumulative_distribution(d1) -
                                          inputs.strike * standard_normal_cumulative_distribution(d2));
        delta = inputs.discount_factor * standard_normal_cumulative_distribution(d1);
    } else {
        price = inputs.discount_factor * (inputs.strike * standard_normal_cumulative_distribution(-d2) -
                                          inputs.forward * standard_normal_cumulative_distribution(-d1));
        delta = -inputs.discount_factor * standard_normal_cumulative_distribution(-d1);
    }

    return BlackScholesGreeks{
        price,
        delta,
        inputs.discount_factor * density_at_d1 /
            (inputs.forward * inputs.volatility * square_root_of_years),
        inputs.discount_factor * inputs.forward * density_at_d1 * square_root_of_years,
        -inputs.discount_factor * inputs.forward * density_at_d1 * inputs.volatility /
            (2.0 * square_root_of_years),
    };
}

}
