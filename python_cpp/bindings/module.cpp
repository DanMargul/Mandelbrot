#include "volarb/forward_curve.hpp"
#include "volarb/implied_vol.hpp"
#include "volarb/market_data.hpp"
#include "volarb/pricing.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <filesystem>
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
using volarb::AsOfChainReader;
using volarb::ChainDatasetError;
using volarb::ChainQuery;
using volarb::ContractQuote;
using volarb::CorruptDatasetError;
using volarb::format_canonical_date;
using volarb::format_canonical_timestamp;
using volarb::KnowledgeHorizon;
using volarb::LookaheadRequestedError;
using volarb::open_chain_dataset;
using volarb::parse_canonical_timestamp;
using volarb::ForwardCurvePoint;
using volarb::imply_forward_curve;
using volarb::name_of_forward_curve_status;

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

AsOfChainReader open_chain_dataset_from_strings(const std::string& dataset_root,
                                                const std::string& knowledge_horizon) {
    return open_chain_dataset(std::filesystem::path(dataset_root),
                              KnowledgeHorizon{parse_canonical_timestamp(knowledge_horizon)});
}

std::vector<ContractQuote> chain_as_of_from_strings(const AsOfChainReader& reader,
                                                    const std::string& underlying_symbol,
                                                    const std::string& observation_time,
                                                    bool include_adjusted_contracts) {
    return reader.chain_as_of(ChainQuery{underlying_symbol, parse_canonical_timestamp(observation_time),
                                         include_adjusted_contracts});
}

std::vector<ForwardCurvePoint> imply_forward_curve_from_strings(
    const std::vector<ContractQuote>& quotes, const std::string& observation_time) {
    return imply_forward_curve(quotes, parse_canonical_timestamp(observation_time));
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
    py::register_exception<ChainDatasetError>(module, "ChainDatasetError", PyExc_ValueError);
    py::register_exception<LookaheadRequestedError>(module, "LookaheadRequestedError", PyExc_ValueError);
    py::register_exception<CorruptDatasetError>(module, "CorruptDatasetError", PyExc_ValueError);

    py::class_<ContractQuote>(module, "ContractQuote")
        .def_readonly("contract_symbol", &ContractQuote::contract_symbol)
        .def_readonly("strike", &ContractQuote::strike)
        .def_readonly("contract_multiplier", &ContractQuote::contract_multiplier)
        .def_readonly("is_standard_deliverable", &ContractQuote::is_standard_deliverable)
        .def_readonly("ingest_sequence", &ContractQuote::ingest_sequence)
        .def_readonly("underlying_price", &ContractQuote::underlying_price)
        .def_readonly("bid_price", &ContractQuote::bid_price)
        .def_readonly("ask_price", &ContractQuote::ask_price)
        .def_readonly("bid_size", &ContractQuote::bid_size)
        .def_readonly("ask_size", &ContractQuote::ask_size)
        .def_property_readonly(
            "expiry_date", [](const ContractQuote& quote) { return format_canonical_date(quote.expiry_date); })
        .def_property_readonly(
            "option_type", [](const ContractQuote& quote) { return name_of_option_type(quote.option_type); })
        .def_property_readonly(
            "event_time",
            [](const ContractQuote& quote) { return format_canonical_timestamp(quote.event_time); })
        .def_property_readonly("knowledge_time", [](const ContractQuote& quote) {
            return format_canonical_timestamp(quote.knowledge_time);
        });

    py::class_<AsOfChainReader>(module, "AsOfChainReader")
        .def("chain_as_of", &chain_as_of_from_strings, py::arg("underlying_symbol"),
             py::arg("observation_time"), py::arg("include_adjusted_contracts"))
        .def_property_readonly("dataset_digest", &AsOfChainReader::dataset_digest)
        .def_property_readonly("knowledge_horizon", [](const AsOfChainReader& reader) {
            return format_canonical_timestamp(reader.knowledge_horizon());
        });

    module.def("open_chain_dataset", &open_chain_dataset_from_strings, py::arg("dataset_root"),
               py::arg("knowledge_horizon"));

    py::class_<ForwardCurvePoint>(module, "ForwardCurvePoint")
        .def_readonly("years_to_expiry", &ForwardCurvePoint::years_to_expiry)
        .def_readonly("spot_price", &ForwardCurvePoint::spot_price)
        .def_readonly("forward", &ForwardCurvePoint::forward)
        .def_readonly("forward_standard_error", &ForwardCurvePoint::forward_standard_error)
        .def_readonly("discount_factor", &ForwardCurvePoint::discount_factor)
        .def_readonly("discount_factor_standard_error",
                      &ForwardCurvePoint::discount_factor_standard_error)
        .def_readonly("implied_zero_rate", &ForwardCurvePoint::implied_zero_rate)
        .def_readonly("implied_carry_rate", &ForwardCurvePoint::implied_carry_rate)
        .def_readonly("parity_pair_count", &ForwardCurvePoint::parity_pair_count)
        .def_readonly("active_pair_count", &ForwardCurvePoint::active_pair_count)
        .def_readonly("chi_square_per_degree_of_freedom",
                      &ForwardCurvePoint::chi_square_per_degree_of_freedom)
        .def_readonly("discount_factor_is_monotone_in_expiry",
                      &ForwardCurvePoint::discount_factor_is_monotone_in_expiry)
        .def_property_readonly(
            "expiry_date",
            [](const ForwardCurvePoint& point) { return format_canonical_date(point.expiry_date); })
        .def_property_readonly("status", [](const ForwardCurvePoint& point) {
            return name_of_forward_curve_status(point.status);
        });

    module.def("imply_forward_curve", &imply_forward_curve_from_strings, py::arg("quotes"),
               py::arg("observation_time"));

    module.def(
        "out_of_the_money_option_type",
        [](double forward, double strike) {
            return name_of_option_type(out_of_the_money_option_type(forward, strike));
        },
        py::arg("forward"), py::arg("strike"));
}
