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

*Extends Phase 2. **Done.** See `spec/interfaces/american.md` and the stripping section of
`spec/interfaces/forward_curve.md`.*

SPX is European and deferred that problem. Single names are not. Bjerksund-Stensland 2002
for throughput, Andersen-Lake-Offengenden or CRR with Richardson extrapolation for accuracy,
with the fast pricer validated against the accurate one.

The ambitious part was going to be a cross-check: de-Americanize calls and puts on the same
strike, require the same implied volatility, and read any disagreement as a borrow error
feeding back into step 2. Measurement changed the shape of that.

**The rate is not identifiable this way.** Parity already pins the forward, so `r` and `q`
have only one free parameter between them, and the call-put volatility disagreement turned
out to move by about `0.002` volatility points across a **twelve percentage point** range of
rate. Quote noise alone is `0.003`. There is no signal there to solve for.

**What the measurement found instead is more useful.** Running the parity regression on
American quotes at all is invalid, because parity is a European relation. On synthetic data
with known parameters it produced a discount factor of `1.0077`, above one, reported as
converged. Stripping the early exercise premium first cut the forward error by a factor of
seven and restored a sane discount factor.

So the deliverable is de-Americanization rather than a disagreement diagnostic: invert the
American quote for its volatility, evaluate the European price at that volatility, and run
the parity regression on those. `forward_curve` already refuses unstripped American quotes
rather than fitting them, so nothing downstream can consume the biased number in the
meantime.

This is also where the native tracks start to matter. Inverting an American price means
inverting a numerical pricer, and the Phase 1 benchmark already showed 5.78x on European
inversion.

**Done when** the forward implied from de-Americanized American quotes recovers synthetic
ground truth to the same accuracy as the European case, and no expiry containing American
contracts is ever fitted without stripping.

---

## 4. A surface that is arbitrage-free by construction, not by inspection

*Extends Phase 3. **Done.** See `spec/interfaces/svi.md`, `spec/interfaces/svi_surface.md`
and `spec/interfaces/essvi.md`.*

SVI per slice, eSSVI globally with calendar-monotone total variance, calibrated under the
Durrleman condition. That much is standard.

What makes it ambitious is the acceptance test. Checking that fitted parameters sit inside
the no-arbitrage region is weaker than it sounds, because the region is checked at the
parameters and violated between them. The real test is that the surface produces a
non-negative risk-neutral density and a valid non-negative local volatility via Dupire, on a
dense grid, everywhere. A surface that passes the parameter check and fails the density
check is arbitrageable, and it is the density that the strategy is implicitly trading.

The acceptance test is built **before** the calibrator, deliberately. A calibration is only
as good as the test it must pass, and fitting first invites the test to be relaxed until the
fit passes, which is exactly backwards.

Two things the checker turned up. The risk-neutral density and Durrleman's function differ
only by a strictly positive factor, so non-negative density and non-negative `g` are the same
condition rather than two; both are reported because the density carries units a reader can
reason about. And a grid alone is not enough: on a deliberately arbitrageable slice a 16-step
grid finds only `-1.64` of a true `-2.29` minimum, missing forty percent of the depth, so the
scan refines around its lowest point by golden section. The depth matters as much as the
detection, because it says whether a fit is slightly imperfect or badly wrong.

The status is `arbitrage_free_on_grid`, never `arbitrage_free`. A finite scan cannot prove
absence of a violation between its points and says nothing outside its range, and the name
carries that limit rather than hiding it.

Calibration then produced the sharpest lesson so far about what conformance is for.
Nelder-Mead is chaotic, so a single ulp anywhere sends the two tracks down different
trajectories to the same minimum: objectives agree to `1e-13` while iteration counts differ
by half a percent. Chasing a bit-identical path was rejected as a contract that cannot be
kept across independent implementations. The measurement that decided it: on an almost flat
smile the fitted parameters differ between tracks by `1.5e-2` while the curve they describe
differs by `3.4e-16`. The parameters are a coordinate system; the curve is the answer. The
result now carries the fitted curve at seventeen reference points, compared tightly, with the
parameters kept as loosely compared output. **Conformance must compare the answer, not the
route to it.**

