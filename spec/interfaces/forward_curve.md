# `forward_curve`

Below the parity boundary. Three implementations, conformance tested.

Implies the forward and the discount factor for each expiry from the option chain itself,
using put-call parity, rather than assuming them from a rate and a dividend forecast.

## Why this module decides whether anything downstream is real

`C - P = DF * (F - K)` is model-free. It holds whatever the volatility surface looks like,
so the forward it produces owes nothing to a model that could be wrong.

The alternative is to build the forward from a rate curve and a dividend forecast. Both are
estimates, and the dividend estimate in particular is exactly the quantity the options
market prices more accurately than any forecast does. A forward that is wrong by a tenth of
a point shifts every implied volatility in the slice, and that shift then appears in the
surface residuals as a mispricing that is not there. Every downstream result inherits this
number.

## Types

```
ForwardCurveStatus =
    "converged"
  | "too_few_pairs"
  | "degenerate_strike_range"
  | "non_positive_discount_factor"

ParityPair:
    strike: float
    call_minus_put_mid: float
    weight: float

ForwardCurvePoint:
    expiry_date: Date
    years_to_expiry: float
    spot_price: float
    forward: float
    forward_standard_error: float
    discount_factor: float
    discount_factor_standard_error: float
    implied_zero_rate: float
    implied_carry_rate: float
    parity_pair_count: int
    active_pair_count: int
    chi_square_per_degree_of_freedom: float
    discount_factor_is_monotone_in_expiry: bool
    status: ForwardCurveStatus
```

## Functions

```
parity_pairs_from_chain(quotes: list[ContractQuote]) -> dict[Date, list[ParityPair]]
imply_forward_curve(quotes: list[ContractQuote], observation_time: Timestamp) -> list[ForwardCurvePoint]
```

## Constants

Part of the contract. Changing one changes the trimming path and therefore the comparison.

```
MINIMUM_PARITY_PAIRS             = 4
MAXIMUM_TRIMMING_PASSES          = 5
OUTLIER_REJECTION_SIGMAS         = 4.0
MEDIAN_ABSOLUTE_DEVIATION_SCALE  = 1.4826
MINIMUM_HALF_SPREAD              = 1e-8
MINIMUM_COVARIANCE_INFLATION     = 1.0
EXPIRY_SETTLEMENT_HOUR_UTC       = 21
DAYS_PER_YEAR                    = 365.0
```

## Pairing

A strike contributes a pair when it carries both a call and a put, each with
`ask_price >= bid_price` and `ask_price > 0`. A zero bid is legal and kept; a crossed market
is dropped. Adjusted contracts never reach this module because the reader excludes them.

```
strike  = K
y       = call_mid - put_mid
weight  = 1 / (call_half_spread^2 + put_half_spread^2)
```

The weight is the inverse variance of the measured quantity under the assumption that a
mid price is uncertain by about its half spread. It is model-free, which matters: the
weight cannot be `volatility_uncertainty` from `implied_vol`, because that quantity needs a
vega, which needs a forward, which is what this module is computing. See `docs/math.md`.

## Fitting

Weighted least squares of `y` on `K`, **centred on the weighted mean strike**, with
median-absolute-deviation trimming.

Centring is not a stylistic choice. The uncentred normal equations compute the slope as a
difference of two large products, and the slope here is close to `-1`, so the cancellation
is severe. Measured across the tracks, centring improved agreement on the discount factor
from `2.5e-13` to `2.3e-16` and on the implied carry rate from `4.3e-10` to `2.8e-13`, a
factor of a thousand in both cases. It also removes the slope-intercept covariance term,
because in the centred parameterisation the slope and the weighted mean value are
uncorrelated:

```
mean_strike = sum(w * K) / sum(w)
mean_value  = sum(w * y) / sum(w)
slope       = sum(w * (K - mean_strike) * (y - mean_value)) / sum(w * (K - mean_strike)^2)

discount_factor = -slope
forward         = mean_strike - mean_value / slope

var(slope)      = inflation / sum(w * (K - mean_strike)^2)
var(mean_value) = inflation / sum(w)
var(forward)    = var(mean_value) / slope^2 + mean_value^2 * var(slope) / slope^4
```

The trimming loop, in the same parameterisation:

