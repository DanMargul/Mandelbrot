# `implied_vol`

## Types

```
InversionStatus =
    "converged"
  | "below_intrinsic"
  | "above_no_arbitrage_bound"
  | "below_volatility_floor"
  | "above_volatility_ceiling"
  | "not_converged"
  | "degenerate_expiry"

ImpliedVolatilityInputs:
    forward: float
    strike: float
    years_to_expiry: float
    discount_factor: float
    option_price: float
    option_type: OptionType

ImpliedVolatilityResult:
    volatility: float
    status: InversionStatus
    iterations: int
    absolute_price_error: float
    volatility_uncertainty: float
```

## Functions

```
out_of_the_money_option_type(forward: float, strike: float) -> OptionType
undiscounted_out_of_the_money_target_price(inputs: ImpliedVolatilityInputs) -> float
volatility_uncertainty_from_price_resolution(forward: float, strike: float, vega: float) -> float
invert_black_implied_volatility(inputs: ImpliedVolatilityInputs) -> ImpliedVolatilityResult
```

## Constants

Fixed identically in all three tracks. These are part of the contract, not tuning knobs;
changing one changes the iteration path and therefore the cross-track comparison.

```
MINIMUM_VOLATILITY               = 1e-9
MAXIMUM_VOLATILITY               = 10.0
MAXIMUM_ITERATIONS               = 100
VOLATILITY_CONVERGENCE_TOLERANCE = 1e-12
MINIMUM_USABLE_VEGA              = 1e-12
```

## Inversion is always performed on the out-of-the-money option

`strike < forward` selects the put, otherwise the call. An in-the-money quote is converted
to its out-of-the-money equivalent by put-call parity before solving, never the other way
around.

This is the single most consequential decision in the module. Measured over a grid of 3121
converged cases spanning strikes from a quarter to four times the forward, expiries from
0.7 days to five years and volatilities from 3% to 300%:

- an out-of-the-money quote whose reported uncertainty is resolvable at all (1418 of the
  1716 out-of-the-money cases) recovers the volatility to `1.13e-12` relative
- the same solver applied after a parity conversion degrades to as much as `9.2e-2`

The loss is entirely in the conversion, not the solver. Adding a `1e-9` put to a `$20`
intrinsic leaves the option's whole volatility content below the last representable bit of
the sum. Downstream modules should therefore prefer the out-of-the-money side of each
strike, which is also the side that actually trades.

## `volatility_uncertainty`

A first-order estimate of how much of the returned volatility is real, given that every
price involved is a double:

```
largest_price_intermediate = max(largest_price_term, quoted_undiscounted_price)
volatility_uncertainty     = DBL_EPSILON * largest_price_intermediate / vega
```

`largest_price_term` is the larger of the two additive terms in the Black formula at the
solution, which is where the formula's own cancellation error comes from.
`quoted_undiscounted_price` covers the representation error of the input, which is what
dominates when an in-the-money quote has been converted by parity. Taking the larger of the
two covers both sources in one expression, with no tuned constant.

Bounding by `max(forward, strike)` instead would also be conservative, but it would report
the same uncertainty for an in-the-money and an out-of-the-money quote on the same strike
and so would be useless for the purpose. On a one-year 80 strike at 5% volatility the two
expressions differ by a factor of 55,000, which is exactly the distinction a consumer needs.

Consumers filter on this rather than on strike or moneyness rules. It is the same criterion
expressed in units that matter, and it degrades smoothly instead of cutting at a threshold
that has to be re-justified for every expiry.

**It is an estimate, not a guaranteed bound.** It is first order in the price error, and
vega can vary by orders of magnitude across the resulting interval on a steep wing, which
is precisely where the estimate is largest. Measured across the 3121-case grid:

| statistic | realized error / estimate |
|---|---|
| median | 0.00 |
| 90th percentile | 0.52 |
| 99th percentile | 3.12 |
| worst observed | 27.08 |

97.3% of realized errors fall inside the estimate. Consumers should apply a safety factor;
the test suite enforces 64x, which is comfortably above the worst case observed and still
far tighter than any threshold a trading rule would use.

## Failure semantics

A failure returns `volatility` as `0.0` and `volatility_uncertainty` as infinity, with a
status naming the cause. It never returns `NaN`. A `NaN` volatility is indistinguishable
from a missing quote by the time it reaches a signal, and the reason for it is gone.

Non-finite floats are serialized as JSON `null` in every track, since `Infinity` is not
valid JSON and the tracks would otherwise disagree on the encoding rather than on the
number.

`iterations` is a compared field. Two tracks reaching the same volatility by different
iteration counts have diverged in a way that will eventually change an answer, and it is
far cheaper to catch that on a fixture than in a backtest.

## Invariants under test

- round trip on a resolvable out-of-the-money quote recovers `sigma` to `1.13e-12` relative
- realized round-trip error never exceeds
  `64 * (volatility_uncertainty + 1e-12 * volatility)`
- a price at or below intrinsic returns `below_intrinsic`, never a small positive volatility
- a price at or above the no-arbitrage ceiling (`forward` for a call, `strike` for a put)
  returns `above_no_arbitrage_bound`
- every returned status other than `converged` carries `volatility == 0.0`
