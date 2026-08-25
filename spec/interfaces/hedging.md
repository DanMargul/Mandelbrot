# `hedging`

Below the parity boundary. Three implementations, conformance tested.

Delta hedging under proportional transaction costs: the no-transaction band, and what a
policy costs and risks when it is actually run.

## The control problem

Hedging continuously is impossible when trading is not free; hedging never is not hedging. The
answer is a band around the Black-Scholes delta inside which nothing is done. Whalley and
Wilmott give its asymptotic half-width:

```
H = ( 3/2 * cost * S * gamma^2 / risk_aversion )^(1/3)
```

so the band widens as the cube root of cost and as the two-thirds power of gamma, and narrows
as the cube root of risk aversion. Those three scalings are asserted directly rather than
inferred from a simulation, because they are the content of the formula.

**Zakamouline was considered and is not implemented.** Its form carries several fitted
constants, and reproducing them from memory rather than from the derivation would put a number
in the repository that nobody could check. An absent formula is better than an unverifiable
one; if it is wanted later it should arrive with its source.

## What is simulated

A short call, delta hedged, over a geometric path from `random_source.md`. Each step: move the
spot, mark the hedge profit, recompute delta, and rebalance only if the hedge has drifted
outside the band. Costs are proportional and charged on opening, on every rebalance, and on
closing.

The reported statistic is the certainty equivalent, `mean - risk_aversion * variance / 2`,
because that is the objective the band is derived to maximise. Comparing bands on cost alone
would rank "never hedge" first, and on variance alone would rank "hedge continuously" first;
neither is the question.

## The measurement, and the trap in it

The program says the asymptotic bands beat a fixed band. Run naively, the answer looks like
**no**. Over 4000 paths, a quarter-year at-the-money call, 10bp cost, risk aversion `0.10`:

| policy | mean | s.d. | cost | rebalances | certainty equivalent |
|---|---|---|---|---|---|
| fixed `0.00` | `-0.4605` | `0.351` | `0.465` | `125.6` | `-0.4666` |
| fixed `0.10` | `-0.2533` | `0.573` | `0.265` | `14.1` | `-0.2697` |
| fixed `0.30` | `-0.1233` | `1.386` | `0.165` | `3.8` | **`-0.2194`** |
| Whalley-Wilmott | `-0.2179` | `0.710` | `0.219` | `11.0` | `-0.2431` |

The best fixed band wins. But **the best fixed band was chosen by searching eight widths on
the very paths it is then scored on**, and Whalley-Wilmott used no paths at all. That is not a
comparison between two policies, it is a comparison between a fitted policy and an unfitted
one, scored in sample. It is the same error `research.md` exists to prevent, arriving in a
place that does not look like a backtest.

Scored on paths the tuning never saw:

| | in sample | out of sample |
|---|---|---|
| fixed, width chosen in sample | `-0.2194` | `-0.2701` |
| Whalley-Wilmott | `-0.2431` | `-0.2576` |

and across eight held-out path sets **Whalley-Wilmott wins seven**. The program's claim is
right; the naive comparison is what is wrong.

At the smaller scale the tests run at, the same mechanism shows more cleanly than the
head-to-head does. With 400 paths the tuned band's advantage over Whalley-Wilmott is `+0.0602`
in sample and `-0.0002` out of it, and its own certainty equivalent degrades on **ten of ten**
held-out sets. The tests assert that — the mechanism — rather than the head-to-head, because
at 400 paths the head-to-head is a coin flip and asserting it would be asserting noise.

**That is worth stating on its own: comparing two hedging rules is itself a noisy statistic,
and it took 4000 paths to resolve.** A comparison that needs 4000 paths to separate two
policies will not separate them on one year of daily data.

## Conformance

Every statistic agrees **bit for bit** across all three tracks. The path generator is exactly
reproducible, the pricer is, and the band arithmetic is; the one place the tracks can differ
is the standard normal transform in `random_source.md`, and on these seeds it does not.

## Constants

```
WHALLEY_WILMOTT_FACTOR = 1.5
MINIMUM_BAND           = 1e-12
MINIMUM_PATHS          = 2
```

The band is floored so that a zero-gamma step, where the formula gives exactly zero, rebalances
on any drift rather than dividing the decision by nothing.

## Verb

`simulate-hedging`, input `hedging_request/v1`, output `hedging_statistics/v1`. Seeds cross the
boundary as decimal strings, for the reason given in `random_source.md`.

## Invariants under test

- the band scales as the cube root of cost, the two-thirds power of gamma, and the inverse
  cube root of risk aversion, and is zero when gamma is
- a wider band trades less often and pays less
- a wider band carries more risk
- with no cost and no band the hedge replicates the option: mean profit near zero and a small
  spread
- the same seed reproduces the same statistics and a different sequence does not
- the certainty equivalent is the mean penalised by variance, and is below the mean
- a fixed band tuned in sample wins in sample
- that same band degrades on every held-out path set
- its in-sample advantage does not survive out of sample
- malformed inputs, a negative band, a single path and a bad seed are all rejected
