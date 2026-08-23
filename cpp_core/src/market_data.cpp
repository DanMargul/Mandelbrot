#include "volarb/market_data.hpp"

#include <arrow/api.h>
#include <arrow/io/api.h>
#include <nlohmann/json.hpp>
#include <parquet/arrow/reader.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <map>
#include <tuple>

namespace volarb {

namespace {

constexpr std::int64_t microseconds_per_second = 1000000;
constexpr const char* manifest_filename = "manifest.json";
constexpr const char* manifest_schema_id = "chain_dataset_manifest/v1";

using ResolutionKey = std::tuple<EpochMicroseconds, EpochMicroseconds, std::int64_t>;

ResolutionKey resolution_key(const ContractQuote& quote) {
    return {quote.event_time, quote.knowledge_time, quote.ingest_sequence};
}

std::tuple<DaysSinceEpoch, double, std::string, std::string> chain_sort_key(const ContractQuote& quote) {
    return {quote.expiry_date, quote.strike, name_of_option_type(quote.option_type), quote.contract_symbol};
}

std::string require_string(const nlohmann::json& payload, const std::string& field) {
    const auto entry = payload.find(field);
    if (entry == payload.end() || !entry->is_string()) {
        throw CorruptDatasetError("manifest field '" + field + "' must be a string");
    }
    return entry->get<std::string>();
}

std::int64_t require_integer(const nlohmann::json& payload, const std::string& field) {
    const auto entry = payload.find(field);
    if (entry == payload.end() || !entry->is_number_integer()) {
        throw CorruptDatasetError("manifest field '" + field + "' must be an integer");
    }
    return entry->get<std::int64_t>();
}

std::shared_ptr<arrow::Table> read_parquet_table(const std::filesystem::path& path) {
    auto input = arrow::io::ReadableFile::Open(path.string());
    if (!input.ok()) {
        throw CorruptDatasetError(path.string() + ": " + input.status().ToString());
    }

    auto opened = parquet::arrow::OpenFile(*input, arrow::default_memory_pool());
    if (!opened.ok()) {
        throw CorruptDatasetError(path.string() + ": " + opened.status().ToString());
    }
    const std::unique_ptr<parquet::arrow::FileReader> reader = std::move(*opened);

    auto read = reader->ReadTable();
    if (!read.ok()) {
        throw CorruptDatasetError(path.string() + ": " + read.status().ToString());
    }

    const auto combined = (*read)->CombineChunks(arrow::default_memory_pool());
    if (!combined.ok()) {
        throw CorruptDatasetError(path.string() + ": " + combined.status().ToString());
    }
    return *combined;
}

template <typename ArrayType>
std::shared_ptr<ArrayType> typed_column(const arrow::Table& table, const std::string& name) {
    const std::shared_ptr<arrow::ChunkedArray> column = table.GetColumnByName(name);
    if (column == nullptr || column->num_chunks() != 1) {
        throw CorruptDatasetError("column '" + name + "' is missing or not contiguous");
    }
    auto typed = std::dynamic_pointer_cast<ArrayType>(column->chunk(0));
    if (typed == nullptr) {
        throw CorruptDatasetError("column '" + name + "' has an unexpected type");
    }
    return typed;
}

struct ChainColumns {
    std::shared_ptr<arrow::StringArray> contract_symbol;
    std::shared_ptr<arrow::Date32Array> expiry_date;
    std::shared_ptr<arrow::DoubleArray> strike;
    std::shared_ptr<arrow::StringArray> option_type;
    std::shared_ptr<arrow::Int32Array> contract_multiplier;
    std::shared_ptr<arrow::BooleanArray> is_standard_deliverable;
    std::shared_ptr<arrow::TimestampArray> event_time;
    std::shared_ptr<arrow::TimestampArray> knowledge_time;
    std::shared_ptr<arrow::Int64Array> ingest_sequence;
    std::shared_ptr<arrow::DoubleArray> underlying_price;
    std::shared_ptr<arrow::DoubleArray> bid_price;
    std::shared_ptr<arrow::DoubleArray> ask_price;
    std::shared_ptr<arrow::Int64Array> bid_size;
    std::shared_ptr<arrow::Int64Array> ask_size;
};

ChainColumns bind_columns(const arrow::Table& table) {
    return ChainColumns{
        typed_column<arrow::StringArray>(table, "contract_symbol"),
        typed_column<arrow::Date32Array>(table, "expiry_date"),
        typed_column<arrow::DoubleArray>(table, "strike"),
        typed_column<arrow::StringArray>(table, "option_type"),
        typed_column<arrow::Int32Array>(table, "contract_multiplier"),
        typed_column<arrow::BooleanArray>(table, "is_standard_deliverable"),
        typed_column<arrow::TimestampArray>(table, "event_time"),
        typed_column<arrow::TimestampArray>(table, "knowledge_time"),
        typed_column<arrow::Int64Array>(table, "ingest_sequence"),
        typed_column<arrow::DoubleArray>(table, "underlying_price"),
        typed_column<arrow::DoubleArray>(table, "bid_price"),
        typed_column<arrow::DoubleArray>(table, "ask_price"),
        typed_column<arrow::Int64Array>(table, "bid_size"),
        typed_column<arrow::Int64Array>(table, "ask_size"),
    };
}

ContractQuote quote_at(const ChainColumns& columns, std::int64_t row) {
    const EpochMicroseconds event_time = columns.event_time->Value(row);
    const EpochMicroseconds knowledge_time = columns.knowledge_time->Value(row);
    const std::string contract_symbol = columns.contract_symbol->GetString(row);
    if (knowledge_time < event_time) {
        throw CorruptDatasetError(contract_symbol + ": knowledge_time precedes event_time");
    }
    return ContractQuote{
        contract_symbol,
        columns.expiry_date->Value(row),
        columns.strike->Value(row),
        option_type_from_name(columns.option_type->GetString(row)),
        columns.contract_multiplier->Value(row),
        columns.is_standard_deliverable->Value(row),
        event_time,
        knowledge_time,
        columns.ingest_sequence->Value(row),
        columns.underlying_price->Value(row),
        columns.bid_price->Value(row),
        columns.ask_price->Value(row),
        columns.bid_size->Value(row),
        columns.ask_size->Value(row),
    };
}

}

EpochMicroseconds parse_canonical_timestamp(const std::string& text) {
    int year = 0;
    unsigned month = 0;
    unsigned day = 0;
    int hour = 0;
    int minute = 0;
    int second = 0;
    long fraction = 0;

    const int matched = std::sscanf(text.c_str(), "%4d-%2u-%2uT%2d:%2d:%2d.%6ld", &year, &month, &day,
                                    &hour, &minute, &second, &fraction);
    if (matched < 6) {
        throw CorruptDatasetError("not a canonical timestamp: " + text);
    }
    if (matched == 6) {
        fraction = 0;
    }

    const std::chrono::year_month_day date{std::chrono::year{year}, std::chrono::month{month},
                                           std::chrono::day{day}};
    const auto days = std::chrono::sys_days{date}.time_since_epoch().count();
    const std::int64_t seconds =
        days * 86400LL + hour * 3600LL + minute * 60LL + static_cast<std::int64_t>(second);
    return seconds * microseconds_per_second + static_cast<std::int64_t>(fraction);
}

std::string format_canonical_timestamp(EpochMicroseconds microseconds) {
    std::int64_t seconds = microseconds / microseconds_per_second;
    std::int64_t fraction = microseconds % microseconds_per_second;
    if (fraction < 0) {
        fraction += microseconds_per_second;
        seconds -= 1;
    }
    std::int64_t days = seconds / 86400;
    std::int64_t remainder = seconds % 86400;
    if (remainder < 0) {
        remainder += 86400;
        days -= 1;
    }

    const std::chrono::year_month_day date{
        std::chrono::sys_days{std::chrono::days{static_cast<int>(days)}}};
    char buffer[40];
    std::snprintf(buffer, sizeof(buffer), "%04d-%02u-%02uT%02lld:%02lld:%02lld.%06lldZ",
                  static_cast<int>(date.year()), static_cast<unsigned>(date.month()),
                  static_cast<unsigned>(date.day()), static_cast<long long>(remainder / 3600),
                  static_cast<long long>((remainder % 3600) / 60), static_cast<long long>(remainder % 60),
                  static_cast<long long>(fraction));
    return std::string(buffer);
}

std::string format_canonical_date(DaysSinceEpoch days) {
    const std::chrono::year_month_day date{std::chrono::sys_days{std::chrono::days{days}}};
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "%04d-%02u-%02u", static_cast<int>(date.year()),
                  static_cast<unsigned>(date.month()), static_cast<unsigned>(date.day()));
    return std::string(buffer);
}

