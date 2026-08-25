from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

RESULT_SCHEMA_ID: Final[str] = "return_series/v1"
DIGEST_LENGTH: Final[int] = 64


class ResultStoreError(ValueError):
    pass


@dataclass(frozen=True)
class StoredSeries:
    digest: str
    observation_count: int
    relative_path: str


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def series_payload(
    trial_id: str, dataset_digest: str, returns: list[float], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA_ID,
        "trial_id": trial_id,
        "dataset_digest": dataset_digest,
        "returns": list(returns),
        "metadata": dict(metadata),
    }


def digest_of(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()


def path_for(store_root: Path, digest: str) -> Path:
    return store_root / digest[:2] / f"{digest}.json"


def write_return_series(
    store_root: Path,
    trial_id: str,
    dataset_digest: str,
    returns: list[float],
    metadata: Mapping[str, Any] | None = None,
) -> StoredSeries:
    if not returns:
        raise ResultStoreError("a return series must not be empty")
    payload = series_payload(trial_id, dataset_digest, returns, metadata or {})
    digest = digest_of(payload)
    destination = path_for(store_root, digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        handle.write(canonical_json(payload) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return StoredSeries(
        digest=digest,
        observation_count=len(returns),
        relative_path=str(destination.relative_to(store_root)),
    )


def read_return_series(store_root: Path, digest: str) -> dict[str, Any]:
    if len(digest) != DIGEST_LENGTH:
        raise ResultStoreError(f"a digest is {DIGEST_LENGTH} hex characters, got {len(digest)}")
    source = path_for(store_root, digest)
    if not source.is_file():
        raise ResultStoreError(f"no stored series for {digest}")
    payload: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    if digest_of(payload) != digest:
        raise ResultStoreError(f"{source} does not hash to the digest it is filed under")
    return payload


def returns_of(store_root: Path, digest: str) -> list[float]:
    payload = read_return_series(store_root, digest)
    return [float(value) for value in payload["returns"]]
