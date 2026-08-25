#include "volarb/american.hpp"
#include "volarb/forward_curve.hpp"
#include "volarb/implied_vol.hpp"
#include "volarb/market_data.hpp"
#include "volarb/pricing.hpp"
#include "volarb/svi.hpp"
#include "volarb/svi_calibration.hpp"
#include "volarb/svi_surface.hpp"
#include "volarb/essvi.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <filesystem>
#include <optional>
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
using volarb::early_exercise_premium;
using volarb::european_counterpart;
using volarb::exercise_style_from_name;
using volarb::ExerciseStyle;
using volarb::InvalidLatticeInputsError;
using volarb::LatticeInputs;
using volarb::richardson_base_steps;
using volarb::richardson_extrapolated_price;
using volarb::AmericanInversionInputs;
using volarb::AmericanInversionResult;
using volarb::invert_american_implied_volatility;
using volarb::name_of_american_inversion_status;
using volarb::default_scan_steps;
using volarb::InvalidSviParametersError;
using volarb::calibrate_essvi_surface;
using volarb::default_surface_scan_steps;
using volarb::EssviCalibration;
using volarb::EssviSliceQuotes;
using volarb::InvalidEssviInputsError;
using volarb::name_of_essvi_status;
using volarb::default_time_steps_per_interval;
using volarb::InvalidSviSurfaceError;
using volarb::name_of_svi_status;
using volarb::name_of_svi_surface_status;
using volarb::scan_svi_surface;
using volarb::SviSurfaceScan;
using volarb::SviSurfaceSlice;
using volarb::scan_svi_slice;
using volarb::SviParameters;
using volarb::SviSliceScan;
using volarb::calibrate_svi_slice;
using volarb::InvalidCalibrationInputsError;
using volarb::name_of_svi_calibration_status;
using volarb::SliceObservation;
using volarb::SviCalibration;

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
    const std::vector<ContractQuote>& quotes, const std::string& observation_time,
    std::optional<double> zero_rate) {
    return imply_forward_curve(quotes, parse_canonical_timestamp(observation_time), zero_rate);
}

AmericanInversionResult invert_american_from_strings(double spot_price, double strike,
                                                     double years_to_expiry, double zero_rate,
                                                     double carry_rate, double option_price,
                                                     const std::string& option_type,
                                                     const std::string& exercise_style) {
    return invert_american_implied_volatility(AmericanInversionInputs{
        spot_price, strike, years_to_expiry, zero_rate, carry_rate, option_price,
        option_type_from_name(option_type), exercise_style_from_name(exercise_style)});
}

SviCalibration calibrate_svi_slice_from_values(const std::vector<double>& log_moneyness,
                                               const std::vector<double>& total_variances,
                                               const std::vector<double>& weights,
                                               double lowest_log_moneyness,
                                               double highest_log_moneyness) {
    if (log_moneyness.size() != total_variances.size() || log_moneyness.size() != weights.size()) {
        throw InvalidCalibrationInputsError("observation columns must be the same length");
    }
    std::vector<SliceObservation> observations;
    observations.reserve(log_moneyness.size());
    for (std::size_t index = 0; index < log_moneyness.size(); ++index) {
        observations.push_back(
            SliceObservation{log_moneyness[index], total_variances[index], weights[index]});
    }
    return calibrate_svi_slice(observations, lowest_log_moneyness, highest_log_moneyness);
}

std::vector<double> field_of(const EssviCalibration& calibration, int which) {
    std::vector<double> values;
    values.reserve(calibration.slices.size());
    for (const SviParameters& slice : calibration.slices) {
        const double picked = which == 0   ? slice.a
                              : which == 1 ? slice.b
                              : which == 2 ? slice.rho
                              : which == 3 ? slice.m
                                           : slice.sigma;
        values.push_back(picked);
    }
    return values;
}

EssviCalibration calibrate_essvi_surface_from_values(
    const std::vector<double>& years_to_expiry, const std::vector<std::vector<double>>& log_moneyness,
    const std::vector<std::vector<double>>& total_variances,
    const std::vector<std::vector<double>>& weights, double lowest_log_moneyness,
    double highest_log_moneyness) {
    if (years_to_expiry.size() != log_moneyness.size() ||
        years_to_expiry.size() != total_variances.size() || years_to_expiry.size() != weights.size()) {
        throw InvalidEssviInputsError("every slice column must have the same length");
    }
    std::vector<EssviSliceQuotes> quotes;
    quotes.reserve(years_to_expiry.size());
    for (std::size_t slice = 0; slice < years_to_expiry.size(); ++slice) {
        if (log_moneyness[slice].size() != total_variances[slice].size() ||
            log_moneyness[slice].size() != weights[slice].size()) {
            throw InvalidEssviInputsError("every observation column must have the same length");
        }
        std::vector<SliceObservation> observations;
        observations.reserve(log_moneyness[slice].size());
        for (std::size_t index = 0; index < log_moneyness[slice].size(); ++index) {
            observations.push_back(SliceObservation{log_moneyness[slice][index],
                                                    total_variances[slice][index],
                                                    weights[slice][index]});
        }
        quotes.push_back(EssviSliceQuotes{years_to_expiry[slice], observations});
    }
    return calibrate_essvi_surface(quotes, lowest_log_moneyness, highest_log_moneyness);
}