DatasetManifest read_manifest(const std::filesystem::path& dataset_root) {
    const std::filesystem::path manifest_path = dataset_root / manifest_filename;
    std::ifstream stream(manifest_path);
    if (!stream) {
        throw CorruptDatasetError(dataset_root.string() + ": no " + manifest_filename);
    }

    nlohmann::json payload = nlohmann::json::parse(stream, nullptr, false);
    if (payload.is_discarded() || !payload.is_object()) {
        throw CorruptDatasetError(manifest_path.string() + ": is not a JSON object");
    }
    if (require_string(payload, "schema") != manifest_schema_id) {
        throw CorruptDatasetError(manifest_path.string() + ": unexpected manifest schema");
    }

    DatasetManifest manifest;
    manifest.dataset_digest = require_string(payload, "dataset_digest");
    for (const nlohmann::json& entry : payload.at("partitions")) {
        manifest.partitions.push_back(PartitionEntry{
            require_string(entry, "relative_path"),
            require_string(entry, "underlying_symbol"),
            require_integer(entry, "row_count"),
            require_string(entry, "content_hash"),
            parse_canonical_timestamp(require_string(entry, "minimum_event_time")),
            parse_canonical_timestamp(require_string(entry, "minimum_knowledge_time")),
        });
    }
    return manifest;
}

