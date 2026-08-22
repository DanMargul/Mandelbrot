# Conventions

## No comments, no docstrings

Source files carry no `#` comments, no `//` or `/* */` comments, and no docstrings.
`tools/check_no_comments.py` fails the build on violations.

The permitted exceptions, and nothing else:

- a shebang on the first line of an executable script
- `# noqa`, `# type:`, `# pragma`, and `#include` style preprocessor directives
- an SPDX license identifier line

Prose belongs in `docs/`. A file that needs explaining gets an entry there, not a comment
block that will drift out of date the first time someone edits the code beneath it.

## Names do the work

Because there is nothing else to read, names must be complete:

```
calibrate_svi_slice_to_mid_implied_volatilities
detect_butterfly_arbitrage_violations_in_slice
total_implied_variance_from_svi_parameters
forward_from_put_call_parity_regression
```

Not `calibrate`, `check_arb`, `w`, `fwd`. A local variable inside a three-line numerical
kernel may be short when it maps to a symbol defined in `docs/math.md` (`d1`, `d2`, `sigma`),
and only then.

## Typing is the contract

With docstrings banned, type signatures are the only machine-checked description of an
interface. `mypy --strict` is mandatory on both Python tracks and is not waivable per file.

C++ uses concrete structs with named fields rather than tuples or `std::pair`, for the same
reason: the field name is the documentation.

## Cross-track naming

Public function names are identical across all three tracks, in `snake_case` in both
languages. Types are `PascalCase` in both. When reviewing a diff you should be able to read
the three implementations of a module side by side and match them line for line.

## Complexity budget

- no function longer than roughly 30 lines
- no more than three levels of nesting
- prefer an early return to an `else`
- split rather than nest; a name on the extracted piece is worth more than the saved line

## Errors

Failures are raised or returned, never logged and swallowed. Python raises typed exceptions
defined in each module. C++ returns `std::expected` where failure is an expected outcome of
valid input (an option price outside no-arbitrage bounds) and throws where it indicates a
programming error (a negative time to expiry).

Numerical routines never silently return a sentinel. If implied volatility cannot be
inverted, that is a result with a reason attached, not a `NaN` that propagates into a
signal three modules later.
