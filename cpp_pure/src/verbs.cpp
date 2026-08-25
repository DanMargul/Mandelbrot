#include "verbs.hpp"

#include "volarb/american.hpp"
#include "volarb/svi.hpp"
#include "volarb/svi_calibration.hpp"
#include "volarb/svi_surface.hpp"
#include "volarb/essvi.hpp"
#include "volarb/execution.hpp"
#include "volarb/rate_curve.hpp"
#include "volarb/factors.hpp"
#include "volarb/random_source.hpp"
#include "volarb/hedging.hpp"
#include "volarb/portfolio.hpp"
#include "volarb/forward_curve.hpp"
#include "volarb/implied_vol.hpp"
#include "volarb/market_data.hpp"
#include "volarb/pricing.hpp"

#include <filesystem>
#include <map>
#include <string>
#include <utility>

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

namespace {

nlohmann::json chain_snapshot_record(const std::string& query_id, const ContractQuote& quote) {
    nlohmann::json result;
    result["id"] = query_id + "|" + quote.contract_symbol;
    result["query_id"] = query_id;
    result["contract_symbol"] = quote.contract_symbol;
    result["expiry_date"] = format_canonical_date(quote.expiry_date);
    result["strike"] = quote.strike;
    result["option_type"] = name_of_option_type(quote.option_type);
    result["contract_multiplier"] = quote.contract_multiplier;
    result["is_standard_deliverable"] = quote.is_standard_deliverable;
    result["exercise_style"] = name_of_exercise_style(quote.exercise_style);
    result["event_time"] = format_canonical_timestamp(quote.event_time);
    result["knowledge_time"] = format_canonical_timestamp(quote.knowledge_time);
    result["ingest_sequence"] = quote.ingest_sequence;
    result["underlying_price"] = quote.underlying_price;
    result["bid_price"] = quote.bid_price;
    result["ask_price"] = quote.ask_price;
    result["bid_size"] = quote.bid_size;
    result["ask_size"] = quote.ask_size;
    return result;
}

std::function<nlohmann::json(const nlohmann::json&)> mapped_over_records(
    std::function<nlohmann::json(const nlohmann::json&)> transform) {
    return [transform = std::move(transform)](const nlohmann::json& records) {
        nlohmann::json results = nlohmann::json::array();
        for (const nlohmann::json& record : records) {
            results.push_back(transform(record));
        }
        return results;
    };
}

}

nlohmann::json price_american_option_record(const nlohmann::json& record) {
    const LatticeInputs inputs{
        required_number(record, "spot_price"),
        required_number(record, "strike"),
        required_number(record, "years_to_expiry"),
        required_number(record, "volatility"),
        required_number(record, "zero_rate"),
        required_number(record, "carry_rate"),
        required_option_type(record, "option_type"),
        required_exercise_style(record, "exercise_style"),
    };

    nlohmann::json result;
    result["id"] = required_string(record, "id");
    result["price"] = richardson_extrapolated_price(inputs, richardson_base_steps);
    result["european_price"] =
        richardson_extrapolated_price(european_counterpart(inputs), richardson_base_steps);
    result["early_exercise_premium"] = early_exercise_premium(inputs, richardson_base_steps);
    result["lattice_steps"] = richardson_base_steps;
    return result;
}

nlohmann::json invert_american_implied_volatility_record(const nlohmann::json& record) {
    const AmericanInversionResult result = invert_american_implied_volatility(AmericanInversionInputs{
        required_number(record, "spot_price"),
        required_number(record, "strike"),
        required_number(record, "years_to_expiry"),
        required_number(record, "zero_rate"),
        required_number(record, "carry_rate"),
        required_number(record, "option_price"),
        required_option_type(record, "option_type"),
        required_exercise_style(record, "exercise_style"),
    });

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["volatility"] = result.volatility;
    output["status"] = name_of_american_inversion_status(result.status);
    output["iterations"] = result.iterations;
    output["absolute_price_error"] = result.absolute_price_error;
    return output;
}

