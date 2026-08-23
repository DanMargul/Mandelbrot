# Program: ten ambitious steps

`roadmap.md` describes the table stakes: the phases that have to exist before anything can
be claimed. This document describes the program that subsumes it. Each step below either
extends a roadmap phase or adds something the roadmap does not reach.

The steps are dependency-ordered, with one deliberate exception noted at step 7.

---

## 1. A point-in-time data spine that cannot leak the future

*Extends Phase 2. **Done.** See `docs/data.md` and `spec/interfaces/market_data.md`.*

Polygon ingestion into partitioned Parquet, with every row carrying both an event time and
a knowledge time. Corporate actions handled explicitly: splits, special dividends, symbol
changes, ticker reuse, and OCC contract adjustments, where the deliverable stops being 100
shares and every downstream assumption quietly breaks.

The hard part is not ingestion, it is making lookahead structurally impossible rather than
merely discouraged. The reader takes an as-of timestamp and has no API that can return a
row whose knowledge time is later. A backtest cannot cheat because there is no call that
would let it.

**Done when** a deliberate lookahead attempt fails as a type or contract error rather than
returning data, the Parquet manifest carries content hashes, and adjusted contracts are
either handled or excluded by an explicit flag, never silently mixed in.

---

## 2. Forwards, discounts, and borrow implied from the options themselves

*Extends Phase 2. **Done.** See `spec/interfaces/forward_curve.md`.*

For each underlying and expiry, `C - P = DF * (F - K)`, so regressing the call-put
difference on strike gives `-DF` as slope and `DF * F` as intercept. Robust regression, not
least squares, because the wings are noisy.

The weights were going to come from Phase 1, on the reasoning that
`volatility_uncertainty` already says which quotes resolve anything. **That was wrong, and
the implementation found it.** That quantity needs a vega, a vega needs a forward, and the
forward is what this step computes; the dependency is circular. The weight is instead the
inverse variance of the measured difference, `1 / (call_half_spread^2 + put_half_spread^2)`,
which is model-free like parity itself.

From the forward term structure, back out implied borrow and implied dividends. A forward
below the no-borrow forward means expensive borrow, which is simultaneously a data-quality
flag and a tradeable signal.

The measured outcome changed the plan for what comes after. The forward is recovered to a
few parts in `1e5`; the discount factor only to about `1e-3`, which is two percentage points
of zero rate at a four-week expiry. A discount factor error is a per-slice level shift that a
surface fit largely absorbs, so within-expiry relative value is close to immune, but it does
not cancel across expiries. **Calendar and term-structure signals therefore need a real rate
curve and cannot use rates implied from parity.** That is now a prerequisite of step 5 rather
than an assumption inside it.

**Done when** the forward and discount factor recover synthetic ground truth inside their own
reported standard errors, a deliberately stale quote is trimmed, and hard-to-borrow names are
flagged rather than silently producing garbage surfaces.

---

## 3. American exercise, and the early-exercise premium as a first-class quantity

*Extends Phase 2.*

SPX is European and deferred that problem. Single names are not. Bjerksund-Stensland 2002
for throughput, Andersen-Lake-Offengenden or CRR with Richardson extrapolation for accuracy,
with the fast pricer validated against the accurate one.

The ambitious part is the cross-check. De-Americanize calls and puts on the same strike and
they must imply the same volatility. When they do not, the error is almost never in the
option pricer; it is in the borrow or dividend assumption from step 2. That disagreement
becomes a diagnostic that feeds backwards, and the two steps are calibrated jointly rather
than in sequence.

This is also where the native tracks start to matter. Inverting an American price means
inverting a numerical pricer, and the Phase 1 benchmark already showed 5.78x on European
inversion.

**Done when** call-implied and put-implied volatilities agree across the strike range after
de-Americanization, and residual disagreement is attributed to borrow rather than absorbed.

---

## 4. A surface that is arbitrage-free by construction, not by inspection

*Extends Phase 3.*

SVI per slice, eSSVI globally with calendar-monotone total variance, calibrated under the
Durrleman condition. That much is standard.

