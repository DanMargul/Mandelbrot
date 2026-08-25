# `implied_correlation`

Below the parity boundary. Three implementations, conformance tested.

The first half of step 9: what an index's volatility says about the correlation of the things
inside it, and what a dispersion trade has to hold to be exposed to that and nothing else.

## The identity everything rests on

A basket's variance under a single correlation `rho` shared by every pair is

```
sigma_I^2 = sum_i sum_j w_i w_j sigma_i sigma_j rho_ij       rho_ii = 1
```

which needs `n^2` terms. Splitting the diagonal off collapses it to two sums:

```
S1 = sum_i w_i sigma_i          S2 = sum_i (w_i sigma_i)^2
sigma_I^2 = S2 + rho * (S1^2 - S2)
```

because the off-diagonal weight is exactly `S1^2 - S2`. Inverting it gives the correlation the
market is quoting:

```
rho = (sigma_I^2 - S2) / (S1^2 - S2)
```

This is not an approximation. It agrees with the full quadratic form to `1.1e-16` over two
hundred random baskets, and both tests assert it directly against a naive double loop.

**It is also the difference between a pipeline that finishes and one that does not.** At five
hundred names:

| | one basket | a 500-point surface, per day |
|---|---|---|
| quadratic form | `7.73 ms` | `3.9 s` |
| two-sum identity | `0.026 ms` | `0.013 s` |

**294 times faster**, and the gap grows linearly in the name count. Step 9's data volume is the
reason to care.

## Dropping the diagonal, and exactly what it costs

The widely used form ignores the diagonal correction entirely:

```
rho_dirty = sigma_I^2 / S1^2
```

That is not a different estimator with its own error bar. Substituting the identity above,

```
rho_dirty = f + rho * (1 - f)          f = S2 / S1^2
```

so

```
rho_dirty - rho = f * (1 - rho)
```

**exactly**, verified to `1.1e-15` over two thousand random baskets. The error is the
concentration `f` — a volatility-weighted Herfindahl, equal to the plain Herfindahl when the
constituent volatilities are equal — multiplied by the distance from perfect correlation. It is
always an *overstatement* below `rho = 1`, and it vanishes only at `rho = 1`.

The size of it depends entirely on how concentrated the basket is. Five hundred names, weights
falling as `1/rank^alpha`, planted at `rho = 0.35`:

| `alpha` | top-ten weight | concentration `f` | dirty | overstatement |
|---|---|---|---|---|
| `0.0` | `0.020` | `0.00205` | `0.3513` | `+0.0013` |
| `0.5` | `0.116` | `0.00339` | `0.3522` | `+0.0022` |
| `0.8` | `0.276` | `0.01072` | `0.3570` | `+0.0070` |
| `1.0` | `0.431` | `0.02688` | `0.3675` | `+0.0175` |
| `1.3` | `0.669` | `0.08641` | `0.4062` | `+0.0562` |

**A large name count is not what makes the correction negligible; a flat weight distribution
is.** At five hundred equally weighted names the error is a tenth of a correlation point and
can be ignored. At five hundred names with two thirds of the weight in ten of them it is
`5.6` points, which is larger than the moves a dispersion book is trying to trade.

Both numbers are reported. `clean_correlation` is the one to use; `dirty_correlation` and
`diagonal_bias` exist so the difference is visible rather than assumed away.

## When there is no such basket

Equicorrelation is only a covariance matrix when

```
-1/(n - 1) <= rho <= 1
```

The floor is the point where the matrix stops being positive semidefinite, and it tightens
towards zero as the basket grows: `-1` for a pair, `-0.5` for three names, `-0.002` for five
hundred. The ceiling is more useful in practice — `rho = 1` means the index is worth exactly its
weighted-average volatility, so **an index quoted above `S1` implies a correlation above one**,
which is not a rich correlation but a statement that the index and constituent quotes are
mutually inconsistent.

That is reported, not thrown: `is_admissible` and `exceeds_perfect_correlation` carry it, and
the sensitivities come back empty, because a sensitivity to a covariance matrix that does not
exist is not a number worth printing. The fixture carries such a case, implying `1.181`.

## What a dispersion trade holds

Selling index volatility against constituent volatility is only a correlation trade if it is
neutral to the constituents' own volatilities. The index's sensitivity to one of them is

```
d(sigma_I)/d(sigma_i) = w_i * (w_i sigma_i + rho * (S1 - w_i sigma_i)) / sigma_I
```

and holding `index_vega * that` in name `i` is what makes the book flat to a move in name `i`.

`sigma_I` is homogeneous of degree one in the constituent volatilities, so Euler's theorem
gives an exact check that costs nothing:

```
sum_i sigma_i * d(sigma_I)/d(sigma_i) = sigma_I
```

Both tracks assert it to `1e-12`, and separately assert each sensitivity against a central
difference of the basket volatility itself. **The constituent legs always sum to less than the
index vega**, which is the whole trade: the shortfall is what is exposed to correlation.

## Constants

```
MINIMUM_CONSTITUENTS      = 2
MINIMUM_OFF_DIAGONAL      = 1e-18
WEIGHT_TOTAL_TOLERANCE    = 1e-9
```

Weights are required to sum to one within the tolerance rather than being normalised silently,
because a basket whose weights do not add up is a data error and normalising it would hide the
error while still returning a number.

## Verb

`imply-correlation`, input `correlation_request/v1`, output `correlation_report/v1`.

## Conformance

Bit-identical across all three tracks on every field, with **no tolerance entry of its own** —
the whole suite passes with the default tolerance set to exactly zero. There is no search here,
no iteration and no transcendental beyond one square root, so there is nothing for the tracks to
disagree about.

The fixture oracle is independent of the implementation: every admissible case is repriced
through the full `n^2` quadratic form at the implied correlation and required to reproduce the
quoted index volatility, the bias is checked against its closed form, and the sensitivities are
checked against Euler. Six of the seven cases are round trips from a planted correlation, and
each recovers it — `0.30`, `0.42`, `-0.20`, `0.985`, `0.35`, `0.35`.

## What is not done

**Step 9's own completion condition is not met.** It asks that the implied correlation series
reproduce published benchmarks within a stated tolerance, on the grounds that external
validation is worth more than any internal check. Nothing here has been compared to a published
series. The numbers above are internal consistency — exact internal consistency, checked three
ways — and that is a different and weaker thing.

Writing down remembered benchmark values to close the gap would be the mistake `hedging.md`
declined to make with Zakamouline's constants: a number in the repository that nobody can check.
The comparison needs the published series and a constituent universe with real weights, and
until it has both this module is machinery awaiting its validation.

The rest of step 9 is also outstanding: per-name surfaces across a real constituent universe,
with borrow from `forward_curve.md`, American exercise from `american.md`, and changing weights
and corporate actions, none of which this module needs and all of which feeding it does.

## Invariants under test

- the two-sum form agrees with the full quadratic form, from two names to forty
- a basket built at a correlation implies that correlation back, across the admissible range
- the dirty correlation exceeds the clean one by exactly the concentration times `1 - rho`
- the bias vanishes at perfect correlation and falls as the basket spreads out
- concentration, not name count, is what drives the bias
- a perfectly correlated basket is worth its weighted volatility
- an index above that implies more than perfect correlation and is flagged inadmissible
- the admissible floor tightens towards zero as the basket grows
- the sensitivities satisfy Euler's identity and match a central difference of the basket
- every sensitivity is positive, and the constituent legs sum to less than the index vega
- a single name, a basket that does not add to one, a negative weight, a negative or zero
  volatility, a zero index volatility and a correlation outside the admissible range are all
  rejected
