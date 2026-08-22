# `implied_vol`

## Types

```
InversionStatus =
    "converged"
  | "below_intrinsic"
  | "above_forward"
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
```

## Functions

```
invert_black_implied_volatility(inputs: ImpliedVolatilityInputs) -> ImpliedVolatilityResult
```

## Constants

Fixed identically in all three tracks. These are part of the contract, not tuning knobs;
changing one changes the iteration path and therefore the cross-track comparison.

```
MINIMUM_VOLATILITY          = 1e-9
MAXIMUM_VOLATILITY          = 10.0
MAXIMUM_ITERATIONS          = 100
PRICE_CONVERGENCE_TOLERANCE = 1e-14
BRACKET_CONVERGENCE_WIDTH   = 1e-14
MINIMUM_USABLE_VEGA         = 1e-12
```

## Failure semantics

A failure returns `volatility` as `0.0` with a status naming the cause. It never returns
`NaN`. A `NaN` volatility is indistinguishable from a missing quote three modules later,
and by the time it reaches a signal the reason for it is gone.

`iterations` is part of the compared output. Two tracks that reach the same volatility by
different iteration counts have diverged in a way that will eventually produce different
answers, and conformance should catch that on the fixture that is easy to debug rather than
on the backtest that is not.

## Invariants under test

- round trip: for `sigma` in `[0.01, 3.0]`, inverting `black_scholes_price(sigma)` recovers
  `sigma` to within `1e-10` absolute
- a price at or below intrinsic returns `below_intrinsic`, never a small positive volatility
- a price at or above the undiscounted forward returns `above_forward`
- `status == "converged"` implies `absolute_price_error <= 1e-14 * forward`
