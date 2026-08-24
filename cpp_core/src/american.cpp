#include "volarb/american.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

namespace volarb {

namespace {

struct LatticeParameters {
    double time_step;
    double log_up;
    double discount;
    double up_probability;
    double down_probability;
};

LatticeParameters lattice_parameters(const LatticeInputs& inputs, int steps) {
    const double time_step = inputs.years_to_expiry / static_cast<double>(steps);
    const double log_up = inputs.volatility * std::sqrt(time_step);
    const double up_move = std::exp(log_up);
    const double down_move = std::exp(-log_up);
    const double growth = std::exp((inputs.zero_rate - inputs.carry_rate) * time_step);
    const double discount = std::exp(-inputs.zero_rate * time_step);
    const double up_probability = (growth - down_move) / (up_move - down_move);
    return LatticeParameters{time_step, log_up, discount, up_probability, 1.0 - up_probability};
}

bool has_no_optionality(const LatticeInputs& inputs) {
    return inputs.years_to_expiry <= 0.0 || inputs.volatility <= 0.0;
}

double one_step_black_scholes_value(const LatticeInputs& inputs, double spot_price, double time_step) {
    const double carry = inputs.zero_rate - inputs.carry_rate;
    return black_scholes_price(BlackScholesInputs{
        spot_price * std::exp(carry * time_step),
        inputs.strike,
        time_step,
        inputs.volatility,
        std::exp(-inputs.zero_rate * time_step),
        inputs.option_type,
    });
}

}

ExerciseStyle exercise_style_from_name(const std::string& name) {
    if (name == "european") {
        return ExerciseStyle::European;
    }
    if (name == "american") {
        return ExerciseStyle::American;
    }
    throw InvalidLatticeInputsError("exercise_style must be 'european' or 'american', found '" + name + "'");
}

std::string name_of_exercise_style(ExerciseStyle exercise_style) {
    return exercise_style == ExerciseStyle::European ? "european" : "american";
}

void validate_lattice_inputs(const LatticeInputs& inputs, int steps) {
    if (!(inputs.spot_price > 0.0)) {
        throw InvalidLatticeInputsError("spot_price must be positive, got " +
                                        std::to_string(inputs.spot_price));
    }
    if (!(inputs.strike > 0.0)) {
        throw InvalidLatticeInputsError("strike must be positive, got " + std::to_string(inputs.strike));
    }
    if (inputs.years_to_expiry < 0.0) {
        throw InvalidLatticeInputsError("years_to_expiry must not be negative, got " +
                                        std::to_string(inputs.years_to_expiry));
    }
    if (inputs.volatility < 0.0) {
        throw InvalidLatticeInputsError("volatility must not be negative, got " +
                                        std::to_string(inputs.volatility));
    }
    if (steps < minimum_lattice_steps || steps > maximum_lattice_steps) {
        throw InvalidLatticeInputsError("steps out of range, got " + std::to_string(steps));
    }
}

double intrinsic_value(double spot_price, double strike, OptionType option_type) {
    if (option_type == OptionType::Call) {
        return std::max(spot_price - strike, 0.0);
    }
    return std::max(strike - spot_price, 0.0);
}

std::vector<double> spot_ladder(double spot_price, double log_up, int steps) {
    std::vector<double> ladder;
    ladder.reserve(static_cast<std::size_t>(2 * steps + 1));
    for (int index = 0; index <= 2 * steps; ++index) {
        ladder.push_back(spot_price * std::exp(log_up * static_cast<double>(index - steps)));
    }
    return ladder;
}

double cox_ross_rubinstein_price(const LatticeInputs& inputs, int steps) {
    validate_lattice_inputs(inputs, steps);
    if (has_no_optionality(inputs)) {
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type);
    }

    const LatticeParameters parameters = lattice_parameters(inputs, steps);
    const std::vector<double> ladder = spot_ladder(inputs.spot_price, parameters.log_up, steps);
    const bool is_american = inputs.exercise_style == ExerciseStyle::American;

    std::vector<double> values(static_cast<std::size_t>(steps + 1));
    for (int node = 0; node <= steps; ++node) {
        values[static_cast<std::size_t>(node)] = intrinsic_value(
            ladder[static_cast<std::size_t>(2 * node)], inputs.strike, inputs.option_type);
    }

