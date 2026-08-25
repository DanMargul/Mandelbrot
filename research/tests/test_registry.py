from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pins import ResultPins, hash_of_configuration
from registry import (
    TRIAL_COMPLETED,
    TRIAL_STARTED,
    RegistryError,
    abandoned_trial_identifiers,
    read_entries,
    record_outcome,
    register_trial,
    trial_count,
    verify_registry,
)

MOMENT = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
STARTED_TRIALS = 7
COMPLETED_TRIALS = 4
ABANDONED_STARTED = 5
ABANDONED_COMPLETED = 2
ABANDONED_REMAINING = 3
CHAIN_LENGTH = 5
EDITED_SEQUENCE = 5
DELETED_TOTAL = 6
DELETED_REMAINING = 5
DELETED_BREAK_SEQUENCE = 4
TRUNCATED_KEPT = 4
REPEATED_TRIALS = 2


def pins_for_test(seed: int) -> ResultPins:
    return ResultPins(
        commit_sha="a" * 40,
        working_tree_clean=True,
        dataset_digest="b" * 64,
        config_hash=hash_of_configuration({"window": seed}),
        seed=seed,
    )


def registry_with(path: Path, started: int, completed: int) -> None:
    entries = []
    for index in range(started):
        entries.append(
            register_trial(path, "surface_residual", {"window": index}, pins_for_test(index), MOMENT)
        )
    for entry in entries[:completed]:
        record_outcome(path, entry, {"sharpe_ratio": 0.1}, MOMENT)


def test_a_fresh_registry_verifies_and_counts_nothing(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    verification = verify_registry(path)
    assert verification.intact
    assert verification.entry_count == 0
    assert trial_count(path) == 0


def test_every_registered_trial_is_counted(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    registry_with(path, started=STARTED_TRIALS, completed=COMPLETED_TRIALS)
    verification = verify_registry(path)
    assert verification.intact
    assert verification.trials_started == STARTED_TRIALS
    assert verification.trials_completed == COMPLETED_TRIALS
    assert trial_count(path) == STARTED_TRIALS


def test_an_abandoned_trial_stays_in_the_count(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    registry_with(path, started=ABANDONED_STARTED, completed=ABANDONED_COMPLETED)
    assert trial_count(path) == ABANDONED_STARTED
    assert len(abandoned_trial_identifiers(path)) == ABANDONED_REMAINING


def test_the_configuration_is_recorded_before_the_outcome_is_known(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    started = register_trial(path, "surface_residual", {"window": 60}, pins_for_test(1), MOMENT)
    assert trial_count(path) == 1
    entries = read_entries(path)
    assert len(entries) == 1
    assert entries[0].kind == TRIAL_STARTED
    assert entries[0].payload["configuration"] == {"window": 60}

    record_outcome(path, started, {"sharpe_ratio": 0.4}, MOMENT)
    entries = read_entries(path)
    assert [entry.kind for entry in entries] == [TRIAL_STARTED, TRIAL_COMPLETED]
    assert entries[1].trial_id == entries[0].trial_id


def test_editing_an_entry_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    registry_with(path, started=CHAIN_LENGTH, completed=CHAIN_LENGTH)
    assert verify_registry(path).intact

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[4])
    payload["payload"]["outcome"] = {"sharpe_ratio": 99.0}
    lines[4] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = verify_registry(path)
    assert not verification.intact
    assert verification.first_broken_sequence == EDITED_SEQUENCE
    assert "edited" in verification.reason


def test_deleting_an_entry_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    registry_with(path, started=DELETED_TOTAL, completed=0)
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[2]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verification = verify_registry(path)
    assert not verification.intact
    assert verification.trials_started == DELETED_REMAINING
    assert verification.first_broken_sequence == DELETED_BREAK_SEQUENCE


def test_removing_the_last_trials_is_still_detectable_by_count(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    registry_with(path, started=DELETED_TOTAL, completed=0)
    full = trial_count(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:4]) + "\n", encoding="utf-8")

    truncated = verify_registry(path)
    assert truncated.intact
    assert truncated.trials_started == TRUNCATED_KEPT
    assert full == DELETED_TOTAL


def test_an_outcome_must_follow_a_started_entry(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    started = register_trial(path, "surface_residual", {"window": 1}, pins_for_test(1), MOMENT)
    completed = record_outcome(path, started, {"sharpe_ratio": 0.1}, MOMENT)
    with pytest.raises(RegistryError):
        record_outcome(path, completed, {"sharpe_ratio": 0.2}, MOMENT)


def test_the_same_configuration_run_twice_is_two_trials(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    register_trial(path, "surface_residual", {"window": 60}, pins_for_test(1), MOMENT)
    register_trial(path, "surface_residual", {"window": 60}, pins_for_test(1), MOMENT)
    assert trial_count(path) == REPEATED_TRIALS
    entries = read_entries(path)
    assert entries[0].trial_id != entries[1].trial_id
