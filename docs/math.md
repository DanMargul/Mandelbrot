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
delta_put  = DF * (N(d1) - 1)
gamma      = DF * n(d1) / (F * sigma * sqrt(T))
vega       = DF * F * n(d1) * sqrt(T)
theta      = -DF * F * n(d1) * sigma / (2 * sqrt(T))
```

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

At the kink `F == K` the delta is defined as `0` for both. This is a convention, not a
limit; it is chosen so that a call and a put on the same strike satisfy the parity relation
`delta_call - delta_put = DF` at every point including the kink.

## Implied volatility inversion

`invert_black_implied_volatility` solves `black_price(sigma) = target` by bracketed Newton
with a bisection safeguard. The algorithm is fixed in every detail so that all three tracks
follow the identical iteration path.

1. Undiscount the target price: `p = target / DF`.
2. If the option is a put, convert to the equivalent call by parity: `c = p + F - K`.
3. Reject prices outside the no-arbitrage bounds `max(F - K, 0) < c < F`, returning a
   typed failure rather than a sentinel.
4. Bracket `sigma` in `[1e-9, 10.0]`.
5. Seed with the Brenner-Subrahmanyam approximation `sqrt(2 * pi / T) * c / F`, clamped
   into the bracket.
6. Iterate at most 100 times. Each step tightens the bracket from the sign of the price
   error, then takes a Newton step using vega. The step is rejected in favour of a
   bisection when it falls outside the bracket or when vega is below `1e-12`.
7. Converged when the absolute price error is at or below `1e-14 * F`, or when the bracket
   is narrower than `1e-14`.

The bisection safeguard is what makes this reproducible across languages. Unguarded Newton
takes wildly different paths from tiny differences in the seed when vega is small, and the
tracks then disagree in the fifth digit on deep wings.

## Pseudo-random numbers

Not used before Phase 5. When introduced, both languages use PCG64 with the seed sequence
specified per run in the strategy configuration, so simulated paths are identical bit for
bit and conformance stays exact rather than statistical.
