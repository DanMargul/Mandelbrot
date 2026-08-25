#include "documents.hpp"
#include "verbs.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <filesystem>
#include <map>
#include <set>
#include <string>
#include <vector>

using Catch::Approx;
using volarb::cli::Document;
using volarb::cli::read_document;
using volarb::cli::supported_verbs;
using volarb::cli::Verb;

namespace {

const std::filesystem::path fixture_root = VOLARB_FIXTURE_ROOT;
const std::set<std::string> exactly_compared_fields = {"id", "status", "iterations"};
struct FieldTolerance {
    double relative;
    double absolute;
};

const std::map<std::string, FieldTolerance> mirrored_tolerances = {
    {"a", {5e-2, 1e-10}},
    {"b", {5e-2, 1e-10}},
    {"rho", {5e-2, 1e-10}},
    {"m", {5e-2, 1e-10}},
    {"sigma", {5e-2, 1e-10}},
    {"objective", {5e-2, 1e-10}},
    {"weighted_root_mean_square_residual", {5e-2, 1e-10}},
    {"simplex_iterations", {5e-1, 1.0}},
    {"fitted_curve", {1e-6, 1e-14}},
};

FieldTolerance tolerance_for(const std::string& field) {
    const auto entry = mirrored_tolerances.find(field);
    if (entry == mirrored_tolerances.end()) {
        return FieldTolerance{1e-12, 1e-300};
    }
    return entry->second;
}

std::vector<std::string> fixture_families(const std::string& verb) {
    std::vector<std::string> families;
    for (const auto& entry : std::filesystem::directory_iterator(fixture_root / verb)) {
        const std::string name = entry.path().filename().string();
        const std::string suffix = ".input.json";
        if (name.size() > suffix.size() && name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0) {
            families.push_back(name.substr(0, name.size() - suffix.size()));
        }
    }
    return families;
}

void require_values_agree(const nlohmann::json& actual_value, const nlohmann::json& expected_value,
                          const std::string& field, const std::string& context);

void require_fields_agree(const nlohmann::json& produced, const nlohmann::json& expected, const std::string& context) {
    for (const auto& [field, expected_value] : expected.items()) {
        INFO(context << " field " << field);
        REQUIRE(produced.contains(field));
        require_values_agree(produced.at(field), expected_value, field, context);
    }
}

void require_values_agree(const nlohmann::json& actual_value, const nlohmann::json& expected_value,
                          const std::string& field, const std::string& context) {
    if (expected_value.is_array()) {
        REQUIRE(actual_value.is_array());
        REQUIRE(actual_value.size() == expected_value.size());
        for (std::size_t position = 0; position < expected_value.size(); ++position) {
            require_values_agree(actual_value[position], expected_value[position], field, context);
        }
        return;
    }

    const bool compare_exactly = exactly_compared_fields.contains(field) || expected_value.is_string() ||
                                 expected_value.is_null() || expected_value.is_boolean();
    if (compare_exactly) {
        REQUIRE(actual_value == expected_value);
        return;
    }

    const double expected_number = expected_value.get<double>();
    const double actual_number = actual_value.get<double>();
    if (expected_number == 0.0 || !std::isfinite(expected_number)) {
        REQUIRE(actual_number == expected_number);
        return;
    }
    const FieldTolerance tolerance = tolerance_for(field);
    REQUIRE(actual_number ==
            Approx(expected_number).epsilon(tolerance.relative).margin(tolerance.absolute));
}

}

TEST_CASE("every golden fixture is reproduced", "[verbs]") {
    int compared_records = 0;
    for (const auto& [verb_name, verb] : supported_verbs()) {
        for (const std::string& family : fixture_families(verb_name)) {
            const Document request =
                read_document(fixture_root / verb_name / (family + ".input.json"), verb.input_schema);
            const Document expected =
                read_document(fixture_root / verb_name / (family + ".expected.json"), verb.output_schema);
            const nlohmann::json produced_records = verb.transform_records(request.records);
            REQUIRE(produced_records.size() == expected.records.size());
            for (std::size_t index = 0; index < request.records.size(); ++index) {
                const nlohmann::json& produced = produced_records[index];
                const std::string context = verb_name + "/" + family + " record " + std::to_string(index);
                require_fields_agree(produced, expected.records[index], context);
                ++compared_records;
            }
        }
    }
    REQUIRE(compared_records > 1000);
}

TEST_CASE("a schema mismatch is rejected", "[verbs]") {
    REQUIRE_THROWS_AS(
        read_document(fixture_root / "price-options" / "ordinary.input.json", "implied_volatility_request/v1"),
        volarb::cli::DocumentError);
}

TEST_CASE("a missing file is rejected", "[verbs]") {
    REQUIRE_THROWS_AS(read_document(fixture_root / "absent.json", "pricing_request/v1"),
                      volarb::cli::DocumentError);
}
