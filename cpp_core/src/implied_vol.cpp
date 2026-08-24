#include "volarb/implied_vol.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>

namespace volarb {

namespace {

const double double_precision_epsilon = std::numeric_limits<double>::epsilon();

struct InversionProblem {
    double forward;
    double strike;
    double years_to_expiry;
    OptionType option_type;
    double target_price;
    double quoted_undiscounted_price;
};

struct PriceAndVega {
    double price;
    double vega;
};

ImpliedVolatilityResult failed_inversion(InversionStatus status) {
    return ImpliedVolatilityResult{0.0, status, 0, 0.0, std::numeric_limits<double>::infinity()};
}

PriceAndVega undiscounted_price_and_vega(
    double forward, double strike, double years_to_expiry, double volatility, OptionType option_type) {
    const BlackScholesGreeks greeks = black_scholes_price_and_greeks(
        BlackScholesInputs{forward, strike, years_to_expiry, volatility, 1.0, option_type});
    return {greeks.price, greeks.vega_with_respect_to_volatility};
}

double undiscounted_price(
    double forward, double strike, double years_to_expiry, double volatility, OptionType option_type) {
    return undiscounted_price_and_vega(forward, strike, years_to_expiry, volatility, option_type).price;
}




ImpliedVolatilityResult completed_inversion(
    const InversionProblem& problem, double volatility, InversionStatus status, int iterations) {
    const PriceAndVega evaluated = undiscounted_price_and_vega(
        problem.forward, problem.strike, problem.years_to_expiry, volatility, problem.option_type);
    const double largest_price_term = largest_price_term_magnitude(BlackScholesInputs{
        problem.forward, problem.strike, problem.years_to_expiry, volatility, 1.0, problem.option_type});
    return ImpliedVolatilityResult{
        volatility,
        status,
        iterations,
        std::abs(evaluated.price - problem.target_price),
        volatility_uncertainty_from_price_resolution(
            largest_price_term, problem.quoted_undiscounted_price, evaluated.vega),
    };
}

ImpliedVolatilityResult solve_bracketed_newton(const InversionProblem& problem) {
    double lower = minimum_volatility;
    double upper = maximum_volatility;
    const double seed =
        brenner_subrahmanyam_seed(problem.forward, problem.years_to_expiry, problem.target_price);
    double volatility = clamp_into_bracket(seed, lower, upper);

    for (int iteration = 1; iteration <= maximum_iterations; ++iteration) {
        const PriceAndVega evaluated = undiscounted_price_and_vega(
            problem.forward, problem.strike, problem.years_to_expiry, volatility, problem.option_type);
        if (evaluated.price > problem.target_price) {
            upper = volatility;
        } else {
            lower = volatility;
        }
        const double next_volatility = next_volatility_estimate(
            volatility, evaluated.price - problem.target_price, evaluated.vega, lower, upper);
        const double step_size = std::abs(next_volatility - volatility);
        volatility = next_volatility;
        if (step_size <= volatility_convergence_tolerance * volatility) {
            return completed_inversion(problem, volatility, InversionStatus::Converged, iteration);
        }
    }

    return completed_inversion(problem, volatility, InversionStatus::NotConverged, maximum_iterations);
}

}

std::string name_of_inversion_status(InversionStatus status) {
    switch (status) {
    case InversionStatus::Converged:
        return "converged";
    case InversionStatus::BelowIntrinsic:
        return "below_intrinsic";
    case InversionStatus::AboveNoArbitrageBound:
        return "above_no_arbitrage_bound";
    case InversionStatus::BelowVolatilityFloor:
        return "below_volatility_floor";
    case InversionStatus::AboveVolatilityCeiling:
        return "above_volatility_ceiling";
    case InversionStatus::NotConverged:
        return "not_converged";
    case InversionStatus::DegenerateExpiry:
        return "degenerate_expiry";
    }
    return "not_converged";
}

double brenner_subrahmanyam_seed(double forward, double years_to_expiry, double target_price) {
    return std::sqrt(2.0 * std::numbers::pi / years_to_expiry) * target_price / forward;
}

double clamp_into_bracket(double value, double lower, double upper) {
    return std::min(std::max(value, lower), upper);
}

double next_volatility_estimate(
    double volatility, double price_error, double vega, double lower, double upper) {
    const double bisection = 0.5 * (lower + upper);
    if (vega < minimum_usable_vega) {
        return bisection;
    }
    const double newton_candidate = volatility - price_error / vega;
    if (newton_candidate <= lower || newton_candidate >= upper) {
        return bisection;
    }
    return newton_candidate;
}

OptionType out_of_the_money_option_type(double forward, double strike) {
    return strike < forward ? OptionType::Put : OptionType::Call;
}

double undiscounted_out_of_the_money_target_price(const ImpliedVolatilityInputs& inputs) {
    const double undiscounted_price_of_quote = inputs.option_price / inputs.discount_factor;
    const OptionType target_type = out_of_the_money_option_type(inputs.forward, inputs.strike);
    if (inputs.option_type == target_type) {
        return undiscounted_price_of_quote;
    }
    if (target_type == OptionType::Call) {
        return undiscounted_price_of_quote + inputs.forward - inputs.strike;
    }
    return undiscounted_price_of_quote - inputs.forward + inputs.strike;
}

double undiscounted_no_arbitrage_price_ceiling(double forward, double strike, OptionType option_type) {
    return option_type == OptionType::Call ? forward : strike;
}

double volatility_uncertainty_from_price_resolution(
    double largest_price_term, double quoted_undiscounted_price, double vega) {
    if (vega < minimum_usable_vega) {
        return std::numeric_limits<double>::infinity();
    }
    const double largest_price_intermediate = std::max(largest_price_term, quoted_undiscounted_price);
    return double_precision_epsilon * largest_price_intermediate / vega;
}

ImpliedVolatilityResult invert_black_implied_volatility(const ImpliedVolatilityInputs& inputs) {
    if (inputs.years_to_expiry <= 0.0) {
        return failed_inversion(InversionStatus::DegenerateExpiry);
    }

    const double forward = inputs.forward;
    const double strike = inputs.strike;
    const double years = inputs.years_to_expiry;
    const OptionType option_type = out_of_the_money_option_type(forward, strike);
    const double target_price = undiscounted_out_of_the_money_target_price(inputs);

    if (target_price <= 0.0) {
        return failed_inversion(InversionStatus::BelowIntrinsic);
    }
    if (target_price >= undiscounted_no_arbitrage_price_ceiling(forward, strike, option_type)) {
        return failed_inversion(InversionStatus::AboveNoArbitrageBound);
    }
    if (target_price <= undiscounted_price(forward, strike, years, minimum_volatility, option_type)) {
        return failed_inversion(InversionStatus::BelowVolatilityFloor);
    }
    if (target_price >= undiscounted_price(forward, strike, years, maximum_volatility, option_type)) {
        return failed_inversion(InversionStatus::AboveVolatilityCeiling);
    }

    return solve_bracketed_newton(InversionProblem{
        forward, strike, years, option_type, target_price, inputs.option_price / inputs.discount_factor});
}

}
