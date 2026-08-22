from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "spec" / "fixtures"
SCHEMA_ROOT = REPOSITORY_ROOT / "spec" / "schemas"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_families(verb: str) -> list[str]:
    return sorted(
        path.name.removesuffix(".input.json") for path in (FIXTURE_ROOT / verb).glob("*.input.json")
    )
