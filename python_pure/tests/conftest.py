from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "spec" / "fixtures"
SCHEMA_ROOT = REPOSITORY_ROOT / "spec" / "schemas"
TOLERANCES_PATH = REPOSITORY_ROOT / "spec" / "tolerances.toml"


def load_tolerances() -> dict[str, Any]:
    with TOLERANCES_PATH.open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
    return loaded


TOLERANCES = load_tolerances()


def field_tolerance(schema: str, field: str) -> tuple[float, float, bool]:
    defaults = TOLERANCES["defaults"]
    entry = TOLERANCES.get(schema, {}).get(field, {})
    return (
        float(entry.get("relative", defaults["relative"])),
        float(entry.get("absolute", defaults["absolute"])),
        bool(entry.get("exact", False)),
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_families(verb: str) -> list[str]:
    return sorted(
        path.name.removesuffix(".input.json") for path in (FIXTURE_ROOT / verb).glob("*.input.json")
    )


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    return FIXTURE_ROOT


@pytest.fixture(scope="session")
def schema_root() -> Path:
    return SCHEMA_ROOT
