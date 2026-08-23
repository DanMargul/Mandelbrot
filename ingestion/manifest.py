from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

MANIFEST_FILENAME: Final[str] = "manifest.json"
MANIFEST_SCHEMA_ID: Final[str] = "chain_dataset_manifest/v1"
HASH_READ_BLOCK_BYTES: Final[int] = 1 << 20


@dataclass(frozen=True)
class PartitionEntry:
    relative_path: str
    underlying_symbol: str
    row_count: int
    content_hash: str
    minimum_event_time: str
    maximum_event_time: str
    minimum_knowledge_time: str
    maximum_knowledge_time: str


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(HASH_READ_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def dataset_digest(partitions: list[PartitionEntry]) -> str:
    digest = hashlib.sha256()
    for partition in sorted(partitions, key=lambda entry: entry.relative_path):
        digest.update(partition.relative_path.encode())
        digest.update(b"\0")
        digest.update(partition.content_hash.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def write_manifest(
    dataset_root: Path, partitions: list[PartitionEntry], source: str, created_at: datetime
) -> None:
    ordered = sorted(partitions, key=lambda entry: entry.relative_path)
    payload: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA_ID,
        "source": source,
        "created_at": canonical_timestamp(created_at),
        "dataset_digest": dataset_digest(ordered),
        "partitions": [asdict(partition) for partition in ordered],
    }
    (dataset_root / MANIFEST_FILENAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