nlohmann::json scan_svi_slice_record(const nlohmann::json& record) {
    const SviParameters parameters{
        required_number(record, "a"),   required_number(record, "b"),
        required_number(record, "rho"), required_number(record, "m"),
        required_number(record, "sigma"),
    };
    const auto steps = record.find("scan_steps");
    const int scan_steps =
        steps == record.end() || !steps->is_number_integer() ? default_scan_steps : steps->get<int>();
    const SviSliceScan scan =
        scan_svi_slice(parameters, required_number(record, "lowest_log_moneyness"),
                       required_number(record, "highest_log_moneyness"), scan_steps);

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["minimum_durrleman_value"] = scan.minimum_durrleman_value;
    output["log_moneyness_at_minimum"] = scan.log_moneyness_at_minimum;
    output["minimum_total_variance"] = scan.minimum_total_variance;
    output["minimum_risk_neutral_density"] = scan.minimum_risk_neutral_density;
    output["scan_steps"] = scan.scan_steps;
    output["status"] = name_of_svi_status(scan.status);
    return output;
}

int optional_step_count(const nlohmann::json& record, const char* field, int fallback) {
    const auto found = record.find(field);
    if (found == record.end() || !found->is_number_integer()) {
        return fallback;
    }
    return found->get<int>();
}

std::vector<SviSurfaceSlice> surface_slices_from(const nlohmann::json& record) {
    const auto raw = record.find("slices");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'slices' must be an array");
    }
    std::vector<SviSurfaceSlice> slices;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every entry of 'slices' must be an object");
        }
        slices.push_back(SviSurfaceSlice{
            required_number(entry, "years_to_expiry"),
            SviParameters{
                required_number(entry, "a"), required_number(entry, "b"),
                required_number(entry, "rho"), required_number(entry, "m"),
                required_number(entry, "sigma"),
            },
        });
    }
    return slices;
}

std::vector<Candidate> portfolio_candidates_from(const nlohmann::json& record) {
    const auto raw = record.find("candidates");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'candidates' must be an array");
    }
    std::vector<Candidate> candidates;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every entry of 'candidates' must be an object");
        }
        const auto exposures = entry.find("factor_exposures");
        if (exposures == entry.end() || !exposures->is_array()) {
            throw DocumentError("field 'factor_exposures' must be an array");
        }
        candidates.push_back(Candidate{
            required_number(entry, "expected_edge"),
            required_number(entry, "vega"),
            required_number(entry, "gamma"),
            required_number(entry, "theta"),
            exposures->get<std::vector<double>>(),
            required_number(entry, "maximum_size"),
            required_number(entry, "spread_cost"),
        });
    }
    return candidates;
}

nlohmann::json allocate_portfolio_record(const nlohmann::json& record) {
    const PortfolioLimits limits{
        required_number(record, "vega_budget"),      required_number(record, "gamma_budget"),
        required_number(record, "theta_budget"),     required_number(record, "factor_tolerance"),
        required_number(record, "risk_aversion"),    required_number(record, "proportional_cost"),
        required_number(record, "spot"),             required_number(record, "volatility"),
        required_number(record, "years_to_expiry"),
    };
    const Allocation allocation = allocate(portfolio_candidates_from(record), limits,
                                           optional_boolean(record, "charge_hedging", true));

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["weights"] = allocation.weights;
    output["expected_edge"] = allocation.expected_edge;
    output["spread_cost"] = allocation.spread_cost;
    output["hedging_cost"] = allocation.hedging_cost;
    output["objective"] = allocation.objective;
    output["net_vega"] = allocation.net_vega;
    output["net_gamma"] = allocation.net_gamma;
    output["net_theta"] = allocation.net_theta;
    output["worst_factor_exposure"] = allocation.worst_factor_exposure;
    output["charged_for_hedging"] = allocation.charged_for_hedging;
    return output;
}

nlohmann::json simulate_hedging_record(const nlohmann::json& record) {
    const HedgingInputs inputs{
        required_number(record, "spot"),
        required_number(record, "strike"),
        required_number(record, "years_to_expiry"),
        required_number(record, "volatility"),
        static_cast<int>(required_integer(record, "steps")),
        required_number(record, "proportional_cost"),
        required_number(record, "risk_aversion"),
    };
    const BandPolicy policy{band_rule_from_name(required_string(record, "rule")),
                            required_number(record, "fixed_width")};
    const HedgingStatistics statistics =
        hedging_statistics(inputs, policy, required_string(record, "initial_state"),
                           required_string(record, "sequence"),
                           static_cast<int>(required_integer(record, "path_count")));

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["path_count"] = statistics.path_count;
    output["mean_profit"] = statistics.mean_profit;
    output["profit_standard_deviation"] = statistics.profit_standard_deviation;
    output["mean_transaction_cost"] = statistics.mean_transaction_cost;
    output["mean_rebalance_count"] = statistics.mean_rebalance_count;
    output["certainty_equivalent"] = statistics.certainty_equivalent;
    return output;
}