The surface scan then made the same point a second time, in the other direction. Checking
the two expiries that bound an interval is not enough: two slices can each be butterfly-free,
their term structure can be calendar-monotone, and the surface interpolated between them can
still carry a negative risk-neutral density. A search over 20,000 random pairs of
individually arbitrage-free slices found 66 such pairs. The fixture carries one, where both
knots scan clean at `+2.60e-02` and `+2.38e-01` while the surface at `T = 0.310` reaches
`-3.14e-02`. **The region is checked at the parameters and violated between them, and that is
as true along maturity as it is along strike.**

Two further things the surface work settled. The Dupire local variance is `w_T / g`, where
`g` is Durrleman's function, so a non-negative local volatility is not a third condition at
all — it is the conjunction of the calendar and butterfly conditions already being tested.
What is independent, and was worth building, is the round trip against Dupire's original
price-space formula, which agrees to `2.4e-6` but only once it is run on out-of-the-money
options: on calls everywhere it loses five digits deep in the money to cancellation, because
the price is `O(1)` there while its second difference is `O(1e-4)`.

And refining a two-dimensional scan is not the one-dimensional problem twice. Refining
strike at each sampled maturity and then maturity at the best strike is coordinate descent,
and it stalls `1.5%` short when the true minimum sits at the edge of the range. Refining the
strike-minimised profile instead removes both grids from the answer: the reported depth is
now identical to machine precision across every grid resolution tried, where the grid alone
missed `28%` of it.

The eSSVI global fit that ties the slices together was then built against that test, and the
test immediately earned its keep. The first version enforced the butterfly condition with a
penalty, as the slice calibrator does. Fed observations sampled from a badly arbitrageable
surface, it reduced the violation from `-2.29` to `-0.022` and stopped: the data pull and the
penalty balanced at a point that was still arbitrageable. **A penalty is a soft constraint and
it loses when the data pulls hard enough.** The butterfly condition moved into the
construction instead, as a bound on the curvature scale derived from the Gatheral-Jacquier
sufficient conditions, so no reachable coordinate describes an arbitrageable slice. The price
is that those conditions are sufficient and not necessary, so the reachable set is smaller
than the arbitrage-free set.

The calendar condition could not follow it, because eSSVI exists precisely to let the
correlation vary and the constant-correlation argument does not survive that. What the
penalty does there is worth recording, because it looks like a tuning problem and is not:
pushed against inconsistent data it converges to the constraint **boundary**, where the sign
is decided by rounding. At weight `1e6` the minimum time slope is `-9.4e-08`, at `1e8` it is
`+1.0e-10`, at `1e10` it is `-1.0e-11`. Choosing `1e8` because it happened to pass would be
tuning a test until it goes green.

So the calibrator reports the verdict instead of assuming it. `calibrate_essvi_surface` runs
the acceptance test on its own fitted slices and returns `arbitrage_not_eliminated` when it
does not pass. **The fit either returns a surface that passes the acceptance test, or it says
it could not**, and a caller cannot ship an arbitrageable surface by forgetting to check.
On ordinary smiles, on 2% noise, and on data sampled from a calendar-violating surface, it
converges and the fitted surface is arbitrage-free; the calendar case is repaired rather than
reproduced.

That also drew a line around what conformance can do. Every converged case agrees across
tracks on the fitted surface to `1.3e-8`. The one fit that reports it could not eliminate
arbitrage has two tracks landing on surfaces `98%` apart, because the objective there has
many near-equal minima and the simplex picks one chaotically. Such cases are covered by unit
tests in all three tracks rather than by the shared fixture. **Conformance compares the
answer, and a fit that reports it could not eliminate arbitrage is telling you there is not
one.**

**Done when** dense-grid density non-negativity, calendar monotonicity, and a Dupire
round-trip all hold as fixture assertions, so a refactor that reproduces the parameter
values but breaks the constraint still fails. **Done.**

---

## 5. A surface factor model, so signals trade the residual and nothing else

*Extends Phase 4. **The rate curve prerequisite and the factor decomposition are done**, see
`spec/interfaces/rate_curve.md` and `spec/interfaces/factors.md`. P&L attribution waits on the
backtester.*

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

The prerequisite landed first, and it was worth building carefully rather than reaching for
the obvious interpolation. A discount curve is defined by its nodes and by what fills the gaps
between them, and filling them by interpolating the zero rate — which looks equivalent to
interpolating its integral and is not — turns a curve of 1% at one month rising to 4% at three
months into an instantaneous forward that ranges over `2.56%` to `8.44%` inside that single
segment, a factor of `3.3`. Interpolating `z(t) * t` instead gives one constant `5.50%`.
**Calendar structure trades exactly that quantity**, so the artefact would have gone straight
into the signal this step is supposed to produce.

