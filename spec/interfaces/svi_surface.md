# `svi_surface`

Below the parity boundary. Three implementations, conformance tested.

A term structure of SVI slices treated as one surface, and the diagnostics that decide
whether that surface admits butterfly or calendar arbitrage. `svi.md` covers a single
expiry; this covers what happens between expiries, which is where the interesting failures
live.

## Types

```
SviSurfaceStatus = "arbitrage_free_on_grid" | "butterfly_arbitrage_found"
                 | "calendar_arbitrage_found" | "invalid_surface"

SviSurfaceSlice:
    years_to_expiry: float
    parameters: SviParameters

SviSurfaceScan:
    slice_count: int
    scan_steps: int
    time_steps_per_interval: int
    minimum_durrleman_value: float
    log_moneyness_at_minimum_durrleman_value: float
    years_to_expiry_at_minimum_durrleman_value: float
    minimum_risk_neutral_density: float
    minimum_total_variance_time_slope: float
    log_moneyness_at_minimum_time_slope: float
    years_to_expiry_at_minimum_time_slope: float
    minimum_local_variance: float
    log_moneyness_at_minimum_local_variance: float
    years_to_expiry_at_minimum_local_variance: float
    worst_local_variance_round_trip_error: float
    log_moneyness_at_worst_round_trip_error: float
    round_trip_point_count: int
    status: SviSurfaceStatus
```

`invalid_surface` exists so the schema can name the condition. Like `invalid_parameters` on
the slice scan it is raised rather than returned: fewer than two slices, a non-positive
expiry, or expiries that do not strictly increase are programming errors.

## The surface between the slices

Slices are given at discrete expiries. Everything between them is defined by interpolation,
and the choice of interpolation is part of the model rather than a detail:

```
w(k, T) = (1 - f) * w_i(k) + f * w_{i+1}(k),    f = (T - T_i) / (T_{i+1} - T_i)
```

Linear in total variance along fixed log-moneyness. `w_k` and `w_kk` interpolate the same
way; `w_T` is therefore constant on each interval and discontinuous at the knots.

**The interpolation is written `(1 - f) * a + f * b`, not `a + f * (b - a)`.** The second
form is exact at `f = 0` and wrong by one ulp at `f = 1`, so a knot shared by two intervals
would take two different values depending on which interval reached it. The tests assert
exact recovery of both endpoints, and that assertion is what caught it.

## The calendar condition

Total variance must not fall as expiry increases. Because `w` is linear in `T` between
knots, `w_T >= 0` on every interval is equivalent to `w_{i+1}(k) >= w_i(k)` at every `k`, so
the condition only has to be checked on adjacent pairs.

The reported quantity is `minimum_total_variance_time_slope`, the smallest `w_T` found. It
is the slope rather than the raw difference because the slope is the numerator of the local
variance and does not shrink just because two expiries are close together.

## Local variance, and why the Dupire round trip is not a third test

Gatheral's local variance in terms of total variance is

```
local_variance(k, T) = w_T / g(k, T)
```

where `g` is exactly Durrleman's function from `svi.md`. The numerator is non-negative
precisely when the calendar condition holds and the denominator precisely when the butterfly
condition holds, so **a non-negative local variance is not an independent third check; it is
the conjunction of the two already being made.** It is reported because it is the quantity
the strategy is implicitly trading and it carries units a reader can reason about.

Where `g` collapses the local variance does not exist. The denominator is floored at
`MINIMUM_DURRLEMAN_DENOMINATOR` so the reported number stays finite and identical across
tracks; on such a surface the status already records the violation and the saturated
magnitude carries no meaning.

### The round trip that is a real check

What does have independent content is checking the algebra above against Dupire's original
formula in price space. Price European options off the surface, then form

```
local_variance = c_T / (0.5 * (c_kk - c_k))
```

on a driftless unit forward, where `c` is the undiscounted option price as a function of log
strike. Agreement between the two routes validates the total-variance form against the
definition it was derived from. Two measurements shaped how it is done.

**It must be run on out-of-the-money options.** Using calls everywhere, the round trip
agrees to `1e-7` near the money and degrades to `4.3e-5` at `k = -1.5`. That is not
truncation, it is cancellation: deep in the money the call price is `O(1)` while its second
difference is `O(1e-4)`, so the subtraction throws away the digits that carry the answer.
Switching to the put below the forward removes the `O(1)` offset and the same point agrees
to `2.7e-9`. Put-call parity is what makes this legitimate: the operator `∂_kk - ∂_k`
annihilates the parity term `1 - e^k` exactly, so the put and the call give the same
density.

**The branch must be chosen once per stencil, not once per evaluation.** Choosing per node
puts a put at `k - h` and a call at `k` and `k + h`, mixing the two sides of the parity
relation inside a single difference: at `k = 0` the round trip is then wrong by a factor of
one. The branch is a property of the stencil centre.

With those two decisions, and steps chosen from the truncation-versus-roundoff curve, the
worst round-trip error across the arbitrage-free fixture cases is `2.4e-6`.

The round trip is skipped where the analytic local variance is below
`ROUND_TRIP_LOCAL_VARIANCE_FLOOR`, and `round_trip_point_count` reports how many points were
actually checked. A flat term structure has `w_T = 0` everywhere and so checks zero points,
which is the honest count rather than a silent pass. On a surface that is not arbitrage-free
the round trip is meaningless — there is no valid price surface to round-trip against — and
the fixture asserts the budget only for surfaces that scan clean.