SviSurfaceScan scan_svi_surface_from_values(const std::vector<double>& years_to_expiry,
                                            const std::vector<double>& a, const std::vector<double>& b,
                                            const std::vector<double>& rho,
                                            const std::vector<double>& m,
                                            const std::vector<double>& sigma,
                                            double lowest_log_moneyness, double highest_log_moneyness,
                                            int scan_steps, int time_steps_per_interval) {
    if (years_to_expiry.size() != a.size() || years_to_expiry.size() != b.size() ||
        years_to_expiry.size() != rho.size() || years_to_expiry.size() != m.size() ||
        years_to_expiry.size() != sigma.size()) {
        throw InvalidSviSurfaceError("every slice column must have the same length");
    }
    std::vector<SviSurfaceSlice> slices;
    slices.reserve(years_to_expiry.size());
    for (std::size_t index = 0; index < years_to_expiry.size(); ++index) {
        slices.push_back(SviSurfaceSlice{years_to_expiry[index],
                                         SviParameters{a[index], b[index], rho[index], m[index],
                                                       sigma[index]}});
    }
    return scan_svi_surface(slices, lowest_log_moneyness, highest_log_moneyness, scan_steps,
                            time_steps_per_interval);
}

SviSliceScan scan_svi_slice_from_values(double a, double b, double rho, double m, double sigma,
                                        double lowest_log_moneyness, double highest_log_moneyness,
                                        int scan_steps) {
    return scan_svi_slice(SviParameters{a, b, rho, m, sigma}, lowest_log_moneyness,
                          highest_log_moneyness, scan_steps);
}

