from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TOLERANCES_PATH: Final[Path] = REPOSITORY_ROOT / "spec" / "tolerances.toml"


@dataclass(frozen=True)
class FieldTolerance:
    relative: float
    absolute: float
    exact: bool


@dataclass(frozen=True)
class Difference:
    record_id: str
    field: str
    left: Any
    right: Any
    detail: str

    def render(self) -> str:
        return f"{self.record_id}.{self.field}: {self.left!r} vs {self.right!r} ({self.detail})"


def load_tolerances() -> dict[str, Any]:
    with TOLERANCES_PATH.open("rb") as handle:
        return tomllib.load(handle)


def tolerance_for(tolerances: dict[str, Any], schema: str, field: str) -> FieldTolerance:
    defaults = tolerances["defaults"]
    entry = tolerances.get(schema, {}).get(field, {})
    return FieldTolerance(
        relative=float(entry.get("relative", defaults["relative"])),
        absolute=float(entry.get("absolute", defaults["absolute"])),
        exact=bool(entry.get("exact", False)),
    )


def requires_exact_comparison(left: Any, right: Any, tolerance: FieldTolerance) -> bool:
    return tolerance.exact or left is None or right is None or isinstance(left, str) or isinstance(right, str)


def numbers_agree(left: float, right: float, tolerance: FieldTolerance) -> tuple[bool, str]:
    if math.isnan(left) or math.isnan(right):
        return False, "not a number"
    if left == right:
        return True, "identical"
    difference = abs(left - right)
    if difference <= tolerance.absolute:
        return True, "within absolute tolerance"
    relative_difference = difference / max(abs(left), abs(right))
    if relative_difference <= tolerance.relative:
        return True, "within relative tolerance"
    return False, f"absolute {difference:.3e}, relative {relative_difference:.3e}"


def values_agree(left: Any, right: Any, tolerance: FieldTolerance) -> tuple[bool, str]:
    if requires_exact_comparison(left, right, tolerance):
        return left == right, "exact comparison"
    return numbers_agree(float(left), float(right), tolerance)


def index_records_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in document["records"]}


def compare_documents(
    left: dict[str, Any], right: dict[str, Any], schema: str, tolerances: dict[str, Any]
) -> list[Difference]:
    left_records = index_records_by_id(left)
    right_records = index_records_by_id(right)

    differences: list[Difference] = []
    for missing in sorted(set(left_records) - set(right_records)):
        differences.append(Difference(missing, "*", "present", "absent", "record missing"))
    for extra in sorted(set(right_records) - set(left_records)):
        differences.append(Difference(extra, "*", "absent", "present", "unexpected record"))

    for record_id in sorted(set(left_records) & set(right_records)):
        left_record = left_records[record_id]
        right_record = right_records[record_id]
        for field in sorted(set(left_record) | set(right_record)):
            tolerance = tolerance_for(tolerances, schema, field)
            agree, detail = values_agree(left_record.get(field), right_record.get(field), tolerance)
            if not agree:
                differences.append(
                    Difference(record_id, field, left_record.get(field), right_record.get(field), detail)
                )
    return differences