## What the interior of an interval is for

Checking the knots is not enough, and this is the calendar-direction version of the lesson
already recorded for the slice scan: **the region is checked at the parameters and violated
between them.**

Two SVI slices can each be butterfly-free, their term structure can be calendar-monotone,
and the linear-in-total-variance surface between them can still admit butterfly arbitrage.
Searching 20,000 random pairs of individually arbitrage-free slices found 66 such pairs, a
third of a percent. The fixture carries one of them:

| | minimum `g` on `[-1, 1]` |
|---|---|
| near slice alone, 20000-step scan | `+2.60e-02` |
| far slice alone, 20000-step scan | `+2.38e-01` |
| surface between them, at `T = 0.310` | `-3.14e-02` |

Both knots are comfortably clean. The surface between them has a negative risk-neutral
density. Nothing evaluated only at the two expiries can see it.

## Refinement in both directions

The slice scan established that a grid alone understates the depth of a violation, and that
the depth matters as much as the detection. In two dimensions that is worse, and fixing it
took two attempts.

Refining in log-moneyness at each sampled maturity, then refining maturity at the
log-moneyness where the grid was worst, is coordinate descent, and it gets stuck. On the
fixture case above the true minimum sits at the edge of the range, `k = +1.0`; the maturity
refinement runs at `k = +0.957` because that is where the grid best happened to land, and
converges to a maturity whose own minimum is `1.5%` shallower.

The fix is to refine the right object. Define the profile

```
phi(f) = the refined minimum of g over the log-moneyness grid at fraction f
```

and golden-section `phi` rather than `g` at a frozen `k`. Each evaluation costs a full
log-moneyness scan, which is why it is worth stating that the cost is bounded and small: a
few tens of milliseconds per interval.

The result is worth the trouble, because it removes both grids from the answer:

| | minimum `g` |
|---|---|
| grid alone, 256 by 8 | `-0.022463` |
| refined in log-moneyness only | `-0.030919` |
| profile refined in maturity | `-0.031382` |

The grid alone misses `28%` of the depth. And the reported depth is now identical to
machine precision for every combination of `scan_steps` in `(16, 256, 512)` and
`time_steps_per_interval` in `(1, 4, 8, 16)`, which is asserted in all three tracks. The
grids choose where to start looking; they no longer choose the answer.

## Status precedence

A surface can violate both conditions. Butterfly takes precedence in the reported status
because a negative density is a violation at a point, while a calendar violation is a
statement about a pair of slices, and it is the density the strategy trades. Both
`minimum_durrleman_value` and `minimum_total_variance_time_slope` are always reported, so
the status never hides the other number.

The name is `arbitrage_free_on_grid`, never `arbitrage_free`, for the reasons given in
`svi.md`, and now in two dimensions rather than one.

## Constants

```
DEFAULT_SURFACE_SCAN_STEPS         = 256
MINIMUM_SURFACE_SCAN_STEPS         = 2
MINIMUM_SURFACE_SLICES             = 2
DEFAULT_TIME_STEPS_PER_INTERVAL    = 8
MINIMUM_TIME_STEPS_PER_INTERVAL    = 1
CALENDAR_TOLERANCE                 = -1e-12
MINIMUM_DURRLEMAN_DENOMINATOR      = 1e-12
ROUND_TRIP_MONEYNESS_STEP          = 1e-4
ROUND_TRIP_TIME_STEP               = 1e-5
ROUND_TRIP_LOCAL_VARIANCE_FLOOR    = 1e-6
```

Adjacent expiries must be more than `2 * ROUND_TRIP_TIME_STEP` apart, so the round trip's
central difference in maturity cannot step outside the interval it was taken in.

`REFINEMENT_PASSES` and `GOLDEN_SECTION_RATIO` are shared with `svi.md`, and for the same
reason: a fixed pass count rather than a convergence test, so all three tracks perform an
identical number of identical evaluations.

## Verb

`scan-svi-surface`, input `svi_surface_scan_request/v1`, output `svi_surface_scan_result/v1`.

## Conformance

Unlike calibration, this scan is a fixed sequence of deterministic evaluations with no
chaotic search inside it, so there is nothing here that forces the tracks apart. Across the
36 fixture cases all three tracks agree **bit for bit on every field**, including the
argmin locations and the round-trip error. The tolerances in `spec/tolerances.toml` are set
tight rather than fitted to an observed spread.

## Invariants under test

- a calendar-monotone term structure of clean slices reports `arbitrage_free_on_grid`
  with a positive density, a positive time slope, and a positive local variance
- a slice that falls in total variance reports `calendar_arbitrage_found`, while every one
  of its slices scans clean on its own
- two individually arbitrage-free knots can interpolate into `butterfly_arbitrage_found`,
  strictly between the two expiries, with the calendar condition still satisfied
- an unchanged term structure sits exactly on the calendar boundary: a time slope of
  exactly zero is not a violation
- the interpolation reproduces both knots exactly, not to within an ulp
- local variance equals the time slope over the Durrleman function at every point
- the price-space route reproduces the total-variance route to `1e-5` away from the wings
- the reported depth is unchanged by either grid resolution
- a finer grid never reports a shallower violation
- expiries closer together than the round-trip step are rejected rather than differenced
  across an interval boundary
