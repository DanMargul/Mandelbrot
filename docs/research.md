# Research integrity

Step 7 of `program.md`, landed out of order and deliberately so. Multiple-testing correction
needs the true number of configurations ever evaluated, and that number cannot be recovered
after the fact. It has to be recorded while the search is happening or it is already lost.

**Above the parity boundary: Python only.** These modules are bookkeeping and statistics run
once per result, not numerics on a hot path, so there is no comparison across tracks worth
paying for. See the table in `architecture.md`.

## Why the count matters more than it looks

Three years of daily returns, a realistic return distribution (skew `-0.5`, excess kurtosis
`3.0`), and a 95% threshold. The annualised Sharpe a strategy must clear, purely as a
function of how many things were tried:

| trials | annualised Sharpe needed |
|---|---|
| 1 | `0.95` |
| 10 | `1.86` |
| 100 | `2.41` |
| 1000 | `2.83` |
| 10000 | `3.18` |

Read the other way round, with a fixed observed result of Sharpe `1.5`:

| trials | deflated probability | clears 95%? |
|---|---|---|
| 1 | `0.994` | yes |
| 10 | `0.830` | **no** |
| 100 | `0.499` | no |
| 1000 | `0.234` | no |

**The same backtest stops being significant somewhere between the first attempt and the
tenth.** That is the entire argument for the registry: nobody remembers "about ten" honestly
six months later, and the honest number is always larger than it feels.

## The registry

An append-only log at one entry per line, where each entry's hash covers the previous
entry's hash. Editing or removing an entry in the middle breaks every hash after it, and the
break is reported with the sequence number where it starts.

### Registration happens before the outcome is known

This is the design decision that makes the count trustworthy, and it is worth stating on its
own. A registry written on completion can be gamed without lying: run a configuration, see a
bad number, decline to record it. Nothing was falsified and the count is still wrong.

So a trial is written in two entries. `register_trial` records the configuration and the
pins **at the moment the trial starts**, before any result exists. `record_outcome` appends a
second entry referring back to it. `trial_count` counts trials *started*, never trials
completed.

A trial that is started and never completed therefore stays in the count and is reported as
abandoned. That is the point: **an abandoned trial is still a trial**, and the multiple-testing
correction has to know about it.

### What the chain catches, and what it does not

Verified against a six-trial sweep:

| tampering | detected |
|---|---|
| an outcome edited in place | yes, "the entry has been edited since it was written" |
| an entry deleted from the middle | yes, the sequence and the chain both break |
| entries truncated from the **end** | **no** |

The last row is the honest limit and the name of the check is not allowed to hide it. A
truncated log is a shorter valid chain: nothing inside it is inconsistent. Detecting that
requires a witness outside the file, which is what the tip hash is for — a published result
must carry the registry tip and the trial count it was computed against, so a later
truncation shows up as a mismatch against the result rather than against the log.

`research/run.py verify` exits non-zero on a broken chain, so it can gate a report.

## The pins

A result is reproducible when four things are pinned, and it is worth being exact about the
fourth:

- `commit_sha` — the code
- `dataset_digest` — the data, read from the Parquet manifest written by ingestion, which has
  carried a content hash since step 1 for precisely this purpose
- `config_hash` — SHA-256 of the configuration in canonical JSON, so key order cannot change
  the hash and a string `"60"` cannot collide with an integer `60`
- `seed` — the randomness

Plus `working_tree_clean`, which is not a pin but a statement about whether the first one
means anything. **A dirty working tree makes the commit SHA a lie**, so `pins_are_reproducible`
returns false regardless of how well everything else matches, and `reasons_pins_differ`
reports it even when comparing a set of pins against itself. `run.py summarise` counts how
many trials were run on a dirty tree, because that count should be zero in anything that
gets published.

## Deflated Sharpe

The Bailey and Lopez de Prado correction. The expected maximum Sharpe under the null across
`N` independent trials is

```
E[max SR] = sigma_SR * ((1 - g) * Z(1/N) + g * Z(1/(N*e)))
```

with `g` the Euler-Mascheroni constant and `Z` the upper-tail quantile, and the deflated
probability is the normal CDF of `(SR - E[max SR]) / sigma_SR`. The standard error of the
Sharpe estimate carries the third and fourth moments, so negative skew and fat tails widen
it, which is the direction that makes an observed Sharpe less impressive rather than more.

### The quantile is taken from the tail, not from one minus the tail

`Z(1 - p)` with `p = 1/N` is the obvious way to write it and the wrong way to compute it. At
`N = 1e17` the expression `1 - 1/N` rounds to exactly `1.0` and the quantile is infinite for
no reason but arithmetic. The implementation solves the upper tail directly through
`erfc`, so the argument stays small and accurate where it matters. Checked against `mpmath`
at 50 decimal digits, the quantile agrees to `2.2e-16` relative across tail probabilities
from `0.4` down to `1e-200`, well past the point where `mpmath`'s own `erfinv` overflows.

This is the same lesson as always-invert-the-out-of-the-money-option in `math.md`: pick the
formulation whose small quantity is represented directly rather than as a difference of two
large ones.

### One defect, caught by its own test

The reflection for probabilities above the median recursed on `1 - p`, which at exactly
`p = 0.5` is `0.5` again: infinite recursion. That is not a corner nobody reaches. It is
`N = 2`, the second trial anybody ever runs. The median is now handled before the reflection.

## Layout

```
research/
  pins.py         ResultPins, configuration hashing, git and manifest interrogation
  registry.py     the hash-chained append-only trial log
  statistics.py   deflated Sharpe and the tail quantile it needs
  run.py          verify and summarise a registry from the command line
```

## What is not here yet

The probability of backtest overfitting via combinatorially symmetric cross-validation, and
strictly out-of-sample walk-forward selection. Both consume the registry rather than
changing it, so they are the next increment rather than a change to this one.
