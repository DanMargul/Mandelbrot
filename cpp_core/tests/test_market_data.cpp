#include "volarb/market_data.hpp"

#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <string>

using volarb::ChainQuery;
using volarb::ContractQuote;
using volarb::CorruptDatasetError;
using volarb::format_canonical_date;
using volarb::format_canonical_timestamp;
using volarb::KnowledgeHorizon;
using volarb::LookaheadRequestedError;
using volarb::open_chain_dataset;
using volarb::parse_canonical_timestamp;

namespace {

const std::filesystem::path dataset_root = VOLARB_DATASET_ROOT;
const std::string correction_target = "SPX260918C04800000";
const std::string late_listing = "SPX260918C05520000";

std::vector<ContractQuote> chain(const std::string& horizon, const std::string& observation,
                                 bool include_adjusted = false) {
    const auto reader =
        open_chain_dataset(dataset_root, KnowledgeHorizon{parse_canonical_timestamp(horizon)});
    return reader.chain_as_of(ChainQuery{"SPX", parse_canonical_timestamp(observation), include_adjusted});
}

const ContractQuote* find(const std::vector<ContractQuote>& quotes, const std::string& symbol) {
    for (const ContractQuote& quote : quotes) {
        if (quote.contract_symbol == symbol) {
            return &quote;
        }
    }
    return nullptr;
}

}

TEST_CASE("canonical timestamps round trip", "[market_data]") {
    const std::string text = "2026-08-21T16:30:45.123456Z";
    REQUIRE(format_canonical_timestamp(parse_canonical_timestamp(text)) == text);
    REQUIRE(format_canonical_timestamp(0) == "1970-01-01T00:00:00.000000Z");
    REQUIRE(format_canonical_date(0) == "1970-01-01");
    REQUIRE(format_canonical_date(20686) == "2026-08-21");
}

TEST_CASE("a correction is invisible below its knowledge time", "[market_data]") {
    const auto before = chain("2026-08-21T17:00:00.000000Z", "2026-08-21T16:00:00.000000Z");
    const auto after = chain("2026-08-21T18:00:00.000000Z", "2026-08-21T16:00:00.000000Z");
    const ContractQuote* early = find(before, correction_target);
    const ContractQuote* late = find(after, correction_target);
    REQUIRE(early != nullptr);
    REQUIRE(late != nullptr);
    REQUIRE(early->bid_price != late->bid_price);
    REQUIRE(early->knowledge_time < late->knowledge_time);
}

TEST_CASE("a contract listed later is absent from earlier observations", "[market_data]") {
    REQUIRE(find(chain("2026-08-21T17:00:00.000000Z", "2026-08-21T16:00:00.000000Z"), late_listing) == nullptr);
    REQUIRE(find(chain("2026-08-21T17:00:00.000000Z", "2026-08-21T17:00:00.000000Z"), late_listing) != nullptr);
}

TEST_CASE("adjusted contracts are excluded unless requested", "[market_data]") {
    const auto standard_only = chain("2026-08-21T17:00:00.000000Z", "2026-08-21T17:00:00.000000Z");
    const auto with_adjusted = chain("2026-08-21T17:00:00.000000Z", "2026-08-21T17:00:00.000000Z", true);
    REQUIRE(with_adjusted.size() > standard_only.size());
    for (const ContractQuote& quote : standard_only) {
        REQUIRE(quote.is_standard_deliverable);
    }
}

TEST_CASE("raising the horizon never removes a contract", "[market_data]") {
    const auto narrow = chain("2026-08-21T17:00:00.000000Z", "2026-08-21T17:00:00.000000Z");
    const auto wide = chain("2026-08-22T12:00:00.000000Z", "2026-08-21T17:00:00.000000Z");
    for (const ContractQuote& quote : narrow) {
        REQUIRE(find(wide, quote.contract_symbol) != nullptr);
    }
}

TEST_CASE("lookahead is rejected rather than filtered", "[market_data]") {
    REQUIRE_THROWS_AS(chain("2026-08-21T16:00:00.000000Z", "2026-08-21T17:00:00.000000Z"),
                      LookaheadRequestedError);
}

TEST_CASE("an absent underlying is empty rather than an error", "[market_data]") {
    const auto reader = open_chain_dataset(
        dataset_root, KnowledgeHorizon{parse_canonical_timestamp("2026-08-21T17:00:00.000000Z")});
    const auto quotes =
        reader.chain_as_of(ChainQuery{"NVDA", parse_canonical_timestamp("2026-08-21T17:00:00.000000Z"), false});
    REQUIRE(quotes.empty());
}

TEST_CASE("a missing dataset is a typed error", "[market_data]") {
    REQUIRE_THROWS_AS(open_chain_dataset("/nonexistent/dataset", KnowledgeHorizon{0}), CorruptDatasetError);
}

TEST_CASE("results are sorted by expiry, strike, type, symbol", "[market_data]") {
    const auto quotes = chain("2026-08-21T17:00:00.000000Z", "2026-08-21T17:00:00.000000Z");
    REQUIRE(quotes.size() > 1);
    for (std::size_t index = 1; index < quotes.size(); ++index) {
        const ContractQuote& previous = quotes[index - 1];
        const ContractQuote& current = quotes[index];
        const bool ordered =
            std::tie(previous.expiry_date, previous.strike, previous.contract_symbol) <
            std::tie(current.expiry_date, current.strike, current.contract_symbol);
        REQUIRE(ordered);
    }
}