Scope was set by a measurement already on the record rather than by re-deriving it: step 2
found that supplying an external rate does not improve the parity forward, `4.8e-5` against
`4.9e-5`, so the curve is deliberately **not** wired into the forward regression. It exists
for discounting across expiries, which is the one place the earlier measurement said a real
curve is needed.

The decomposition then sharpened the orthogonality discipline into something more exact than
the sentence above. Projecting each surface onto a named basis of level, term slope, skew and
curvature gives a residual orthogonal to those shapes **across the grid on that date**. It does
not follow that the residual at one grid point is uncorrelated with the level loading **through
time**, and measured on a factor-driven series it is not: the correlation is `1.18e-01`. A
second, time-domain regression of the residual series on the loading series drives it to
`6.1e-18`. Cross-sectional orthogonality is not time-series neutrality, and only the second one
makes a trade neutral.

The step's claim about disguised bets is measured rather than repeated: a deviation from the
mean surface correlates `+0.84` with the level factor while the orthogonal residual correlates
`-0.02`.

The z-scoring warning is quantified. The effective sample size of a persistent residual is
`n (1 - rho) / (1 + rho)`, so at `rho = 0.9` a naive z-score overstates significance by
`4.44x` and **a three-sigma residual is really a `0.7` sigma residual**. The correction runs
both ways, which matters here: a mean-reverting residual, which is what a convergence strategy
wants, has an effective sample size *above* `n` and is more significant than it looks.

Attribution then made the step's own criterion checkable, and the first thing it showed was a
loss. Splitting the vega profit of a short position in an option quoted `4%` rich, held one
day while the surface also moved:

| what moved | vega profit |
|---|---|
| level | `-134.50` |
| term slope | `-19.40` |
| residual | `+71.20` |
| net | `-82.05` |

**The residual bet was right and the trade still lost money.** The option converged and earned
`+71.20`; an unhedged level exposure took `-134.50` back. That is the failure this step exists
to prevent, stated in currency rather than in principle, and it is why the neutralisation is a
second regression through time rather than a hope.

Two things the attribution itself had to get right. `math.md` requires the roll of `F` and
`DF` toward expiry to be attributed separately from theta, so there is an explicit discount
term; price is exactly linear in the discount factor and the term explains that move to
`2.7e-14`. And every greek is exact in its own variable while a *combined* move leaves `89%`
of its residual in cross terms, which no refinement of the individual greeks will reach. The
unexplained share runs from `0.23%` on a one percent move to `14.42%` on a twenty percent one,
so the report carries it rather than letting a reader assume the expansion always holds.

**Done when** P&L attribution shows the return concentrated in residual convergence rather
than in factor exposure, on out-of-sample data. **The decomposition, the honest z-score and the
attribution are done**; running it over out-of-sample dates needs the backtester, so that last
clause waits with step 6.

---

## 6. An execution simulator that models microstructure, not a mid-price fantasy

*Extends Phase 5. **The pessimistic cost model and the event loop are done**, see
`spec/interfaces/execution.md` and `docs/backtest.md`. Queue position, depth beyond the touch
and adverse selection remain, and all three need observed fills to calibrate against.*

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

The pessimistic model landed first, as this section prescribes, and immediately produced the
number the go/no-go turns on. Expressing the cost of crossing in the units the strategy
actually trades — volatility points rather than dollars — and measuring it through the module
on the synthetic chain, one contract per line:

| underlying | median round trip | 75th | 90th |
|---|---|---|---|
| SPX | `0.36` | `0.98` | `2.82` |
| AAPL | `0.65` | `2.98` | `5.23` |
| THIN | `1.46` | `5.90` | `8.16` |

**A round trip in the median SPX line costs a third of a volatility point, and one in the
ninetieth percentile costs nearly three.** Surface relative value is measured in the same
units and often in smaller numbers, which is the whole argument for scheduling a go/no-go
here rather than after step 9.

Two things the model made precise. The bound is on price per contract executed, not on
quantity: an order larger than the displayed size is left partly unfilled here where reality
would sweep deeper and fill more at worse prices, so on large orders it understates cost and
fill together. The unfilled remainder is reported rather than assumed away. And the cost in
volatility points is a property of the package rather than its legs — a pair that nets to no
vega has paid the spread on both legs and bought no exposure, so cost per unit of vega
diverges. That is a real trade, so it is reported with a flag rather than rejected.

