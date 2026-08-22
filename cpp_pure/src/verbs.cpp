#include "verbs.hpp"

#include "volarb/implied_vol.hpp"
#include "volarb/pricing.hpp"

namespace volarb::cli {

nlohmann::json price_option_record(const nlohmann::json& record) {
    const BlackScholesGreeks greeks = black_scholes_price_and_greeks(BlackScholesInputs{
        required_number(record, "forward"),
        required_number(record, "strike"),
        required_number(record, "years_to_expiry"),
        required_number(record, "volatility"),
        required_number(record, "discount_factor"),
        required_option_type(record, "option_type"),
    });

    nlohmann::json result;
    result["id"] = required_string(record, "id");
    result["price"] = greeks.price;
    result["delta_with_respect_to_forward"] = greeks.delta_with_respect_to_forward;
    result["gamma_with_respect_to_forward"] = greeks.gamma_with_respect_to_forward;
    result["vega_with_respect_to_volatility"] = greeks.vega_with_respect_to_volatility;
    result["theta_with_respect_to_time"] = greeks.theta_with_respect_to_time;
    return result;
}

nlohmann::json invert_implied_volatility_record(const nlohmann::json& record) {
    const ImpliedVolatilityResult inversion = invert_black_implied_volatility(ImpliedVolatilityInputs{
        required_number(record, "forward"),
        required_number(record, "strike"),
        required_number(record, "years_to_expiry"),
        required_number(record, "discount_factor"),
        required_number(record, "option_price"),
        required_option_type(record, "option_type"),
    });

    nlohmann::json result;
    result["id"] = required_string(record, "id");
    result["volatility"] = inversion.volatility;
    result["status"] = name_of_inversion_status(inversion.status);
    result["iterations"] = inversion.iterations;
    result["absolute_price_error"] = inversion.absolute_price_error;
    result["volatility_uncertainty"] = json_safe_number(inversion.volatility_uncertainty);
    return result;
}

const std::map<std::string, Verb>& supported_verbs() {
    static const std::map<std::string, Verb> verbs = {
        {"price-options",
         Verb{"price-options", "pricing_request/v1", "pricing_result/v1", price_option_record}},
        {"invert-implied-volatility",
         Verb{"invert-implied-volatility", "implied_volatility_request/v1",
              "implied_volatility_result/v1", invert_implied_volatility_record}},
    };
    return verbs;
}

}
