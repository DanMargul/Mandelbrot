# Architecture

## The problem this layout solves

Three independent implementations of the same platform are worth building only if they can
be proven equivalent and compared fairly. Left to themselves, three tracks diverge silently:
a rounding difference becomes a different calibration, which becomes a different trade, and
the comparison stops meaning anything.

So the load-bearing component is not a track. It is the pairing of `spec/` and
`conformance/`. Everything else is held against them.

## Directory map

```
docs/            prose (code carries no comments; the explanation lives here)
spec/
  interfaces/    one file per module: exact function names and typed signatures
  schemas/       JSON Schema for every record type that crosses a boundary
  fixtures/      golden inputs and expected outputs, version controlled
  tolerances.toml
python_pure/     track 1
cpp_core/        shared C++20 engine
python_cpp/      track 2: pybind11 over cpp_core
cpp_pure/        track 3: native CLI over cpp_core
conformance/     cross-track differ; depends on no track
benchmarks/      identical workloads timed across all three tracks
tools/           bootstrap, convention linter, fixture generation
configs/         strategy and run configuration
data/            gitignored: Polygon cache and normalized Parquet
```

## The parity mechanism

Every track exposes an identical command line contract:

```
<runner> <verb> --input <path> --output <path> [--config <path>]
```

The verbs, the input schema and the output schema are defined once in `spec/` and are the
same for all three. `conformance/run.py` invokes each track over the same fixture inputs and
compares the outputs field by field against `spec/tolerances.toml`.

This is deliberately a process boundary rather than an in-process one. A harness that
imported all three tracks would need the bindings to work before it could test whether the
bindings work, and it would let shared Python helpers leak between tracks that are supposed
to be independent. Shelling out keeps the tracks genuinely separable and makes the contract
language-agnostic.

Unit-level parity is a separate concern, handled inside each track's own test suite, which
reads the same fixture files directly.

## Fixture provenance

`python_pure` is written first for each module and produces candidate outputs. A candidate
only becomes a golden fixture once it is cross-checked against an oracle that is independent
of the implementation:

- closed-form identities and limiting cases
- `mpmath` recomputation at 50 decimal digits
- put-call parity and other model-free relations
- no-arbitrage invariants (Durrleman condition, calendar monotonicity)

Pure Python being the reference track does not make it correct. The oracle, not the track,
is what confers authority on a fixture.

## Module map

Every module below exists under the same name, with the same public function names, in all
three tracks.

| Module | Responsibility |
|---|---|
| `market_data` | Polygon client, Parquet reader, chain snapshot normalization |
| `instruments` | Contract definitions, expiry calendar, forward and discount curves |
| `pricing` | Black-Scholes-Merton price and greeks; American via Bjerksund-Stensland and CRR |
| `implied_vol` | Robust inversion: bracketed Newton with bisection safeguard |
| `surface` | SVI slice calibration, SSVI global fit, no-arbitrage constraints, interpolation |
| `arbitrage` | Static bound violations and fitted-surface residuals |
| `signals` | Residual z-scores, ranking, entry and exit rules |
| `portfolio` | Positions, aggregated greeks, delta-band hedging |
| `backtest` | Snapshot event loop, fill model, transaction costs |
| `execution` | `PaperBroker` behind a broker interface; live adapter stubbed |
| `risk` | Position and greek limits, kill switches |
| `reporting` | P&L attribution into delta, gamma, vega, theta and residual |

## The parity boundary

Full parity across three tracks is not the default. It is a decision made per module,
recorded here, and enforced by whether a module appears in `spec/interfaces/`.

Phase 1 could afford parity everywhere because it was pure functions with no state and no
I/O. Everything after it has all three, and ten roadmap steps times three tracks is thirty
implementations. Left undeclared, the discipline collapses somewhere in the middle of the
program, and it collapses unevenly: the guarantee is lost on the numerics while the cost is
still paid on the plumbing. So the line is drawn explicitly instead.

### Below the line: three tracks, conformance tested

| module | reason |
|---|---|
| `pricing` | hot path, and a silent disagreement corrupts every downstream number |
| `implied_vol` | hot path, iterative, the largest measured interpreted-versus-native gap |
| `american` | numerical pricer inside an inversion loop |
| `surface` | calibration is the most expensive per-snapshot work in the pipeline |
| `local_volatility` | dense-grid evaluation, and the arbitrage-free acceptance test |
| `factors` | decomposition over the full history |
| `portfolio` | constrained optimization |
| `hedging` | control problem solved per path |
| `market_data` reader | the as-of resolution is on the backtest inner loop |

These are the modules where the arithmetic is the product. A disagreement between tracks is
a defect in one of them, and conformance is what finds it.

### Above the line: Python only, by declaration

| module | reason |
|---|---|
| `ingestion` (Polygon HTTP client) | REST, auth, pagination, retry, rate limits; no hot path |
| `manifest` writing | runs once per ingest, not once per backtest step |
| `experiment` registry | orchestration and bookkeeping |
| `reporting` and attribution | presentation, run once per result |
| plotting | presentation |

Reimplementing any of these in C++ costs real effort and produces no comparison worth
reading. They are excluded deliberately, not by neglect.

### Where the boundary is crossed

The handoff is the canonical Parquet dataset described in `data.md`. Ingestion writes it;
everything below the line reads it. That file format is part of `spec/schemas/`, so the
tracks stay at parity for everything downstream of the boundary even though only one of
them can produce the data.

Adding a module to the upper table requires an entry here saying why. Adding one to the
lower table requires an interface file in `spec/interfaces/` and fixtures in
`spec/fixtures/`.

## Determinism

No Monte Carlo is used before Phase 5. When it is introduced, both languages use a PCG64
generator specified in `docs/math.md` with fixed seeds, so paths are identical bit for bit
and conformance remains meaningful rather than statistical.
