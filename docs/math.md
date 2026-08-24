# Model definitions

All formulas below are stated in the forward measure. Spot, carry and dividends enter only
through the forward `F` and the discount factor `DF`, both of which are produced by the
`instruments` module and are inputs everywhere else. Nothing downstream of `instruments`
knows what a dividend is.

## Notation

| Symbol | Meaning |
|---|---|
| `F` | forward price of the underlying to the option expiry |
| `K` | strike |
| `T` | year fraction to expiry, ACT/365F |
| `sigma` | Black implied volatility |
| `DF` | discount factor from expiry to valuation date |
| `n(x)` | standard normal probability density |
| `N(x)` | standard normal cumulative distribution |
| `w` | total implied variance, `sigma^2 * T` |
| `k` | log moneyness, `log(K / F)` |

## Black-Scholes in the forward measure

```
d1 = (log(F / K) + 0.5 * sigma^2 * T) / (sigma * sqrt(T))
d2 = d1 - sigma * sqrt(T)

call = DF * (F * N(d1) - K * N(d2))
put  = DF * (K * N(-d2) - F * N(-d1))
```

`N` is evaluated as `0.5 * erfc(-x / sqrt(2))` in every track. This is chosen over
`0.5 * (1 + erf(x / sqrt(2)))` because it does not lose the left tail to cancellation, and
because both Python and C++ then route to an `erfc` of comparable quality, which is what
keeps the tracks agreeing to `1e-12` relative rather than `1e-8`.

## Greek conventions

The greeks are forward-measure sensitivities. This matters for conformance: "delta" is
ambiguous unless the variable being differentiated and the quantities held fixed are both
stated.

| Field | Definition | Held fixed |
|---|---|---|
| `delta_with_respect_to_forward` | `d(price) / dF` | `K, T, sigma, DF` |
| `gamma_with_respect_to_forward` | `d2(price) / dF^2` | `K, T, sigma, DF` |
| `vega_with_respect_to_volatility` | `d(price) / d(sigma)` | `F, K, T, DF` |
| `theta_with_respect_to_time` | `-d(price) / dT` | `F, K, sigma, DF` |

```
delta_call = DF * N(d1)
delta_put  = -DF * N(-d1)
gamma      = DF * n(d1) / (F * sigma * sqrt(T))
vega       = DF * F * n(d1) * sqrt(T)
theta      = -DF * F * n(d1) * sigma / (2 * sqrt(T))
```

The put delta is written as `-DF * N(-d1)` rather than the algebraically identical
`DF * (N(d1) - 1)`. On a deep out-of-the-money put `N(d1)` rounds to exactly `1.0`, and the
subtraction returns zero for a delta whose true value may be `1e-49`. Evaluating the tail
directly costs nothing and keeps full relative precision. The same reasoning is why the put
price uses `N(-d2)` and `N(-d1)` rather than being derived from the call by parity.

Vega is per unit of volatility, not per volatility point. Theta is per year, not per day.
Both are scaled at the reporting layer and nowhere else.

`theta` holds the forward and the discount factor fixed, so it captures volatility decay
only and excludes the roll of `F` and `DF` toward expiry. That roll is a property of the
curve, not of the option, and is attributed separately in `reporting`.

## Degenerate inputs

When `T <= 0` or `sigma <= 0` the option is worth its forward intrinsic value:

```
price = DF * max(F - K, 0)   for a call
price = DF * max(K - F, 0)   for a put
delta = DF * 1{F > K}        for a call
gamma = vega = theta = 0
```

At the kink `F == K` the indicator is `0`, so the call delta is `0` and the put delta is
`-DF`. This is a convention rather than a limit, chosen so that a call and a put on the same
strike satisfy `delta_call - delta_put = DF` at every point including the kink.

## Implied volatility inversion

### Always invert the out-of-the-money option

The strike selects the option type: `strike < forward` uses the put, otherwise the call.
An in-the-money quote is first converted to its out-of-the-money equivalent by put-call
parity; the conversion is never made in the other direction.

The reason is numerical rather than stylistic. Consider a one-year 80 strike call on a
forward of 100 at 3% volatility. It is worth about 20.6, of which the entire volatility
content is roughly `1e-9`. Converting the out-of-the-money 80 put into that call, or
inverting the call directly, requires resolving a `1e-9` quantity inside a number of
magnitude 20. A double carries about `4e-15` of absolute resolution there, so only about
six significant digits of the time value survive, and the recovered volatility inherits the
loss.

Measured over 3121 converged cases spanning strikes from a quarter to four times the
forward, expiries from 0.7 days to five years and volatilities from 3% to 300%: inverting a
resolvable out-of-the-money quote natively recovers the volatility to `1.13e-12` relative,
while applying the identical solver after a parity conversion degrades to as much as
`9.2e-2`. The solver is not the limiting factor in either case.

### The solver

`invert_black_implied_volatility` solves `black_price(sigma) = target` by bracketed Newton
with a bisection safeguard, fixed in every detail so that all three tracks follow the
identical iteration path.

1. Reject `T <= 0` as `degenerate_expiry`.
2. Select the out-of-the-money type and convert the quote to it by parity.
3. Reject a target at or below zero as `below_intrinsic`, and one at or above the
   no-arbitrage ceiling (`F` for a call, `K` for a put) as `above_no_arbitrage_bound`.
4. Evaluate the price at both ends of the volatility bracket `[1e-9, 10.0]` and reject a
   target outside it as `below_volatility_floor` or `above_volatility_ceiling`.
5. Seed with the Brenner-Subrahmanyam approximation `sqrt(2 * pi / T) * target / F`,
   clamped into the bracket.
