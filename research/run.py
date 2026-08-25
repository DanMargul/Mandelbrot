#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from registry import (
    TRIAL_STARTED,
    abandoned_trial_identifiers,
    read_entries,
    verify_registry,
)

EXIT_OK: Final[int] = 0
EXIT_BROKEN: Final[int] = 1


def report_verification(path: Path) -> int:
    verification = verify_registry(path)
    print(f"registry:           {path}")
    print(f"entries:            {verification.entry_count}")
    print(f"trials started:     {verification.trials_started}")
    print(f"trials completed:   {verification.trials_completed}")
    print(f"abandoned:          {len(abandoned_trial_identifiers(path))}")
    if verification.intact:
        print(f"chain:              intact, {verification.reason}")
        return EXIT_OK
    print(f"chain:              BROKEN at sequence {verification.first_broken_sequence}")
    print(f"reason:             {verification.reason}")
    return EXIT_BROKEN


def report_summary(path: Path) -> int:
    entries = read_entries(path)
    strategies = Counter(entry.strategy for entry in entries if entry.kind == TRIAL_STARTED)
    dirty = sum(
        1
        for entry in entries
        if entry.kind == TRIAL_STARTED and not entry.payload["pins"]["working_tree_clean"]
    )
    print(f"registry:           {path}")
    print("trials by strategy:")
    for strategy, count in sorted(strategies.items()):
        print(f"  {strategy:<40} {count}")
    print(f"trials run on a dirty working tree: {dirty}")
    return EXIT_OK


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="research")
    parser.add_argument("command", choices=["verify", "summarise"])
    parser.add_argument("--registry", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)
    if arguments.command == "verify":
        return report_verification(arguments.registry)
    return report_summary(arguments.registry)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
