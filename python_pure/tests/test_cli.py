from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from conftest import FIXTURE_ROOT, SCHEMA_ROOT, field_tolerance, fixture_families, load_json
from volarb_py.cli import VERBS, main

VERB_NAMES = sorted(VERBS)
EXACT_FIELDS = frozenset(
    {
        "id",
        "status",
        "iterations",
        "query_id",
        "contract_symbol",
        "expiry_date",
        "option_type",
        "contract_multiplier",
        "is_standard_deliverable",
        "event_time",
        "knowledge_time",
        "ingest_sequence",
        "bid_size",
        "ask_size",
    }
)


def every_fixture() -> list[tuple[str, str]]:
    return [(verb, family) for verb in VERB_NAMES for family in fixture_families(verb)]


def load_schema(schema_id: str) -> dict[str, Any]:
    filename = schema_id.replace("/v1", "") + ".schema.json"
    return load_json(SCHEMA_ROOT / filename)


def assert_matches_within_specified_tolerance(
    actual: Any, expected: Any, schema: str, field: str, context: str
) -> None:
    relative, absolute, exact = field_tolerance(schema, field)
    if exact or expected is None or isinstance(expected, str | bool):
        assert actual == expected, context
        return
    if math.isinf(expected):
        assert actual == expected, context
        return
    assert actual == pytest.approx(expected, rel=relative, abs=absolute), context


@pytest.mark.parametrize(("verb", "family"), every_fixture())
def test_fixture_inputs_and_outputs_match_their_schemas(verb: str, family: str) -> None:
    specification = VERBS[verb]
    for suffix, schema_id in (
        ("input", specification.input_schema),
        ("expected", specification.output_schema),
    ):
        document = load_json(FIXTURE_ROOT / verb / f"{family}.{suffix}.json")
        jsonschema.validate(document, load_schema(schema_id))


@pytest.mark.parametrize(("verb", "family"), every_fixture())
def test_track_reproduces_the_golden_fixture(verb: str, family: str) -> None:
    specification = VERBS[verb]
    request = load_json(FIXTURE_ROOT / verb / f"{family}.input.json")
    expected = load_json(FIXTURE_ROOT / verb / f"{family}.expected.json")

    produced = specification.transform_records(request["records"])
    assert len(produced) == len(expected["records"])

    for actual_record, expected_record in zip(produced, expected["records"], strict=True):
        assert actual_record["id"] == expected_record["id"]
        for field, expected_value in expected_record.items():
            context = f"{verb}/{family} {expected_record['id']} field {field}"
            assert_matches_within_specified_tolerance(
                actual_record[field], expected_value, specification.output_schema, field, context
            )


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


def test_output_is_written_as_valid_json_without_non_finite_literals(tmp_path: Path) -> None:
    input_path = FIXTURE_ROOT / "invert-implied-volatility" / "boundary.input.json"
    output_path = tmp_path / "out.json"
    assert main(["invert-implied-volatility", "--input", str(input_path), "--output", str(output_path)]) == 0

    raw = output_path.read_text(encoding="utf-8")
    assert "Infinity" not in raw
    assert "NaN" not in raw
    document = json.loads(raw)
    uncertainties = [record["volatility_uncertainty"] for record in document["records"]]
    assert None in uncertainties


def test_schema_mismatch_is_a_run_level_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wrong_input = tmp_path / "wrong.json"
    wrong_input.write_text(json.dumps({"schema": "pricing_request/v1", "records": []}), encoding="utf-8")
    output_path = tmp_path / "out.json"

    assert main(["invert-implied-volatility", "--input", str(wrong_input), "--output", str(output_path)]) == 1
    assert capsys.readouterr().err.startswith("error: ")
    assert not output_path.exists()


def test_missing_input_is_a_run_level_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(
            ["price-options", "--input", str(tmp_path / "absent.json"), "--output", str(tmp_path / "o.json")]
        )
        == 1
    )
    assert capsys.readouterr().err.startswith("error: ")


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
