from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from conftest import FIXTURE_ROOT, SCHEMA_ROOT, fixture_families, load_json
from volarb_cpp.cli import VERBS, main

VERB_NAMES = sorted(VERBS)
EXACT_FIELDS = frozenset({"id", "status", "iterations"})


def every_fixture() -> list[tuple[str, str]]:
    return [(verb, family) for verb in VERB_NAMES for family in fixture_families(verb)]


def load_schema(schema_id: str) -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / (schema_id.replace("/v1", "") + ".schema.json"))


def assert_numerically_equal(actual: Any, expected: Any, context: str) -> None:
    if expected is None or isinstance(expected, str | bool):
        assert actual == expected, context
        return
    if math.isinf(expected) or expected == 0.0:
        assert actual == expected, context
        return
    assert actual == pytest.approx(expected, rel=1e-15, abs=1e-300), context


@pytest.mark.parametrize(("verb", "family"), every_fixture())
def test_fixture_documents_match_their_schemas(verb: str, family: str) -> None:
    specification = VERBS[verb]
    for suffix, schema_id in (
        ("input", specification.input_schema),
        ("expected", specification.output_schema),
    ):
        jsonschema.validate(
            load_json(FIXTURE_ROOT / verb / f"{family}.{suffix}.json"), load_schema(schema_id)
        )


@pytest.mark.parametrize(("verb", "family"), every_fixture())
def test_track_reproduces_the_golden_fixture(verb: str, family: str) -> None:
    specification = VERBS[verb]
    request = load_json(FIXTURE_ROOT / verb / f"{family}.input.json")
    expected = load_json(FIXTURE_ROOT / verb / f"{family}.expected.json")

    produced = [specification.transform_record(record) for record in request["records"]]
    for actual_record, expected_record in zip(produced, expected["records"], strict=True):
        for field, expected_value in expected_record.items():
            context = f"{verb}/{family} {expected_record['id']} field {field}"
            if field in EXACT_FIELDS:
                assert actual_record[field] == expected_value, context
            else:
                assert_numerically_equal(actual_record[field], expected_value, context)


@pytest.mark.parametrize(("verb", "family"), every_fixture())
def test_command_line_round_trip(verb: str, family: str, tmp_path: Path) -> None:
    input_path = FIXTURE_ROOT / verb / f"{family}.input.json"
    output_path = tmp_path / "out.json"
    assert main([verb, "--input", str(input_path), "--output", str(output_path)]) == 0
    produced = load_json(output_path)
    expected = load_json(FIXTURE_ROOT / verb / f"{family}.expected.json")
    assert produced["schema"] == expected["schema"]
    assert [record["id"] for record in produced["records"]] == [
        record["id"] for record in expected["records"]
    ]


def test_output_has_no_non_finite_literals(tmp_path: Path) -> None:
    input_path = FIXTURE_ROOT / "invert-implied-volatility" / "boundary.input.json"
    output_path = tmp_path / "out.json"
    assert main(["invert-implied-volatility", "--input", str(input_path), "--output", str(output_path)]) == 0
    raw = output_path.read_text(encoding="utf-8")
    assert "Infinity" not in raw
    assert "NaN" not in raw
    assert None in [record["volatility_uncertainty"] for record in json.loads(raw)["records"]]


def test_schema_mismatch_is_a_run_level_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wrong_input = tmp_path / "wrong.json"
    wrong_input.write_text(json.dumps({"schema": "pricing_request/v1", "records": []}), encoding="utf-8")
    output_path = tmp_path / "out.json"
    assert main(["invert-implied-volatility", "--input", str(wrong_input), "--output", str(output_path)]) == 1
    assert capsys.readouterr().err.startswith("error: ")
    assert not output_path.exists()


def test_precondition_violation_is_a_run_level_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_input = tmp_path / "bad.json"
    bad_input.write_text(
        json.dumps(
            {
                "schema": "pricing_request/v1",
                "records": [
                    {
                        "id": "negative_expiry",
                        "forward": 100.0,
                        "strike": 100.0,
                        "years_to_expiry": -1.0,
                        "volatility": 0.2,
                        "discount_factor": 1.0,
                        "option_type": "call",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "out.json"
    assert main(["price-options", "--input", str(bad_input), "--output", str(output_path)]) == 1
    assert capsys.readouterr().err.startswith("error: ")
    assert not output_path.exists()
