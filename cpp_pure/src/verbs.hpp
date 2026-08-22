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
    std::function<nlohmann::json(const nlohmann::json&)> transform_record;
};

nlohmann::json price_option_record(const nlohmann::json& record);
nlohmann::json invert_implied_volatility_record(const nlohmann::json& record);

const std::map<std::string, Verb>& supported_verbs();

}
