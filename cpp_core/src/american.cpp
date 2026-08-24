#include "volarb/american.hpp"

#include <algorithm>
#include <cmath>

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
