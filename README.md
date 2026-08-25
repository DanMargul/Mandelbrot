# Mandelbrot

A volatility arbitrage research and trading platform for US equity and index options,
built simultaneously along three tracks held at full functional parity.

| Track | Directory | Description |
|---|---|---|
| Pure Python | `python_pure/` | Full stack in Python over numpy/scipy |
| Python + C++ | `python_cpp/` | Same public API, pybind11 bindings over `cpp_core` |
| Pure C++ | `cpp_pure/` | Full stack native, over `cpp_core` |

Three implementations are only worth building if they can be proven equivalent, so the
centre of the repository is not any single track. It is `spec/` (interface contracts,
schemas, golden fixtures, numerical tolerances) and `conformance/`, which drives all three
tracks over the same fixtures and diffs the results.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — layout, parity mechanism, module map
- [`docs/conventions.md`](docs/conventions.md) — naming and style rules, and why they are enforced
- [`docs/math.md`](docs/math.md) — model definitions, greek conventions, algorithms
- [`docs/roadmap.md`](docs/roadmap.md) — phased delivery and exit criteria
- [`docs/program.md`](docs/program.md) — the ten-step program beyond the roadmap
- [`docs/runbook.md`](docs/runbook.md) — how to build, test, and run everything
- [`docs/benchmarks.md`](docs/benchmarks.md) — cross-track timings and how to read them
- [`docs/data.md`](docs/data.md) — the bitemporal data spine and as-of query semantics
- [`docs/research.md`](docs/research.md) — the trial registry, result pins, and the statistics that consume them

## Quick start

```sh
tools/bootstrap.sh
tools/check_all.sh
```

## Status

**Phase 1 complete; steps 1 to 4 of [`docs/program.md`](docs/program.md) complete.** Pricing,
implied volatility, the point-in-time data spine, forwards implied from put-call parity,
American exercise with premium stripping, SVI slice calibration, the surface acceptance test
covering butterfly arbitrage, calendar monotonicity and the Dupire round-trip, and the eSSVI
global surface fit judged by that test are implemented in all three tracks and pass
conformance: 80 comparisons over 2364 golden fixture records, each track against the golden
documents and each against the others. The fixtures themselves are verified against
independent oracles: an `mpmath` recomputation at 50 decimal digits for the closed-form
results, and a far finer scan for the arbitrage diagnostics.

Agreement is exact, not merely within tolerance. A one-year at-the-money option prices to
`7.8672269492716005` in every track, inverts to `0.20000000000000026` in every track, and
takes 31 solver iterations in every track. The surface scan agrees bit for bit across all
three tracks on every field of all 36 fixture cases, argmin locations included.

| gate | result |
|---|---|
| `python_pure` tests | 2711 passed |
| `python_cpp` tests | 393 passed |
| C++ tests (Catch2) | 81 passed |
| conformance | 80 comparisons, all tracks agree |
| ingestion tests | 13 passed |
| research tests | 55 passed |
| `mypy --strict` | clean |
| convention linter | clean |

No live venue connectivity exists, and none will be wired until the paper trading gate in
[`docs/runbook.md`](docs/runbook.md) is signed off. That gate is **not started**.
