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
- [`docs/runbook.md`](docs/runbook.md) — how to build, test, and run everything

## Quick start

```sh
tools/bootstrap.sh
tools/check_all.sh
```

## Status

Phase 1 of 7. Pricing and implied volatility are implemented and conformant across all
three tracks. No live venue connectivity exists, and none will be wired until the paper
trading gate in `docs/runbook.md` is signed off.
