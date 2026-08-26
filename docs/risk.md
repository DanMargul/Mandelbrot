# The risk gate, and what breaking it found

Above the parity boundary, Python only. `risk/`.

Step 10 asks for pre-trade limits, rate limits, fat-finger bounds, kill switches and daily
reconciliation with break detection, and then says the thing that matters:

> Kill switches that have never been fired are decoration.

So the order here was: build the gate, then fire everything at it, then report what the firing
found rather than what the design intended.

## The shape

A `Broker` protocol with `submit` and `snapshot`. `PaperBroker` implements it over the
tri-implemented `execution` fill model, so paper fills cross the spread exactly as
`backtest/` charges for them. A live adapter would implement the same two methods.

`RiskGate` wraps any broker. Before an order reaches the venue it checks, in order: the kill
switch, whether a clean reconciliation is recent enough, the order rate, fat-finger bounds on
both quantity and notional, mark staleness, per-contract and per-underlying position limits,
whether every projected holding can be measured at all, and the aggregate delta, gamma, vega and
theta budgets. Any breach raises with **every** breach attached, not the first one.

## What the fault injection found

`risk/fault_injection.py` runs seven scenarios against a gate that believes it is healthy. This
is the table it printed against the first implementation:

| fault | halted | ours | theirs | reconciles |
|---|---|---|---|---|
| none | no | `4` | `4` | yes |
| connection died before the venue saw it | **yes** | `0` | `0` | yes |
| connection died after the venue took it | **yes** | `0` | `4` | no |
| acknowledged but never executed | **no** | `4` | `0` | **no** |
| filled in part | no | `2` | `2` | yes |
| broker reports a position we never sent | **no** | `4` | `4` | **no** |
| broker snapshot frozen in the past | **no** | `4` | `4` | **no** |

Three rows say *the books disagree and nothing stopped*. The gate had a `mark_unreconciled`
method that halted on a break, and **nothing ever called it**. Every break was detectable and
none was detected, because reconciliation was something an operator had to remember to run.

That is precisely the failure the step names, arrived at from the other side: not a kill switch
that was never fired, but one that was never *wired*. It only showed up because the scenarios
were run rather than reasoned about.

Two more defects fell out of probing around it.

**A position the gate cannot measure was treated as riskless.** `aggregate_greeks` skipped any
contract with no greek entry, so ten thousand contracts of something unrecognised contributed
exactly zero to a vega budget of `40,000`, and the check passed on the `8,400` of measured risk
sitting next to it. The holding a risk system cannot price is the one it should refuse hardest,
and it was invisible.

**`resume()` cleared a reconciliation halt without reconciling.** An operator could clear a halt
raised by a known position break and put the next order straight into a book the broker
disagreed with.

**And one suspicion was refuted rather than confirmed.** The submission log looked like it grew
without bound; the first measurement showed six entries after four hundred orders, which looked
like a refutation. It was not — trading had stopped six orders in, because the test harness was
feeding a mark that aged past the staleness horizon while the clock advanced. That is the
staleness check working, and it was masking the question. Re-measured with marks that track the
clock, the log held **2,000 stamps for a window that can never need more than 6**, and
`rate_breaches` scanned all of them on every order. A risk check that gets slower the longer it
runs is a defect, and the first measurement had said the opposite.

## After the fixes

Reconciliation is now the gate's own job. `reconcile_now` halts on a break; a clean
reconciliation must exist and be recent before any order is allowed out; an order whose outcome
is unknown clears that stamp; `resume` refuses unless the books agree; unmeasured holdings raise
their own breach; the submission log is pruned to the rate window.

| fault | raised | halted | ours | theirs |
|---|---|---|---|---|
| none | — | no | `4` | `4` |
| connection died before the venue saw it | — | yes | `0` | `0` |
| connection died after the venue took it | break, 2 breaches | yes | `0` | `4` |
| acknowledged but never executed | break, 1 breach | yes | `4` | `0` |
| filled in part | — | no | `2` | `2` |
| broker reports a position we never sent | rejected, kill switch | yes | `0` | `0` |
| broker snapshot frozen in the past | break, 2 breaches | yes | `4` | `4` |

Everything that should halt halts, and the two rows that should not — a clean order and a
partial fill — still do not. The phantom-position row improved further than expected: the
pre-trade reconciliation catches the disagreement **before** the order is sent, so it is
rejected by the kill switch rather than filled and then found.

## Two judgements worth stating

**A stale snapshot is indistinguishable from a break.** The frozen-snapshot row halts even
though the underlying positions actually agree — the gate cannot tell a broker that is wrong
from a broker that is behind, and treating the ambiguity as a break is the only safe reading.
The cost is a false halt when a feed lags. That is the right side to be wrong on.

**A break is not resolved by believing the broker.** Adopting the broker's positions would make
every reconciliation pass and would hide the bug that caused the drift. The gate halts and
requires the disagreement to be gone before it will resume; it never picks a winner.

## Constants

Every limit is data on `RiskLimits`, including the reconciliation interval and the rate window,
so the numbers in `fault_injection.py` are one configuration and not the policy. There is no
default set in the module, because a risk limit that a caller did not choose is a risk limit
nobody owns.

## What this is not

Not wired to a venue, as `roadmap.md` says Phase 7 would not be. `PaperBroker` is the only
implementation of the protocol, and the live adapter it was designed around does not exist.

**Step 10 is not met.** Its four conditions live in `runbook.md`, and this closes exactly one of
them — risk limits and kill switches exercised under deliberate fault injection. The other three
need a quarter of paper trading, attribution on realised paper P&L, and modelled costs validated
against observed fills. None of the three can be produced by writing code, and the last of them
is the same uncalibrated fill model that decided every result in `docs/history_run.md` and
`docs/dispersion_data.md`.

## Invariants under test

- a clean order fills, leaves the gate running, and reconciles
- nothing trades before a clean reconciliation, and a reconciliation goes out of date
- a halted gate refuses everything, and resuming requires the books to agree
- a stale mark blocks the order it cannot price, and a mark from the future is stale too
- a position the gate cannot measure stops it trading
- a fat finger never reaches the broker, on quantity or on notional
- a burst is throttled, and the rate log stays the size of its window
- a connection dying before the venue halts and still reconciles
- a connection dying after the venue leaves a break the gate finds
- an order acknowledged but never executed is caught by reconciliation
- a partial fill is believed rather than assumed away
- a frozen broker snapshot halts, being indistinguishable from a break
- every budget is checked, each is two-sided, and a short counts like a long
- cash inside the tolerance is not a break, and outside it is one even when positions agree
