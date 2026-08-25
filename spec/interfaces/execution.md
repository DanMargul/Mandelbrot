# `execution`

Below the parity boundary. Three implementations, conformance tested.

The pessimistic fill model: what an order costs when nothing goes your way. It sits on the
backtest inner loop, which is why it is tri-implemented rather than declared Python-only.

## Why pessimistic first

Step 6 of `program.md` has a bootstrap problem it states plainly: the simulator should be
calibrated from observed fills, observed fills need paper trading, and paper trading needs a
simulator to justify it. The resolution is to start with an assumption that needs no
calibration at all — **pay the full spread, every time** — and refine it once real fills
exist.

That is a lower bound on quality of execution rather than an estimate of it, and the
distinction is the point. A backtest at mid is not an optimistic result, it is not a result;
a backtest at the touch is a result you can only beat.

## The model

```
OrderSide  = "buy" | "sell"
FillStatus = "filled" | "partially_filled" | "unfilled"

Quote:       bid_price, ask_price, bid_size, ask_size
PackageLeg:  quote, side, quantity, contract_multiplier, vega_with_respect_to_volatility
```

A buy pays the ask, a sell receives the bid, and nothing fills beyond the size displayed at
the touch. There is no queue, no price improvement, no hidden liquidity and no depth behind
the best level.

`cost_against_mid` is the half spread times filled quantity times multiplier, which is what
crossing costs relative to a mid-price fantasy. It is never negative: a taker is never paid
to cross.

### The bound is on price, not on quantity

Being precise about what "pessimistic" buys is worth a paragraph, because the honest claim is
narrower than it sounds.

Cost **per contract executed** is bounded: a real fill can be better than the touch and never
worse, at the touch. Quantity is a different matter. An order larger than the displayed size
returns a partial fill here, where reality would sweep deeper levels and fill more, at worse
prices. So on large orders this model understates cost *and* understates fill.

That is deliberate and the unfilled remainder is reported rather than assumed away. A caller
that wants the rest must decide what to do with it, and the conservative choice — not trading
it — forgoes edge rather than inventing it. Depth beyond the touch is the first thing to add
once real fills exist to calibrate against.

## Cost in volatility points, which is the number that matters

A strategy trading a surface trades implied volatility, so a cost in dollars says nothing
until it is put in those units:

```
round_trip_cost_in_volatility_points = 2 * total_cost_against_mid / |net_vega|
```

The factor of two is getting in and back out. The multiplier cancels between numerator and
denominator when legs share one, and correctly does not when they differ, which is why it is
carried per leg rather than per package.

Measured on the synthetic chain through this module, one buy of one contract per line:

| underlying | contracts | median | 75th | 90th |
|---|---|---|---|---|
| SPX | 141 | `0.36` | `0.98` | `2.82` |
| AAPL | 63 | `0.65` | `2.98` | `5.23` |
| THIN | 22 | `1.46` | `5.90` | `8.16` |

**A round trip in the median SPX line costs about a third of a volatility point, and one in
the ninetieth percentile costs nearly three.** Surface relative value is measured in the same
units and frequently in smaller numbers. This is the arithmetic behind the go/no-go the
program schedules after this step, and it is why that go/no-go exists.

## A vega-neutral package pays spread for nothing

The cost in volatility points is a property of the **package**, not of its legs. Two legs
that individually carry vega can net to none, and then the package has paid the spread on
both and bought no exposure at all: the denominator goes to zero and cost per unit of vega
diverges.

That is a real trade, not a pathology — it is what a calendar or a ratio can become when the
legs move — so it is reported rather than rejected. `net_vega` is floored at
`MINIMUM_NET_VEGA` so the reported number stays finite and identical across tracks, and
`net_vega_is_negligible` is set when the floor binds. The same pattern, and the same reason,
as the Durrleman denominator in `svi_surface.md`.

## Edge cases the tests pin down

- a **crossed book** (bid above ask) raises rather than trading; it is bad data, not an
  opportunity
- a **locked book** (bid equal to ask) costs exactly nothing to cross, and the touch is the
  mid
- an **empty side** fills nothing and reports `unfilled` with zero cost, rather than filling
  at the other side's price
- a **partial fill** reports the vega it actually got, not the vega it asked for

## Constants

```
MINIMUM_NET_VEGA       = 1e-12
ROUND_TRIP_CROSSINGS   = 2.0
```

## Verb

`simulate-fills`, input `fill_request/v1`, output `fill_result/v1`. One record is one package.

## Conformance

There is no iteration and no search here, only arithmetic on quoted prices, so all three
tracks agree **bit for bit on every field** of all 47 fixture cases. The tolerances are set
tight rather than fitted to an observed spread.

## Invariants under test

- a taker pays the touch and never the mid, and buying and selling the same quote cost the
  same
- size beyond the displayed quantity is left unfilled rather than filled at a worse price
- an empty book fills nothing; a locked book costs nothing
- a package pays the full spread on every leg, with no package price improvement
- a vega-neutral package reports a positive cost, a zero net vega, and the negligible flag
- a partly filled package reports the vega it actually got
- the cost in volatility points does not depend on the contract multiplier
- crossed books, non-positive quantities and non-positive multipliers are rejected
