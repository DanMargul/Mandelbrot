from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow
import pyarrow.parquet
from chain_schema import OPTION_CHAIN_SNAPSHOT_SCHEMA
from manifest import PartitionEntry, canonical_timestamp, sha256_of_file, write_manifest

STANDARD_CONTRACT_MULTIPLIER = 100


class IngestionError(ValueError):
    pass


def validate_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row["knowledge_time"] < row["event_time"]:
            raise IngestionError(
                f"{row['contract_symbol']}: knowledge_time {row['knowledge_time']} "
                f"precedes event_time {row['event_time']}"
            )
        if row["is_standard_deliverable"] and row["contract_multiplier"] != STANDARD_CONTRACT_MULTIPLIER:
            raise IngestionError(
                f"{row['contract_symbol']}: standard deliverable with multiplier {row['contract_multiplier']}"
            )
    sequences = [row["ingest_sequence"] for row in rows]
    if len(set(sequences)) != len(sequences):
        raise IngestionError("ingest_sequence must be unique across the dataset")


def partition_key(row: dict[str, Any]) -> tuple[str, date]:
    event_time: datetime = row["event_time"]
    return row["underlying_symbol"], event_time.date()


def relative_partition_path(underlying_symbol: str, observation_date: date) -> str:
    return f"underlying={underlying_symbol}/observation_date={observation_date:%Y-%m-%d}/part-00000.parquet"


def write_partition(dataset_root: Path, relative_path: str, rows: list[dict[str, Any]]) -> PartitionEntry:
    ordered = sorted(rows, key=lambda row: row["ingest_sequence"])
    columns = {field.name: [row[field.name] for row in ordered] for field in OPTION_CHAIN_SNAPSHOT_SCHEMA}
    table = pyarrow.Table.from_pydict(columns, schema=OPTION_CHAIN_SNAPSHOT_SCHEMA)

    destination = dataset_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    pyarrow.parquet.write_table(table, destination, compression="zstd", version="2.6")

    return PartitionEntry(
        relative_path=relative_path,
        underlying_symbol=ordered[0]["underlying_symbol"],
        row_count=len(ordered),
        content_hash=sha256_of_file(destination),
        minimum_event_time=canonical_timestamp(min(row["event_time"] for row in ordered)),
        maximum_event_time=canonical_timestamp(max(row["event_time"] for row in ordered)),
        minimum_knowledge_time=canonical_timestamp(min(row["knowledge_time"] for row in ordered)),
        maximum_knowledge_time=canonical_timestamp(max(row["knowledge_time"] for row in ordered)),
    )


def write_dataset(
    dataset_root: Path, rows: list[dict[str, Any]], source: str, created_at: datetime
) -> list[PartitionEntry]:
    validate_rows(rows)
    if dataset_root.exists():
        shutil.rmtree(dataset_root)
    dataset_root.mkdir(parents=True)

    grouped: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[partition_key(row)].append(row)

    partitions = [
        write_partition(dataset_root, relative_partition_path(underlying_symbol, observation_date), group)
        for (underlying_symbol, observation_date), group in sorted(grouped.items())
    ]
    write_manifest(dataset_root, partitions, source, created_at)
    return partitions