UnsignedWide wide_from_decimal(const std::string& text) {
    if (text.empty()) {
        throw DocumentError("a seed must be a decimal integer string");
    }
    UnsignedWide value = 0;
    for (const char digit : text) {
        if (digit < '0' || digit > '9') {
            throw DocumentError("a seed must be a decimal integer string, got " + text);
        }
        value = value * 10 + static_cast<UnsignedWide>(digit - '0');
    }
    return value;
}

nlohmann::json draw_random_sample_record(const nlohmann::json& record) {
    const auto count = static_cast<int>(required_integer(record, "count"));
    if (count < 0) {
        throw DocumentError("count must not be negative");
    }
    const PcgState source = seeded_source(wide_from_decimal(required_string(record, "initial_state")),
                                          wide_from_decimal(required_string(record, "sequence")));
    std::vector<std::string> words;
    PcgState current = source;
    for (int index = 0; index < count; ++index) {
        const auto drawn = next_bits(current);
        current = drawn.state;
        words.push_back(std::to_string(drawn.bits));
    }

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["count"] = count;
    output["bits"] = words;
    output["uniforms"] = uniforms(source, count);
    output["standard_normals"] = standard_normals(source, count);
    return output;
}

std::vector<SurfacePoint> surface_grid_from(const nlohmann::json& record) {
    const auto raw = record.find("grid");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'grid' must be an array");
    }
    std::vector<SurfacePoint> grid;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every entry of 'grid' must be an object");
        }
        grid.push_back(SurfacePoint{required_number(entry, "log_moneyness"),
                                    required_number(entry, "years_to_expiry")});
    }
    return grid;
}

std::vector<std::vector<double>> surface_observations_from(const nlohmann::json& record) {
    const auto raw = record.find("observations");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'observations' must be an array");
    }
    std::vector<std::vector<double>> observations;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_array()) {
            throw DocumentError("every entry of 'observations' must be an array");
        }
        observations.push_back(entry.get<std::vector<double>>());
    }
    return observations;
}

nlohmann::json decompose_surface_factors_record(const nlohmann::json& record) {
    const FactorDecomposition decomposition =
        decompose_surface_factors(surface_grid_from(record), surface_observations_from(record));
    const auto found = record.find("scored_grid_index");
    const int scored =
        found == record.end() || !found->is_number_integer() ? 0 : found->get<int>();
    if (scored < 0 || static_cast<std::size_t>(scored) >= decomposition.residuals[0].size()) {
        throw DocumentError("scored_grid_index is outside the grid");
    }

    std::vector<double> series;
    for (const std::vector<double>& residual : decomposition.residuals) {
        series.push_back(residual[static_cast<std::size_t>(scored)]);
    }
    const NeutralisedResidual neutralised = neutralise_against_loadings(
        series, decomposition.loadings, decomposition.identified_factor_count);
    const ResidualScore score = score_residual(neutralised.values);

    std::vector<double> level;
    std::vector<double> term;
    std::vector<double> skew;
    std::vector<double> curvature;
    for (const FactorLoadings& entry : decomposition.loadings) {
        level.push_back(entry.level);
        term.push_back(entry.term_slope);
        skew.push_back(entry.skew);
        curvature.push_back(entry.curvature);
    }

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["observation_count"] = decomposition.observation_count;
    output["grid_point_count"] = decomposition.grid_point_count;
    output["identified_factor_count"] = decomposition.identified_factor_count;
    output["variance_explained"] = decomposition.variance_explained;
    output["residual_share"] = decomposition.residual_share;
    output["worst_residual_factor_correlation"] = decomposition.worst_residual_factor_correlation;
    output["level_loading"] = level;
    output["term_slope_loading"] = term;
    output["skew_loading"] = skew;
    output["curvature_loading"] = curvature;
    output["scored_grid_index"] = scored;
    output["scored_worst_factor_correlation_before"] = neutralised.worst_factor_correlation_before;
    output["scored_worst_factor_correlation_after"] = neutralised.worst_factor_correlation;
    output["scored_lag_one_autocorrelation"] = score.lag_one_autocorrelation;
    output["scored_effective_sample_size"] = score.effective_sample_size;
    output["scored_naive_z_score"] = score.naive_z_score;
    output["scored_adjusted_z_score"] = score.adjusted_z_score;
    output["scored_naive_overstatement"] = score.naive_overstatement;
    output["scored_residual_is_degenerate"] = score.residual_is_degenerate;
    return output;
}

