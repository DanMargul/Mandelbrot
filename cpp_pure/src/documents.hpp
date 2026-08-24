#pragma once

#include "volarb/american.hpp"
#include "volarb/pricing.hpp"

#include <nlohmann/json.hpp>

#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>

namespace volarb::cli {

class DocumentError : public std::runtime_error {
  public:
    explicit DocumentError(const std::string& message) : std::runtime_error(message) {}
};

struct Document {
    std::string schema;
    nlohmann::json records;
};

Document read_document(const std::filesystem::path& path, const std::string& expected_schema);
void write_document(const std::filesystem::path& path, const Document& document);

std::string required_string(const nlohmann::json& record, const std::string& field);
double required_number(const nlohmann::json& record, const std::string& field);
OptionType required_option_type(const nlohmann::json& record, const std::string& field);
bool optional_boolean(const nlohmann::json& record, const std::string& field, bool fallback);
std::optional<double> optional_number(const nlohmann::json& record, const std::string& field);
ExerciseStyle required_exercise_style(const nlohmann::json& record, const std::string& field);
nlohmann::json json_safe_number(double value);
nlohmann::json json_optional_number(const std::optional<double>& value);

}