std::vector<const PartitionEntry*> AsOfChainReader::readable_partitions(const ChainQuery& query) const {
    std::vector<const PartitionEntry*> selected;
    for (const PartitionEntry& partition : manifest_.partitions) {
        const bool matches = partition.underlying_symbol == query.underlying_symbol &&
                             partition.minimum_knowledge_time <= horizon_ &&
                             partition.minimum_event_time <= query.observation_time;
        if (matches) {
            selected.push_back(&partition);
        }
    }
    return selected;
}

std::vector<ContractQuote> AsOfChainReader::quotes_in_partition(
    const PartitionEntry& partition, const ChainQuery& query) const {
    const std::shared_ptr<arrow::Table> table = read_parquet_table(dataset_root_ / partition.relative_path);
    const ChainColumns columns = bind_columns(*table);

    std::vector<ContractQuote> quotes;
    for (std::int64_t row = 0; row < table->num_rows(); ++row) {
        if (columns.knowledge_time->Value(row) > horizon_) {
            continue;
        }
        if (columns.event_time->Value(row) > query.observation_time) {
            continue;
        }
        quotes.push_back(quote_at(columns, row));
    }
    return quotes;
}

std::vector<ContractQuote> AsOfChainReader::chain_as_of(const ChainQuery& query) const {
    if (query.observation_time > horizon_) {
        throw LookaheadRequestedError("observation_time " + format_canonical_timestamp(query.observation_time) +
                                      " is past knowledge horizon " + format_canonical_timestamp(horizon_));
    }

    std::map<std::string, ContractQuote> latest;
    for (const PartitionEntry* partition : readable_partitions(query)) {
        for (ContractQuote& quote : quotes_in_partition(*partition, query)) {
            const auto existing = latest.find(quote.contract_symbol);
            if (existing == latest.end()) {
                latest.emplace(quote.contract_symbol, std::move(quote));
            } else if (resolution_key(quote) > resolution_key(existing->second)) {
                existing->second = std::move(quote);
            }
        }
    }

    std::vector<ContractQuote> selected;
    for (auto& [contract_symbol, quote] : latest) {
        if (query.include_adjusted_contracts || quote.is_standard_deliverable) {
            selected.push_back(std::move(quote));
        }
    }
    std::sort(selected.begin(), selected.end(), [](const ContractQuote& left, const ContractQuote& right) {
        return chain_sort_key(left) < chain_sort_key(right);
    });
    return selected;
}

AsOfChainReader open_chain_dataset(const std::filesystem::path& dataset_root, KnowledgeHorizon horizon) {
    return AsOfChainReader(dataset_root, read_manifest(dataset_root), horizon.as_of);
}

}
