#pragma once

#include "volarb/american.hpp"
#include "volarb/pricing.hpp"

#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

using EpochMicroseconds = std::int64_t;
using DaysSinceEpoch = std::int32_t;

inline constexpr std::int32_t standard_contract_multiplier = 100;

class ChainDatasetError : public std::runtime_error {
  public:
    explicit ChainDatasetError(const std::string& message) : std::runtime_error(message) {}
};

class LookaheadRequestedError : public ChainDatasetError {
  public:
    explicit LookaheadRequestedError(const std::string& message) : ChainDatasetError(message) {}
};

class CorruptDatasetError : public ChainDatasetError {
  public:
    explicit CorruptDatasetError(const std::string& message) : ChainDatasetError(message) {}
};

struct KnowledgeHorizon {
    EpochMicroseconds as_of;
};

struct ChainQuery {
    std::string underlying_symbol;
    EpochMicroseconds observation_time;
    bool include_adjusted_contracts;
};

struct ContractQuote {
    std::string contract_symbol;
    DaysSinceEpoch expiry_date;
    double strike;
    OptionType option_type;
    std::int32_t contract_multiplier;
    bool is_standard_deliverable;
    ExerciseStyle exercise_style;
    EpochMicroseconds event_time;
    EpochMicroseconds knowledge_time;
    std::int64_t ingest_sequence;
    double underlying_price;
    double bid_price;
    double ask_price;
    std::int64_t bid_size;
    std::int64_t ask_size;
};

struct PartitionEntry {
    std::string relative_path;
    std::string underlying_symbol;
    std::int64_t row_count;
    std::string content_hash;
    EpochMicroseconds minimum_event_time;
    EpochMicroseconds minimum_knowledge_time;
};

struct DatasetManifest {
    std::string dataset_digest;
    std::vector<PartitionEntry> partitions;
};

EpochMicroseconds parse_canonical_timestamp(const std::string& text);
std::string format_canonical_timestamp(EpochMicroseconds microseconds);
std::string format_canonical_date(DaysSinceEpoch days);

DatasetManifest read_manifest(const std::filesystem::path& dataset_root);

class AsOfChainReader {
  public:
    std::vector<ContractQuote> chain_as_of(const ChainQuery& query) const;
    const std::string& dataset_digest() const { return manifest_.dataset_digest; }
    EpochMicroseconds knowledge_horizon() const { return horizon_; }

  private:
    AsOfChainReader(std::filesystem::path dataset_root, DatasetManifest manifest, EpochMicroseconds horizon)
        : dataset_root_(std::move(dataset_root)), manifest_(std::move(manifest)), horizon_(horizon) {}

    friend AsOfChainReader open_chain_dataset(const std::filesystem::path&, KnowledgeHorizon);

    std::vector<const PartitionEntry*> readable_partitions(const ChainQuery& query) const;
    std::vector<ContractQuote> quotes_in_partition(const PartitionEntry& partition, const ChainQuery& query) const;

    std::filesystem::path dataset_root_;
    DatasetManifest manifest_;
    EpochMicroseconds horizon_;
};

AsOfChainReader open_chain_dataset(const std::filesystem::path& dataset_root, KnowledgeHorizon horizon);

}
