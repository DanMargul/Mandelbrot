from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

PCG_MULTIPLIER: Final[int] = 0x2360ED051FC65DA44385DF649FCCF645
STATE_MASK: Final[int] = (1 << 128) - 1
WORD_MASK: Final[int] = (1 << 64) - 1
ROTATION_SHIFT: Final[int] = 122
MANTISSA_SHIFT: Final[int] = 11
MANTISSA_SCALE: Final[float] = 1.0 / 9007199254740992.0
TWO_PI: Final[float] = 6.283185307179586


class InvalidRandomSourceError(ValueError):
    pass


@dataclass(frozen=True)
class PcgState:
    state: int
    increment: int


@dataclass(frozen=True)
class NormalPair:
    state: PcgState
    first: float
    second: float


def advanced(source: PcgState) -> PcgState:
    return PcgState(
        state=(source.state * PCG_MULTIPLIER + source.increment) & STATE_MASK,
        increment=source.increment,
    )


def rotate_right(value: int, rotation: int) -> int:
    return ((value >> rotation) | (value << ((-rotation) & 63))) & WORD_MASK


def output_of(source: PcgState) -> int:
    xorshifted = ((source.state >> 64) ^ source.state) & WORD_MASK
    return rotate_right(xorshifted, source.state >> ROTATION_SHIFT)


def seeded_source(initial_state: int, sequence: int) -> PcgState:
    if initial_state < 0 or sequence < 0:
        raise InvalidRandomSourceError(f"a seed must not be negative, got {initial_state} and {sequence}")
    increment = ((sequence << 1) | 1) & STATE_MASK
    source = advanced(PcgState(state=0, increment=increment))
    source = PcgState(state=(source.state + initial_state) & STATE_MASK, increment=increment)
    return advanced(source)


def next_bits(source: PcgState) -> tuple[PcgState, int]:
    stepped = advanced(source)
    return stepped, output_of(stepped)


def next_uniform(source: PcgState) -> tuple[PcgState, float]:
    stepped, bits = next_bits(source)
    return stepped, (bits >> MANTISSA_SHIFT) * MANTISSA_SCALE


def next_positive_uniform(source: PcgState) -> tuple[PcgState, float]:
    stepped, bits = next_bits(source)
    return stepped, ((bits >> MANTISSA_SHIFT) + 1) * MANTISSA_SCALE


def next_standard_normal_pair(source: PcgState) -> NormalPair:
    after_first, first_uniform = next_positive_uniform(source)
    after_second, second_uniform = next_uniform(after_first)
    radius = math.sqrt(-2.0 * math.log(first_uniform))
    angle = TWO_PI * second_uniform
    return NormalPair(state=after_second, first=radius * math.cos(angle), second=radius * math.sin(angle))


def uniforms(source: PcgState, count: int) -> tuple[PcgState, list[float]]:
    if count < 0:
        raise InvalidRandomSourceError(f"count must not be negative, got {count}")
    values: list[float] = []
    current = source
    for _ in range(count):
        current, value = next_uniform(current)
        values.append(value)
    return current, values


def standard_normals(source: PcgState, count: int) -> tuple[PcgState, list[float]]:
    if count < 0:
        raise InvalidRandomSourceError(f"count must not be negative, got {count}")
    values: list[float] = []
    current = source
    while len(values) < count:
        pair = next_standard_normal_pair(current)
        current = pair.state
        values.append(pair.first)
        if len(values) < count:
            values.append(pair.second)
    return current, values
