from __future__ import annotations

import json
from pathlib import Path

import pytest
from results import (
    ResultStoreError,
    read_return_series,
    returns_of,
    write_return_series,
)

TRIAL = "a" * 32
DATASET_DIGEST = "b" * 64
RETURNS = [0.01, -0.004, 0.002]
DISTINCT_SERIES = 3


def test_a_series_survives_a_round_trip(tmp_path: Path) -> None:
    stored = write_return_series(tmp_path, TRIAL, DATASET_DIGEST, RETURNS, {"note": "one"})
    assert stored.observation_count == len(RETURNS)
    assert returns_of(tmp_path, stored.digest) == RETURNS

    payload = read_return_series(tmp_path, stored.digest)
    assert payload["trial_id"] == TRIAL
    assert payload["dataset_digest"] == DATASET_DIGEST
    assert payload["metadata"] == {"note": "one"}


def test_the_same_series_lands_on_the_same_digest(tmp_path: Path) -> None:
    first = write_return_series(tmp_path, TRIAL, DATASET_DIGEST, RETURNS)
    second = write_return_series(tmp_path, TRIAL, DATASET_DIGEST, RETURNS)
    assert first.digest == second.digest


def test_a_different_series_lands_elsewhere(tmp_path: Path) -> None:
    first = write_return_series(tmp_path, TRIAL, DATASET_DIGEST, RETURNS)
    second = write_return_series(tmp_path, TRIAL, DATASET_DIGEST, [*RETURNS, 0.0])
    third = write_return_series(tmp_path, TRIAL, "c" * 64, RETURNS)
    assert len({first.digest, second.digest, third.digest}) == DISTINCT_SERIES


def test_an_edited_series_no_longer_hashes_to_its_own_name(tmp_path: Path) -> None:
    stored = write_return_series(tmp_path, TRIAL, DATASET_DIGEST, RETURNS)
    path = tmp_path / stored.relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["returns"] = [9.0, 9.0, 9.0]
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(ResultStoreError, match="does not hash"):
        read_return_series(tmp_path, stored.digest)


def test_an_empty_series_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResultStoreError):
        write_return_series(tmp_path, TRIAL, DATASET_DIGEST, [])


def test_a_missing_or_malformed_digest_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ResultStoreError):
        read_return_series(tmp_path, "d" * 64)
    with pytest.raises(ResultStoreError):
        read_return_series(tmp_path, "short")
