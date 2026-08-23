from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from manifest import dataset_digest, sha256_of_file
from polygon import MissingApiKeyError, api_key_from_environment, replay_pages, rows_from_snapshot_pages
from synthetic import synthetic_rows
from writer import IngestionError, validate_rows, write_dataset

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RECORDED_DIRECTORY = REPOSITORY_ROOT / "spec" / "fixtures" / "recorded"
RECEIVED_AT = datetime(2026, 8, 21, 20, 5, 0, tzinfo=UTC)

QUOTED_CONTRACT_COUNT = 2
EXPECTED_STRIKE = 4800.0
EXPECTED_BID_PRICE = 101.2
EXPECTED_ASK_SIZE = 30
EXPECTED_OPEN_INTEREST = 4210
ADJUSTED_MULTIPLIER = 125
STANDARD_MULTIPLIER = 100


def recorded_rows() -> list[dict[str, object]]:
    return rows_from_snapshot_pages(replay_pages(RECORDED_DIRECTORY, "SPXTEST"), RECEIVED_AT)


def test_a_recorded_snapshot_maps_onto_the_canonical_schema() -> None:
    rows = recorded_rows()
    assert len(rows) == QUOTED_CONTRACT_COUNT
    first = rows[0]
    assert first["contract_symbol"] == "SPXTEST260918C04800000"
    assert first["underlying_symbol"] == "SPXTEST"
    assert first["strike"] == EXPECTED_STRIKE
    assert first["option_type"] == "call"
    assert first["bid_price"] == EXPECTED_BID_PRICE
    assert first["ask_size"] == EXPECTED_ASK_SIZE
    assert first["open_interest"] == EXPECTED_OPEN_INTEREST
    assert first["source"] == "polygon"


def test_the_ticker_prefix_is_stripped() -> None:
    assert all(not str(row["contract_symbol"]).startswith("O:") for row in recorded_rows())


def test_a_contract_without_a_quote_is_skipped_rather_than_defaulted() -> None:
    symbols = {row["contract_symbol"] for row in recorded_rows()}
    assert "SPXTEST260918C05000000" not in symbols


def test_a_non_standard_deliverable_is_flagged() -> None:
    adjusted = next(row for row in recorded_rows() if row["contract_multiplier"] == ADJUSTED_MULTIPLIER)
    assert adjusted["is_standard_deliverable"] is False
    standard = next(row for row in recorded_rows() if row["contract_multiplier"] == STANDARD_MULTIPLIER)
    assert standard["is_standard_deliverable"] is True


def test_knowledge_time_is_the_moment_of_receipt() -> None:
    assert all(row["knowledge_time"] == RECEIVED_AT for row in recorded_rows())


def test_event_time_never_exceeds_receipt_time() -> None:
    event_times = [row["event_time"] for row in recorded_rows()]
    assert all(isinstance(moment, datetime) and moment <= RECEIVED_AT for moment in event_times)


def test_ingest_sequence_is_unique_and_dense() -> None:
    sequences = [row["ingest_sequence"] for row in recorded_rows()]
    assert sequences == list(range(len(sequences)))


def test_a_row_knowable_before_it_happened_is_rejected() -> None:
    rows = recorded_rows()
    rows[0]["knowledge_time"] = datetime(2020, 1, 1, tzinfo=UTC)
    with pytest.raises(IngestionError, match="precedes event_time"):
        validate_rows(rows)


def test_a_standard_deliverable_with_a_strange_multiplier_is_rejected() -> None:
    rows = recorded_rows()
    rows[0]["contract_multiplier"] = 10
    with pytest.raises(IngestionError, match="standard deliverable"):
        validate_rows(rows)


def test_duplicate_ingest_sequences_are_rejected() -> None:
    rows = recorded_rows()
    rows[1]["ingest_sequence"] = rows[0]["ingest_sequence"]
    with pytest.raises(IngestionError, match="unique"):
        validate_rows(rows)


def test_a_missing_api_key_is_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError, match="--source recorded"):
        api_key_from_environment()


def test_writing_the_same_rows_twice_produces_the_same_bytes(tmp_path: Path) -> None:
    rows = synthetic_rows()
    created_at = max(row["knowledge_time"] for row in rows)
    first = write_dataset(tmp_path / "one", rows, "synthetic", created_at)
    second = write_dataset(tmp_path / "two", rows, "synthetic", created_at)
    assert dataset_digest(first) == dataset_digest(second)
    assert (tmp_path / "one" / "manifest.json").read_text() == (
        tmp_path / "two" / "manifest.json"
    ).read_text()


def test_the_committed_fixture_dataset_matches_its_manifest() -> None:
    dataset_root = REPOSITORY_ROOT / "spec" / "fixtures" / "datasets" / "synthetic_chain"
    manifest = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    for partition in manifest["partitions"]:
        assert sha256_of_file(dataset_root / partition["relative_path"]) == partition["content_hash"]