RateCurve rate_curve_from(const nlohmann::json& record) {
    const auto raw = record.find("nodes");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'nodes' must be an array");
    }
    std::vector<CurveNode> nodes;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every entry of 'nodes' must be an object");
        }
        nodes.push_back(CurveNode{required_number(entry, "years_to_maturity"),
                                  required_number(entry, "continuously_compounded_zero_rate")});
    }
    return RateCurve{nodes};
}

nlohmann::json evaluate_rate_curve_record(const nlohmann::json& record) {
    const RateCurve curve = rate_curve_from(record);
    const double years = required_number(record, "years_to_maturity");
    const std::optional<double> start = optional_number(record, "forward_start_years");
    const std::optional<double> end = optional_number(record, "forward_end_years");
    const double forward_start = start.has_value() && end.has_value() ? *start : years;
    const double forward_end = start.has_value() && end.has_value() ? *end : years + 1.0;

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["years_to_maturity"] = years;
    output["discount_factor"] = discount_factor(curve, years);
    output["zero_rate"] = zero_rate(curve, years);
    output["integrated_rate"] = integrated_rate(curve, years);
    output["forward_rate"] = forward_rate(curve, forward_start, forward_end);
    output["forward_discount_factor"] = forward_discount_factor(curve, forward_start, forward_end);
    return output;
}

std::vector<PackageLeg> package_legs_from(const nlohmann::json& record) {
    const auto raw = record.find("legs");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'legs' must be an array");
    }
    std::vector<PackageLeg> legs;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every entry of 'legs' must be an object");
        }
        legs.push_back(PackageLeg{
            Quote{
                required_number(entry, "bid_price"),
                required_number(entry, "ask_price"),
                required_integer(entry, "bid_size"),
                required_integer(entry, "ask_size"),
            },
            order_side_from_name(required_string(entry, "side")),
            required_integer(entry, "quantity"),
            static_cast<int>(required_integer(entry, "contract_multiplier")),
            required_number(entry, "vega_with_respect_to_volatility"),
        });
    }
    return legs;
}

nlohmann::json simulate_fills_record(const nlohmann::json& record) {
    const PackageFill fill = fill_package(package_legs_from(record));

    std::vector<long long> filled_quantity;
    std::vector<double> touch_price;
    std::vector<double> mid;
    std::vector<double> spread;
    std::vector<double> cost;
    std::vector<std::string> statuses;
    for (const LegFill& leg : fill.leg_fills) {
        filled_quantity.push_back(leg.filled_quantity);
        touch_price.push_back(leg.touch_price);
        mid.push_back(leg.mid_price);
        spread.push_back(leg.half_spread);
        cost.push_back(leg.cost_against_mid);
        statuses.push_back(name_of_fill_status(leg.status));
    }

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["status"] = name_of_fill_status(fill.status);
    output["requested_quantity"] = fill.requested_quantity;
    output["filled_quantity"] = fill.filled_quantity;
    output["total_cost_against_mid"] = fill.total_cost_against_mid;
    output["net_vega"] = fill.net_vega;
    output["net_vega_is_negligible"] = fill.net_vega_is_negligible;
    output["round_trip_cost_in_volatility_points"] = fill.round_trip_cost_in_volatility_points;
    output["leg_filled_quantity"] = filled_quantity;
    output["leg_touch_price"] = touch_price;
    output["leg_mid_price"] = mid;
    output["leg_half_spread"] = spread;
    output["leg_cost_against_mid"] = cost;
    output["leg_status"] = statuses;
    return output;
}

std::vector<EssviSliceQuotes> essvi_slice_quotes_from(const nlohmann::json& record) {
    const auto raw = record.find("slices");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'slices' must be an array");
    }
    std::vector<EssviSliceQuotes> quotes;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every entry of 'slices' must be an object");
        }
        const auto raw_observations = entry.find("observations");
        if (raw_observations == entry.end() || !raw_observations->is_array()) {
            throw DocumentError("field 'observations' must be an array");
        }
        std::vector<SliceObservation> observations;
        for (const nlohmann::json& item : *raw_observations) {
            if (!item.is_object()) {
                throw DocumentError("every observation must be an object");
            }
            observations.push_back(SliceObservation{
                required_number(item, "log_moneyness"),
                required_number(item, "total_variance"),
                required_number(item, "weight"),
            });
        }
        quotes.push_back(EssviSliceQuotes{required_number(entry, "years_to_expiry"), observations});
    }
    return quotes;
}

