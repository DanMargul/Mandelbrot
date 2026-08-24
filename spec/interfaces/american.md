# `american`

Below the parity boundary. Three implementations, conformance tested.

Prices options that may be exercised before expiry, and reports the early exercise premium
as a quantity in its own right rather than as a correction buried inside a price.

## Why the premium is a first-class output

Index options are European and Phase 1 could ignore this entirely. Single names are not, and
the whole of steps 5 and 9 needs them.

The early exercise premium is worth naming separately because it is the only part of an
American price that depends on the zero rate and the carry rate **individually** rather than
only through the forward. A European price depends on `r` and `q` solely through
`F = S exp((r - q) T)` and `DF = exp(-r T)`, so no European quote can separate them. An
American price can, which is what makes the diagnostic in step 3 of `docs/program.md`
possible at all.

## Types

```
ExerciseStyle = "european" | "american"

LatticeInputs:
    spot_price: float
    strike: float
    years_to_expiry: float
    volatility: float
    zero_rate: float
    carry_rate: float
    option_type: OptionType
    exercise_style: ExerciseStyle
```

## Functions

```
cox_ross_rubinstein_price(inputs: LatticeInputs, steps: int) -> float
richardson_extrapolated_price(inputs: LatticeInputs, base_steps: int) -> float
early_exercise_premium(inputs: LatticeInputs, base_steps: int) -> float
```

## Constants

```
RICHARDSON_BASE_STEPS  = 128
MINIMUM_LATTICE_STEPS  = 2
MAXIMUM_LATTICE_STEPS  = 4096
```

`RICHARDSON_BASE_STEPS` is part of the contract. The lattice price depends on the step count,
so three tracks agreeing requires them to use the same one.

## The lattice

Cox-Ross-Rubinstein, with the up factor from the volatility and the risk-neutral probability
from the carry:

```
dt   = T / steps
u    = exp(sigma * sqrt(dt))
p    = (exp((r - q) * dt) - 1/u) / (u - 1/u)
node price at level i, node j  =  S * exp(sigma * sqrt(dt) * (2j - i))
```

### Why the spot ladder is precomputed

Every node price is read from a table of `2 * steps + 1` values built once with scalar
`exp`, and the backward induction then performs only addition, multiplication and
comparison.

This is what makes the three tracks agree bit for bit, and they do: across the 540 case
lattice fixture the largest relative difference between the pure Python and pure C++ tracks
is exactly zero on every output field.

Addition, multiplication and maximum are exact IEEE operations, so a scalar loop and an
array operation over the same values give identical results. `exp` is not: a vectorised
`exp` may differ from the scalar library one by an ulp, and over a hundred and twenty-eight
backward steps that difference compounds. Confining every transcendental call to a table
built once with scalar `exp` removes the problem rather than budgeting for it, and leaves
the Python track free to be vectorised later without breaking parity.

## The Black-Scholes terminal correction

The plain lattice converges as `O(1/steps)`: on a one-year at-the-money option the error is
`-3.74e-2` at 64 steps, `-9.36e-3` at 256 and `-2.34e-3` at 1024, falling fourfold for each
fourfold refinement.

Richardson extrapolation, `2 * price(2N) - price(N)`, cancels that first-order term and on
that one option looks excellent. It is not enough on its own. Binomial convergence is not
smooth: the error oscillates with the step count because the strike falls in a different
place between lattice nodes each time, and extrapolating through an oscillation does not
remove it. Measured across the whole 552-case fixture, plain Richardson at 64 steps was still
wrong by `2.07e-3` of spot in the worst case, on a long-dated high-volatility wing. That is
about 0.4 volatility points, which is larger than the signals this platform is being built to
find.

The fix is to replace the final backward step with a closed-form one-step Black-Scholes
value at each node. The terminal payoff kink is what generates the oscillation, and
evaluating that last step analytically removes it. Combined with Richardson, the worst error
over the same fixture fell from `2.07e-3` to `1.81e-5` against the closed form, a factor of
114.

`RICHARDSON_BASE_STEPS` is 128 rather than 64 for the same reason, chosen from measurement
rather than habit: on the worst case in the fixture, an American put whose free boundary the
correction cannot smooth, 64 steps gives `1.37e-4` of spot and 128 gives `2.83e-5` for four
times the work. That is roughly 0.006 volatility points of pricer error, comfortably below
anything the strategy is trying to measure.

The residual error is concentrated in American puts rather than European options, because
the early exercise boundary is a free boundary that no terminal correction aligns to the
lattice. It is also largely common to a call and its matching put, so it cancels in the
call-put comparison that step 3 of `docs/program.md` is really after.

## Preconditions

`spot_price > 0`, `strike > 0`, `years_to_expiry >= 0`, `volatility >= 0`, and `steps` inside
the stated bounds. Violations raise; they are programming errors. `years_to_expiry == 0` and
`volatility == 0` return intrinsic value.

## Invariants under test

- a European lattice converges to the Black-Scholes price as the step count rises
- the corrected lattice with Richardson is closer to Black-Scholes than a plain lattice of
  1024 steps
- the terminal correction alone beats the plain lattice at the same step count
- every price agrees with a lattice four times finer to within `1e-4` of spot
- an American price is never below its European counterpart
- an American **call** on a zero-carry underlying has a premium of exactly zero, because
  early exercise is never optimal there and the lattice must reproduce that identically
  rather than approximately
- an American put on a positive rate carries a strictly positive premium
- an American call on a dividend-paying underlying carries a strictly positive premium
- the premium is zero by construction whenever `exercise_style` is `european`

## Verb

`price-american-options`, input `american_pricing_request/v1`, output
`american_pricing_result/v1`. The verb always uses `RICHARDSON_BASE_STEPS`, so the step count
is not a request field and cannot drift between tracks.