What makes it ambitious is the acceptance test. Checking that fitted parameters sit inside
the no-arbitrage region is weaker than it sounds, because the region is checked at the
parameters and violated between them. The real test is that the surface produces a
non-negative risk-neutral density and a valid non-negative local volatility via Dupire, on a
dense grid, everywhere. A surface that passes the parameter check and fails the density
check is arbitrageable, and it is the density that the strategy is implicitly trading.

**Done when** dense-grid density non-negativity, calendar monotonicity, and a Dupire
round-trip all hold as fixture assertions, so a refactor that reproduces the parameter
values but breaks the constraint still fails.

---

## 5. A surface factor model, so signals trade the residual and nothing else

*Extends Phase 4.*

Decompose the surface time series into level, term slope, skew, and smile curvature, either
by PCA on total variance or on a parametric basis. What remains after reconstruction is the
idiosyncratic residual, and that is the only thing worth trading.

The discipline is orthogonality by construction. A signal built on raw fit residuals is
mostly a disguised bet on the level factor, which is to say a disguised bet on whether
volatility goes up. Constructing the signal orthogonal to the factors means the trade is
neutral to level, skew, and term moves by design rather than by hope.

Z-scoring needs a real model too. Residuals are autocorrelated and heteroskedastic, so a
rolling mean and standard deviation will systematically misstate how unusual a residual is,
in the direction that makes everything look tradeable.

**Done when** P&L attribution shows the return concentrated in residual convergence rather
than in factor exposure, on out-of-sample data.

---

## 6. An execution simulator that models microstructure, not a mid-price fantasy

*Extends Phase 5.*

Quote-level NBBO with size, queue position for resting orders, spread crossing for
aggressive ones, and adverse selection, because the fills you get are disproportionately the
ones you did not want. Multi-leg spreads price as packages with their own NBBO and carry
legging risk when they do not.

This matters more here than in most strategies. Option spreads on single names routinely run
five to twenty percent of premium, and surface relative value edge is frequently smaller
than the spread being crossed to capture it. A backtest at mid is not an optimistic result;
it is not a result.

There is a bootstrap problem: the simulator should be calibrated from observed fills, and
observed fills require paper trading, which requires a simulator to justify. Resolve it by
starting deliberately pessimistic, paying the full spread on every trade, which is a lower
bound rather than an estimate, then refining once paper fills exist.

**Done when** simulated fill distributions reproduce observed paper fills, and until then,
when every quoted result carries the pessimistic cost assumption explicitly.

---

## 7. Research integrity, before the search rather than after it

*Extends Phase 6. **Land this out of order, before serious signal search.***

Every result pinned to a git SHA, a data manifest hash, a config hash, and a seed, so any
number in any document can be regenerated bit for bit. The determinism discipline from
Phase 1 already makes this achievable rather than aspirational.

Then the statistics that make a backtest mean something: deflated Sharpe ratio corrected for
the number of trials, probability of backtest overfitting via combinatorially symmetric
cross-validation, and strictly out-of-sample walk-forward parameter selection.

The genuinely hard part is the trial registry. Multiple-testing correction needs the true
number of configurations ever evaluated, and nobody remembers that number honestly after the
fact; it is always larger than it feels. A registry that logs every configuration at the
moment it runs is the only way to get it right, and it has to exist before the search starts
or the count is already lost. That is why this step jumps the dependency order.

**Done when** the registry exists, results are reproducible from their pins, and no strategy
can be promoted without a deflated Sharpe above a threshold stated in advance.

---

## 8. Portfolio construction and hedging solved as one problem

*Extends Phase 5 and 6.*

Not signal ranking. A constrained optimization: maximize expected residual convergence net
of modeled cost, subject to vega, gamma, and theta budgets, factor neutrality from step 5,
per-name concentration limits, and liquidity.

Hedging is the other half of the same problem. Optimal delta bands under proportional
transaction costs are a control problem with known asymptotic solutions, Whalley-Wilmott and
Zakamouline among them, and both beat a fixed band. But the hedging cost depends on gamma,
and gamma is exactly what the optimizer is allocating, so solving them separately leaves the
optimizer allocating risk it has mispriced. Solve jointly, or iterate to a fixed point.

