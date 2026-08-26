# Recovering a planted correlation

Above the parity boundary, Python only. `ingestion/basket.py` and `backtest/correlation_run.py`.

`spec/interfaces/implied_correlation.md` proved the correlation arithmetic against itself. This
runs it against a market: an index and eight constituents quoted as option chains, where the
correlation is known because it was planted, and the only way to see it is through prices.

## An index consistent with the things inside it

`ingestion/run.py --source synthetic_basket` writes
`spec/fixtures/datasets/synthetic_basket`: 60 business days, an index and eight names, two
expiries, five strikes, calls and puts — 10,800 rows over 540 partitions.

The point of it is that **the index is not quoted independently**. Each day:

- a correlation `rho_t` reverts to `0.45` with a daily reversion of `0.10`, floored and capped
  inside the admissible range
- constituent returns are drawn as `sqrt(rho) * common + sqrt(1 - rho) * own`, so their pairwise
  correlation is exactly `rho_t`
- each name's volatility level reverts to its own base
- the index level is the weighted basket of constituent levels
- **the index's at-the-money volatility is `basket_volatility(constituent levels, rho_t)`**

so the index and its constituents cannot disagree, and any correlation recovered from their
option prices has a known right answer. Weights fall as `1/rank^0.8` over eight names, which is
concentrated on purpose.

`correlation_truth.json` records `rho_t`, the index level, every constituent volatility and the
weights, and it is written *after* the dataset, because `write_dataset` clears the directory
first — the same trap `docs/history_run.md` recorded.

## What survives the round trip

`backtest/correlation_run.py` never reads the generator. It reads `correlation_truth.json` for
the weights and the rate, and everything else comes out of the quotes: invert each call to an
implied volatility, fit `log sigma` as a quadratic in log-moneyness by least squares, evaluate
at a common moneyness, and imply the correlation.

That is the whole pipeline — Black-Scholes pricing, a bid/ask spread, a Parquet round trip,
Newton inversion, a cross-sectional fit, and the correlation identity — and the answer comes
back:

| | |
|---|---|
| observations | `60` |
| mean planted correlation | `0.48229` |
| mean error at the money | `-0.000001` |
| worst error at the money | `-0.000035` |
| **rms error at the money** | **`0.000007`** |

**Seven parts in a million.** The residual is quote granularity: prices are rounded to a
hundredth of a cent, and that rounding is the entire error budget. Nothing in the method
contributes at a level that can be seen above it.

## The formula that drops the diagonal is useless here

On the same sixty days, at the money:

| | |
|---|---|
| mean error from dropping the diagonal | `+0.10694` |
| worst error from dropping the diagonal | `+0.16536` |

**Ten to sixteen correlation points.** `implied_correlation.md` gives the closed form —
`concentration * (1 - rho)` — and eight names with weights falling as `1/rank^0.8` have a
concentration around `0.20`, so at `rho = 0.48` the overstatement is about `0.10`. The
measurement matches the algebra, and the practical statement is blunt: on a basket of eight the
approximation is not an approximation, it is a different number.

## The correlation skew, which was not planted

The one thing quoted with a free hand is the index's skew: constituents get a slope of `-0.30`
in log-moneyness, the index gets `-0.65`, which is the familiar stylised fact that index skew
is steeper than single-name skew. **Nothing about correlation was planted away from the money.**

What comes out:

| log-moneyness | mean implied correlation |
|---|---|
| `-0.060` | `0.51420` |
| `0.000` | `0.48229` |
| `+0.060` | `0.45168` |

```
d(rho) / d(-k)  =  +0.52     ranging  +0.38  to  +0.67  across the sixty days
```

**Implied correlation rises into the downside**, and it does so as a *consequence* of the index
skew being steeper, not because anything said it should. That is the mechanism behind the
observation, produced rather than asserted.

It carries a warning with it. **There is no such thing as "the" implied correlation for this
basket** — it is `0.514` or `0.482` or `0.452` depending only on where you evaluate it, a spread
of `0.06` across a `12%` band of moneyness. A correlation number without a moneyness attached is
not a number.

## Extrapolation costs accuracy even when the form is exactly right

The strike ladder is fixed at the first day's price, so contracts persist — the lesson from
`docs/history_run.md`. But the forward carries and the spot moves, so a fixed strike does not
hold a fixed moneyness, and the `+6%` target drifts outside the quoted range whenever a name
rallies. Only **103 of 180** evaluations are interpolations; the rest reach past the last strike.

The generated slice is *exactly* quadratic in log-moneyness, so a quadratic fit ought to
extrapolate perfectly. It does not:

| | at-the-money rms error | mean correlation skew |
|---|---|---|
| interpolated only, 13 days | `1.26e-06` | `+0.4850` |
| partly extrapolated, 47 days | `7.75e-06` | `+0.5310` |

**Six times the error**, and a skew `9%` steeper, from reaching past the data. Both numbers are
tiny here, which is the point: this is the *best possible case* — the functional form is exactly
right and the only noise is price rounding — and extrapolation still amplifies it six-fold. On
quotes whose true shape is not a quadratic, the amplification would land on model error rather
than on rounding. The coverage count is reported on every run for that reason.

## What this is not

The correlation here is recovered from a market that was built to contain it. That establishes
the pipeline works end to end and that its error budget is quote granularity; it establishes
nothing about a real index.

**Step 9's completion condition remains unmet**, and this does not move it: it asks for
agreement with a *published* correlation series, and agreeing with a number this repository
planted is the opposite of external validation. See `spec/interfaces/implied_correlation.md`.

Nor is there a dispersion trade here yet. The vega weights that would carry one exist and are
tested, but nothing has been held, financed or charged a spread.

## Invariants under test

- the planted weights sum to one
- the quadratic fit reproduces an exactly quadratic slice at every strike
- too few strikes, and repeated strikes, are typed errors rather than a division by nothing
- the planted correlation is recovered on every one of the sixty days to `1e-4`
- every day implies an admissible correlation
- dropping the diagonal overstates by more than `0.05` on every day of this basket
- a steeper index skew implies correlation rising monotonically into the downside
- extrapolating the slice costs accuracy even where the functional form is exact
