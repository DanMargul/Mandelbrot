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
