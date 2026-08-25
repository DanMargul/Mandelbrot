#pragma once

#include "documents.hpp"

#include <functional>
#include <map>
#include <string>

namespace volarb::cli {

struct Verb {
    std::string name;
    std::string input_schema;
    std::string output_schema;
    std::function<nlohmann::json(const nlohmann::json&)> transform_records;
};

nlohmann::json price_option_record(const nlohmann::json& record);
nlohmann::json invert_implied_volatility_record(const nlohmann::json& record);
nlohmann::json read_chain_as_of_records(const nlohmann::json& records);
nlohmann::json imply_forward_curve_records(const nlohmann::json& records);
nlohmann::json price_american_option_record(const nlohmann::json& record);
nlohmann::json invert_american_implied_volatility_record(const nlohmann::json& record);
nlohmann::json scan_svi_slice_record(const nlohmann::json& record);
nlohmann::json calibrate_svi_slice_record(const nlohmann::json& record);

const std::map<std::string, Verb>& supported_verbs();

}