nlohmann::json calibrate_essvi_surface_record(const nlohmann::json& record) {
    const EssviCalibration calibration = calibrate_essvi_surface(
        essvi_slice_quotes_from(record), required_number(record, "lowest_log_moneyness"),
        required_number(record, "highest_log_moneyness"));

    std::vector<double> slice_a;
    std::vector<double> slice_b;
    std::vector<double> slice_rho;
    std::vector<double> slice_m;
    std::vector<double> slice_sigma;
    for (const SviParameters& slice : calibration.slices) {
        slice_a.push_back(slice.a);
        slice_b.push_back(slice.b);
        slice_rho.push_back(slice.rho);
        slice_m.push_back(slice.m);
        slice_sigma.push_back(slice.sigma);
    }

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["status"] = name_of_essvi_status(calibration.status);
    output["slice_count"] = calibration.slice_count;
    output["observation_count"] = calibration.observation_count;
    output["simplex_iterations"] = calibration.simplex_iterations;
    output["objective"] = calibration.objective;
    output["weighted_root_mean_square_residual"] = calibration.weighted_root_mean_square_residual;
    output["atm_total_variance"] = calibration.parameters.atm_total_variance;
    output["curvature_scale"] = calibration.parameters.curvature_scale;
    output["power_law_exponent"] = calibration.parameters.power_law_exponent;
    output["correlation_intercept"] = calibration.parameters.correlation_intercept;
    output["correlation_slope"] = calibration.parameters.correlation_slope;
    output["slice_a"] = slice_a;
    output["slice_b"] = slice_b;
    output["slice_rho"] = slice_rho;
    output["slice_m"] = slice_m;
    output["slice_sigma"] = slice_sigma;
    output["fitted_surface"] = calibration.fitted_surface;
    output["surface_minimum_durrleman_value"] = calibration.surface_minimum_durrleman_value;
    output["surface_minimum_total_variance_time_slope"] =
        calibration.surface_minimum_total_variance_time_slope;
    return output;
}

nlohmann::json scan_svi_surface_record(const nlohmann::json& record) {
    const SviSurfaceScan scan = scan_svi_surface(
        surface_slices_from(record), required_number(record, "lowest_log_moneyness"),
        required_number(record, "highest_log_moneyness"),
        optional_step_count(record, "scan_steps", default_surface_scan_steps),
        optional_step_count(record, "time_steps_per_interval", default_time_steps_per_interval));

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["slice_count"] = scan.slice_count;
    output["scan_steps"] = scan.scan_steps;
    output["time_steps_per_interval"] = scan.time_steps_per_interval;
    output["minimum_durrleman_value"] = scan.minimum_durrleman_value;
    output["log_moneyness_at_minimum_durrleman_value"] = scan.log_moneyness_at_minimum_durrleman_value;
    output["years_to_expiry_at_minimum_durrleman_value"] =
        scan.years_to_expiry_at_minimum_durrleman_value;
    output["minimum_risk_neutral_density"] = scan.minimum_risk_neutral_density;
    output["minimum_total_variance_time_slope"] = scan.minimum_total_variance_time_slope;
    output["log_moneyness_at_minimum_time_slope"] = scan.log_moneyness_at_minimum_time_slope;
    output["years_to_expiry_at_minimum_time_slope"] = scan.years_to_expiry_at_minimum_time_slope;
    output["minimum_local_variance"] = scan.minimum_local_variance;
    output["log_moneyness_at_minimum_local_variance"] = scan.log_moneyness_at_minimum_local_variance;
    output["years_to_expiry_at_minimum_local_variance"] =
        scan.years_to_expiry_at_minimum_local_variance;
    output["worst_local_variance_round_trip_error"] = scan.worst_local_variance_round_trip_error;
    output["log_moneyness_at_worst_round_trip_error"] = scan.log_moneyness_at_worst_round_trip_error;
    output["round_trip_point_count"] = scan.round_trip_point_count;
    output["status"] = name_of_svi_surface_status(scan.status);
    return output;
}