6. Iterate at most 100 times. Each step tightens the bracket from the sign of the price
   error, then takes a Newton step using vega. The step is rejected in favour of a
   bisection when it falls outside the bracket or when vega is below `1e-12`.
7. Stop when the volatility step falls to `1e-12` relative.

Two details are worth stating because they are easy to get wrong.

The endpoint checks in step 4 cost two extra price evaluations but remove every edge case
from the loop. Once they pass, the price function is continuous and strictly increasing
across a bracket that is known to contain the root, so bisection alone guarantees
termination well inside 100 iterations and the loop needs no special handling for a root
that escapes the bracket.

Convergence is measured on the volatility, not on the price. A price-based criterion scaled
by the forward is far too loose on the wings, where the entire option price can be smaller
than the tolerance and any volatility across a wide band appears to converge. The bisection
safeguard is what makes the iteration reproducible across languages: unguarded Newton takes
a wildly different path from a tiny difference in the seed when vega is small, and the
tracks then disagree in the fifth digit.

### Reported uncertainty

```
volatility_uncertainty = DBL_EPSILON * max(largest_price_term, quoted_price) / vega
```

`largest_price_term` is the larger of the two additive terms in the Black formula at the
solution, which is the source of the formula's own cancellation error. `quoted_price` is
the undiscounted input, which dominates when an in-the-money quote has been converted by
parity. One expression, both sources, no tuned constant.

Using `max(F, K)` instead would be conservative but useless: it reports the same figure for
the in-the-money and out-of-the-money option on a strike, when the whole point is to tell
them apart. On a one-year 80 strike at 5% volatility the two forms differ by 55,000x.

This is what downstream modules filter on, in place of a moneyness or strike-range rule. It
expresses the same idea in units that matter and degrades smoothly rather than cutting at a
threshold that would need re-justifying for every expiry.

It is an estimate, not a guaranteed bound. It is first order in the price error, while vega
can vary by orders of magnitude across the resulting interval on a steep wing, which is
exactly where the estimate is largest. Across the grid it contains 97.3% of realized errors;
the 99th percentile overshoot is 3.1x and the worst observed is 27x. Apply a safety factor.

## The forward and discount factor from put-call parity

Undiscounted parity is model-free:

```
C - P = DF * (F - K)
```

Regressing the mid difference `C - P` on strike gives `-DF` as the slope and `DF * F` as
the intercept, so both quantities come out of the quotes themselves without a rate curve or
a dividend forecast. The dividend in particular is worth taking from the market rather than
from a forecast, because the options market prices it more accurately than a forecast does,
and because a wrong dividend puts a bias in the forward that reappears downstream as a
mispricing that is not there.

`spec/interfaces/forward_curve.md` carries the estimator in full: weights, trimming,
centring, and the measured accuracy. Three consequences belong here because they constrain
what the rest of the platform may assume.

### Parity is a European relation

`C - P = DF * (F - K)` holds with equality only for European exercise. American contracts
satisfy an inequality instead, `S - K <= C - P <= S - K * DF`, because either side may be
exercised early and the two sides carry different early exercise premiums.

Running the regression anyway does not produce a slightly worse forward. On a synthetic
American chain with known parameters it produced a **discount factor above one**, which at a
positive rate is free money, and a forward biased seven times more than the European case.
The bias then reappears as a systematic disagreement between call-implied and put-implied
volatility that looks like a data problem and is not.

So `forward_curve` refuses any expiry containing American contracts. The early exercise
premium has to be stripped first, using the lattice in `american`, and the same measurement
shows that doing so restores the forward to European accuracy and the discount factor to
below one.

The general lesson is worth keeping: a model-free relation is only model-free inside its own
assumptions, and parity's assumption is European exercise.

### The weight cannot be `volatility_uncertainty`

It would be natural to weight the regression by the quantity `implied_vol` already produces
for exactly this purpose. It is not available: `volatility_uncertainty` needs a vega, a vega
needs a forward, and the forward is what this regression computes. The dependency is
circular.

The weight used instead is `1 / (call_half_spread^2 + put_half_spread^2)`, the inverse
variance of the measured difference under the assumption that a mid is uncertain by about
its half spread. It is model-free, which is the same property that makes parity worth using
in the first place.

### The forward is well determined and the discount factor is not

Measured against known ground truth, the forward comes out to a few parts in `1e5` while
the discount factor is uncertain at the `1e-3` level. Since `DF = exp(-r T)`, a `1e-3`
uncertainty is a **two percentage point** uncertainty in the zero rate at a four-week
expiry, and the rate error scales as `1/T`.

This is a property of the data, not of the estimator. The slope of `C - P` against `K` is
close to `-1` for any short-dated chain, and no strike range available in practice pins the
small deviation from it.

### What a discount factor error does downstream

An error in `DF` scales every option price in that expiry by the same factor. Converted to
implied volatility it is close to a uniform level shift of the whole smile.

That shift is **largely absorbed by a surface fit**, so relative value within an expiry, the
strategy family this platform is built for, is close to immune to it. It is **not** absorbed
across expiries, because each expiry has its own independent discount factor error. Calendar
structure and any term-structure signal therefore need a real rate curve, and cannot rely on
rates implied from parity.

That is the dividing line to remember: parity gives a forward good enough for everything,
and a rate good enough only for diagnostics.

## Pseudo-random numbers

Not used before Phase 5. When introduced, both languages use PCG64 with the seed sequence
specified per run in the strategy configuration, so simulated paths are identical bit for
bit and conformance stays exact rather than statistical.