```
active = all pairs
repeat up to MAXIMUM_TRIMMING_PASSES:
    fit       = centred weighted least squares over active
    residuals = y - fit.value_at(K) over active
    scale     = MEDIAN_ABSOLUTE_DEVIATION_SCALE * median(|residual - median(residual)|)
    if scale <= 0: stop
    kept = { i in active : |residual_i - median(residual)| <= OUTLIER_REJECTION_SIGMAS * scale }
    if |kept| < MINIMUM_PARITY_PAIRS or |kept| == |active|: stop
    active = kept
```

`median` is defined as: sort ascending; for an odd count take the middle element, for an
even count take the arithmetic mean of the two central elements. It is stated because three
implementations must agree on it and language libraries do not.

## Uncertainty

The covariance comes from the weighted normal equations, inflated when the fit is worse than
the weights predict but **never deflated when it is better**:

```
chi_square_per_degree_of_freedom = sum(w * residual^2) / (active_count - 2)
covariance_inflation             = max(chi_square_per_degree_of_freedom, 1.0)
```

The floor is the important part, and it was put there by measurement rather than by taste.
With plain chi-square scaling the reported discount factor error was understated by up to a
factor of fourteen against known ground truth.

The cause is that **a chi-square computed after outlier trimming is optimistically small,
because trimming removed exactly the points that would have inflated it.** Selecting the
points that agree and then using their agreement as evidence of precision is circular. So
the fit quality is allowed to widen an error bar and never to narrow one.

`chi_square_per_degree_of_freedom` is still reported, unscaled, as a diagnostic. A value far
above one means the quotes in that slice do not satisfy parity and something is wrong with
the data rather than with the fit.

The consequence is error bars that are conservative by roughly a factor of three, because a
half spread is an upper bound on the uncertainty of a mid rather than an estimate of it.
That is the right direction to be wrong in for a quantity whose entire job is to say how
much the forward can be trusted.

`forward_standard_error` follows by the delta method through
`F = mean_strike - mean_value / slope`. In the centred parameterisation there is no
covariance term to carry, which is the second reason for centring.

The implied rates are the worst-conditioned outputs in the module, because
`r = -log(DF) / T` takes the logarithm of a number very close to one and then divides by a
small year fraction. They agree across tracks to `3e-13` relative against `2e-16` for the
discount factor itself, and that six-hundred-fold amplification is the conditioning of the
transformation rather than a defect in any track. Treat them as diagnostics.

## What the numbers are worth

Measured on the synthetic fixture, where the true forward and discount factor are known:

Nine slices, three observation times, two underlyings, three expiries:

| quantity | realized error / reported standard error |
|---|---|
| forward | median 0.15, worst 0.33 |
| discount factor | median 0.25, worst 0.61 |

Every realized error falls inside its reported standard error, with roughly threefold
headroom, so the module's self-assessment is honest and errs toward caution.

**The forward is well determined and the discount factor is not.** A discount factor
uncertain by `2e-3` is a zero rate uncertain by about two percentage points at a
four-week expiry, because the rate error scales as `1/T`. This is not a defect in the
estimator; it is a property of the data. The slope of `C - P` against `K` is close to `-1`
for any short-dated chain, and the strike range is not wide enough to pin the small
deviation from it.

Supplying an external rate instead of implying one was measured and does **not** improve the
forward: the standard error moves from `4.8e-5` to `4.9e-5`. There is therefore no
supplied-rate mode. The two-parameter fit costs nothing, and the implied rate is retained as
a diagnostic rather than as a curve.

The consequence for downstream work is in `docs/math.md`: a discount factor error is a
per-slice level effect that a surface fit largely absorbs, so it is close to harmless for
relative value within an expiry, and it does not cancel across expiries, so calendar
structure needs a real rate curve.

## Errors and failure semantics

| condition | status |
|---|---|
| fewer than `MINIMUM_PARITY_PAIRS` usable pairs | `too_few_pairs` |
| every usable pair at the same strike | `degenerate_strike_range` |
| fitted slope is zero or positive | `non_positive_discount_factor` |

A failed point returns `forward` and `discount_factor` as `0.0`, and every uncertainty,
rate, and fit-quality field as null. It never returns `NaN`, for the reason given in
`spec/interfaces/implied_vol.md`.

