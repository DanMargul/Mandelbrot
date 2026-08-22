# `pricing`

## Types

```
OptionType = "call" | "put"

BlackScholesInputs:
    forward: float
    strike: float
    years_to_expiry: float
    volatility: float
    discount_factor: float
    option_type: OptionType

BlackScholesGreeks:
    price: float
    delta_with_respect_to_forward: float
    gamma_with_respect_to_forward: float
    vega_with_respect_to_volatility: float
    theta_with_respect_to_time: float
```

## Functions

```
standard_normal_cumulative_distribution(x: float) -> float
standard_normal_probability_density(x: float) -> float

black_scholes_price(inputs: BlackScholesInputs) -> float
black_scholes_price_and_greeks(inputs: BlackScholesInputs) -> BlackScholesGreeks
```

## Preconditions

`forward > 0`, `strike > 0`, `discount_factor > 0`, `years_to_expiry >= 0`,
`volatility >= 0`. Violations raise or throw; they are programming errors, not market
conditions. The degenerate but legal cases `years_to_expiry == 0` and `volatility == 0`
return forward intrinsic value as defined in `docs/math.md`.

## Invariants under test

- put-call parity: `call - put == DF * (F - K)` to within `1e-12` relative
- `delta_call - delta_put == DF` everywhere, including at the kink `F == K`
- gamma, vega and theta are identical for a call and a put on the same strike
- price is monotone increasing in `volatility` and in `years_to_expiry`
- price is bounded by `DF * max(F - K, 0) <= call <= DF * F`
