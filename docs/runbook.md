# Runbook

## Bootstrap

```sh
tools/bootstrap.sh
```

Installs the native toolchain via Homebrew, syncs both `uv` projects, and configures the
CMake release preset. It is idempotent; rerun it whenever dependencies change.

### Why Homebrew and not vcpkg

The native dependencies are `cmake`, `ninja`, `apache-arrow`, `nlohmann-json` and `catch2`,
all from Homebrew. The project was originally set up with a vcpkg manifest, and that was
reversed after vcpkg failed to build two required ports on this platform:

| port | pulled in by | failure |
|---|---|---|
| `libb2` | `pybind11` | build error on `arm64-osx` |
| `thrift` | `arrow` | build error on `arm64-osx` |

Neither failure is in a port we control, and both are in transitive dependencies of
libraries the project cannot do without. The choice was between vendoring patches for other
people's ports and using prebuilt bottles, and bottles win: the whole native stack installs
in about a minute, against roughly forty for a from-source Arrow that then does not link.

The cost is that Homebrew pins less precisely than a vcpkg manifest. That is a real
reproducibility loss and it is accepted knowingly. The mitigating factor is that the C++
dependency surface is deliberately small: Arrow and Parquet for the data spine,
nlohmann-json for the document layer, Catch2 for tests, and nothing else. `pybind11` comes
from the Python environment, which is the correct source for it in any case, since the
extension must match the interpreter it will be loaded into.

`cmake/volarb_native_dependencies.cmake` resolves the Homebrew prefix by asking `brew`
rather than hardcoding `/opt/homebrew`, so the same build works on Intel macOS and under a
non-default prefix.

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
uv run --no-sync pytest ingestion/tests
uv run --no-sync --project python_pure pytest python_pure
uv run --no-sync --project python_cpp  pytest python_cpp

cmake --preset release
cmake --build --preset release
ctest --preset release

uv run conformance/run.py --all
uv run conformance/run.py --verb price-options --track python_pure

uv run tools/check_no_comments.py .
uv run --project python_pure mypy --strict src

uv run benchmarks/run.py
```

## Building a dataset

```sh
uv run --no-sync ingestion/run.py --source synthetic \
    --dataset-root spec/fixtures/datasets/synthetic_chain

uv run --no-sync ingestion/run.py --source recorded --underlying SPXTEST \
    --dataset-root data/recorded_chain

export POLYGON_API_KEY=...
uv run --no-sync ingestion/run.py --source polygon --underlying SPX \
    --dataset-root data/spx --record-to spec/fixtures/recorded
```

The synthetic dataset is byte-reproducible and is committed, so the whole stack is testable
with no key and no network. `--record-to` captures live responses for later offline replay,
which is how the Polygon mapping gets test coverage without a key.

The API key is read from `POLYGON_API_KEY` and is never accepted on the command line or in
configuration, so it cannot end up in a shell history or a committed config file.

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