    for (int level = steps - 1; level >= 0; --level) {
        const int offset = steps - level;
        for (int node = 0; node <= level; ++node) {
            const auto index = static_cast<std::size_t>(node);
            const double continuation =
                parameters.discount * (parameters.up_probability * values[index + 1] +
                                       parameters.down_probability * values[index]);
            if (is_american) {
                const double exercise = intrinsic_value(
                    ladder[static_cast<std::size_t>(offset + 2 * node)], inputs.strike, inputs.option_type);
                values[index] = std::max(continuation, exercise);
            } else {
                values[index] = continuation;
            }
        }
    }
    return values[0];
}

double binomial_black_scholes_price(const LatticeInputs& inputs, int steps) {
    validate_lattice_inputs(inputs, steps);
    if (has_no_optionality(inputs)) {
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type);
    }

    const LatticeParameters parameters = lattice_parameters(inputs, steps);
    const std::vector<double> ladder = spot_ladder(inputs.spot_price, parameters.log_up, steps);
    const bool is_american = inputs.exercise_style == ExerciseStyle::American;

    std::vector<double> values(static_cast<std::size_t>(steps + 1), 0.0);
    for (int node = 0; node < steps; ++node) {
        const double spot_at_node = ladder[static_cast<std::size_t>(1 + 2 * node)];
        double smoothed = one_step_black_scholes_value(inputs, spot_at_node, parameters.time_step);
        if (is_american) {
            smoothed = std::max(smoothed, intrinsic_value(spot_at_node, inputs.strike, inputs.option_type));
        }
        values[static_cast<std::size_t>(node)] = smoothed;
    }

    for (int level = steps - 2; level >= 0; --level) {
        const int offset = steps - level;
        for (int node = 0; node <= level; ++node) {
            const auto index = static_cast<std::size_t>(node);
            const double continuation =
                parameters.discount * (parameters.up_probability * values[index + 1] +
                                       parameters.down_probability * values[index]);
            if (is_american) {
                const double exercise = intrinsic_value(
                    ladder[static_cast<std::size_t>(offset + 2 * node)], inputs.strike, inputs.option_type);
                values[index] = std::max(continuation, exercise);
            } else {
                values[index] = continuation;
            }
        }
    }
    return values[0];
}

double richardson_extrapolated_price(const LatticeInputs& inputs, int base_steps) {
    const double coarse = binomial_black_scholes_price(inputs, base_steps);
    const double fine = binomial_black_scholes_price(inputs, 2 * base_steps);
    return 2.0 * fine - coarse;
}

LatticeInputs european_counterpart(const LatticeInputs& inputs) {
    LatticeInputs european = inputs;
    european.exercise_style = ExerciseStyle::European;
    return european;
}

double early_exercise_premium(const LatticeInputs& inputs, int base_steps) {
    if (inputs.exercise_style == ExerciseStyle::European) {
        return 0.0;
    }
    const double american = richardson_extrapolated_price(inputs, base_steps);
    const double european = richardson_extrapolated_price(european_counterpart(inputs), base_steps);
    return std::max(american - european, 0.0);
}

double black_scholes_reference_price(const LatticeInputs& inputs) {
    if (has_no_optionality(inputs)) {
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type);
    }
    const double carry = inputs.zero_rate - inputs.carry_rate;
    return black_scholes_price(BlackScholesInputs{
        inputs.spot_price * std::exp(carry * inputs.years_to_expiry),
        inputs.strike,
        inputs.years_to_expiry,
        inputs.volatility,
        std::exp(-inputs.zero_rate * inputs.years_to_expiry),
        inputs.option_type,
    });
}

}

