#include "documents.hpp"
#include "verbs.hpp"

#include "volarb/pricing.hpp"

#include <exception>
#include <filesystem>
#include <iostream>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace {

using volarb::cli::Document;
using volarb::cli::DocumentError;
using volarb::cli::read_document;
using volarb::cli::supported_verbs;
using volarb::cli::Verb;
using volarb::cli::write_document;

struct Arguments {
    std::string verb;
    std::filesystem::path input;
    std::filesystem::path output;
    std::optional<std::filesystem::path> config;
};

void print_usage(std::ostream& stream) {
    stream << "usage: volarb-native <verb> --input <path> --output <path> [--config <path>]\n";
    stream << "verbs:\n";
    for (const auto& [name, verb] : supported_verbs()) {
        stream << "  " << name << "  " << verb.input_schema << " -> " << verb.output_schema << "\n";
    }
}

std::string value_following(std::span<const std::string> arguments, std::size_t index, const std::string& flag) {
    if (index + 1 >= arguments.size()) {
        throw DocumentError(flag + " requires a value");
    }
    return arguments[index + 1];
}

Arguments parse_arguments(std::span<const std::string> arguments) {
    if (arguments.empty()) {
        throw DocumentError("a verb is required");
    }

    Arguments parsed;
    parsed.verb = arguments[0];
    if (!supported_verbs().contains(parsed.verb)) {
        throw DocumentError("unknown verb '" + parsed.verb + "'");
    }

    for (std::size_t index = 1; index < arguments.size(); ++index) {
        const std::string& flag = arguments[index];
        if (flag == "--input") {
            parsed.input = value_following(arguments, index, flag);
        } else if (flag == "--output") {
            parsed.output = value_following(arguments, index, flag);
        } else if (flag == "--config") {
            parsed.config = value_following(arguments, index, flag);
        } else {
            continue;
        }
        ++index;
    }

    if (parsed.input.empty() || parsed.output.empty()) {
        throw DocumentError("--input and --output are both required");
    }
    return parsed;
}

void run_verb(const Verb& verb, const Arguments& arguments) {
    const Document request = read_document(arguments.input, verb.input_schema);
    write_document(arguments.output, Document{verb.output_schema, verb.transform_records(request.records)});
}

}

int main(int argc, char** argv) {
    const std::vector<std::string> arguments(argv + 1, argv + argc);
    if (arguments.empty() || arguments[0] == "--help" || arguments[0] == "-h") {
        print_usage(std::cout);
        return arguments.empty() ? 1 : 0;
    }

    try {
        const Arguments parsed = parse_arguments(arguments);
        run_verb(supported_verbs().at(parsed.verb), parsed);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << "\n";
        return 1;
    }
    return 0;
}
