#include "volarb/implied_vol.hpp"
#include "volarb/pricing.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <string>
#include <vector>

namespace py = pybind11;

using volarb::black_scholes_price;
using volarb::black_scholes_price_and_greeks;
using volarb::BlackScholesGreeks;
using volarb::BlackScholesInputs;
using volarb::ImpliedVolatilityInputs;
using volarb::ImpliedVolatilityResult;
using volarb::InvalidOptionInputsError;
using volarb::invert_black_implied_volatility;
using volarb::name_of_inversion_status;
using volarb::name_of_option_type;
using volarb::option_type_from_name;
using volarb::out_of_the_money_option_type;
using volarb::standard_normal_cumulative_distribution;
using volarb::standard_normal_probability_density;

namespace {

BlackScholesInputs make_black_scholes_inputs(
    double forward, double strike, double years_to_expiry, double volatility, double discount_factor,
    const std::string& option_type) {
    return BlackScholesInputs{
        forward, strike, years_to_expiry, volatility, discount_factor, option_type_from_name(option_type)};
}

ImpliedVolatilityInputs make_implied_volatility_inputs(
    double forward, double strike, double years_to_expiry, double discount_factor, double option_price,
    const std::string& option_type) {
    return ImpliedVolatilityInputs{
        forward, strike, years_to_expiry, discount_factor, option_price, option_type_from_name(option_type)};
}

std::vector<BlackScholesGreeks> black_scholes_price_and_greeks_batch(
    const std::vector<BlackScholesInputs>& batch) {
    std::vector<BlackScholesGreeks> results;
    results.reserve(batch.size());
    for (const BlackScholesInputs& inputs : batch) {
        results.push_back(black_scholes_price_and_greeks(inputs));
    }
    return results;
}

std::vector<ImpliedVolatilityResult> invert_black_implied_volatility_batch(
    const std::vector<ImpliedVolatilityInputs>& batch) {
    std::vector<ImpliedVolatilityResult> results;
    results.reserve(batch.size());
    for (const ImpliedVolatilityInputs& inputs : batch) {
        results.push_back(invert_black_implied_volatility(inputs));
    }
    return results;
}

}

PYBIND11_MODULE(_volarb_core, module) {
    py::register_exception<InvalidOptionInputsError>(module, "InvalidOptionInputsError", PyExc_ValueError);

    py::class_<BlackScholesInputs>(module, "BlackScholesInputs")
        .def(py::init(&make_black_scholes_inputs), py::arg("forward"), py::arg("strike"),
             py::arg("years_to_expiry"), py::arg("volatility"), py::arg("discount_factor"),
             py::arg("option_type"))
        .def_readonly("forward", &BlackScholesInputs::forward)
        .def_readonly("strike", &BlackScholesInputs::strike)
        .def_readonly("years_to_expiry", &BlackScholesInputs::years_to_expiry)
        .def_readonly("volatility", &BlackScholesInputs::volatility)
        .def_readonly("discount_factor", &BlackScholesInputs::discount_factor)
        .def_property_readonly("option_type", [](const BlackScholesInputs& inputs) {
            return name_of_option_type(inputs.option_type);
        });

    py::class_<BlackScholesGreeks>(module, "BlackScholesGreeks")
        .def_readonly("price", &BlackScholesGreeks::price)
        .def_readonly("delta_with_respect_to_forward", &BlackScholesGreeks::delta_with_respect_to_forward)
        .def_readonly("gamma_with_respect_to_forward", &BlackScholesGreeks::gamma_with_respect_to_forward)
        .def_readonly("vega_with_respect_to_volatility", &BlackScholesGreeks::vega_with_respect_to_volatility)
        .def_readonly("theta_with_respect_to_time", &BlackScholesGreeks::theta_with_respect_to_time);

    py::class_<ImpliedVolatilityInputs>(module, "ImpliedVolatilityInputs")
        .def(py::init(&make_implied_volatility_inputs), py::arg("forward"), py::arg("strike"),
             py::arg("years_to_expiry"), py::arg("discount_factor"), py::arg("option_price"),
             py::arg("option_type"))
        .def_readonly("forward", &ImpliedVolatilityInputs::forward)
        .def_readonly("strike", &ImpliedVolatilityInputs::strike)
        .def_readonly("years_to_expiry", &ImpliedVolatilityInputs::years_to_expiry)
        .def_readonly("discount_factor", &ImpliedVolatilityInputs::discount_factor)
        .def_readonly("option_price", &ImpliedVolatilityInputs::option_price)
        .def_property_readonly("option_type", [](const ImpliedVolatilityInputs& inputs) {
            return name_of_option_type(inputs.option_type);
        });

    py::class_<ImpliedVolatilityResult>(module, "ImpliedVolatilityResult")
        .def_readonly("volatility", &ImpliedVolatilityResult::volatility)
        .def_readonly("iterations", &ImpliedVolatilityResult::iterations)
        .def_readonly("absolute_price_error", &ImpliedVolatilityResult::absolute_price_error)
        .def_readonly("volatility_uncertainty", &ImpliedVolatilityResult::volatility_uncertainty)
        .def_property_readonly("status", [](const ImpliedVolatilityResult& result) {
            return name_of_inversion_status(result.status);
        });

    module.def("standard_normal_cumulative_distribution", &standard_normal_cumulative_distribution,
               py::arg("x"));
    module.def("standard_normal_probability_density", &standard_normal_probability_density, py::arg("x"));
    module.def("black_scholes_price", &black_scholes_price, py::arg("inputs"));
    module.def("black_scholes_price_and_greeks", &black_scholes_price_and_greeks, py::arg("inputs"));
    module.def("black_scholes_price_and_greeks_batch", &black_scholes_price_and_greeks_batch,
               py::arg("batch"));
    module.def("invert_black_implied_volatility", &invert_black_implied_volatility, py::arg("inputs"));
    module.def("invert_black_implied_volatility_batch", &invert_black_implied_volatility_batch,
               py::arg("batch"));
    module.def(
        "out_of_the_money_option_type",
        [](double forward, double strike) {
            return name_of_option_type(out_of_the_money_option_type(forward, strike));
        },
        py::arg("forward"), py::arg("strike"));
}
