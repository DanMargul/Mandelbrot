#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polygon import (
    POLYGON_SOURCE,
    api_key_from_environment,
    record_pages,
    replay_pages,
    rows_from_snapshot_pages,
    snapshot_pages,
)
from synthetic import SYNTHETIC_SOURCE, synthetic_rows
from writer import write_dataset

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_RECORDED_DIRECTORY: Final[Path] = REPOSITORY_ROOT / "spec" / "fixtures" / "recorded"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ingest")
    parser.add_argument("--source", choices=[SYNTHETIC_SOURCE, "recorded", POLYGON_SOURCE], required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--underlying", action="append", default=[])
    parser.add_argument("--recorded-directory", type=Path, default=DEFAULT_RECORDED_DIRECTORY)
    parser.add_argument("--record-to", type=Path)
    return parser.parse_args()


def rows_from_recorded(directory: Path, underlyings: list[str]) -> list[dict[str, Any]]:
    received_at = datetime.now(tz=UTC)
    rows: list[dict[str, Any]] = []
    for symbol in underlyings:
        rows.extend(rows_from_snapshot_pages(replay_pages(directory, symbol), received_at, len(rows)))
    return rows


def rows_from_polygon(underlyings: list[str], record_to: Path | None) -> list[dict[str, Any]]:
    api_key = api_key_from_environment()
    rows: list[dict[str, Any]] = []
    for symbol in underlyings:
        received_at = datetime.now(tz=UTC)
        pages = snapshot_pages(symbol, api_key)
        if record_to is not None:
            record_pages(record_to, symbol, pages)
        rows.extend(rows_from_snapshot_pages(pages, received_at, len(rows)))
    return rows


def creation_time_for(source: str, rows: list[dict[str, Any]]) -> datetime:
    if source != SYNTHETIC_SOURCE:
        return datetime.now(tz=UTC)
    latest: datetime = max(row["knowledge_time"] for row in rows)
    return latest


def collect_rows(arguments: argparse.Namespace) -> tuple[list[dict[str, Any]], str]:
    if arguments.source == SYNTHETIC_SOURCE:
        return synthetic_rows(), SYNTHETIC_SOURCE
    if not arguments.underlying:
        raise SystemExit("error: --underlying is required unless --source synthetic")
    if arguments.source == "recorded":
        return rows_from_recorded(arguments.recorded_directory, arguments.underlying), "recorded"
    return rows_from_polygon(arguments.underlying, arguments.record_to), POLYGON_SOURCE


def main() -> int:
    arguments = parse_arguments()
    rows, source = collect_rows(arguments)
    if not rows:
        print("error: no rows ingested", file=sys.stderr)
        return 1
    partitions = write_dataset(arguments.dataset_root, rows, source, creation_time_for(source, rows))
    total_rows = sum(partition.row_count for partition in partitions)
    print(f"{arguments.dataset_root}: {total_rows} rows across {len(partitions)} partitions")
    for partition in partitions:
        print(f"  {partition.relative_path}  {partition.row_count:>6} rows  {partition.content_hash[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
