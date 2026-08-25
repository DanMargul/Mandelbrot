# `essvi`

Below the parity boundary. Three implementations, conformance tested.

The global surface fit: one eSSVI surface calibrated across every expiry at once, judged by
the acceptance test in `svi_surface.md` that was built before it.

## The parameterisation

With `theta` the at-the-money total variance at an expiry, `phi` a curvature scale and
`rho` a correlation:

```
w(k, theta) = (theta / 2) * (1 + rho * phi * k + sqrt((phi * k + rho)^2 + 1 - rho^2))
```

`theta` is free per expiry. `phi` follows a power law and `rho` a linear term structure:

```
phi(theta)  = eta * theta^(-gamma)
rho(theta)  = tanh(c0 + c1 * position(theta))
```

where `position` is the normalised place of `theta` between the first and last expiry, zero
at the front and one at the back. `c1 = 0` recovers SSVI with a constant correlation; a
non-zero `c1` is what makes this eSSVI. So the fit carries `n + 4` parameters for `n`
expiries.

## The exact map to a raw SVI slice

At a fixed `theta` the surface above **is** a raw SVI slice, exactly:

```
a = theta * (1 - rho^2) / 2      b = theta * phi / 2      rho_svi = rho
m = -rho / phi                   sigma = sqrt(1 - rho^2) / phi
```

Two properties make this map worth stating rather than deriving at each call site. The
validity floor is `a + b * sigma * sqrt(1 - rho^2) = theta * (1 - rho^2)`, which is
non-negative for every reachable `theta` and `rho`, so **every point the optimiser can reach
is a valid SVI slice by construction**. And `w(0) = theta` identically, so the parameter
named "at-the-money total variance" is exactly that. Both are asserted directly.

The fit therefore reports raw SVI slices alongside its own parameters, and those slices feed
`scan-svi-surface` unchanged.

## Constraints by construction, and the one that could not be

The optimiser works in unconstrained coordinates, following the same discipline as
`svi_calibration.md`:

| quantity | construction | what it guarantees |
|---|---|---|
| `theta_j` | cumulative sum of bounded exponentials | positive and **strictly increasing in expiry** |
| `gamma` | `(1 + tanh(u)) / 2` in `(0, 1)` | `d(theta * phi)/d(theta) >= 0`, the first calendar condition |
| `rho` | `tanh`, clamped to `MAXIMUM_CORRELATION` | inside the SVI validity region |
| `eta` | a bounded **fraction of a bound**, see below | the Gatheral-Jacquier butterfly conditions |

### The butterfly bound, and why a penalty was not enough

The first implementation enforced the butterfly condition with a penalty on Durrleman's
function over a grid, exactly as the slice calibrator does. **The acceptance test caught it
failing.** Fed observations sampled from a badly arbitrageable surface, the fit reduced the
violation from `-2.29` to `-0.022` and then stopped: the data pull and the penalty balanced
at a point that was still arbitrageable. A penalty is a soft constraint and it loses when
the data pulls hard enough.

The fix is to make it unreachable. Gatheral and Jacquier give sufficient conditions for an
SSVI slice to be free of butterfly arbitrage:

```
theta * phi * (1 + |rho|) < 4        and        theta * phi^2 * (1 + |rho|) <= 4
```

Both are bounds on `phi` given `theta` and `rho`, so with the power law they become a bound
on `eta`:

```
eta <= min over expiries of  min( 4 / (theta^(1 - gamma) * (1 + |rho|)),
                                  sqrt(4 / (theta^(1 - 2 * gamma) * (1 + |rho|))) )
```

`eta` is then parameterised as a fraction of that bound, so every coordinate the simplex can
reach describes a butterfly-free surface. This costs something real and it should be said
plainly: the conditions are **sufficient, not necessary**, so the reachable set is smaller
than the set of arbitrage-free surfaces. That is the trade — a guarantee in exchange for
some reach.

### The calendar condition could not be moved into the construction

`theta` increasing and `gamma` in `(0, 1)` give calendar monotonicity for constant `rho`,
because the second Gatheral-Jacquier condition reduces to `1 - gamma <= (1 + sqrt(1 - rho^2)) / rho^2`
and the right side is never below one. A **varying** `rho` breaks that argument, and eSSVI
exists precisely to let `rho` vary. So the calendar condition stays a penalty on the fitted
slices, and the measurement below says what that costs.

## What a penalty converges to

Pushed against data sampled from an arbitrageable surface, the calendar penalty does not
converge to a satisfied constraint. It converges to the **boundary**, and at the boundary
the sign is decided by rounding:

| `CALENDAR_PENALTY_WEIGHT` | minimum total variance time slope | verdict |
|---|---|---|
| `1e4` | `-2.96e-04` | violated |
| `1e6` | `-9.37e-08` | violated |
| `1e8` | `+9.95e-11` | free |
| `1e10` | `-1.01e-11` | violated |

Raising the weight does not fix the fit; it walks the answer to zero from alternating sides.
Choosing `1e8` because it happened to pass would be tuning a test until it goes green. **The
weight is left at `1e4` and the verdict is reported instead.**

## The calibrator is judged by the acceptance test, in the result

`calibrate_essvi_surface` runs `scan_svi_surface` on its own fitted slices and carries the
answer:

