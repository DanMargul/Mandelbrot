# `rate_curve`

Below the parity boundary. Three implementations, conformance tested.

A discount curve: zero rates at a set of maturities, and the discount factors and forward
rates that follow from them.

## What this is for, and what it is not for

`forward_curve.md` records a measurement that decides the scope here. Supplying an external
rate instead of implying one from put-call parity **does not improve the forward** — the
standard error moves from `4.8e-5` to `4.9e-5` — so there is no supplied-rate mode and this
curve is not wired into the parity regression.

What the same section records is where a rate curve *is* needed: a discount factor error is a
per-slice level effect that a surface fit largely absorbs, so within-expiry relative value is
close to immune, and **it does not cancel across expiries**. Calendar and term-structure work
discounts with this; a single expiry does not need it.

Building it now is the prerequisite step 2 declared for step 5, not a second attempt at
something already measured and rejected.

## Interpolation is on the integral, not on the rate

The curve carries continuously compounded zero rates at nodes. Everything is derived from

```
y(t) = z(t) * t = -log DF(t)
```

which is linear between nodes, with `y(0) = 0`. That makes the instantaneous forward rate
**piecewise constant**: one value per segment, changing only at nodes.

The obvious alternative — interpolate the zero rate itself — looks equivalent and is not.
With `z` linear between nodes the forward is `z(t) + t * z'(t)`, which varies across the
segment. On a curve of 1% at one month rising to 4% at three months:

| | instantaneous forward inside the first segment |
|---|---|
| linear in the zero rate | ranges over `2.56%` to `8.44%`, a factor of **3.3** |
| linear in `y`, as implemented | constant at `5.50%` |

A two-node input turned into a forward rate that more than triples across a single segment,
purely as an artefact of how the gap was filled. Anything trading calendar structure is
trading exactly that quantity, which is why the choice belongs in the interface rather than
in a comment.

The interpolation is written `(1 - f) * y_i + f * y_j` rather than `y_i + f * (y_j - y_i)`,
so both endpoints are reproduced exactly and a node reached from either side gives the same
number. That is the ulp lesson from `svi_surface.md`, applied where it was already known.

## The ends of the curve

- **Before the first node** the zero rate is flat at the first node's rate, which is the same
  as anchoring `y(0) = 0` and interpolating to the first node.
- **Beyond the last node** the final segment's forward rate continues. A one-node curve has no
  final segment, so it is flat at that node's rate everywhere, and flat zero and flat forward
  coincide.

Extrapolation is an assumption rather than information, and both choices above are the ones
that keep the forward rate continuous where the data runs out.

## Negative rates are a market condition

Rates may be negative, discount factors may exceed one, and neither is rejected. This is not
hypothetical: EUR and JPY curves spent years there.

It is worth stating one consequence, because it caught a test assertion that looked obviously
right. On a curve of `-0.6%` at six months rising to `-0.2%` at two years, the zero rate is
**rising** and the forward over that period is **negative**: `y` goes from `-0.003` to
`-0.004`, so the forward is `-0.067%`. Rising zero rates do not imply positive forwards when
the level is below zero, and the discount factor rises with maturity rather than falling.

## Types

```
CurveNode:  years_to_maturity, continuously_compounded_zero_rate
RateCurve:  nodes

integrated_rate(curve, years)                    -> y(t)
discount_factor(curve, years)                    -> exp(-y(t))
zero_rate(curve, years)                          -> y(t) / t
forward_rate(curve, start_years, end_years)      -> (y(t2) - y(t1)) / (t2 - t1)
forward_discount_factor(curve, start, end)
```

`zero_rate` at zero is the instantaneous rate rather than a division by zero, and
`discount_factor` at zero is exactly one.

## Constants

```
MINIMUM_CURVE_NODES     = 1
MINIMUM_YEAR_FRACTION   = 1e-12
```

## Verb

`evaluate-rate-curve`, input `rate_curve_query/v1`, output `rate_curve_point/v1`.

## Conformance

Interpolation and two exponentials, with no iteration and no search, so all three tracks
agree **bit for bit on every field** of all 50 fixture cases across five curve shapes.

## Invariants under test

- the curve reproduces every one of its own nodes exactly, in both zero rate and discount
  factor
- the forward rate is constant inside a segment, and interpolating the zero rate instead
  would not be
- discount factors compose: `DF(t2) = DF(t1) * forward DF(t1, t2)`
- discounting is monotone whenever every forward rate is positive
- the short end is flat at the first node and `DF(0)` is exactly one
- beyond the last node the final segment's forward continues
- a one-node curve is flat everywhere
- negative rates give discount factors above one and are not an error
- rising zero rates do not imply a positive forward when the level is negative
- an empty curve, a non-positive maturity, out-of-order nodes, a negative year fraction and a
  non-positive forward period are all rejected
