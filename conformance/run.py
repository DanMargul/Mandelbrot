#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comparison import Difference, compare_documents, load_tolerances

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FIXTURE_ROOT: Final[Path] = REPOSITORY_ROOT / "spec" / "fixtures"
TRACKS_PATH: Final[Path] = Path(__file__).resolve().parent / "tracks.toml"
RUN_TIMEOUT_SECONDS: Final[float] = 300.0


@dataclass(frozen=True)
class Track:
    name: str
    command: list[str]
    built_when_present: Path


@dataclass(frozen=True)
class Fixture:
    verb: str
    family: str
    input_path: Path
    expected_path: Path


@dataclass(frozen=True)
class TrackState:
    track: Track
    condition: str
    failure: str | None


@dataclass(frozen=True)
class ComparisonSettings:
    schema: str
    tolerances: dict[str, Any]
    maximum_differences_reported: int


@dataclass
class Report:
    ready_tracks: list[str] = field(default_factory=list)
    missing_tracks: list[str] = field(default_factory=list)
    checks_run: int = 0
    failures: list[str] = field(default_factory=list)


def load_configuration() -> tuple[dict[str, Track], dict[str, dict[str, str]]]:
    with TRACKS_PATH.open("rb") as handle:
        configuration = tomllib.load(handle)
    tracks = {
        name: Track(name, entry["command"], REPOSITORY_ROOT / entry["built_when_present"])
        for name, entry in configuration["tracks"].items()
    }
    return tracks, configuration["verbs"]


def probe_track(track: Track) -> str | None:
    probe = subprocess.run(
        [*track.command, "--help"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        timeout=RUN_TIMEOUT_SECONDS,
        check=False,
    )
    if probe.returncode != 0:
        return probe.stderr.decode().strip().splitlines()[-1] if probe.stderr else "probe exited non-zero"
    expected_name = Path(track.command[-1]).name.encode()
    if expected_name not in probe.stdout:
        return f"probe output does not mention {expected_name.decode()}"
    return None


def classify_track(track: Track) -> TrackState:
    if not track.built_when_present.exists():
        return TrackState(track, "missing", None)
    failure = probe_track(track)
    if failure is not None:
        return TrackState(track, "broken", failure)
    return TrackState(track, "ready", None)


def discover_fixtures(verbs: dict[str, dict[str, str]], selected_verb: str | None) -> list[Fixture]:
    fixtures: list[Fixture] = []
    for verb in sorted(verbs):
        if selected_verb is not None and verb != selected_verb:
            continue
        for input_path in sorted((FIXTURE_ROOT / verb).glob("*.input.json")):
            family = input_path.name.removesuffix(".input.json")
            expected_path = input_path.with_name(f"{family}.expected.json")
            if expected_path.exists():
                fixtures.append(Fixture(verb, family, input_path, expected_path))
    return fixtures


def run_track_on_fixture(track: Track, fixture: Fixture, output_path: Path) -> str | None:
    completed = subprocess.run(
        [*track.command, fixture.verb, "--input", str(fixture.input_path), "--output", str(output_path)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        timeout=RUN_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        return completed.stderr.decode().strip() or f"exit status {completed.returncode}"
    if not output_path.exists():
        return "no output file written"
    return None


def load_json(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def render_differences(label: str, differences: list[Difference], limit: int) -> str:
    lines = [f"{label}: {len(differences)} differing field(s)"]
    lines.extend(f"    {difference.render()}" for difference in differences[:limit])
    if len(differences) > limit:
        lines.append(f"    ... {len(differences) - limit} more")
    return "\n".join(lines)


def check_fixture(
    fixture: Fixture, tracks: list[Track], settings: ComparisonSettings, report: Report
) -> None:
    expected = load_json(fixture.expected_path)
    produced: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory() as directory:
        for track in tracks:
            output_path = Path(directory) / f"{track.name}.json"
            failure = run_track_on_fixture(track, fixture, output_path)
            if failure is not None:
                report.failures.append(f"{track.name} {fixture.verb}/{fixture.family}: {failure}")
                continue
            produced[track.name] = load_json(output_path)

        for name, document in produced.items():
            record_comparison(
                f"{name} vs golden {fixture.verb}/{fixture.family}", expected, document, settings, report
            )

        for left, right in pairwise(sorted(produced)):
            record_comparison(
                f"{left} vs {right} {fixture.verb}/{fixture.family}",
                produced[left],
                produced[right],
                settings,
                report,
            )


def record_comparison(
    label: str,
    left: dict[str, Any],
    right: dict[str, Any],
    settings: ComparisonSettings,
    report: Report,
) -> None:
    report.checks_run += 1
    differences = compare_documents(left, right, settings.schema, settings.tolerances)
    if differences:
        report.failures.append(render_differences(label, differences, settings.maximum_differences_reported))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="conformance")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--verb")
    parser.add_argument("--track", action="append")
    parser.add_argument("--max-differences", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    all_tracks, verbs = load_configuration()
    tolerances = load_tolerances()

    selected = arguments.track or sorted(all_tracks)
    report = Report()
    runnable: list[Track] = []
    for name in selected:
        state = classify_track(all_tracks[name])
        if state.condition == "ready":
            runnable.append(state.track)
            report.ready_tracks.append(name)
        elif state.condition == "missing":
            report.missing_tracks.append(name)
        else:
            report.failures.append(f"{name}: present but not runnable: {state.failure}")

    fixtures = discover_fixtures(verbs, arguments.verb)
    for fixture in fixtures:
        settings = ComparisonSettings(
            schema=verbs[fixture.verb]["output_schema"],
            tolerances=tolerances,
            maximum_differences_reported=arguments.max_differences,
        )
        check_fixture(fixture, runnable, settings, report)

    print(f"tracks ready:       {', '.join(report.ready_tracks) or 'none'}")
    if report.missing_tracks:
        print(f"tracks not built:   {', '.join(report.missing_tracks)}")
    print(f"fixtures:           {len(fixtures)}")
    print(f"comparisons:        {report.checks_run}")

    if report.failures:
        print(f"\n{len(report.failures)} failure(s):\n", file=sys.stderr)
        for failure in report.failures:
            print(failure, file=sys.stderr)
        return 1

    if not runnable:
        print("\nno tracks were runnable; nothing was verified", file=sys.stderr)
        return 1

    print("\nconformance passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
