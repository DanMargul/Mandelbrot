# Reporting and attribution

P&L attribution into delta, gamma, vega, theta, the discount roll, and what is left over.

**Above the parity boundary: Python only.** Attribution runs once per result, not on the
backtest inner loop, so there is no comparison across tracks worth paying for. It imports the
`python_pure` track directly as the reference implementation.

## The terms

For a position priced in the forward measure, between an opening and a closing state:

| term | expression |
|---|---|
| delta | `dP/dF * (F1 - F0)` |
| gamma | `1/2 * d2P/dF2 * (F1 - F0)^2` |
| vega | `dP/dsigma * (sigma1 - sigma0)` |
| theta | `theta * (T0 - T1)` |
| discount | `P0 / DF0 * (DF1 - DF0)` |
| unexplained | the remainder |

The discount term exists because `math.md` says it must. Theta there is defined holding the
forward and the discount factor fixed, so it captures volatility decay only and **excludes the
roll of `F` and `DF` toward expiry**; that roll is a property of the curve, and the same
section says it is attributed separately here. Without the term the roll would silently land
in "unexplained", which is the worst place for a known effect to go.

Price is exactly linear in the discount factor, so the term is not an approximation. Moving
only `DF`, it explains the entire profit to `2.7e-14`.

## Every term is exact in its own variable

Moving one variable at a time, on a ten-lot at-the-money call:

| variable moved | profit | explained by | left over |
|---|---|---|---|
| discount factor, `+0.0002` | `0.7976` | discount | `2.7e-14` |
| forward, `+0.5%` | `262.287` | delta + gamma | `-0.013` |
| volatility, `+1` point | `197.217` | vega | `-0.013` |
| time, one day | `-31.432` | theta | `-0.126` |

Each residual is the next order in that one variable: third order in the forward, volga in
volatility, and the curvature of decay in time.

## The residual of a real move is mostly cross terms

Those four residuals sum to `-0.151`. Moving all four variables together in the same step
leaves `-1.419`. **The cross terms account for `89%` of what is unexplained**, and no amount
of refining the individual greeks will touch them: vanna and charm are not corrections to
delta or to vega, they are corrections to the assumption that the variables moved one at a
time.

That is worth knowing before reading an attribution report. A residual of a few tenths of a
percent is the expansion working; it is not a sign that a greek is wrong.

## How far the expansion carries

Same position, one day of decay, one volatility point, varying the size of the forward move:

| forward move | unexplained share |
|---|---|
| `1%` | `0.23%` |
| `2%` | `0.31%` |
| `5%` | `1.14%` |
| `10%` | `3.94%` |
| `20%` | `14.42%` |

A second-order attribution is a good description of a daily move and a poor description of a
crash. The report carries `unexplained_share` on every result so a reader can see which
regime they are in rather than assuming.

## Splitting the vega profit by what actually moved

This is the part step 5 is defined by. The vega profit says the surface moved; it does not say
whether it moved because the whole level shifted or because one quoted option converged to
fair. The factor decomposition in `factors.md` answers that, because a change in log total
variance at a grid point is exactly a sum of factor contributions plus a residual change, and
`sigma` is a monotone function of `w` at fixed `T`. So the vega profit divides in the same
proportions.

Worked on a short position in an option quoted `4%` rich in total variance, held one day while
the surface also moved:

| what moved | vega profit |
|---|---|
| level | `-134.50` |
| term slope | `-19.40` |
| skew | `-0.00` |
| curvature | `+0.64` |
| **residual** | **`+71.20`** |
| net vega profit | `-82.05` |

**The residual bet was right and the trade still lost money.** The option converged, the
position earned `+71.20` for it, and an unhedged level exposure took `-134.50` back. That is
precisely the failure the step exists to prevent, and it is the argument for the time-domain
neutralisation in `factors.md` rather than a hope that the residual is uncorrelated.

`residual_share` is reported against the sum of **absolute** contributions rather than against
the net, because the net can pass through zero while the position is carrying large offsetting
exposures, and a share computed against it would be meaningless exactly when it mattered most.

## What is missing

The attribution takes two market states and a position. Assembling those states from a
backtest, over many dates, is the backtester's job, and so is writing the resulting return
series to a store the trial registry can point at. Both wait on step 6, which is also where
the `research.md` seam is closed. Until then this module answers "what explains this move"
rather than "what explains this strategy".
