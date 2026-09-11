# Mandelbrot

A volatility arbitrage research and trading platform for US equity and index options,
built simultaneously along three tracks held at full functional parity.

| Track | Directory | Description |
|---|---|---|
| Pure Python | `python_pure/` | Full stack in Python over numpy/scipy |
| Python + C++ | `python_cpp/` | Same public API, pybind11 bindings over `cpp_core` |
| Pure C++ | `cpp_pure/` | Full stack native, over `cpp_core` |

Very important places:  `spec/` (interface contracts,
schemas, golden fixtures, numerical tolerances) and `conformance/`, which verifies these tracks yield identical results for identical input.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — layout, parity mechanism, module map
- [`docs/conventions.md`](docs/conventions.md) — naming and style rules, and why they are enforced
- [`docs/math.md`](docs/math.md) — model definitions, greek conventions, algorithms
- [`docs/roadmap.md`](docs/roadmap.md) — phased delivery and exit criteria
- [`docs/program.md`](docs/program.md) — the ten-step program beyond the roadmap
- [`docs/runbook.md`](docs/runbook.md) — how to build, test, and run everything
- [`docs/benchmarks.md`](docs/benchmarks.md) — cross-track timings and how to read them
- [`docs/data.md`](docs/data.md) — the bitemporal data spine and as-of query semantics
- [`docs/backtest.md`](docs/backtest.md) — the event loop, the lookahead guarantee, and the results store
- [`docs/reporting.md`](docs/reporting.md) — P&L attribution into greeks, and into factors versus residual
- [`docs/research.md`](docs/research.md) — the trial registry, result pins, and the statistics that consume them
- [`docs/history_run.md`](docs/history_run.md) — the end-to-end run on dated data, and the go/no-go it produced
- [`spec/interfaces/implied_correlation.md`](spec/interfaces/implied_correlation.md) — implied correlation, the diagonal everyone drops, and dispersion weights
- [`docs/dispersion_data.md`](docs/dispersion_data.md) — planting a correlation in an option market and recovering it from the prices
- [`docs/risk.md`](docs/risk.md) — the pre-trade gate, and the three defects that firing it found
- [`docs/live_data.md`](docs/live_data.md) — everything between this repository and a real option chain

## Quick start

```sh
tools/bootstrap.sh
tools/check_all.sh
```

