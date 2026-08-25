# `svi`

Below the parity boundary. Three implementations, conformance tested.

The raw SVI parameterisation of a single expiry slice, and the diagnostics that decide
whether that slice admits butterfly arbitrage.

## Why the checker is built before the calibrator

A calibration is only as good as the test it has to pass. Fitting first and checking later
invites the check to be relaxed until the fit passes, which is exactly backwards. So the
acceptance test exists first, and the calibrator in the next increment will be judged by it.

## Types

```
SviStatus = "arbitrage_free_on_grid" | "butterfly_arbitrage_found" | "invalid_parameters"

SviParameters:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

SviSliceScan:
    minimum_durrleman_value: float
    log_moneyness_at_minimum: float
    minimum_total_variance: float
    minimum_risk_neutral_density: float
    scan_steps: int
    status: SviStatus
```

## The parameterisation

With `k` the log moneyness `log(K / F)` and `w` the total implied variance `sigma^2 * T`:

```
x  = k - m
s  = sqrt(x^2 + sigma^2)
w  = a + b * (rho * x + s)
w' = b * (rho + x / s)
w" = b * sigma^2 / s^3
```

Working in total variance rather than volatility is what makes the calendar condition in the
next increment a simple monotonicity in `T`, and it is the form the arbitrage conditions are
naturally stated in.

## Parameter validity

`b >= 0`, `-1 < rho < 1`, `sigma > 0`, and `a + b * sigma * sqrt(1 - rho^2) >= 0` so the
minimum of `w` is not negative. Violations raise; they are programming errors rather than
market conditions.

## Butterfly arbitrage and the density are the same test

Durrleman's function:

```
g(k) = (1 - k * w' / (2w))^2 - (w'^2 / 4) * (1 / w + 1 / 4) + w" / 2
```

The risk-neutral density implied by the slice is

```
p(k) = g(k) * exp(-d2^2 / 2) / sqrt(2 * pi * w),    d2 = -k / sqrt(w) - sqrt(w) / 2
```

Everything multiplying `g` is strictly positive, so **a non-negative density and a
non-negative Durrleman function are the same condition**. Both are reported, because the
density carries the units a reader can reason about while `g` is the quantity the test
actually evaluates.

## Scanning, and what the scan can honestly claim

`scan_svi_slice` evaluates `g` on a uniform grid, then refines around the lowest grid point
with a golden-section search on the bracketing interval.

The refinement is not decoration. On a deliberately arbitrageable slice the true minimum is
`-2.293805`; a 16-step grid alone finds only `-1.638486`, missing forty percent of the depth,
and even a 1024-step grid stops at `-2.293796`. Reporting the depth of a violation matters as
much as detecting it, because the depth is what says whether the fit is slightly imperfect or
badly wrong.

**The status is `arbitrage_free_on_grid`, not `arbitrage_free`, and the name is the claim.**
A finite scan cannot prove the absence of a violation between its points, and cannot say
anything at all outside the range it was given. `g` is smooth, so a violation narrow enough
to hide between refined grid points is too narrow to trade, but the honest statement is still
"no violation found here" rather than "none exists".

## Constants

```
DEFAULT_SCAN_STEPS   = 512
MINIMUM_SCAN_STEPS   = 2
REFINEMENT_PASSES    = 60
GOLDEN_SECTION_RATIO = 0.6180339887498949
BUTTERFLY_TOLERANCE  = -1e-12
```

`REFINEMENT_PASSES` is fixed rather than driven by a convergence test so that all three
tracks perform an identical number of identical evaluations.

## Verb

`scan-svi-slice`, input `svi_scan_request/v1`, output `svi_scan_result/v1`.

## Invariants under test

- a slice with a valid shape reports `arbitrage_free_on_grid` with a positive density
- a slice with curvature too large for its level reports `butterfly_arbitrage_found`
- the reported minimum is never above the smallest value on the grid
- refinement finds a strictly lower minimum than a coarse grid alone on a violating slice
- the density and the Durrleman function agree on sign at every point
- `total_variance` is recovered by `implied_volatility` through `w = sigma^2 * T`

---

# Calibration

```
SviCalibrationStatus = "converged" | "too_few_observations" | "simplex_budget_exhausted"

SliceObservation:
    log_moneyness: float
    total_variance: float
    weight: float

calibrate_svi_slice(observations, lowest_log_moneyness, highest_log_moneyness) -> SviCalibration
```

Weighted least squares in total variance, plus a penalty on any butterfly violation over a
fixed grid, minimised by Nelder-Mead from twelve deterministic starting points.

## Constraints by construction rather than by penalty

The optimiser works in unconstrained coordinates that cannot produce an invalid slice:

```
minimum_variance = exp(u0)      b = exp(u1)     rho = tanh(u2)
m                = u3           sigma = exp(u4)
a                = minimum_variance - b * sigma * sqrt(1 - rho^2)
```