## Year fraction

`years_to_expiry` is ACT/365F from the observation time to `EXPIRY_SETTLEMENT_HOUR_UTC` on
the expiry date.

That settlement hour is a **placeholder** and is wrong for real contracts: SPX AM-settled
expiries settle on the opening print, PM-settled ones at the close, and single-name equity
options at the close on a different calendar again. Step 2 against real data must replace
it with a settlement calendar. It is recorded here rather than buried because a wrong
expiry time is indistinguishable from a wrong volatility on the shortest-dated options,
which are precisely the ones most sensitive to it.

## Invariants under test

- the fitted forward recovers the synthetic ground truth to within the reported standard error
- the fitted discount factor recovers ground truth to within the reported standard error
- a deliberately stale, widened quote is trimmed from the active set
- removing the stale quote from the input does not change the fitted forward materially
- `discount_factor_is_monotone_in_expiry` is true on the synthetic fixture
- every non-converged point carries `forward == 0.0` and null uncertainties
- the implied carry rate recovers the synthetic dividend yield to within its own propagated error

---

# American quotes are refused, not fitted

`C - P = DF * (F - K)` is a **European** relation. For American contracts early exercise
breaks it into an inequality, `S - K <= C - P <= S - K * DF`, and the regression above has no
right to be run on such quotes at all.

This was not caught by reasoning about it. It was caught by pricing a synthetic American
chain with known parameters and looking at what the estimator said:

| input | fitted forward | error | fitted discount factor |
|---|---|---|---|
| raw American quotes | 224.3261 | `+4.75e-04` relative | **1.007720** |
| after stripping the premium | 224.2354 | `+7.07e-05` relative | 0.997706 |
| truth | 224.2196 | | 0.996726 |

The discount factor came out **above one**. At a positive interest rate that is free money,
and the module reported it as `converged` because the only check was on the sign of the
slope. The forward was biased by a factor of seven more than the European case, and the bias
appeared downstream as a systematic `0.003` volatility point disagreement between calls and
puts that no amount of quote cleaning would have removed.

## Stripping the premium

`imply_forward_curve` takes an optional `zero_rate`. Without one, an expiry containing
American contracts returns `american_quotes_not_stripped` rather than a number that looks
fitted. With one, the premium is stripped and the fit proceeds.

The premium depends on the carry, the carry depends on the forward, and the forward is what
the regression computes, so it is a fixed point:

```
forward = raw parity fit          (biased, but the right order of magnitude)
repeat up to MAXIMUM_STRIPPING_PASSES:
    carry            = zero_rate - log(forward / spot) / T
    for each quote:  volatility = invert_american(quote, zero_rate, carry)
                     european   = quote_mid - early_exercise_premium(volatility, zero_rate, carry)
    forward          = centred parity fit over the european prices
    stop when the forward moves by less than FORWARD_STRIPPING_TOLERANCE relative
```

```
MAXIMUM_STRIPPING_PASSES   = 4
FORWARD_STRIPPING_TOLERANCE = 1e-6
```

It settles in three passes. Measured on the synthetic American chain:

| pass | forward | error |
|---|---|---|
| raw | 224.3261 | `+4.75e-04` |
| 1 | 224.2484 | `+1.29e-04` |
| 2 | 224.2390 | `+8.65e-05` |
| 3 | 224.2377 | `+8.13e-05` |

**The result barely depends on the supplied rate.** Feeding a zero rate that is 2.25
percentage points too low gives `+9.88e-05`, and one 2.75 points too high gives `+5.46e-05`,
against `+8.07e-05` at the true rate. All three are within a factor of two of each other and
all are five to nine times better than the unstripped fit.

That matters because of what step 2 established: the discount factor is not identifiable from
parity. If stripping needed an accurate rate, it would need the thing this platform cannot
measure. It does not. A rate good to a couple of percentage points, which any curve provides,
is enough to recover the forward to `1e-4`.

`early_exercise_premium_stripped` records on every point whether the premium was removed, so
a consumer never has to infer it from the underlying's exercise style.

The cost is real and is where the native tracks earn their place: the fixed point runs an
American inversion and two lattice evaluations per quote per pass, and one AAPL expiry takes
about 2.4 seconds in pure Python.
