#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workloads import implied_volatility_workload, pricing_workload

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TRACKS_PATH: Final[Path] = REPOSITORY_ROOT / "conformance" / "tracks.toml"
DEFAULT_RECORD_COUNTS: Final[tuple[int, ...]] = (20_000, 100_000, 400_000)
REPEATS: Final[int] = 3


@dataclass(frozen=True)
class Track:
    name: str
    command: list[str]
    built_when_present: Path


@dataclass(frozen=True)
class Measurement:
    record_count: int
    seconds: float


@dataclass(frozen=True)
class LinearFit:
    fixed_overhead_seconds: float
    nanoseconds_per_record: float


def load_tracks() -> list[Track]:
    with TRACKS_PATH.open("rb") as handle:
        configuration = tomllib.load(handle)
    return [
        Track(name, entry["command"], REPOSITORY_ROOT / entry["built_when_present"])
        for name, entry in sorted(configuration["tracks"].items())
    ]


def time_one_run(track: Track, verb: str, input_path: Path, output_path: Path) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        [*track.command, verb, "--input", str(input_path), "--output", str(output_path)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(f"{track.name} failed on {verb}: {completed.stderr.decode().strip()}")
    return elapsed


def fastest_of_repeats(track: Track, verb: str, input_path: Path, output_path: Path) -> float:
    return min(time_one_run(track, verb, input_path, output_path) for _ in range(REPEATS))


def fit_line(measurements: list[Measurement]) -> LinearFit:
    count = len(measurements)
    mean_records = sum(measurement.record_count for measurement in measurements) / count
    mean_seconds = sum(measurement.seconds for measurement in measurements) / count
    covariance = sum(
        (measurement.record_count - mean_records) * (measurement.seconds - mean_seconds)
        for measurement in measurements
    )
    variance = sum((measurement.record_count - mean_records) ** 2 for measurement in measurements)
    slope = covariance / variance if variance > 0 else 0.0
    return LinearFit(mean_seconds - slope * mean_records, slope * 1e9)


def write_document(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def build_workload_files(
    directory: Path, record_counts: tuple[int, ...], pricing_track: Track
) -> dict[str, dict[int, Path]]:
    workloads: dict[str, dict[int, Path]] = {"price-options": {}, "invert-implied-volatility": {}}
    for record_count in record_counts:
        pricing_path = directory / f"pricing_{record_count}.json"
        write_document(pricing_path, pricing_workload(record_count))
        workloads["price-options"][record_count] = pricing_path

        priced_path = directory / f"priced_{record_count}.json"
        time_one_run(pricing_track, "price-options", pricing_path, priced_path)
        priced_records = json.loads(priced_path.read_text(encoding="utf-8"))["records"]

        inversion_path = directory / f"inversion_{record_count}.json"
        write_document(inversion_path, implied_volatility_workload(record_count, priced_records))
        workloads["invert-implied-volatility"][record_count] = inversion_path
    return workloads


def render_table(verb: str, fits: dict[str, LinearFit], measurements: dict[str, list[Measurement]]) -> str:
    baseline = min(fit.nanoseconds_per_record for fit in fits.values())
    lines = [
        f"### `{verb}`",
        "",
        "| track | fixed overhead | ns per option | relative | largest run |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in sorted(fits):
        fit = fits[name]
        largest = max(measurements[name], key=lambda measurement: measurement.record_count)
        lines.append(
            f"| {name} | {fit.fixed_overhead_seconds * 1000:.0f} ms | "
            f"{fit.nanoseconds_per_record:.1f} | "
            f"{fit.nanoseconds_per_record / baseline:.2f}x | "
            f"{largest.record_count:,} in {largest.seconds:.2f} s |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="benchmarks")
    parser.add_argument("--records", type=int, nargs="+", default=list(DEFAULT_RECORD_COUNTS))
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    record_counts = tuple(sorted(arguments.records))
    tracks = [track for track in load_tracks() if track.built_when_present.exists()]
    if not tracks:
        print("no tracks are built", file=sys.stderr)
        return 1

    sections: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        workloads = build_workload_files(workspace, record_counts, tracks[0])
        output_path = workspace / "benchmark_output.json"

        for verb, inputs_by_count in workloads.items():
            measurements: dict[str, list[Measurement]] = {}
            fits: dict[str, LinearFit] = {}
            for track in tracks:
                track_measurements = [
                    Measurement(count, fastest_of_repeats(track, verb, path, output_path))
                    for count, path in sorted(inputs_by_count.items())
                ]
                measurements[track.name] = track_measurements
                fits[track.name] = fit_line(track_measurements)
            sections.append(render_table(verb, fits, measurements))

    report = "\n\n".join(sections)
    print(report)
    if arguments.output is not None:
        arguments.output.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
