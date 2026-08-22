# Runbook

## Bootstrap

```sh
tools/bootstrap.sh
```

Installs `cmake` and `ninja` via Homebrew, clones and bootstraps vcpkg into `~/vcpkg` if
`VCPKG_ROOT` is unset, syncs both `uv` projects, and configures the CMake release preset.
It is idempotent; rerun it whenever dependencies change.

### Why the Python tracks are installed non-editable

`tools/sync_python_tracks.sh` installs each track with `--no-editable` and an explicit
`--reinstall-package`, and everything downstream runs `uv run --no-sync`. That combination
looks fussy, so it is worth recording why each piece is there.

An editable install works through a `.pth` file in `site-packages`. On macOS, uv marks
those files with the `UF_HIDDEN` flag, and CPython 3.13 skips `.pth` files that are hidden.
The result is an editable install that is present and correct on disk and simply never
takes effect. The only symptom is `ModuleNotFoundError` from the console script, which
looks exactly like a packaging mistake and leads nowhere:

```sh
ls -lO .venv/lib/python3.13/site-packages/*.pth   # shows the "hidden" flag
python -X importtime -c pass 2>&1 | grep pth      # "Skipping hidden .pth file"
```

Clearing the flag with `chflags nohidden` fixes it until the next `uv` invocation quietly
reapplies it, so the workaround does not hold. `--no-editable` avoids `.pth` entirely by
copying the package into `site-packages`.

That introduces the opposite hazard: `uv sync` does not notice a source edit, so a plain
sync leaves the old code installed and the whole suite then verifies a stale artifact. That
failure is far more dangerous than the one being fixed, because it is green. Forcing
`--reinstall-package` on every sync closes it, at a cost of roughly half a second.

`--no-sync` on every `uv run` keeps the environment from being rebuilt underneath a running
comparison. Conformance should measure the environment that `sync_python_tracks.sh`
prepared, not one that changes halfway through the run.

Every environment is also built on the uv-managed CPython pinned in `.python-version`
rather than on whatever interpreter is first on the path, so the toolchain does not depend
on a Homebrew or Miniconda installation that another machine will not have.

## Everything at once

```sh
tools/check_all.sh
```

Runs, in order: the convention linter, `ruff`, `mypy --strict` on both Python tracks, the
Python test suites, the C++ build and `ctest`, and finally the three-way conformance run.
Any failure stops the script.

## Individual steps

```sh
uv run --project python_pure pytest
uv run --project python_cpp  pytest

cmake --preset release
cmake --build --preset release
ctest --preset release

uv run conformance/run.py --all
uv run conformance/run.py --verb price-options --track python_pure

uv run tools/check_no_comments.py .
uv run --project python_pure mypy --strict src

uv run benchmarks/run.py
```

## Regenerating fixtures

```sh
uv run tools/generate_fixtures.py --verb price-options
```

Fixtures are regenerated from `python_pure` and then independently verified against
`mpmath` at 50 digits before they are written. A regeneration that changes an existing
expected value is a red flag, not a routine step: it means either a bug was just fixed or
one was just introduced. Review the diff on `spec/fixtures/` in its own commit, never
bundled with the change that caused it.

## Running a track directly

All three tracks take the same command line.

```sh
uv run --project python_pure volarb-py     price-options --input in.json --output out.json
uv run --project python_cpp  volarb-cpp    price-options --input in.json --output out.json
build/release/cpp_pure/volarb-native       price-options --input in.json --output out.json
```

## Live trading gate

No live venue adapter is wired, and none will be until the following are all true and
recorded here with a date and a signature:

1. A paper trading run of at least one full quarter of market days.
2. Realized paper P&L attribution showing the edge concentrated in vega rather than in
   unhedged delta.
3. Modelled transaction costs validated against observed paper fills, not assumed.
4. Risk limits and kill switches exercised under a deliberate fault injection test.

Status: **not started**. Phase 5 is not yet reached.
