from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from manifest import dataset_digest, sha256_of_file
from polygon import (
    AMERICAN_STYLE,
    CROSSED_QUOTE,
    EUROPEAN_STYLE,
    INCOMPLETE_QUOTE,
    MISSING_QUOTE,
    MISSING_UNDERLYING_PRICE,
    NON_POSITIVE_ASK,
    MissingApiKeyError,
    api_key_from_environment,
    contract_row_from_snapshot,
    exercise_style_for,
    mapped_snapshot_pages,
    quote_rejection,
    rejection_reason,
    replay_pages,
    rows_from_snapshot_pages,
)
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


def index_pages(underlying_ticker: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = json.loads(json.dumps(replay_pages(RECORDED_DIRECTORY, "SPXTEST")))
    for page in pages:
        for entry in page["results"]:
            if "details" in entry:
                entry["details"]["underlying_ticker"] = underlying_ticker
    return pages


def test_recorded_rows_write_through_to_a_dataset(tmp_path: Path) -> None:
    rows = recorded_rows()
    partitions = write_dataset(tmp_path / "recorded", rows, "recorded", RECEIVED_AT)
    assert sum(partition.row_count for partition in partitions) == len(rows)


def test_every_row_carries_an_exercise_style() -> None:
    for row in recorded_rows():
        assert row["exercise_style"] in {EUROPEAN_STYLE, AMERICAN_STYLE}


@pytest.mark.parametrize(
    ("underlying_ticker", "expected"),
    [
        ("I:SPX", EUROPEAN_STYLE),
        ("SPX", EUROPEAN_STYLE),
        ("SPXW", EUROPEAN_STYLE),
        ("XSP", EUROPEAN_STYLE),
        ("VIX", EUROPEAN_STYLE),
        ("I:SOMETHINGNEW", EUROPEAN_STYLE),
        ("OEX", AMERICAN_STYLE),
        ("I:OEX", AMERICAN_STYLE),
        ("AAPL", AMERICAN_STYLE),
        ("SPY", AMERICAN_STYLE),
        ("QQQ", AMERICAN_STYLE),
    ],
)
def test_the_exercise_style_follows_the_underlying(underlying_ticker: str, expected: str) -> None:
    assert exercise_style_for(underlying_ticker) == expected


def test_the_american_index_exception_beats_the_index_prefix() -> None:
    assert exercise_style_for("I:OEX") == AMERICAN_STYLE
    assert exercise_style_for("I:XEO") == EUROPEAN_STYLE


def test_an_index_underlying_loses_its_feed_prefix() -> None:
    rows = rows_from_snapshot_pages(index_pages("I:SPX"), RECEIVED_AT)
    assert rows
    for row in rows:
        assert row["underlying_symbol"] == "SPX"
        assert row["exercise_style"] == EUROPEAN_STYLE


def test_an_index_chain_writes_through_to_a_dataset(tmp_path: Path) -> None:
    rows = rows_from_snapshot_pages(index_pages("I:SPX"), RECEIVED_AT)
    partitions = write_dataset(tmp_path / "index", rows, "recorded", RECEIVED_AT)
    assert partitions[0].underlying_symbol == "SPX"


def test_a_rejected_contract_is_counted_with_its_reason() -> None:
    mapped = mapped_snapshot_pages(replay_pages(RECORDED_DIRECTORY, "SPXTEST"), RECEIVED_AT)
    assert mapped.rejected[MISSING_QUOTE] == 1
    assert len(mapped.rows) == QUOTED_CONTRACT_COUNT


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ({"bid": 1.0, "ask": 1.2}, None),
        ({"bid": 0.0, "ask": 0.05}, None),
        ({"ask": 1.2}, INCOMPLETE_QUOTE),
        ({"bid": 1.0}, INCOMPLETE_QUOTE),
        ({"bid": 0.0, "ask": 0.0}, NON_POSITIVE_ASK),
        ({"bid": 1.5, "ask": 1.2}, CROSSED_QUOTE),
    ],
)
def test_a_quote_is_judged_before_it_becomes_a_row(quote: dict[str, float], expected: str | None) -> None:
    assert quote_rejection(quote) == expected


def test_a_zero_bid_is_a_market_and_not_a_defect() -> None:
    entry = {
        "details": {
            "ticker": "O:AAPL260918C00200000",
            "underlying_ticker": "AAPL",
            "expiration_date": "2026-09-18",
            "strike_price": 200,
            "contract_type": "call",
            "shares_per_contract": 100,
        },
        "last_quote": {"bid": 0.0, "ask": 0.05, "bid_size": 0, "ask_size": 40},
        "underlying_asset": {"price": 190.0},
    }
    row = contract_row_from_snapshot(entry, RECEIVED_AT, 0)
    assert row is not None
    assert row["bid_price"] == 0.0
    assert row["exercise_style"] == AMERICAN_STYLE


def test_a_missing_underlying_price_is_rejected_rather_than_defaulted() -> None:
    entry = {"details": {"ticker": "O:X"}, "last_quote": {"bid": 1.0, "ask": 1.2}}
    assert rejection_reason(entry) == MISSING_UNDERLYING_PRICE
    assert contract_row_from_snapshot(entry, RECEIVED_AT, 0) is None
