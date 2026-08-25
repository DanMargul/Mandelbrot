# `random_source`

Below the parity boundary. Three implementations, conformance tested.

PCG64 with the XSL-RR output function, and the uniform and standard-normal draws built on it.
`math.md` specified this module before it existed and named the algorithm; what it also
claimed about the result turned out to need correcting, and that correction is the finding
here.

## Verified against an independent implementation

The repository's method is to check numerics against somebody else's arithmetic rather than
against itself, which is why `mpmath` is a dependency. `numpy` is now one too, for the same
reason and nothing else: `numpy.random.PCG64` accepts a raw 128-bit state and increment and
exposes `random_raw`, which makes it a direct oracle for the generator.

Seeded with the reference procedure at `initial_state = 42`, `sequence = 54`, the first six
64-bit words are

```
9705778491962043240   1370407407632858425   11774395822783136600
17944889938176486912  14437308781460811564   6944869453235589526
```

and `numpy` produces the same six. That check covers the multiplier, the seeding sequence, the
XSL-RR output function and the rotation together; getting any one of them wrong moves every
word. The vector is asserted in all three tracks, so it is a fixed point rather than a
one-off comparison.

## What is bit-identical and what is not

This is the correction. `math.md` said that both languages using PCG64 makes "simulated paths
identical bit for bit". Two of the three layers manage it and one does not.

| layer | built from | tracks differ |
|---|---|---|
| 64-bit words | 128-bit integer multiply-add, xor, rotate | `0` of `2560` |
| uniforms | a shift and one multiplication by `2^-53` | `0` of `2560` |
| standard normals | Box-Muller: `log`, `sqrt`, `cos`, `sin` | `4` of `2560` |

The first two are exact because IEEE-754 requires integer arithmetic and a single
multiplication to be exactly rounded. The third is not, because `log`, `cos` and `sin` are not
required to be correctly rounded and Python's libm and the C++ one disagree in the last bit on
about one draw in six hundred. The worst disagreement measured is `2.09e-16` relative, which
is one unit in the last place.

**The fixture is sized so that it actually contains such a case.** At 64 draws per stream the
divergence never appeared and the fixture would have locked in a property it was not testing;
at 512 it appears four times. Setting the tolerance to exact makes conformance fail on both
native tracks, so the tolerance is load-bearing rather than decorative.

### It does not amplify

The question that matters is not whether the last bit differs but whether it grows. Over 400
independent 252-step geometric paths, one terminal value differs between the tracks, by
`3.31e-16` relative. A path is a product of smooth factors, so a one-ulp perturbation stays a
one-ulp perturbation; there is no branch for it to flip, unlike the simplex in
`svi_calibration.md`.

That measurement is why this module does **not** carry its own logarithm. Replacing libm with
arithmetic-only approximations would buy back the last bit, and the evidence says the last bit
is not costing anything. Building it would have been effort spent against a number nobody
would ever see.

## The honest claim

> The 64-bit stream and the uniforms derived from it are identical bit for bit across all
> three tracks. Standard normals agree to one unit in the last place, because Box-Muller
> depends on library transcendentals, and that difference does not amplify along a path.

That is what `math.md` now says, in place of the stronger sentence it used to.

## Seeding

The reference procedure, unchanged:

```
increment = (sequence << 1) | 1
state     = 0
state     = state * MULTIPLIER + increment
state    += initial_state
state     = state * MULTIPLIER + increment
```

Seeds are 128-bit, so they cross the JSON boundary as **decimal strings** rather than numbers.
A JSON number cannot hold `2^128 - 1`, and a silently truncated seed is a reproducibility bug
that would look like an unlucky run. The 64-bit output words are returned as strings for the
same reason: above `2^53` a JSON number is no longer the integer that was drawn.

## Constants

```
PCG_MULTIPLIER   = 0x2360ED051FC65DA44385DF649FCCF645
ROTATION_SHIFT   = 122
MANTISSA_SHIFT   = 11
MANTISSA_SCALE   = 2^-53
```

`next_uniform` returns `[0, 1)`; `next_positive_uniform` returns `(0, 1]` and is what
Box-Muller takes the logarithm of, so the transform has no special case to guard.

## Verb

`draw-random-sample`, input `random_sample_request/v1`, output `random_sample/v1`. One record
is one seeded stream, returning the words, the uniforms and the normals together so a single
fixture exercises all three layers and their three different tolerances.

## Invariants under test

- the seeded stream reproduces the reference words, in all three tracks
- rotation wraps rather than discarding bits
- uniforms lie in `[0, 1)` and cover both ends of it
- standard normals have mean zero and variance one over 200,000 draws
- different sequences give different streams and the same seed repeats exactly
- an odd normal count consumes whole Box-Muller pairs and agrees with the even one on the
  values they share
- a negative count and a malformed seed are rejected; a zero count is empty rather than an
  error
