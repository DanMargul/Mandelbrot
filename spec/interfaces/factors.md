# `factors`

Below the parity boundary. Three implementations, conformance tested.

The surface factor model: decompose a time series of surfaces into named factors, and hand
back what is left over as a residual that is neutral to them by construction.

## A named basis rather than PCA

Step 5 permits either, and the named basis wins on the property the step actually cares
about. Four functions of the grid, applied to **log total variance** so a level move is
proportional rather than additive:

| factor | basis function |
|---|---|
| level | `1` |
| term slope | `log T` |
| skew | `k` |
| smile curvature | `k^2` |

Orthonormalised on the grid by modified Gram-Schmidt, twice over, in a fixed order. PCA would
find whatever directions carry variance; a named basis says in advance what it is removing,
and a residual is only interesting if you can say what it is a residual *from*.

The honest check on that choice is how much the named basis leaves behind, which the result
reports as `variance_explained`. On a surface generated from these four factors it is
`1.000000`; on the same surface with one grid point disturbed it is `0.999992`. If a real
surface came back at `0.7`, the "residual" would be mostly unnamed systematic structure and
trading it would be trading a factor nobody had identified.

## Cross-sectional orthogonality is not time-series neutrality

This is the part worth being careful about, because the two are easy to conflate and only one
of them makes a trade neutral.

Projecting each surface onto the basis gives a residual that is orthogonal to every basis
vector **across the grid, at that date**. It does not follow that the residual *at one grid
point, through time* is uncorrelated with the level loading through time. Measured on a
factor-driven series with one disturbed point, the cross-sectional residual still carries a
correlation of `1.18e-01` with the level loading.

So there are two steps, and the second is the one the trade needs:

1. `decompose_surface_factors` removes the factor shapes date by date.
2. `neutralise_against_loadings` regresses a residual series on the loading series through
   time and returns what is left, which carries a factor correlation of `6.1e-18` — machine
   zero, by construction.

The result reports both `worst_factor_correlation_before` and `worst_factor_correlation`, so
the size of what step two removed is visible rather than assumed.

The program's claim that a naive residual is mostly a disguised level bet is measured rather
than repeated: a deviation from the mean surface correlates `+0.84` with the level factor,
while the orthogonal residual correlates `-0.02`.

## Z-scoring an autocorrelated residual

Residuals are persistent, and a rolling mean and standard deviation assume they are not. The
effective sample size of an AR(1) series is `n (1 - rho) / (1 + rho)`, so the standard error
is understated by `sqrt((1 + rho) / (1 - rho))`.

| true `rho` | measured | effective `n` of 500 | naive z overstated by |
|---|---|---|---|
| `0.00` | `0.036` | `466` | `1.04x` |
| `0.50` | `0.515` | `160` | `1.77x` |
| `0.80` | `0.810` | `52` | `3.09x` |
| `0.90` | `0.903` | `25` | `4.44x` |
| `0.95` | `0.944` | `14` | `5.89x` |

**At `rho = 0.9` a three-sigma residual is really a `0.7` sigma residual.** That is exactly
the direction the program warns about: the error makes everything look tradeable.

The correction runs the other way too, and it is worth saying so because it is the case a
convergence strategy actually wants. A **mean-reverting** residual has negative
autocorrelation, an effective sample size *larger* than `n`, and an overstatement factor below
one: it is more significant than the naive z-score suggests, not less. The reported factor is
not clamped at one, and a test asserts the negative-`rho` case explicitly.

## A degenerate residual is flagged, not scored

If a surface is generated purely from the four factors the residual is floating-point noise at
`1e-16`. Dividing that by a standard-deviation floor produced a z-score of order `1e-4` that
differed between tracks, which is a meaningless number computed from rounding error.

`score_residual` now detects that the residual has no variation above
`MINIMUM_STANDARD_DEVIATION`, reports `residual_is_degenerate`, and returns zeros rather than
amplified noise. A residual with nothing in it is a fact about the surface, not a signal.

## Identifiability

A factor direction that the grid cannot distinguish is dropped rather than fitted. A
single-expiry grid has a constant `log T`, so the term-slope vector collapses into the level
vector and Gram-Schmidt discards it: `identified_factor_count` comes back as three and the
unused loading is reported as zero. The alternative — dividing by a near-zero norm — would
produce a large loading on a direction the data cannot see.

## The summation trap this module found

`factors` is where a latent cross-track defect became visible, and the finding applies to
every Python module below the boundary.

**In CPython 3.12 and later, the built-in `sum()` over floats uses Neumaier compensated
summation.** It is exactly equal to `math.fsum`, and it is *not* equal to a naive accumulation
loop:

```
sum(values)      1584651.1907862313
math.fsum(values) 1584651.1907862313
explicit loop     1584651.1907862213
```

So writing `sum(...)` in Python and `total += ...` in C++ is not the same computation. Here
it mattered: the orthonormal basis disagreed in `94` of `140` components, and the disagreement
flowed into every loading. Replacing `math.fsum` with `sum` — which is what a reviewer would
reach for — changes nothing at all.

Both tracks now accumulate explicitly, and the module is bit-identical again. The same pattern
was corrected in `execution.py` as a precaution; its fixture regenerated byte for byte, which
confirms the trap was latent there rather than live, because a sum over one to four legs has
nothing for the compensation to correct.

It remains present in `forward_curve`, `simplex` and the calibrators, which were never claimed
bit-identical and whose tolerances were measured with it in place. Recording that is better
than implying those modules are clean.

## Constants

```
FACTOR_COUNT             = 4
MINIMUM_OBSERVATIONS     = 2
MINIMUM_GRID_POINTS      = 4
MINIMUM_BASIS_NORM       = 1e-10
MINIMUM_STANDARD_DEVIATION = 1e-12
MAXIMUM_AUTOCORRELATION  = 0.99
GRAM_SCHMIDT_PASSES      = 2
```

`GRAM_SCHMIDT_PASSES` is two because one pass of classical Gram-Schmidt loses orthogonality on
an ill-conditioned basis; the second pass restores it, and a fixed count keeps all three tracks
performing identical arithmetic.

## Verb

`decompose-surface-factors`, input `factor_request/v1`, output `factor_decomposition/v1`.

## Conformance

Bit-identical across all three tracks on every field of the fixture, once the summation above
was corrected. Getting there required finding a real defect rather than widening a tolerance,
which is the point of the exercise.

## Invariants under test

- the named basis is orthonormal on the grid
- a surface built only from the factors leaves a residual below `1e-12` everywhere
- residuals are orthogonal to every basis vector at every observation
- a naive residual correlates with the level factor and the orthogonal one correlates less
- time-domain neutralisation drives the factor correlation to machine zero
- a single-expiry grid identifies three factors, not four
- autocorrelation inflates the standard error exactly when it is positive
- a mean-reverting residual has an effective sample size above `n`
- a residual with no variation is flagged rather than scored
- a grid too small, ragged observations, non-positive total variance and a non-positive
  expiry are all rejected
