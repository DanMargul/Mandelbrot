#include "verbs.hpp"

#include "volarb/american.hpp"
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
        for (const ForwardCurvePoint& point :
             imply_forward_curve(readers.at(cache_key).chain_as_of(query), observation_time)) {
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
         Verb{"read-chain-as-of", "chain_query/v1", "chain_snapshot/v1", read_chain_as_of_records}},
        {"imply-forward-curve",
         Verb{"imply-forward-curve", "chain_query/v1", "forward_curve/v1", imply_forward_curve_records}},
        {"price-american-options",
         Verb{"price-american-options", "american_pricing_request/v1", "american_pricing_result/v1",
              mapped_over_records(price_american_option_record)}},
    };
    return verbs;
}

}