The event loop then made the point-in-time guarantee from step 1 into something the loop can
actually keep. The as-of reader refuses a query past its horizon, which protects one query; it
does not protect a loop, because a reader opened once at the end of a run will answer every
step in turn while only the observation time moves. So the engine opens a reader per step and a
test asserts the horizons it asked for.

The dataset carries late corrections, and at the 17:00 step **every one of the 37 SPX contracts
has a revised quote that had not arrived yet**. Running the same strategy both ways gives a net
of `-25,758` honestly and `-32,022` with one late reader: a difference of `24%`. Which
direction it went is the part worth keeping. **Lookahead did not flatter the backtest, it made
it worse**, because the revisions happened to move against the position — and a disappointing
result is the case nobody goes looking for a bug in. Lookahead is an uncontrolled error of
arbitrary sign, not a bias toward optimism.

One number from that run belongs here rather than in the module doc. Opening a short straddle
in eight contracts cost `26,820` against a gross profit of `1,062` from holding it: **the cost
of crossing was twenty-five times the profit of the position**. It is a fixture and not a
result, but it is the shape of the go/no-go this step is scheduled before.

**Done when** simulated fill distributions reproduce observed paper fills, and until then,
when every quoted result carries the pessimistic cost assumption explicitly. **The
pessimistic model and the loop are in place**; reproducing observed fills waits on paper
trading, exactly as the bootstrap problem above predicts.

---

## 7. Research integrity, before the search rather than after it

*Extends Phase 6. **Done**, and landed out of order as this section instructs. See
`docs/research.md`.*

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

The registry's shape came from one question: what stops a count from being quietly wrong? Not
falsification, which is obvious, but declining to write down a configuration whose result was
disappointing. So a trial is recorded in two entries and the first is written **before the
outcome exists**; `trial_count` counts trials started, never completed, and a trial abandoned
halfway stays in the count. Entries are hash-chained, so an edit or a deletion in the middle
is reported with the sequence where it starts. Truncation from the end is not detectable from
the log alone and the documentation says so rather than implying otherwise; that is what
carrying the tip hash on a published result is for.

The measurement that justifies all of it, on three years of daily returns with realistic
moments: an annualised Sharpe of `1.5` is significant at 95% if it was the only thing tried
(`p = 0.994`), and **not significant by the tenth trial** (`p = 0.830`). The bar rises from
`0.95` to `1.86` to `2.41` as the count goes from one to ten to a hundred. Nobody recovers
that count honestly after the fact, which is exactly why this step jumps the order.

Cross-validation then measured what the count actually costs. A genuine edge of 1.0 annualised
Sharpe hidden among `N - 1` noise configurations, four years of daily data, selected by
walk-forward:

| configurations | best in-sample Sharpe | walk-forward out of sample | folds that found it |
|---|---|---|---|
| 2 | `1.15` | `1.08` | 100% |
| 10 | `1.24` | `0.98` | 55% |
| 50 | `1.31` | `0.22` | 25% |
| 100 | `1.34` | `0.52` | 15% |

**The number you would have quoted barely moves while the number you would have got
collapses.** The in-sample best drifts *up* as the search widens, which is exactly what makes
a widening search feel like progress.

One honest limit is recorded rather than smoothed over: the overfitting probability is
calibrated — it averages `0.51` to `0.55` on pure noise across 40 datasets, against a theoretical
`0.5` — but its spread across datasets is about `0.20`. A single estimate of `0.35` is not
meaningfully different from `0.5`, and with only two configurations competing the statistic
collapses to a count of coin flips. It answers whether selection beats chance, and it answers
coarsely.

**Done when** the registry exists, results are reproducible from their pins, and no strategy
can be promoted without a deflated Sharpe above a threshold stated in advance. **Done**, with
one seam left open and named: nothing yet writes per-trial return series to a store the
registry can point at, so cross-validation takes them as an argument. That store belongs with
the backtester in step 6.

---

## 8. Portfolio construction and hedging solved as one problem