nlohmann::json calibrate_svi_slice_record(const nlohmann::json& record) {
    const auto raw = record.find("observations");
    if (raw == record.end() || !raw->is_array()) {
        throw DocumentError("field 'observations' must be an array");
    }
    std::vector<SliceObservation> observations;
    for (const nlohmann::json& entry : *raw) {
        if (!entry.is_object()) {
            throw DocumentError("every observation must be an object");
        }
        observations.push_back(SliceObservation{
            required_number(entry, "log_moneyness"),
            required_number(entry, "total_variance"),
            required_number(entry, "weight"),
        });
    }

    const SviCalibration calibration =
        calibrate_svi_slice(observations, required_number(record, "lowest_log_moneyness"),
                            required_number(record, "highest_log_moneyness"));

    nlohmann::json output;
    output["id"] = required_string(record, "id");
    output["a"] = calibration.parameters.a;
    output["b"] = calibration.parameters.b;
    output["rho"] = calibration.parameters.rho;
    output["m"] = calibration.parameters.m;
    output["sigma"] = calibration.parameters.sigma;
    output["objective"] = calibration.objective;
    output["weighted_root_mean_square_residual"] = calibration.weighted_root_mean_square_residual;
    output["simplex_iterations"] = calibration.simplex_iterations;
    output["observation_count"] = calibration.observation_count;
    output["fitted_curve"] = calibration.fitted_curve;
    output["status"] = name_of_svi_calibration_status(calibration.status);
    return output;
}

nlohmann::json read_chain_as_of_records(const nlohmann::json& records) {
    std::map<std::pair<std::string, std::string>, AsOfChainReader> readers;
    nlohmann::json snapshots = nlohmann::json::array();

    for (const nlohmann::json& record : records) {
        const std::string dataset_root = required_string(record, "dataset_root");
        const std::string horizon_text = required_string(record, "knowledge_horizon");
        const std::pair<std::string, std::string> cache_key{dataset_root, horizon_text};
        const auto existing = readers.find(cache_key);
        if (existing == readers.end()) {
            readers.emplace(cache_key, open_chain_dataset(std::filesystem::path(dataset_root),
                                                          KnowledgeHorizon{parse_canonical_timestamp(horizon_text)}));
        }

        const ChainQuery query{
            required_string(record, "underlying_symbol"),
            parse_canonical_timestamp(required_string(record, "observation_time")),
            optional_boolean(record, "include_adjusted_contracts", false),
        };
        const std::string query_id = required_string(record, "id");
        for (const ContractQuote& quote : readers.at(cache_key).chain_as_of(query)) {
            snapshots.push_back(chain_snapshot_record(query_id, quote));
        }
    }
    return snapshots;
}

nlohmann::json forward_curve_record(const std::string& query_id, const std::string& underlying_symbol,
                                    const ForwardCurvePoint& point) {
    nlohmann::json result;
    result["id"] = query_id + "|" + format_canonical_date(point.expiry_date);
    result["query_id"] = query_id;
    result["underlying_symbol"] = underlying_symbol;
    result["expiry_date"] = format_canonical_date(point.expiry_date);
    result["years_to_expiry"] = point.years_to_expiry;
    result["spot_price"] = point.spot_price;
    result["forward"] = point.forward;
    result["forward_standard_error"] = json_optional_number(point.forward_standard_error);
    result["discount_factor"] = point.discount_factor;
    result["discount_factor_standard_error"] = json_optional_number(point.discount_factor_standard_error);
    result["implied_zero_rate"] = json_optional_number(point.implied_zero_rate);
    result["implied_carry_rate"] = json_optional_number(point.implied_carry_rate);
    result["parity_pair_count"] = point.parity_pair_count;
    result["active_pair_count"] = point.active_pair_count;
    result["chi_square_per_degree_of_freedom"] =
        json_optional_number(point.chi_square_per_degree_of_freedom);
    result["early_exercise_premium_stripped"] = point.early_exercise_premium_stripped;
    result["discount_factor_is_monotone_in_expiry"] = point.discount_factor_is_monotone_in_expiry;
    result["status"] = name_of_forward_curve_status(point.status);
    return result;
}

