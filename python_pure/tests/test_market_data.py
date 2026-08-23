from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import REPOSITORY_ROOT
from volarb_py.market_data import (
    ChainQuery,
    ContractQuote,
    CorruptDatasetError,
    KnowledgeHorizon,
    LookaheadRequestedError,
    chain_sort_key,
    format_canonical_date,
    format_canonical_timestamp,
    open_chain_dataset,
    parse_canonical_timestamp,
)

DATASET_ROOT = REPOSITORY_ROOT / "spec" / "fixtures" / "datasets" / "synthetic_chain"
CORRECTION_TARGET = "SPX260918C04800000"
SHA256_HEX_LENGTH = 64
LATE_LISTING = "SPX260918C05520000"


def moment(hour: int, minute: int = 0, day: int = 21) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def chain(horizon: datetime, observation: datetime, include_adjusted: bool = False) -> list[ContractQuote]:
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(horizon))
    return reader.chain_as_of(ChainQuery("SPX", observation, include_adjusted))


def find(quotes: list[ContractQuote], symbol: str) -> ContractQuote | None:
    return next((quote for quote in quotes if quote.contract_symbol == symbol), None)


def test_canonical_timestamps_round_trip() -> None:
    text = "2026-08-21T16:30:45.123456Z"
    assert format_canonical_timestamp(parse_canonical_timestamp(text)) == text
    assert parse_canonical_timestamp("2026-08-21T16:30:45Z") == moment(16, 30).replace(second=45)
    assert format_canonical_date(datetime(2026, 8, 21).date()) == "2026-08-21"


def test_a_correction_is_invisible_below_its_knowledge_time() -> None:
    before = find(chain(moment(17), moment(16)), CORRECTION_TARGET)
    after = find(chain(moment(18), moment(16)), CORRECTION_TARGET)
    assert before is not None
    assert after is not None
    assert before.bid_price != after.bid_price
    assert before.knowledge_time < after.knowledge_time
    assert before.event_time == after.event_time


def test_a_later_listing_is_absent_from_earlier_observations() -> None:
    assert find(chain(moment(17), moment(16)), LATE_LISTING) is None
    assert find(chain(moment(17), moment(17)), LATE_LISTING) is not None


def test_adjusted_contracts_are_excluded_unless_requested() -> None:
    standard_only = chain(moment(17), moment(17))
    with_adjusted = chain(moment(17), moment(17), include_adjusted=True)
    assert len(with_adjusted) > len(standard_only)
    assert all(quote.is_standard_deliverable for quote in standard_only)
    assert any(not quote.is_standard_deliverable for quote in with_adjusted)


def test_raising_the_horizon_never_removes_a_contract() -> None:
    narrow = {quote.contract_symbol for quote in chain(moment(17), moment(17))}
    wide = {quote.contract_symbol for quote in chain(moment(12, day=22), moment(17))}
    assert narrow <= wide


def test_advancing_the_horizon_can_replace_a_row_with_a_newer_revision() -> None:
    same_day = find(chain(moment(17), moment(17)), CORRECTION_TARGET)
    next_morning = find(chain(moment(12, day=22), moment(17)), CORRECTION_TARGET)
    assert same_day is not None
    assert next_morning is not None
    assert next_morning.knowledge_time > same_day.knowledge_time
    assert next_morning.event_time == same_day.event_time


def test_no_returned_row_is_past_the_observation_time() -> None:
    for observation in (moment(15), moment(16), moment(17)):
        for quote in chain(moment(12, day=22), observation):
            assert quote.event_time <= observation


def test_no_returned_row_is_past_the_knowledge_horizon() -> None:
    for horizon in (moment(15), moment(17), moment(18), moment(12, day=22)):
        for quote in chain(horizon, moment(15)):
            assert quote.knowledge_time <= horizon


def test_lookahead_is_rejected_rather_than_filtered() -> None:
    with pytest.raises(LookaheadRequestedError, match="past knowledge horizon"):
        chain(moment(16), moment(17))


def test_an_absent_underlying_is_empty_rather_than_an_error() -> None:
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(moment(17)))
    assert reader.chain_as_of(ChainQuery("NVDA", moment(17))) == []


def test_a_missing_dataset_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(CorruptDatasetError, match=r"no manifest\.json"):
        open_chain_dataset(tmp_path / "absent", KnowledgeHorizon(moment(17)))


def test_results_are_totally_ordered() -> None:
    quotes = chain(moment(17), moment(17))
    keys = [chain_sort_key(quote) for quote in quotes]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_the_reader_exposes_the_dataset_digest_for_pinning() -> None:
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(moment(17)))
    assert len(reader.dataset_digest) == SHA256_HEX_LENGTH
    assert reader.knowledge_horizon == moment(17)


def test_the_reader_offers_no_way_to_bypass_the_horizon() -> None:
    reader = open_chain_dataset(DATASET_ROOT, KnowledgeHorizon(moment(17)))
    public_operations = {name for name in dir(reader) if not name.startswith("_")}
    assert public_operations == {"chain_as_of", "dataset_digest", "knowledge_horizon"}
