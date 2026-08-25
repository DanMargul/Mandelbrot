from __future__ import annotations

import pytest
from volarb_py.random_source import (
    InvalidRandomSourceError,
    advanced,
    next_bits,
    next_uniform,
    rotate_right,
    seeded_source,
    standard_normals,
    uniforms,
)

REFERENCE_STREAM = [
    9705778491962043240,
    1370407407632858425,
    11774395822783136600,
    17944889938176486912,
    14437308781460811564,
    6944869453235589526,
]
SAMPLE_SIZE = 200_000
WORD_BITS = 64
SHORT_DRAW = 3
LONGER_DRAW = 4
LOW_TAIL = 0.001
HIGH_TAIL = 0.999


def test_the_seeded_stream_matches_the_reference_implementation() -> None:
    current = seeded_source(42, 54)
    for expected in REFERENCE_STREAM:
        current, bits = next_bits(current)
        assert bits == expected


def test_rotation_wraps_rather_than_discarding_bits() -> None:
    assert rotate_right(1, 0) == 1
    assert rotate_right(1, 1) == 1 << (WORD_BITS - 1)
    assert rotate_right((1 << WORD_BITS) - 1, 37) == (1 << WORD_BITS) - 1


def test_uniforms_land_in_the_half_open_unit_interval() -> None:
    _, values = uniforms(seeded_source(1, 1), SAMPLE_SIZE)
    assert all(0.0 <= value < 1.0 for value in values)
    assert sum(values) / len(values) == pytest.approx(0.5, abs=0.005)
    assert min(values) < LOW_TAIL
    assert max(values) > HIGH_TAIL


def test_standard_normals_have_the_moments_they_claim() -> None:
    _, values = standard_normals(seeded_source(7, 3), SAMPLE_SIZE)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    assert mean == pytest.approx(0.0, abs=0.01)
    assert variance == pytest.approx(1.0, abs=0.02)


def test_different_sequences_are_different_streams() -> None:
    _, one = uniforms(seeded_source(1, 1), 64)
    _, other = uniforms(seeded_source(1, 2), 64)
    assert one != other

    _, repeated = uniforms(seeded_source(1, 1), 64)
    assert one == repeated


def test_the_state_advances_deterministically() -> None:
    source = seeded_source(11, 13)
    assert advanced(source).state == advanced(source).state
    assert advanced(source).increment == source.increment
    assert next_uniform(source)[1] == next_uniform(source)[1]


def test_a_negative_count_is_rejected() -> None:
    with pytest.raises(InvalidRandomSourceError):
        uniforms(seeded_source(1, 1), -1)
    with pytest.raises(InvalidRandomSourceError):
        standard_normals(seeded_source(1, 1), -1)
    with pytest.raises(InvalidRandomSourceError):
        seeded_source(-1, 1)
    assert uniforms(seeded_source(1, 1), 0)[1] == []


def test_an_odd_normal_count_still_consumes_whole_pairs() -> None:
    _, three = standard_normals(seeded_source(5, 5), SHORT_DRAW)
    _, four = standard_normals(seeded_source(5, 5), LONGER_DRAW)
    assert len(three) == SHORT_DRAW
    assert len(four) == LONGER_DRAW
    assert three == four[:SHORT_DRAW]
