from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pins import ResultPins, canonical_json, pins_as_payload

REGISTRY_SCHEMA_ID: Final[str] = "trial_registry/v1"
GENESIS_HASH: Final[str] = "0" * 64
EntryKind = Literal["trial_started", "trial_completed"]

TRIAL_STARTED: Final[EntryKind] = "trial_started"
TRIAL_COMPLETED: Final[EntryKind] = "trial_completed"


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class EntryDraft:
    kind: EntryKind
    trial_id: str
    strategy: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RegistryEntry:
    sequence: int
    kind: EntryKind
    recorded_at: str
    trial_id: str
    strategy: str
    payload: dict[str, Any]
    previous_hash: str
    entry_hash: str


@dataclass(frozen=True)
class RegistryVerification:
    entry_count: int
    trials_started: int
    trials_completed: int
    intact: bool
    first_broken_sequence: int | None
    reason: str


def canonical_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def hashed_body(draft: EntryDraft, sequence: int, recorded_at: str, previous_hash: str) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "kind": draft.kind,
        "recorded_at": recorded_at,
        "trial_id": draft.trial_id,
        "strategy": draft.strategy,
        "payload": dict(draft.payload),
        "previous_hash": previous_hash,
    }


def hash_of_entry(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(body)).encode("utf-8")).hexdigest()


def read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def entry_from_line(line: str) -> RegistryEntry:
    payload = json.loads(line)
    return RegistryEntry(
        sequence=int(payload["sequence"]),
        kind=payload["kind"],
        recorded_at=str(payload["recorded_at"]),
        trial_id=str(payload["trial_id"]),
        strategy=str(payload["strategy"]),
        payload=dict(payload["payload"]),
        previous_hash=str(payload["previous_hash"]),
        entry_hash=str(payload["entry_hash"]),
    )


def read_entries(path: Path) -> list[RegistryEntry]:
    return [entry_from_line(line) for line in read_lines(path)]


def last_hash_and_sequence(path: Path) -> tuple[str, int]:
    entries = read_entries(path)
    if not entries:
        return GENESIS_HASH, 0
    return entries[-1].entry_hash, entries[-1].sequence


def append_entry(path: Path, draft: EntryDraft, moment: datetime) -> RegistryEntry:
    previous_hash, previous_sequence = last_hash_and_sequence(path)
    body = hashed_body(draft, previous_sequence + 1, canonical_timestamp(moment), previous_hash)
    entry = RegistryEntry(
        sequence=int(body["sequence"]),
        kind=draft.kind,
        recorded_at=str(body["recorded_at"]),
        trial_id=draft.trial_id,
        strategy=draft.strategy,
        payload=dict(draft.payload),
        previous_hash=previous_hash,
        entry_hash=hash_of_entry(body),
    )
    line = canonical_json({**body, "entry_hash": entry.entry_hash})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def trial_identifier(strategy: str, pins: ResultPins, sequence: int) -> str:
    return hashlib.sha256(
        canonical_json({"strategy": strategy, "pins": pins_as_payload(pins), "sequence": sequence}).encode(
            "utf-8"
        )
    ).hexdigest()[:32]


def register_trial(
    path: Path,
    strategy: str,
    configuration: Mapping[str, Any],
    pins: ResultPins,
    moment: datetime | None = None,
) -> RegistryEntry:
    _, previous_sequence = last_hash_and_sequence(path)
    trial_id = trial_identifier(strategy, pins, previous_sequence + 1)
    draft = EntryDraft(
        kind=TRIAL_STARTED,
        trial_id=trial_id,
        strategy=strategy,
        payload={"configuration": dict(configuration), "pins": pins_as_payload(pins)},
    )
    return append_entry(path, draft, moment if moment is not None else datetime.now(UTC))


def record_outcome(
    path: Path,
    started: RegistryEntry,
    outcome: Mapping[str, Any],
    moment: datetime | None = None,
) -> RegistryEntry:
    if started.kind != TRIAL_STARTED:
        raise RegistryError(f"an outcome must follow a {TRIAL_STARTED} entry, got {started.kind}")
    draft = EntryDraft(
        kind=TRIAL_COMPLETED,
        trial_id=started.trial_id,
        strategy=started.strategy,
        payload={"outcome": dict(outcome), "started_sequence": started.sequence},
    )
    return append_entry(path, draft, moment if moment is not None else datetime.now(UTC))


def verify_registry(path: Path) -> RegistryVerification:
    entries = read_entries(path)
    previous_hash = GENESIS_HASH
    for position, entry in enumerate(entries, start=1):
        if entry.sequence != position:
            return broken(entries, entry.sequence, f"sequence {entry.sequence} found at position {position}")
        if entry.previous_hash != previous_hash:
            return broken(entries, entry.sequence, "the chain does not reach back to the entry before it")
        draft = EntryDraft(entry.kind, entry.trial_id, entry.strategy, entry.payload)
        recomputed = hash_of_entry(hashed_body(draft, entry.sequence, entry.recorded_at, entry.previous_hash))
        if recomputed != entry.entry_hash:
            return broken(entries, entry.sequence, "the entry has been edited since it was written")
        previous_hash = entry.entry_hash
    return RegistryVerification(
        entry_count=len(entries),
        trials_started=count_of_kind(entries, TRIAL_STARTED),
        trials_completed=count_of_kind(entries, TRIAL_COMPLETED),
        intact=True,
        first_broken_sequence=None,
        reason="every entry hashes to the one after it",
    )


def count_of_kind(entries: list[RegistryEntry], kind: str) -> int:
    return sum(1 for entry in entries if entry.kind == kind)


def broken(entries: list[RegistryEntry], sequence: int, reason: str) -> RegistryVerification:
    return RegistryVerification(
        entry_count=len(entries),
        trials_started=count_of_kind(entries, TRIAL_STARTED),
        trials_completed=count_of_kind(entries, TRIAL_COMPLETED),
        intact=False,
        first_broken_sequence=sequence,
        reason=reason,
    )


def trial_count(path: Path) -> int:
    return count_of_kind(read_entries(path), TRIAL_STARTED)


def abandoned_trial_identifiers(path: Path) -> list[str]:
    entries = read_entries(path)
    completed = {entry.trial_id for entry in entries if entry.kind == TRIAL_COMPLETED}
    return [
        entry.trial_id for entry in entries if entry.kind == TRIAL_STARTED and entry.trial_id not in completed
    ]
