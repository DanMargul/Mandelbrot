from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

MANIFEST_FILENAME: Final[str] = "manifest.json"
UNKNOWN_COMMIT: Final[str] = "unknown"
NO_DATASET: Final[str] = "none"
GIT_TIMEOUT_SECONDS: Final[float] = 30.0


class PinError(ValueError):
    pass


@dataclass(frozen=True)
class ResultPins:
    commit_sha: str
    working_tree_clean: bool
    dataset_digest: str
    config_hash: str
    seed: int


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_of_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def hash_of_configuration(configuration: Mapping[str, Any]) -> str:
    return hash_of_payload(dict(configuration))


def run_git(repository_root: Path, arguments: list[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise PinError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def current_commit_sha(repository_root: Path) -> str:
    return run_git(repository_root, ["rev-parse", "HEAD"])


def working_tree_is_clean(repository_root: Path) -> bool:
    return run_git(repository_root, ["status", "--porcelain"]) == ""


def dataset_digest_of(dataset_root: Path | None) -> str:
    if dataset_root is None:
        return NO_DATASET
    manifest_path = dataset_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise PinError(f"no {MANIFEST_FILENAME} under {dataset_root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = manifest.get("dataset_digest")
    if not isinstance(digest, str) or not digest:
        raise PinError(f"{manifest_path} carries no dataset_digest")
    return digest


def pins_for(
    repository_root: Path,
    configuration: Mapping[str, Any],
    seed: int,
    dataset_root: Path | None = None,
) -> ResultPins:
    return ResultPins(
        commit_sha=current_commit_sha(repository_root),
        working_tree_clean=working_tree_is_clean(repository_root),
        dataset_digest=dataset_digest_of(dataset_root),
        config_hash=hash_of_configuration(configuration),
        seed=seed,
    )


def pins_are_reproducible(pins: ResultPins) -> bool:
    return pins.working_tree_clean and pins.commit_sha != UNKNOWN_COMMIT


def reasons_pins_differ(left: ResultPins, right: ResultPins) -> list[str]:
    reasons: list[str] = []
    for field, description in (
        ("commit_sha", "the code is a different commit"),
        ("dataset_digest", "the data is a different dataset"),
        ("config_hash", "the configuration differs"),
        ("seed", "the seed differs"),
    ):
        if getattr(left, field) != getattr(right, field):
            reasons.append(f"{description}: {getattr(left, field)!r} against {getattr(right, field)!r}")
    if not left.working_tree_clean or not right.working_tree_clean:
        reasons.append("a working tree was dirty, so the commit does not pin the code")
    return reasons


def pins_as_payload(pins: ResultPins) -> dict[str, Any]:
    return asdict(pins)


def pins_from_payload(payload: Mapping[str, Any]) -> ResultPins:
    return ResultPins(
        commit_sha=str(payload["commit_sha"]),
        working_tree_clean=bool(payload["working_tree_clean"]),
        dataset_digest=str(payload["dataset_digest"]),
        config_hash=str(payload["config_hash"]),
        seed=int(payload["seed"]),
    )