**Done when** the jointly optimized portfolio beats naive ranking with fixed-band hedging on
risk-adjusted terms, out of sample, after costs.

---

## 9. Dispersion and the implied correlation surface

*New. The heaviest lift in the program.*

Index implied variance against the weighted basket of constituent implied variances gives
implied correlation, with its own term structure and skew. Trading it means selling index
volatility against constituent volatility when correlation is rich, or the reverse.

Everything above has to work per name across the full constituent universe first. That means
American exercise from step 3, borrow from step 2, and a calibrated surface from step 4, for
five hundred names rather than one index, with changing weights and constant corporate
actions. The data volume is two orders of magnitude beyond SPX alone, and this is where the
native tracks stop being an interesting comparison and start being the reason the pipeline
finishes overnight.

**Done when** the computed implied correlation series reproduces published benchmarks within
a stated tolerance. That external validation is worth more than any internal consistency
check, because it is the one number in this program that can be checked against someone
else's independent implementation.

---

## 10. Paper-to-live promotion, gated by a risk system that has been broken on purpose

*Extends Phase 7.*

The live adapter sits behind the same interface as `PaperBroker`, so promotion changes an
adapter and nothing else. Around it: pre-trade position and greek limits, order rate limits,
fat-finger bounds, kill switches, and daily automated reconciliation of positions and P&L
against the broker with break detection.

Kill switches that have never been fired are decoration. The gate requires deliberate fault
injection, killing the connection mid-order, feeding a stale mark, exceeding a limit on
purpose, and confirming the system does what it claims.

**Done when** the four conditions already recorded in `runbook.md` are met and signed with a
date: a full quarter of paper trading, attribution showing edge in vega rather than unhedged
delta, modeled costs validated against observed fills, and the risk system exercised under
fault injection.

---

# Cross-cutting: the parity boundary

**Ten steps times three tracks is thirty implementations, and that is the largest risk to
this program.** Phase 1 was the easy case: pure functions, no state, no I/O. Everything from
here has all three.

The recommendation is to stop treating full parity as the default and draw an explicit line
in the module map. Below it, tri-implemented and conformance-tested. Above it, Python only,
by declaration rather than by drift.

| | modules | why |
|---|---|---|
| **Below the line** (three tracks) | pricing, implied vol, American exercise, surface calibration, local vol, factor decomposition, portfolio optimization, hedging control | numerics, hot paths, and exactly the code where a silent disagreement corrupts a result |
| **Above the line** (Python only) | Polygon ingestion, experiment registry, reporting and attribution, plotting, orchestration | I/O and glue, no hot path, and no meaningful comparison to make |

The existing "one sanctioned divergence" section in `architecture.md` becomes this table.
Without that line, the three-track discipline collapses under its own weight somewhere
around step 5, and it collapses unevenly, which is worse than deciding deliberately: you
lose the conformance guarantee on the numerics while still paying for it on the glue.

# Cross-cutting: the go/no-go that should come early

The honest risk in this program is not engineering. It is that surface relative value edge
in liquid US index options may be smaller than the cost of capturing it, and the truthful
answer after steps 1 through 7 may be that there is no tradeable edge at this cost level.

That answer is worth reaching cheaply. **Insert a deliberate go/no-go after step 6**, running
the pessimistic full-spread cost model against the best signal available at that point. If
the edge does not survive paying the full spread, steps 8 through 10 are an expensive way to
confirm it. Better to learn it from the cost model than from the P&L.

# If the program has to be cut

Steps 1, 2, 4, 6, and 7 are the irreducible core: data that cannot cheat, a correct forward,
a surface that is genuinely arbitrage-free, costs that are real, and statistics that are
honest. A platform with those five and nothing else can answer whether an edge exists.

Steps 3, 5, 8, and 9 make the edge larger. Step 10 makes it real money. None of them repair
a failure in the first five.