Solving for the minimum of `w` and deriving `a` from it means `a + b sigma sqrt(1 - rho^2)`
is positive for every point the optimiser can reach, so the level constraint never has to be
enforced. Only the butterfly condition needs a penalty, because it is not expressible as a
box on the parameters.

## The overflow that conformance caught

`exp` of an unbounded coordinate overflows. Two separate defects followed, and neither would
have surfaced in a single-track project:

At moderate extremes the objective returned `NaN`, which then flowed into the vertex ordering
and corrupted the simplex silently. Further out, **Python's `math.exp` raises `OverflowError`
where C++ `std::exp` returns infinity**, so the two tracks did not merely disagree, they
failed in different ways: one raising, one continuing.

Both are fixed by clamping the exponent argument to `MAXIMUM_LOG_PARAMETER = 30`, which
bounds every reachable parameter far outside any plausible fit while keeping the objective
finite.

A third defect of the same family sat next to them. `tanh` saturates: `tanh(x)` is **exactly
`1.0`** in double precision for `x` above about 19, so the correlation transform could return
`rho = 1` and make `sqrt(1 - rho^2)` degenerate, which is outside the SVI validity region the
transform exists to guarantee. `rho` is now clamped to `MAXIMUM_CORRELATION = 0.9999` after
the `tanh`, explicitly rather than by trusting the saturation point.

None of these three ever bind on a real fit; the seeds start at `|rho| <= 0.7` and converge
inward. They are reachable only when the simplex throws a vertex far out during expansion,
which it routinely does.

## What conformance compares, and why it is not the parameters

Nelder-Mead is chaotic. A one-ulp difference anywhere flips a branch, after which the simplex
takes an entirely different trajectory to the same minimum. Measured across the fixture, the
two tracks reach objectives agreeing to `1e-13` while their iteration counts differ by about
half a percent.

Chasing that to a bit-identical path was considered and rejected. Even if the current source
were found, the next compiler flag or libm revision reintroduces it; requiring two
independently written implementations to follow identical chaotic trajectories is a contract
that cannot be kept.

The measurement that settles what to do instead:

| slice | worst parameter difference | worst curve difference |
|---|---|---|
| `almost_flat_clean_wide` | `1.49e-02` | `3.37e-16` |
| worst across the fixture | `1.49e-02` | `5.76e-08` |

On an almost flat smile the parameters are barely identified: many `(a, b, rho, m, sigma)`
combinations describe the same curve, and the two tracks land on genuinely different ones
that agree to machine precision on the surface they produce.

**So the parameters are a coordinate system, and the curve is the answer.** The result
carries `fitted_curve`, the total variance at seventeen fixed reference points, and that is
what conformance compares tightly at `1e-6`. The parameters are still reported, because
downstream work needs them, but at a deliberately loose `5e-2`, and `simplex_iterations` is a
path diagnostic compared only to within a factor of two.

The general lesson is worth keeping: **conformance must compare the answer, not the route to
it, and for a non-convex fit the answer is the curve.**

`spec/tolerances.toml` is authoritative and the conformance runner and both Python test
suites read it directly. The Catch2 fixture test in `cpp_pure/tests/test_verbs.cpp` mirrors
the loose set by hand, because reading TOML from C++ would pull in a dependency for a
redundant check. If a tolerance changes here, that list changes too.

## The simplex is shared

The Nelder-Mead itself now lives in a `simplex` module taking a callable and a seed of any
length, because the eSSVI surface fit in `essvi.md` needs `n + 4` parameters rather than
five. The extraction was verified arithmetically inert: this fixture regenerates byte for
byte and the native track's output is byte-identical across the change.

## Constants

```
MINIMUM_OBSERVATIONS         = 5
MAXIMUM_SIMPLEX_ITERATIONS   = 4000
SIMPLEX_SPREAD_TOLERANCE     = 1e-12
SIMPLEX_INITIAL_STEP         = 0.5
BUTTERFLY_PENALTY_WEIGHT     = 1e4
PENALTY_GRID_STEPS           = 64
MAXIMUM_LOG_PARAMETER        = 30.0
MAXIMUM_CORRELATION          = 0.9999
REFERENCE_LOG_MONEYNESS      = 17 points from -0.4 to 0.4
```

## Invariants under test

- a slice sampled without noise is refitted to `1e-6` relative in total variance
- every calibrated slice passes `scan_svi_slice` with `arbitrage_free_on_grid`
- the fitted parameters always satisfy the validity conditions, by construction
- fewer than `MINIMUM_OBSERVATIONS` points reports `too_few_observations` rather than fitting
- an inverted penalty range is rejected
- the coordinate transform yields a valid slice at every reachable coordinate, including
  extremes far outside any fit
