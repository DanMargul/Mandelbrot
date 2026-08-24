#pragma once

#include "volarb/implied_vol.hpp"
#include "volarb/pricing.hpp"

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

enum class ExerciseStyle { European, American };

inline constexpr int richardson_base_steps = 128;
inline constexpr int minimum_lattice_steps = 2;
inline constexpr int maximum_lattice_steps = 4096;
inline constexpr double american_volatility_convergence_tolerance = 1e-7;

class InvalidLatticeInputsError : public std::invalid_argument {
  public:
    explicit InvalidLatticeInputsError(const std::string& message) : std::invalid_argument(message) {}
};

struct LatticeInputs {
    double spot_price;
    double strike;
    double years_to_expiry;
    double volatility;
    double zero_rate;
    double carry_rate;
    OptionType option_type;
    ExerciseStyle exercise_style;
};

ExerciseStyle exercise_style_from_name(const std::string& name);
std::string name_of_exercise_style(ExerciseStyle exercise_style);

void validate_lattice_inputs(const LatticeInputs& inputs, int steps);
double intrinsic_value(double spot_price, double strike, OptionType option_type);
std::vector<double> spot_ladder(double spot_price, double log_up, int steps);

double cox_ross_rubinstein_price(const LatticeInputs& inputs, int steps);
double binomial_black_scholes_price(const LatticeInputs& inputs, int steps);
double richardson_extrapolated_price(const LatticeInputs& inputs, int base_steps = richardson_base_steps);
LatticeInputs european_counterpart(const LatticeInputs& inputs);
double early_exercise_premium(const LatticeInputs& inputs, int base_steps = richardson_base_steps);
double black_scholes_reference_price(const LatticeInputs& inputs);

}

namespace volarb {

enum class AmericanInversionStatus {
    Converged,
    BelowIntrinsic,
    AboveNoArbitrageBound,
    AtExerciseBoundary,
    AboveVolatilityCeiling,
    NotConverged,
    DegenerateExpiry,
};

struct AmericanInversionInputs {
    double spot_price;
    double strike;
    double years_to_expiry;
    double zero_rate;
    double carry_rate;
    double option_price;
    OptionType option_type;
    ExerciseStyle exercise_style;
};

struct AmericanInversionResult {
    double volatility;
    AmericanInversionStatus status;
    int iterations;
    double absolute_price_error;
};

std::string name_of_american_inversion_status(AmericanInversionStatus status);
AmericanInversionResult invert_american_implied_volatility(const AmericanInversionInputs& inputs);

}
