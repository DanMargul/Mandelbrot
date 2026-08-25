from __future__ import annotations

import json
from pathlib import Path

import pytest
from pins import (
    NO_DATASET,
    PinError,
    ResultPins,
    dataset_digest_of,
    hash_of_configuration,
    pins_are_reproducible,
    pins_as_payload,
    pins_for,
    pins_from_payload,
    reasons_pins_differ,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMIT_SHA_LENGTH = 40
TEST_SEED = 7
DIFFERING_PIN_COUNT = 4


def test_the_configuration_hash_ignores_key_order() -> None:
    left = hash_of_configuration({"window": 60, "factors": 3, "half_life": 20})
    right = hash_of_configuration({"half_life": 20, "factors": 3, "window": 60})
    assert left == right


def test_the_configuration_hash_separates_different_values() -> None:
    assert hash_of_configuration({"window": 60}) != hash_of_configuration({"window": 61})
    assert hash_of_configuration({"window": 60}) != hash_of_configuration({"window": "60"})


def test_a_missing_dataset_is_named_rather_than_left_empty() -> None:
    assert dataset_digest_of(None) == NO_DATASET


def test_a_dataset_without_a_manifest_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PinError):
        dataset_digest_of(tmp_path)


def test_a_manifest_digest_is_read_back(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"dataset_digest": "c" * 64}), encoding="utf-8")
    assert dataset_digest_of(tmp_path) == "c" * 64


def test_a_manifest_without_a_digest_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"partitions": []}), encoding="utf-8")
    with pytest.raises(PinError):
        dataset_digest_of(tmp_path)


def test_pins_are_taken_from_the_repository() -> None:
    pins = pins_for(REPOSITORY_ROOT, {"window": 60}, seed=TEST_SEED)
    assert len(pins.commit_sha) == COMMIT_SHA_LENGTH
    assert pins.seed == TEST_SEED
    assert pins.dataset_digest == NO_DATASET
    assert pins.config_hash == hash_of_configuration({"window": 60})


def test_a_dirty_working_tree_is_not_reproducible() -> None:
    clean = ResultPins("a" * 40, True, NO_DATASET, "h", 1)
    dirty = ResultPins("a" * 40, False, NO_DATASET, "h", 1)
    assert pins_are_reproducible(clean)
    assert not pins_are_reproducible(dirty)


def test_a_dirty_tree_is_reported_even_when_every_pin_matches() -> None:
    dirty = ResultPins("a" * 40, False, NO_DATASET, "h", 1)
    reasons = reasons_pins_differ(dirty, dirty)
    assert len(reasons) == 1
    assert "does not pin the code" in reasons[0]


def test_matching_pins_have_nothing_to_report() -> None:
    clean = ResultPins("a" * 40, True, "d" * 64, "h", 1)
    assert reasons_pins_differ(clean, clean) == []


def test_each_differing_pin_is_named() -> None:
    left = ResultPins("a" * 40, True, "d" * 64, "h", 1)
    right = ResultPins("b" * 40, True, "e" * 64, "g", 2)
    reasons = reasons_pins_differ(left, right)
    assert len(reasons) == DIFFERING_PIN_COUNT


def test_pins_survive_a_round_trip_through_their_payload() -> None:
    pins = ResultPins("a" * 40, False, "d" * 64, "h", 11)
    assert pins_from_payload(pins_as_payload(pins)) == pins
