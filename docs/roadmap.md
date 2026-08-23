# Roadmap

This document is the table stakes: the phases that must exist before anything can be
claimed. [`program.md`](program.md) describes the ten-step program that subsumes and
extends it, and states which of these phases each step reaches past.

A phase is complete only when all three tracks pass conformance on that phase's fixtures.
Partial completion in one track is not progress; it is drift.

## Phase 0 — Skeleton (done)

Repository layout, bootstrap, three build systems, spec format, conformance runner,
convention linter. All three tracks build and pass an empty conformance run.

## Phase 1 — Pricing and implied volatility (done)

Complete. All three tracks conformant over 1352 fixture records.

Black-Scholes price and greeks in the forward measure, robust implied volatility inversion.
Fixtures cover deep in and out of the money, near-zero volatility, near-expiry, and
zero-vega degenerate cases, cross-checked against `mpmath` at 50 digits.

This is first because it is the largest expected native speedup and the cleanest possible
conformance target: pure functions, no state, no data dependencies.

## Phase 2 — Data and instruments

Polygon ingestion to canonical Parquet; Parquet readers in all three tracks; expiry
calendar; forward and discount curves **implied from put-call parity** rather than assumed
from a rate and a dividend forecast.

This phase also moves the bulk data path off JSON. The phase 1 benchmarks showed that over
half the wall clock of a 400,000 option pricing run is spent converting text to numbers and
back, in every track, which makes the end-to-end timings a measurement of the JSON library
rather than of anything interesting. JSON stays for the conformance fixtures, where small
readable documents and reviewable diffs are the whole point. See `docs/benchmarks.md`.

Adding `arrow` to `vcpkg.json` belongs here rather than earlier; it is a slow port to
build and phase 1 had no use for it.

That choice is the correctness lever for the whole project. If the forward is wrong, every
surface residual downstream is a curve misspecification wearing the costume of an edge.
Start on SPX, which is European and cash settled, to defer American exercise; add
Bjerksund-Stensland and CRR for single names at the end of the phase.

## Phase 3 — Surface

SVI raw parameterization, slice calibration under the Durrleman butterfly condition, SSVI
global fit with calendar-monotone total variance, interpolation and controlled wing
extrapolation. Fixtures assert the no-arbitrage invariants directly, not only the parameter
values, so a refactor that happens to reproduce the numbers but breaks the constraint still
fails.

## Phase 4 — Arbitrage detection and signals

Static bound violations on raw quotes first: butterfly, calendar and vertical spread
bounds. These are forecast-free, cheap, and make an excellent conformance test because the
answer is a discrete set rather than a float.

Then fitted residuals to z-scores to ranked candidate spreads, vega-neutral by construction.

## Phase 5 — Backtest and paper portfolio

Snapshot event loop, delta-band hedging, spread-crossing and slippage cost model,
`PaperBroker`. Costs are modelled from the first backtest rather than added later. A
surface relative-value result computed at mid is not a result; the edge in this strategy
family is frequently smaller than the spread being crossed to capture it.

## Phase 6 — Reporting

P&L attribution decomposed into delta, gamma, vega, theta and residual, so an apparent edge
can be traced to the vega it was supposed to come from rather than to unhedged delta that
happened to point the right way over the sample.

## Phase 7 — Live interface (stub only)

Broker interface, risk limits, kill switches. Not wired to any venue. Gated on the paper
trading sign-off recorded in `docs/runbook.md`.

## Cross-cutting

`benchmarks/` gains a timed workload for every module from Phase 1 onward, run identically
across all three tracks and reported as a tracked table. Results and their interpretation
live in `docs/benchmarks.md`; the interpretation is not optional, since a ratio quoted
without it has already been misleading once.
