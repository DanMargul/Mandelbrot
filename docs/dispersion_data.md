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

## Holding it

`backtest/dispersion_run.py` trades the correlation rather than just measuring it. When the
implied correlation is high against its own history it sells the index straddle and buys a
straddle in every name, sized by the vega weights of `implied_correlation.md`, and reverses when
it is low. Straddles rather than calls, so the book is roughly delta flat without a hedger.

Running the engine over nine underlyings at once needed the engine to stop assuming one.
`BacktestRequest` now carries `underlying_symbols`, and because `ContractQuote` does not know its
own underlying — the partition knew — `StepContext` carries `quotes_by_underlying` so a strategy
does not have to parse contract symbols to find out.

### The signal is there and the trade still loses

Sixty days, ten index straddles, entry at one standard deviation:

| | |
|---|---|
| steps that traded | `26` of `60` |
| gross profit | `42,023` |
| transaction cost | `69,637` |
| **net profit** | **`-27,614`** |
| contracts traded | `2,616` |

**Cost is 1.66 times gross.** The correlation signal is real — the same signal that was recovered
to seven parts in a million above — and it does not survive being traded.

### Where the cost is

Establishing one full book, at a correlation of `0.617`:

| | weight | straddles | crossing cost | share |
|---|---|---|---|---|
| `IDXB` | | `10` | `1,176` | `23.1%` |
| eight constituents | | `83` | `3,914` | **`76.9%`** |

**Expressing a ten-straddle view on the index takes ninety-three straddles**, and the eight
replicating legs carry three quarters of the cost while quoting a `2.0%` half-spread against the
index's `0.6%`. That is the trade: you buy one instrument by rebuilding it out of eight more
expensive ones, and the arithmetic of that is not a detail of the signal.

### What market it would need

Because the mid price does not move when the spread changes, the implied volatilities and
therefore every trading decision are identical across the sweep — gross and contracts traded are
the same number at every spread, and only the cost moves:

| constituent half-spread | gross | cost | net |
|---|---|---|---|
| `2.0%` | `42,023` | `69,637` | `-27,614` |
| `1.5%` | `42,023` | `56,428` | `-14,405` |
| `1.0%` | `42,023` | `43,218` | `-1,196` |
| `0.5%` | `42,023` | `30,016` | `+12,007` |
| `0.2%` | `42,023` | `22,513` | `+19,509` |

so the break-even is exact: **a constituent half-spread of `0.94%`**, less than half what the
names quote. And the intercept matters as much as the slope — the index leg costs `17,277`
whatever the constituents charge, so **even with the eight legs free the trade clears only
`24,746`**.

### A dispersion book has a minimum size

The vega weights are real numbers and contracts are integers, and with eight legs that rounding
is not a rounding:

| index straddles | worst leg error | rms leg error |
|---|---|---|
| `5` | `18.56%` | `10.27%` |
| `10` | `8.67%` | `4.27%` |
| `20` | `-2.61%` | `1.63%` |
| `50` | `-1.38%` | `0.73%` |
| `200` | `0.24%` | `0.14%` |

**At five index straddles the book misses its own hedge by ten percent**, which is single-name
volatility exposure it did not mean to take and is not being paid for. It shows up in the
results: going from ten to twenty index straddles multiplies gross by `2.21`, not by `2`, because
the larger book is the better hedged one. A dispersion trade has a minimum viable size and it is
set by contract granularity, not by capital.

### The threshold that appears to work

Sweeping the entry threshold produces one positive number:

| entry z | net | steps that traded |
|---|---|---|
| `0.50` | `-24,372` | `37` |
| `0.75` | `-45,000` | `33` |
| `1.00` | `-27,614` | `26` |
| `1.25` | `-24,470` | `22` |
| `1.50` | `-21,884` | `8` |
| `2.00` | **`+15,222`** | **`2`** |

**Two trades.** One threshold out of six, on two of sixty days, and every other threshold loses.
`docs/history_run.md` measured a probability of backtest overfitting of `1.000` for exactly this
shape of search, and this one does not even need the machinery — a result standing on two
observations is not a result. It is recorded here because it is the number a threshold sweep
would have reported, and reporting the sweep without it would be the dishonest version.

## What this is not

The correlation here is recovered from a market that was built to contain it. That establishes
the pipeline works end to end and that its error budget is quote granularity; it establishes
nothing about a real index.

**Step 9's completion condition remains unmet**, and this does not move it: it asks for
agreement with a *published* correlation series, and agreeing with a number this repository
planted is the opposite of external validation. See `spec/interfaces/implied_correlation.md`.

The trade above is held and charged, but it is held against a market whose spreads were chosen
by this repository as surely as its correlation was. The break-even of `0.94%` is a statement
about those numbers. Whether real single-name options quote inside it is the question step 6's
uncalibrated fill model was always going to decide, and it is still uncalibrated.

## Invariants under test

- the planted weights sum to one
- the quadratic fit reproduces an exactly quadratic slice at every strike
- too few strikes, and repeated strikes, are typed errors rather than a division by nothing
- the planted correlation is recovered on every one of the sixty days to `1e-4`
- every day implies an admissible correlation
- dropping the diagonal overstates by more than `0.05` on every day of this basket
- a steeper index skew implies correlation rising monotonically into the downside
- extrapolating the slice costs accuracy even where the functional form is exact
- the engine reaches every underlying in the basket and groups the quotes by it
- a rich correlation is sold short the index and long every name, and a cheap one reverses
- a straddle with no vega is not sized
- contract granularity, not capital, is what limits the hedge
- the correlation signal is found and still does not pay for the spread
- the one profitable threshold trades on at most five of sixty days
