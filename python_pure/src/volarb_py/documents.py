from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from volarb_py.pricing import OptionType

JsonRecord = dict[str, Any]


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class Document:
    schema: str
    records: list[JsonRecord]


def read_document(path: Path, expected_schema: str) -> Document:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DocumentError(f"{path}: top level value must be an object")
    schema = payload.get("schema")
    if schema != expected_schema:
        raise DocumentError(f"{path}: expected schema {expected_schema!r}, found {schema!r}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise DocumentError(f"{path}: records must be an array")
    return Document(schema=expected_schema, records=[validated_record(record, path) for record in records])


def validated_record(record: object, path: Path) -> JsonRecord:
    if not isinstance(record, dict):
        raise DocumentError(f"{path}: every record must be an object")
    return record


def write_document(path: Path, document: Document) -> None:
    payload = {"schema": document.schema, "records": document.records}
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def json_safe_float(value: float) -> float | None:
    return value if math.isfinite(value) else None


def required_string(record: JsonRecord, field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        raise DocumentError(f"field {field!r} must be a string, found {value!r}")
    return value


def required_float(record: JsonRecord, field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DocumentError(f"field {field!r} must be a number, found {value!r}")
    return float(value)


def required_integer(record: JsonRecord, field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentError(f"field {field!r} must be an integer, found {value!r}")
    return value


def optional_boolean(record: JsonRecord, field: str, fallback: bool) -> bool:
    value = record.get(field, fallback)
    if not isinstance(value, bool):
        raise DocumentError(f"field {field!r} must be a boolean, found {value!r}")
    return value


def optional_float(record: JsonRecord, field: str) -> float | None:
    value = record.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DocumentError(f"field {field!r} must be a number, found {value!r}")
    return float(value)


def required_option_type(record: JsonRecord, field: str) -> OptionType:
    value = required_string(record, field)
    if value == "call":
        return "call"
    if value == "put":
        return "put"
    raise DocumentError(f"field {field!r} must be 'call' or 'put', found {value!r}")
