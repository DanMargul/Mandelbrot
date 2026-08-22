#pragma once

#include <stdexcept>
#include <string>

namespace volarb {

enum class OptionType { Call, Put };

struct BlackScholesInputs {
    double forward;
    double strike;
    double years_to_expiry;
    double volatility;
    double discount_factor;
    OptionType option_type;
};

struct BlackScholesGreeks {
    double price;
    double delta_with_respect_to_forward;
    double gamma_with_respect_to_forward;
    double vega_with_respect_to_volatility;
    double theta_with_respect_to_time;
};

class InvalidOptionInputsError : public std::invalid_argument {
  public:
    explicit InvalidOptionInputsError(const std::string& message) : std::invalid_argument(message) {}
};

OptionType option_type_from_name(const std::string& name);
std::string name_of_option_type(OptionType option_type);

double standard_normal_cumulative_distribution(double x);
double standard_normal_probability_density(double x);

void validate_black_scholes_inputs(const BlackScholesInputs& inputs);
bool has_degenerate_expiry(const BlackScholesInputs& inputs);
double forward_intrinsic_value(const BlackScholesInputs& inputs);
double forward_intrinsic_delta(const BlackScholesInputs& inputs);
double largest_price_term_magnitude(const BlackScholesInputs& inputs);

double black_scholes_price(const BlackScholesInputs& inputs);
BlackScholesGreeks black_scholes_price_and_greeks(const BlackScholesInputs& inputs);

}
