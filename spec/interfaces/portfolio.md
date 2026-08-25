# `portfolio`

Below the parity boundary. Three implementations, conformance tested.

The constrained allocator, and the half of step 8 that joins it to hedging.

## Not signal ranking

The objective is

```
sum(w * edge) - sum(|w| * spread) - hedging_cost(net gamma)
```

maximised subject to budgets on net vega, gamma and theta, a tolerance on every factor
exposure from `factors.md`, and a per-candidate size limit standing for concentration and
liquidity together. Ranking by edge and taking the top names optimises none of that.

## Constraints by projection, not by penalty

`essvi.md` recorded what a penalty does when the data pulls against it: it converges to the
boundary and the sign is decided by rounding. So nothing here is a penalty.

- **Size limits** are a box, enforced by clipping. Exact.
- **Budgets and factor tolerances** are slabs, `|a . w| <= b`, enforced by the exact projection
  onto one slab, applied in turn. Alternating projection onto convex sets, a fixed number of
  passes, so all three tracks perform identical arithmetic.

Every reported allocation therefore satisfies every constraint by construction, and the tests
assert that rather than hoping.

## The soft spot at zero

The spread term is `|w| * cost`, which is not differentiable at zero, and the first
implementation took the subgradient there as `-cost`. That makes the gradient at an empty book
`edge + cost`, which is positive even when the edge is nothing at all, so the optimiser walked
away from a correct answer of "hold nothing" and settled on a **negative** objective.

The test that caught it is the obvious one nobody writes: give every candidate zero edge and
check the book stays empty. The subgradient is now selected properly — zero when zero is
optimal, and `raw -/+ cost` only once the edge exceeds its own spread — and a candidate whose
edge is smaller than its spread is correctly not traded at all.

## The joint problem

The program's point is that hedging cost depends on gamma and gamma is what the allocator is
handing out, so solving in sequence prices risk wrongly. The cost enters the objective
directly, through a closed form for the cost of running a Whalley-Wilmott band:

```
delta diffuses with volatility  gamma * sigma * S
a band of half width H accumulates delta adjustment at rate  (gamma sigma S)^2 / H
each unit of delta costs  cost * S
```

so the cost rate is `cost * S * (gamma sigma S)^2 / H`, with `H` the band from `hedging.md`.

**That formula is checked, not asserted.** Against the path simulation in `hedging.md` over
twenty-seven combinations of volatility, cost and risk aversion, the ratio of derived to
simulated cost runs from `0.81` to `1.22`, and is inside `8%` for most of them. It
under-predicts where cost is high and risk aversion low, which is where the band is widest and
an asymptotic result should be expected to fray. It is a cost model, and it is accurate enough
to price the trade-off it exists to price; it is not a valuation.

### What solving separately costs

Eight candidates with similar edges and very different gammas, a 10bp market:

| | edge | spread | hedging | objective | net gamma |
|---|---|---|---|---|---|
| solved ignoring hedging cost, then charged for it | `5.335` | `0.530` | `0.635` | `4.170` | `0.1400` |
| solved jointly | `5.929` | `1.208` | `0.003` | **`4.718`** | `0.0024` |

**The joint solution is 13% better, and it is not a trade-off along one axis.** It collects
*more* gross edge, pays more than twice the spread, and pays almost no hedging cost, because it
found a combination that keeps the edge while netting the gamma away. The sequential solution
was not on a worse point of the same frontier; it was on the wrong frontier.

### A hard gamma budget is not a substitute

Worth reading off the same table: the gamma budget was `0.50`, and the sequential solution's
net gamma was `0.1400`. **The budget never bound.** A limit that is not reached cannot control
anything, and the exposure it failed to control cost `0.635`. Pricing gamma and capping it are
different jobs, and the cap only does the second one.

The binding constraints were the vega budget at `0.9949` of `1.0` and a factor tolerance at
exactly `0.5`.

## Constants

```
ASCENT_PASSES         = 400
PROJECTION_PASSES     = 40
STEP_SIZE             = 0.05 of the largest size limit
GAMMA_DERIVATIVE_STEP = 1e-6
```

Both pass counts are fixed rather than driven by a convergence test, for the reason given
throughout: identical arithmetic in all three tracks. The step is scaled by the largest size
limit so the ascent behaves the same whether positions are measured in lots or in millions.

## Verb

`allocate-portfolio`, input `portfolio_request/v1`, output `portfolio_allocation/v1`. The
`charge_hedging` flag exists so the sequential solution can be produced and then scored
honestly with `report`, which is how the comparison above is made.

## Conformance

Bit-identical across all three tracks on every field of the fixture. Projection and gradient
ascent are arithmetic on fixed-length loops with no search inside them.

## Invariants under test

- every budget, factor tolerance and size limit is respected by the reported allocation
- solving jointly beats solving separately, with lower net gamma and lower hedging cost
- the gamma budget is not what controls gamma in the sequential solution
- the hedging cost is even in gamma, grows with it, and is zero in a free market
- in a free market the two solutions agree
- a zero budget forces that exposure to zero
- candidates with no edge are not traded, and neither is one whose edge is below its spread
- the allocation is deterministic
- an empty candidate list, ragged factor exposures, a negative size and every malformed limit
  are rejected