- `surface_minimum_durrleman_value` and `surface_minimum_total_variance_time_slope`
- a status of `arbitrage_not_eliminated` whenever that scan does not come back
  `arbitrage_free_on_grid`

So the contract is: **the fit either returns a surface that passes the acceptance test, or
it says it could not.** A caller cannot ship an arbitrageable surface by forgetting to check,
because the check is not a separate step.

Measured across the input regimes:

| input | result |
|---|---|
| samples of an exact eSSVI surface | recovered to `9.7e-16` weighted RMS, `converged` |
| ordinary index smiles, clean and at 2% noise | `converged`, arbitrage free |
| samples of a **calendar-violating** surface | `converged`, arbitrage free — the fit repairs it |
| samples of a badly **butterfly-violating** surface | `arbitrage_not_eliminated`, reported |

The third row is the useful one. The input surface falls in total variance; the fitted
surface does not, and the acceptance test confirms it on a dense grid.

## What conformance can and cannot compare

The slice calibrator established that for a non-convex fit the parameters are a coordinate
system and the curve is the answer. The surface fit repeats it and then adds a limit.

Measured across the fixture, on every case that converged:

| quantity | worst cross-track difference |
|---|---|
| `fitted_surface` | `1.3e-08` relative |
| `curvature_scale`, `power_law_exponent`, `correlation_intercept` | `6.2e-09` relative |
| `correlation_slope` on a surface whose true slope is zero | `9.0e-01` relative, `1.8e-13` absolute |
| `simplex_iterations` | `7.6e-02` relative |

`correlation_slope` is the coordinate-system lesson in its clearest form: when the true
correlation is flat the slope is not identified, both tracks land on numbers that are zero
for every practical purpose, and their *relative* difference is ninety percent. It is
compared with an absolute floor for exactly that reason.

**And one case cannot be compared at all.** On the badly butterfly-violating input, where
the fit reports `arbitrage_not_eliminated`, the two tracks land on surfaces differing by
`98%`. That is not a defect: the objective there has many near-equal minima and the simplex
picks one chaotically, so there is no single answer for conformance to compare. Such cases
are therefore covered by unit tests in all three tracks rather than by the shared fixture,
and the fixture asserts that every case in it converged. **Conformance compares the answer,
and a fit that reports it could not eliminate arbitrage is telling you there is not one.**

## The shared simplex

The Nelder-Mead in `svi_calibration` was fixed at five parameters; this fit needs `n + 4`.
It was extracted into a `simplex` module taking a callable and a seed of any length, and
both calibrators now use it. The extraction was verified to be arithmetically inert: the
`calibrate-svi-slice` golden fixture regenerates **byte for byte**, and the native track's
output is byte-identical before and after.

## Constants

```
MINIMUM_ESSVI_SLICES         = 2
GLOBAL_PARAMETER_COUNT       = 4
BUTTERFLY_PENALTY_WEIGHT     = 1e4
CALENDAR_PENALTY_WEIGHT      = 1e4
PENALTY_GRID_STEPS           = 64
MAXIMUM_POWER_LAW_EXPONENT   = 1.0
DURRLEMAN_SUFFICIENT_BOUND   = 4.0
MAXIMUM_CURVATURE_FRACTION   = 0.9999
MINIMUM_CURVATURE_FRACTION   = 1e-12
SEED_CORRELATIONS            = (-0.7, -0.3, 0.0)
SEED_CURVATURE_FRACTIONS     = (0.1, 0.3, 0.6)
```

`MINIMUM_OBSERVATIONS`, `MAXIMUM_CORRELATION` and the reference log-moneyness grid are shared
with `svi_calibration`; the simplex constants are shared with `simplex`.

`MINIMUM_CURVATURE_FRACTION` is the third defect of a family this repository has now found
three times. `tanh` saturates, so far enough out the curvature fraction is **exactly zero**,
and `log(0)` raises `ValueError` in Python where C++ `std::log` returns negative infinity and
carries on. The two tracks did not merely disagree, they failed differently. Clamping the
fraction at both ends removes it, and the extreme-coordinate test that found it now runs in
all three tracks.

## Verb

`calibrate-essvi-surface`, input `essvi_calibration_request/v1`, output
`essvi_calibration_result/v1`.

## Invariants under test

- a surface sampled from an exact eSSVI surface is recovered to `1e-10` weighted RMS, with
  every global parameter back to `1e-6` relative
- the fitted surface passes `scan_svi_surface` whenever the status is `converged`
- calendar arbitrage present in the observations is repaired by the fit
- a fit that cannot eliminate arbitrage reports `arbitrage_not_eliminated` rather than
  returning a surface that fails the acceptance test
- the at-the-money total variance is strictly increasing at every reachable coordinate,
  including coordinates far outside any fit
- every reachable coordinate maps to a valid SVI slice, and `w(0) = theta` exactly
- the curvature bound keeps both Gatheral-Jacquier conditions satisfied at every expiry
- the reported parameters reproduce the reported slices exactly
- fewer than two slices, or any slice with fewer than `MINIMUM_OBSERVATIONS` points, is
  reported rather than fitted
- expiries out of order, or an inverted penalty range, are rejected