namespace volarb {

namespace {

LatticeInputs lattice_at_volatility(const AmericanInversionInputs& inputs, double volatility) {
    return LatticeInputs{inputs.spot_price, inputs.strike,     inputs.years_to_expiry,
                         volatility,        inputs.zero_rate,  inputs.carry_rate,
                         inputs.option_type, inputs.exercise_style};
}

double price_at_volatility(const AmericanInversionInputs& inputs, double volatility) {
    return richardson_extrapolated_price(lattice_at_volatility(inputs, volatility));
}

double european_vega_at_volatility(const AmericanInversionInputs& inputs, double volatility) {
    const double carry = inputs.zero_rate - inputs.carry_rate;
    const BlackScholesGreeks greeks = black_scholes_price_and_greeks(BlackScholesInputs{
        inputs.spot_price * std::exp(carry * inputs.years_to_expiry),
        inputs.strike,
        inputs.years_to_expiry,
        volatility,
        std::exp(-inputs.zero_rate * inputs.years_to_expiry),
        inputs.option_type,
    });
    return greeks.vega_with_respect_to_volatility;
}

std::pair<double, double> forward_and_discount_of(const AmericanInversionInputs& inputs) {
    const double carry = inputs.zero_rate - inputs.carry_rate;
    return {inputs.spot_price * std::exp(carry * inputs.years_to_expiry),
            std::exp(-inputs.zero_rate * inputs.years_to_expiry)};
}

double no_arbitrage_price_floor(const AmericanInversionInputs& inputs) {
    if (inputs.exercise_style == ExerciseStyle::American) {
        return intrinsic_value(inputs.spot_price, inputs.strike, inputs.option_type);
    }
    const auto [forward, discount_factor] = forward_and_discount_of(inputs);
    return discount_factor * intrinsic_value(forward, inputs.strike, inputs.option_type);
}

double no_arbitrage_price_ceiling(const AmericanInversionInputs& inputs) {
    if (inputs.exercise_style == ExerciseStyle::American) {
        return inputs.option_type == OptionType::Call ? inputs.spot_price : inputs.strike;
    }
    const auto [forward, discount_factor] = forward_and_discount_of(inputs);
    return discount_factor * (inputs.option_type == OptionType::Call ? forward : inputs.strike);
}

AmericanInversionResult failed_american_inversion(AmericanInversionStatus status) {
    return AmericanInversionResult{0.0, status, 0, 0.0};
}

AmericanInversionResult solve_american_volatility(const AmericanInversionInputs& inputs) {
    double lower = minimum_volatility;
    double upper = maximum_volatility;
    double volatility = clamp_into_bracket(
        brenner_subrahmanyam_seed(inputs.spot_price, inputs.years_to_expiry, inputs.option_price), lower,
        upper);

    for (int iteration = 1; iteration <= maximum_iterations; ++iteration) {
        const double price = price_at_volatility(inputs, volatility);
        if (price > inputs.option_price) {
            upper = volatility;
        } else {
            lower = volatility;
        }
        const double next_volatility =
            next_volatility_estimate(volatility, price - inputs.option_price,
                                     european_vega_at_volatility(inputs, volatility), lower, upper);
        const double step_size = std::abs(next_volatility - volatility);
        volatility = next_volatility;
        if (step_size <= american_volatility_convergence_tolerance * volatility) {
            const double final_price = price_at_volatility(inputs, volatility);
            return AmericanInversionResult{volatility, AmericanInversionStatus::Converged, iteration,
                                           std::abs(final_price - inputs.option_price)};
        }
    }

    const double final_price = price_at_volatility(inputs, volatility);
    return AmericanInversionResult{volatility, AmericanInversionStatus::NotConverged, maximum_iterations,
                                   std::abs(final_price - inputs.option_price)};
}

}

std::string name_of_american_inversion_status(AmericanInversionStatus status) {
    switch (status) {
    case AmericanInversionStatus::Converged:
        return "converged";
    case AmericanInversionStatus::BelowIntrinsic:
        return "below_intrinsic";
    case AmericanInversionStatus::AboveNoArbitrageBound:
        return "above_no_arbitrage_bound";
    case AmericanInversionStatus::AtExerciseBoundary:
        return "at_exercise_boundary";
    case AmericanInversionStatus::AboveVolatilityCeiling:
        return "above_volatility_ceiling";
    case AmericanInversionStatus::NotConverged:
        return "not_converged";
    case AmericanInversionStatus::DegenerateExpiry:
        return "degenerate_expiry";
    }
    return "not_converged";
}

AmericanInversionResult invert_american_implied_volatility(const AmericanInversionInputs& inputs) {
    if (inputs.years_to_expiry <= 0.0) {
        return failed_american_inversion(AmericanInversionStatus::DegenerateExpiry);
    }
    if (inputs.option_price < no_arbitrage_price_floor(inputs)) {
        return failed_american_inversion(AmericanInversionStatus::BelowIntrinsic);
    }
    if (inputs.option_price >= no_arbitrage_price_ceiling(inputs)) {
        return failed_american_inversion(AmericanInversionStatus::AboveNoArbitrageBound);
    }
    if (inputs.option_price <= price_at_volatility(inputs, minimum_volatility)) {
        return failed_american_inversion(AmericanInversionStatus::AtExerciseBoundary);
    }
    if (inputs.option_price >= price_at_volatility(inputs, maximum_volatility)) {
        return failed_american_inversion(AmericanInversionStatus::AboveVolatilityCeiling);
    }
    return solve_american_volatility(inputs);
}

}