LatticeInputs make_lattice_inputs(double spot_price, double strike, double years_to_expiry,
                                  double volatility, double zero_rate, double carry_rate,
                                  const std::string& option_type, const std::string& exercise_style) {
    return LatticeInputs{spot_price,
                         strike,
                         years_to_expiry,
                         volatility,
                         zero_rate,
                         carry_rate,
                         option_type_from_name(option_type),
                         exercise_style_from_name(exercise_style)};
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
        .def_property_readonly("exercise_style",
                               [](const ContractQuote& quote) {
                                   return name_of_exercise_style(quote.exercise_style);
                               })
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
        .def_readonly("early_exercise_premium_stripped",
                      &ForwardCurvePoint::early_exercise_premium_stripped)
        .def_readonly("discount_factor_is_monotone_in_expiry",
                      &ForwardCurvePoint::discount_factor_is_monotone_in_expiry)
        .def_property_readonly(
            "expiry_date",
            [](const ForwardCurvePoint& point) { return format_canonical_date(point.expiry_date); })
        .def_property_readonly("status", [](const ForwardCurvePoint& point) {
            return name_of_forward_curve_status(point.status);
        });

    module.def("imply_forward_curve", &imply_forward_curve_from_strings, py::arg("quotes"),
               py::arg("observation_time"), py::arg("zero_rate"));

    py::register_exception<InvalidLatticeInputsError>(module, "InvalidLatticeInputsError",
                                                      PyExc_ValueError);
    py::register_exception<InvalidSviParametersError>(module, "InvalidSviParametersError",
                                                      PyExc_ValueError);

    py::class_<SviSliceScan>(module, "SviSliceScan")
        .def_readonly("minimum_durrleman_value", &SviSliceScan::minimum_durrleman_value)
        .def_readonly("log_moneyness_at_minimum", &SviSliceScan::log_moneyness_at_minimum)
        .def_readonly("minimum_total_variance", &SviSliceScan::minimum_total_variance)
        .def_readonly("minimum_risk_neutral_density", &SviSliceScan::minimum_risk_neutral_density)
        .def_readonly("scan_steps", &SviSliceScan::scan_steps)
        .def_property_readonly("status", [](const SviSliceScan& scan) {
            return name_of_svi_status(scan.status);
        });

    py::register_exception<InvalidCalibrationInputsError>(module, "InvalidCalibrationInputsError",
                                                          PyExc_ValueError);

    py::class_<SviCalibration>(module, "SviCalibration")
        .def_readonly("objective", &SviCalibration::objective)
        .def_readonly("weighted_root_mean_square_residual",
                      &SviCalibration::weighted_root_mean_square_residual)
        .def_readonly("simplex_iterations", &SviCalibration::simplex_iterations)
        .def_readonly("observation_count", &SviCalibration::observation_count)
        .def_readonly("fitted_curve", &SviCalibration::fitted_curve)
        .def_property_readonly("a", [](const SviCalibration& c) { return c.parameters.a; })
        .def_property_readonly("b", [](const SviCalibration& c) { return c.parameters.b; })
        .def_property_readonly("rho", [](const SviCalibration& c) { return c.parameters.rho; })
        .def_property_readonly("m", [](const SviCalibration& c) { return c.parameters.m; })
        .def_property_readonly("sigma", [](const SviCalibration& c) { return c.parameters.sigma; })
        .def_property_readonly("status", [](const SviCalibration& c) {
            return name_of_svi_calibration_status(c.status);
        });

    module.def("calibrate_svi_slice", &calibrate_svi_slice_from_values, py::arg("log_moneyness"),
               py::arg("total_variances"), py::arg("weights"), py::arg("lowest_log_moneyness"),
               py::arg("highest_log_moneyness"));

    module.attr("DEFAULT_SCAN_STEPS") = default_scan_steps;
    module.def("scan_svi_slice", &scan_svi_slice_from_values, py::arg("a"), py::arg("b"),
               py::arg("rho"), py::arg("m"), py::arg("sigma"), py::arg("lowest_log_moneyness"),
               py::arg("highest_log_moneyness"), py::arg("scan_steps"));

    py::register_exception<InvalidSviSurfaceError>(module, "InvalidSviSurfaceError", PyExc_ValueError);

    py::class_<SviSurfaceScan>(module, "SviSurfaceScan")
        .def_readonly("slice_count", &SviSurfaceScan::slice_count)
        .def_readonly("scan_steps", &SviSurfaceScan::scan_steps)
        .def_readonly("time_steps_per_interval", &SviSurfaceScan::time_steps_per_interval)
        .def_readonly("minimum_durrleman_value", &SviSurfaceScan::minimum_durrleman_value)
        .def_readonly("log_moneyness_at_minimum_durrleman_value",
                      &SviSurfaceScan::log_moneyness_at_minimum_durrleman_value)
        .def_readonly("years_to_expiry_at_minimum_durrleman_value",
                      &SviSurfaceScan::years_to_expiry_at_minimum_durrleman_value)
        .def_readonly("minimum_risk_neutral_density", &SviSurfaceScan::minimum_risk_neutral_density)
        .def_readonly("minimum_total_variance_time_slope",
                      &SviSurfaceScan::minimum_total_variance_time_slope)
        .def_readonly("log_moneyness_at_minimum_time_slope",
                      &SviSurfaceScan::log_moneyness_at_minimum_time_slope)
        .def_readonly("years_to_expiry_at_minimum_time_slope",
                      &SviSurfaceScan::years_to_expiry_at_minimum_time_slope)
        .def_readonly("minimum_local_variance", &SviSurfaceScan::minimum_local_variance)
        .def_readonly("log_moneyness_at_minimum_local_variance",
                      &SviSurfaceScan::log_moneyness_at_minimum_local_variance)
        .def_readonly("years_to_expiry_at_minimum_local_variance",
                      &SviSurfaceScan::years_to_expiry_at_minimum_local_variance)
        .def_readonly("worst_local_variance_round_trip_error",
                      &SviSurfaceScan::worst_local_variance_round_trip_error)
        .def_readonly("log_moneyness_at_worst_round_trip_error",
                      &SviSurfaceScan::log_moneyness_at_worst_round_trip_error)
        .def_readonly("round_trip_point_count", &SviSurfaceScan::round_trip_point_count)
        .def_property_readonly("status", [](const SviSurfaceScan& scan) {
            return name_of_svi_surface_status(scan.status);
        });

    module.attr("DEFAULT_SURFACE_SCAN_STEPS") = default_surface_scan_steps;
    module.attr("DEFAULT_TIME_STEPS_PER_INTERVAL") = default_time_steps_per_interval;
    module.def("scan_svi_surface", &scan_svi_surface_from_values, py::arg("years_to_expiry"),
               py::arg("a"), py::arg("b"), py::arg("rho"), py::arg("m"), py::arg("sigma"),
               py::arg("lowest_log_moneyness"), py::arg("highest_log_moneyness"), py::arg("scan_steps"),
               py::arg("time_steps_per_interval"));

    py::register_exception<InvalidEssviInputsError>(module, "InvalidEssviInputsError", PyExc_ValueError);

    py::class_<EssviCalibration>(module, "EssviCalibration")
        .def_readonly("objective", &EssviCalibration::objective)
        .def_readonly("weighted_root_mean_square_residual",
                      &EssviCalibration::weighted_root_mean_square_residual)
        .def_readonly("simplex_iterations", &EssviCalibration::simplex_iterations)
        .def_readonly("slice_count", &EssviCalibration::slice_count)
        .def_readonly("observation_count", &EssviCalibration::observation_count)
        .def_readonly("fitted_surface", &EssviCalibration::fitted_surface)
        .def_readonly("surface_minimum_durrleman_value",
                      &EssviCalibration::surface_minimum_durrleman_value)
        .def_readonly("surface_minimum_total_variance_time_slope",
                      &EssviCalibration::surface_minimum_total_variance_time_slope)
        .def_property_readonly(
            "atm_total_variance",
            [](const EssviCalibration& c) { return c.parameters.atm_total_variance; })
        .def_property_readonly("curvature_scale",
                               [](const EssviCalibration& c) { return c.parameters.curvature_scale; })
        .def_property_readonly(
            "power_law_exponent",
            [](const EssviCalibration& c) { return c.parameters.power_law_exponent; })
        .def_property_readonly(
            "correlation_intercept",
            [](const EssviCalibration& c) { return c.parameters.correlation_intercept; })
        .def_property_readonly(
            "correlation_slope",
            [](const EssviCalibration& c) { return c.parameters.correlation_slope; })
        .def_property_readonly("slice_a", [](const EssviCalibration& c) { return field_of(c, 0); })
        .def_property_readonly("slice_b", [](const EssviCalibration& c) { return field_of(c, 1); })
        .def_property_readonly("slice_rho", [](const EssviCalibration& c) { return field_of(c, 2); })
        .def_property_readonly("slice_m", [](const EssviCalibration& c) { return field_of(c, 3); })
        .def_property_readonly("slice_sigma", [](const EssviCalibration& c) { return field_of(c, 4); })
        .def_property_readonly("status", [](const EssviCalibration& c) {
            return name_of_essvi_status(c.status);
        });

    module.def("calibrate_essvi_surface", &calibrate_essvi_surface_from_values,
               py::arg("years_to_expiry"), py::arg("log_moneyness"), py::arg("total_variances"),
               py::arg("weights"), py::arg("lowest_log_moneyness"), py::arg("highest_log_moneyness"));

    py::class_<LatticeInputs>(module, "LatticeInputs")
        .def(py::init(&make_lattice_inputs), py::arg("spot_price"), py::arg("strike"),
             py::arg("years_to_expiry"), py::arg("volatility"), py::arg("zero_rate"),
             py::arg("carry_rate"), py::arg("option_type"), py::arg("exercise_style"))
        .def_readonly("spot_price", &LatticeInputs::spot_price)
        .def_readonly("strike", &LatticeInputs::strike)
        .def_readonly("years_to_expiry", &LatticeInputs::years_to_expiry)
        .def_readonly("volatility", &LatticeInputs::volatility)
        .def_readonly("zero_rate", &LatticeInputs::zero_rate)
        .def_readonly("carry_rate", &LatticeInputs::carry_rate);

    module.attr("RICHARDSON_BASE_STEPS") = richardson_base_steps;
    module.def(
        "richardson_extrapolated_price",
        [](const LatticeInputs& inputs) { return richardson_extrapolated_price(inputs, richardson_base_steps); },
        py::arg("inputs"));
    module.def(
        "european_price",
        [](const LatticeInputs& inputs) {
            return richardson_extrapolated_price(european_counterpart(inputs), richardson_base_steps);
        },
        py::arg("inputs"));
    py::class_<AmericanInversionResult>(module, "AmericanInversionResult")
        .def_readonly("volatility", &AmericanInversionResult::volatility)
        .def_readonly("iterations", &AmericanInversionResult::iterations)
        .def_readonly("absolute_price_error", &AmericanInversionResult::absolute_price_error)
        .def_property_readonly("status", [](const AmericanInversionResult& result) {
            return name_of_american_inversion_status(result.status);
        });

    module.def("invert_american_implied_volatility", &invert_american_from_strings,
               py::arg("spot_price"), py::arg("strike"), py::arg("years_to_expiry"),
               py::arg("zero_rate"), py::arg("carry_rate"), py::arg("option_price"),
               py::arg("option_type"), py::arg("exercise_style"));

    module.def(
        "early_exercise_premium",
        [](const LatticeInputs& inputs) { return early_exercise_premium(inputs, richardson_base_steps); },
        py::arg("inputs"));

    module.def(
        "out_of_the_money_option_type",
        [](double forward, double strike) {
            return name_of_option_type(out_of_the_money_option_type(forward, strike));
        },
        py::arg("forward"), py::arg("strike"));
}
