from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pyarrow.parquet

from volarb_py.american import ExerciseStyle
from volarb_py.pricing import OptionType

MANIFEST_FILENAME: Final[str] = "manifest.json"
MANIFEST_SCHEMA_ID: Final[str] = "chain_dataset_manifest/v1"
CHAIN_SCHEMA_ID: Final[str] = "option_chain_snapshot/v2"
STANDARD_CONTRACT_MULTIPLIER: Final[int] = 100


class ChainDatasetError(ValueError):
    pass


class LookaheadRequestedError(ChainDatasetError):
    pass


class CorruptDatasetError(ChainDatasetError):
    pass


def parse_canonical_timestamp(text: str) -> datetime:
    without_zone = text.removesuffix("Z").removesuffix("+00:00")
    with_fraction = without_zone if "." in without_zone else without_zone + ".000000"
    return datetime.strptime(with_fraction, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)


def format_canonical_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def format_canonical_date(day: date) -> str:
    return day.strftime("%Y-%m-%d")


@dataclass(frozen=True)
class KnowledgeHorizon:
    as_of: datetime


@dataclass(frozen=True)
class ChainQuery:
    underlying_symbol: str
    observation_time: datetime
    include_adjusted_contracts: bool = False


@dataclass(frozen=True)
class ContractQuote:
    contract_symbol: str
    expiry_date: date
    strike: float
    option_type: OptionType
    contract_multiplier: int
    is_standard_deliverable: bool
    exercise_style: ExerciseStyle
    event_time: datetime
    knowledge_time: datetime
    ingest_sequence: int
    underlying_price: float
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int


@dataclass(frozen=True)
class PartitionEntry:
    relative_path: str
    underlying_symbol: str
    row_count: int
    content_hash: str
    minimum_event_time: datetime
    minimum_knowledge_time: datetime


@dataclass(frozen=True)
class DatasetManifest:
    dataset_digest: str
    partitions: tuple[PartitionEntry, ...]


def resolution_key(quote: ContractQuote) -> tuple[datetime, datetime, int]:
    return quote.event_time, quote.knowledge_time, quote.ingest_sequence


def chain_sort_key(quote: ContractQuote) -> tuple[date, float, str, str]:
    return quote.expiry_date, quote.strike, quote.option_type, quote.contract_symbol


def exercise_style_from_name(name: str) -> ExerciseStyle:
    if name == "european":
        return "european"
    if name == "american":
        return "american"
    raise CorruptDatasetError(f"exercise_style must be 'european' or 'american', found {name!r}")


def option_type_from_name(name: str) -> OptionType:
    if name == "call":
        return "call"
    if name == "put":
        return "put"
    raise CorruptDatasetError(f"option_type must be 'call' or 'put', found {name!r}")


def partition_from_payload(payload: dict[str, Any]) -> PartitionEntry:
    return PartitionEntry(
        relative_path=str(payload["relative_path"]),
        underlying_symbol=str(payload["underlying_symbol"]),
        row_count=int(payload["row_count"]),
        content_hash=str(payload["content_hash"]),
        minimum_event_time=parse_canonical_timestamp(str(payload["minimum_event_time"])),
        minimum_knowledge_time=parse_canonical_timestamp(str(payload["minimum_knowledge_time"])),
    )


def read_manifest(dataset_root: Path) -> DatasetManifest:
    manifest_path = dataset_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise CorruptDatasetError(f"{dataset_root}: no {MANIFEST_FILENAME}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != MANIFEST_SCHEMA_ID:
        raise CorruptDatasetError(f"{manifest_path}: expected schema {MANIFEST_SCHEMA_ID!r}")
    if payload.get("chain_schema") != CHAIN_SCHEMA_ID:
        raise CorruptDatasetError(
            f"{manifest_path}: expected chain schema {CHAIN_SCHEMA_ID!r}, "
            f"found {payload.get('chain_schema')!r}"
        )
    return DatasetManifest(
        dataset_digest=str(payload["dataset_digest"]),
        partitions=tuple(partition_from_payload(entry) for entry in payload["partitions"]),
    )


def quote_from_row(row: dict[str, Any]) -> ContractQuote:
    event_time = row["event_time"]
    knowledge_time = row["knowledge_time"]
    if knowledge_time < event_time:
        raise CorruptDatasetError(
            f"{row['contract_symbol']}: knowledge_time {knowledge_time} precedes event_time {event_time}"
        )
    return ContractQuote(
        contract_symbol=str(row["contract_symbol"]),
        expiry_date=row["expiry_date"],
        strike=float(row["strike"]),
        option_type=option_type_from_name(str(row["option_type"])),
        contract_multiplier=int(row["contract_multiplier"]),
        is_standard_deliverable=bool(row["is_standard_deliverable"]),
        exercise_style=exercise_style_from_name(str(row["exercise_style"])),
        event_time=event_time,
        knowledge_time=knowledge_time,
        ingest_sequence=int(row["ingest_sequence"]),
        underlying_price=float(row["underlying_price"]),
        bid_price=float(row["bid_price"]),
        ask_price=float(row["ask_price"]),
        bid_size=int(row["bid_size"]),
        ask_size=int(row["ask_size"]),
    )


class AsOfChainReader:
    def __init__(self, dataset_root: Path, manifest: DatasetManifest, horizon: KnowledgeHorizon) -> None:
        self._dataset_root = dataset_root
        self._manifest = manifest
        self._horizon = horizon.as_of

    @property
    def dataset_digest(self) -> str:
        return self._manifest.dataset_digest

    @property
    def knowledge_horizon(self) -> datetime:
        return self._horizon

    def chain_as_of(self, query: ChainQuery) -> list[ContractQuote]:
        if query.observation_time > self._horizon:
            raise LookaheadRequestedError(
                f"observation_time {format_canonical_timestamp(query.observation_time)} is past "
                f"knowledge horizon {format_canonical_timestamp(self._horizon)}"
            )
        latest: dict[str, ContractQuote] = {}
        for partition in self._readable_partitions(query):
            for quote in self._quotes_in_partition(partition, query):
                previous = latest.get(quote.contract_symbol)
                if previous is None or resolution_key(quote) > resolution_key(previous):
                    latest[quote.contract_symbol] = quote
        return sorted(
            (
                quote
                for quote in latest.values()
                if query.include_adjusted_contracts or quote.is_standard_deliverable
            ),
            key=chain_sort_key,
        )

    def _readable_partitions(self, query: ChainQuery) -> list[PartitionEntry]:
        return [
            partition
            for partition in self._manifest.partitions
            if partition.underlying_symbol == query.underlying_symbol
            and partition.minimum_knowledge_time <= self._horizon
            and partition.minimum_event_time <= query.observation_time
        ]

    def _quotes_in_partition(self, partition: PartitionEntry, query: ChainQuery) -> list[ContractQuote]:
        table = pyarrow.parquet.read_table(
            self._dataset_root / partition.relative_path,
            filters=[
                ("knowledge_time", "<=", self._horizon),
                ("event_time", "<=", query.observation_time),
            ],
        )
        return [quote_from_row(row) for row in table.to_pylist()]


def open_chain_dataset(dataset_root: Path, horizon: KnowledgeHorizon) -> AsOfChainReader:
    return AsOfChainReader(dataset_root, read_manifest(dataset_root), horizon)
