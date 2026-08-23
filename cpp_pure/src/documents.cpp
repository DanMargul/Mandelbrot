#include "documents.hpp"

#include <cmath>
#include <fstream>

namespace volarb::cli {

Document read_document(const std::filesystem::path& path, const std::string& expected_schema) {
    std::ifstream stream(path);
    if (!stream) {
        throw DocumentError(path.string() + ": cannot be opened for reading");
    }

    nlohmann::json payload = nlohmann::json::parse(stream, nullptr, false);
    if (payload.is_discarded()) {
        throw DocumentError(path.string() + ": is not valid JSON");
    }
    if (!payload.is_object()) {
        throw DocumentError(path.string() + ": top level value must be an object");
    }

    const auto schema = payload.find("schema");
    if (schema == payload.end() || !schema->is_string() || schema->get<std::string>() != expected_schema) {
        throw DocumentError(path.string() + ": expected schema '" + expected_schema + "'");
    }

    const auto records = payload.find("records");
    if (records == payload.end() || !records->is_array()) {
        throw DocumentError(path.string() + ": records must be an array");
    }
    for (const nlohmann::json& record : *records) {
        if (!record.is_object()) {
            throw DocumentError(path.string() + ": every record must be an object");
        }
    }

    return Document{expected_schema, *records};
}

void write_document(const std::filesystem::path& path, const Document& document) {
    nlohmann::json payload;
    payload["schema"] = document.schema;
    payload["records"] = document.records;

    std::ofstream stream(path);
    if (!stream) {
        throw DocumentError(path.string() + ": cannot be opened for writing");
    }
    stream << payload.dump(2) << "\n";
}

std::string required_string(const nlohmann::json& record, const std::string& field) {
    const auto entry = record.find(field);
    if (entry == record.end() || !entry->is_string()) {
        throw DocumentError("field '" + field + "' must be a string");
    }
    return entry->get<std::string>();
}

double required_number(const nlohmann::json& record, const std::string& field) {
    const auto entry = record.find(field);
    if (entry == record.end() || !entry->is_number()) {
        throw DocumentError("field '" + field + "' must be a number");
    }
    return entry->get<double>();
}

bool optional_boolean(const nlohmann::json& record, const std::string& field, bool fallback) {
    const auto entry = record.find(field);
    if (entry == record.end()) {
        return fallback;
    }
    if (!entry->is_boolean()) {
        throw DocumentError("field '" + field + "' must be a boolean");
    }
    return entry->get<bool>();
}

OptionType required_option_type(const nlohmann::json& record, const std::string& field) {
    return option_type_from_name(required_string(record, field));
}

nlohmann::json json_safe_number(double value) {
    if (!std::isfinite(value)) {
        return nullptr;
    }
    return value;
}

}