*Extends Phase 5 and 6. **Done**, see `spec/interfaces/random_source.md`,
`spec/interfaces/hedging.md` and `spec/interfaces/portfolio.md`. Now run end to end on a dated
dataset in `docs/history_run.md`, where the allocator turned the same signal from a loss of
`156,179` into a profit of `45,098` and declined the single name outright.*

Not signal ranking. A constrained optimization: maximize expected residual convergence net
of modeled cost, subject to vega, gamma, and theta budgets, factor neutrality from step 5,
per-name concentration limits, and liquidity.

Hedging is the other half of the same problem. Optimal delta bands under proportional
transaction costs are a control problem with known asymptotic solutions, Whalley-Wilmott and
Zakamouline among them, and both beat a fixed band. But the hedging cost depends on gamma,
and gamma is exactly what the optimizer is allocating, so solving them separately leaves the
optimizer allocating risk it has mispriced. Solve jointly, or iterate to a fixed point.

The hedging half landed first and the measurement nearly went the wrong way. Scored on 4000
paths, the best fixed band beat Whalley-Wilmott on certainty equivalent, `-0.2194` against
`-0.2431`, which reads as a refutation of the sentence above. It is not. **That fixed band was
chosen by searching eight widths on the very paths it was then scored on**, and
Whalley-Wilmott used no paths at all. Scored on paths the tuning never saw, the fixed band
falls to `-0.2701` while Whalley-Wilmott holds at `-0.2576`, and across eight held-out sets the
derived band wins seven.

So the claim survives, and the way it nearly failed is the useful part: the in-sample search
was over **eight** configurations, in a place that does not look like a backtest at all, and it
was still enough to invert the answer. Step 7 is not only about signal search.

One limit is recorded rather than glossed. It took 4000 paths for the head-to-head to resolve;
at 1000 it is a coin flip, four wins in eight. The tests therefore assert the mechanism — that
a tuned band degrades on ten of ten held-out sets, and that its `+0.0602` in-sample edge becomes
`-0.0002` out of sample — rather than the head-to-head, because asserting a coin flip is
asserting noise. **A comparison that needs 4000 paths to separate two policies will not
separate them on one year of daily data.**

Zakamouline is deliberately absent. Its constants would have been reproduced from memory rather
than derivation, and an unverifiable formula in the repository is worse than a missing one.

The allocator then answered the other half. Constraints are handled by projection rather than
penalty, following what `essvi.md` learned about penalties, so every reported book satisfies
every budget by construction. The hedging cost enters the objective through a closed form for
running a Whalley-Wilmott band, **checked against the path simulation** across twenty-seven
combinations of volatility, cost and risk aversion: derived over simulated runs `0.81` to
`1.22`, inside `8%` for most, fraying where the band is widest, which is where an asymptotic
result should.

Eight candidates with similar edges and very different gammas, a 10bp market:

| | edge | spread | hedging | objective | net gamma |
|---|---|---|---|---|---|
| solved separately, then charged | `5.335` | `0.530` | `0.635` | `4.170` | `0.1400` |
| solved jointly | `5.929` | `1.208` | `0.003` | `4.718` | `0.0024` |

**The joint solution is 13% better and it is not a trade-off along one axis.** It collects more
gross edge, pays more than twice the spread, and pays almost no hedging cost, because it found
a combination that keeps the edge while netting the gamma away. The sequential answer was not a
worse point on the same frontier; it was on the wrong frontier.

And one thing worth reading off the same table. The gamma budget was `0.50` and the sequential
book's net gamma was `0.1400`, so **the budget never bound** — the exposure it failed to
control cost `0.635`. Pricing a risk and capping it are different jobs, and a cap that is never
reached does neither.

A defect the obvious test caught. The spread term `|w| * cost` is not differentiable at zero,
and taking its subgradient there as `-cost` makes the gradient at an empty book positive even
when the edge is nothing, so the optimiser walked away from "hold nothing" to a **negative**
objective. The test is the one nobody writes: give every candidate zero edge and check the book
stays empty.

**Done when** the jointly optimized portfolio beats naive ranking with fixed-band hedging on
risk-adjusted terms, out of sample, after costs. **The optimizer, the hedging control, the join
between them, and the end-to-end run are done.** On 120 dated observations the allocator beat
the threshold rule by `201,277` on the index while placing fewer contracts, and refused the
single name whose 3% spread the signal could not pay — see `docs/history_run.md`. It is still
in sample, on synthetic data, and the fill model it all rests on is still uncalibrated.

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