nlohmann::json imply_forward_curve_records(const nlohmann::json& records) {
    std::map<std::pair<std::string, std::string>, AsOfChainReader> readers;
    nlohmann::json curve = nlohmann::json::array();

    for (const nlohmann::json& record : records) {
        const std::string dataset_root = required_string(record, "dataset_root");
        const std::string horizon_text = required_string(record, "knowledge_horizon");
        const std::pair<std::string, std::string> cache_key{dataset_root, horizon_text};
        if (readers.find(cache_key) == readers.end()) {
            readers.emplace(cache_key,
                            open_chain_dataset(std::filesystem::path(dataset_root),
                                               KnowledgeHorizon{parse_canonical_timestamp(horizon_text)}));
        }

        const EpochMicroseconds observation_time =
            parse_canonical_timestamp(required_string(record, "observation_time"));
        const std::string underlying_symbol = required_string(record, "underlying_symbol");
        const ChainQuery query{underlying_symbol, observation_time,
                               optional_boolean(record, "include_adjusted_contracts", false)};
        const std::string query_id = required_string(record, "id");
        const auto zero_rate = optional_number(record, "zero_rate");
        for (const ForwardCurvePoint& point :
             imply_forward_curve(readers.at(cache_key).chain_as_of(query), observation_time, zero_rate)) {
            curve.push_back(forward_curve_record(query_id, underlying_symbol, point));
        }
    }
    return curve;
}

const std::map<std::string, Verb>& supported_verbs() {
    static const std::map<std::string, Verb> verbs = {
        {"price-options",
         Verb{"price-options", "pricing_request/v1", "pricing_result/v1",
              mapped_over_records(price_option_record)}},
        {"invert-implied-volatility",
         Verb{"invert-implied-volatility", "implied_volatility_request/v1",
              "implied_volatility_result/v1", mapped_over_records(invert_implied_volatility_record)}},
        {"read-chain-as-of",
         Verb{"read-chain-as-of", "chain_query/v1", "chain_snapshot/v2", read_chain_as_of_records}},
        {"imply-forward-curve",
         Verb{"imply-forward-curve", "forward_curve_query/v1", "forward_curve/v1",
              imply_forward_curve_records}},
        {"calibrate-svi-slice",
         Verb{"calibrate-svi-slice", "svi_calibration_request/v1", "svi_calibration_result/v1",
              mapped_over_records(calibrate_svi_slice_record)}},
        {"allocate-portfolio",
         Verb{"allocate-portfolio", "portfolio_request/v1", "portfolio_allocation/v1",
              mapped_over_records(allocate_portfolio_record)}},
        {"simulate-hedging",
         Verb{"simulate-hedging", "hedging_request/v1", "hedging_statistics/v1",
              mapped_over_records(simulate_hedging_record)}},
        {"draw-random-sample",
         Verb{"draw-random-sample", "random_sample_request/v1", "random_sample/v1",
              mapped_over_records(draw_random_sample_record)}},
        {"decompose-surface-factors",
         Verb{"decompose-surface-factors", "factor_request/v1", "factor_decomposition/v1",
              mapped_over_records(decompose_surface_factors_record)}},
        {"evaluate-rate-curve",
         Verb{"evaluate-rate-curve", "rate_curve_query/v1", "rate_curve_point/v1",
              mapped_over_records(evaluate_rate_curve_record)}},
        {"simulate-fills",
         Verb{"simulate-fills", "fill_request/v1", "fill_result/v1",
              mapped_over_records(simulate_fills_record)}},
        {"calibrate-essvi-surface",
         Verb{"calibrate-essvi-surface", "essvi_calibration_request/v1",
              "essvi_calibration_result/v1", mapped_over_records(calibrate_essvi_surface_record)}},
        {"scan-svi-surface",
         Verb{"scan-svi-surface", "svi_surface_scan_request/v1", "svi_surface_scan_result/v1",
              mapped_over_records(scan_svi_surface_record)}},
        {"scan-svi-slice",
         Verb{"scan-svi-slice", "svi_scan_request/v1", "svi_scan_result/v1",
              mapped_over_records(scan_svi_slice_record)}},
        {"invert-american-implied-volatility",
         Verb{"invert-american-implied-volatility", "american_inversion_request/v1",
              "american_inversion_result/v1",
              mapped_over_records(invert_american_implied_volatility_record)}},
        {"price-american-options",
         Verb{"price-american-options", "american_pricing_request/v1", "american_pricing_result/v1",
              mapped_over_records(price_american_option_record)}},
    };
    return verbs;
}

}
