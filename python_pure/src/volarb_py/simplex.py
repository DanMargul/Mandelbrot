from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

MAXIMUM_SIMPLEX_ITERATIONS: Final[int] = 4000
SIMPLEX_SPREAD_TOLERANCE: Final[float] = 1e-12
SIMPLEX_INITIAL_STEP: Final[float] = 0.5
REFLECTION_COEFFICIENT: Final[float] = 1.0
EXPANSION_COEFFICIENT: Final[float] = 2.0
CONTRACTION_COEFFICIENT: Final[float] = 0.5
SHRINK_COEFFICIENT: Final[float] = 0.5


@dataclass(frozen=True)
class SimplexStep:
    coordinates: list[float]
    value: float


@dataclass(frozen=True)
class ContractionContext:
    centroid: list[float]
    worst_vertex: list[float]
    worst_value: float
    reflected: list[float]
    reflected_value: float


@dataclass(frozen=True)
class SimplexOutcome:
    coordinates: list[float]
    value: float
    iterations: int
    settled: bool


def simplex_vertex_order(vertices: list[list[float]], values: list[float]) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (values[index], vertices[index]))


def centroid_excluding_worst(vertices: list[list[float]], order: list[int]) -> list[float]:
    kept = order[:-1]
    dimension = len(vertices[0])
    return [sum(vertices[index][axis] for index in kept) / len(kept) for axis in range(dimension)]


def combine(base: list[float], direction: list[float], scale: float) -> list[float]:
    return [base[axis] + scale * (direction[axis] - base[axis]) for axis in range(len(base))]


def simplex_spread(vertices: list[list[float]], order: list[int]) -> float:
    best = vertices[order[0]]
    dimension = len(best)
    return max(abs(vertices[index][axis] - best[axis]) for index in order[1:] for axis in range(dimension))


def contracted_replacement(
    context: ContractionContext, evaluate: Callable[[list[float]], float]
) -> SimplexStep | None:
    if context.reflected_value < context.worst_value:
        outside = combine(context.centroid, context.reflected, CONTRACTION_COEFFICIENT)
        outside_value = evaluate(outside)
        if outside_value <= context.reflected_value:
            return SimplexStep(outside, outside_value)
        return None
    inside = combine(context.centroid, context.worst_vertex, CONTRACTION_COEFFICIENT)
    inside_value = evaluate(inside)
    if inside_value < context.worst_value:
        return SimplexStep(inside, inside_value)
    return None


def shrink_towards_best(
    vertices: list[list[float]], values: list[float], best: int, evaluate: Callable[[list[float]], float]
) -> None:
    anchor = list(vertices[best])
    for index in range(len(vertices)):
        if index == best:
            continue
        vertices[index] = combine(anchor, vertices[index], SHRINK_COEFFICIENT)
        values[index] = evaluate(vertices[index])


def advance_simplex(
    vertices: list[list[float]],
    values: list[float],
    order: list[int],
    evaluate: Callable[[list[float]], float],
) -> None:
    best, second_worst, worst = order[0], order[-2], order[-1]
    centroid = centroid_excluding_worst(vertices, order)

    reflected = combine(centroid, vertices[worst], -REFLECTION_COEFFICIENT)
    reflected_value = evaluate(reflected)

    if reflected_value < values[best]:
        expanded = combine(centroid, reflected, EXPANSION_COEFFICIENT)
        expanded_value = evaluate(expanded)
        if expanded_value < reflected_value:
            vertices[worst], values[worst] = expanded, expanded_value
        else:
            vertices[worst], values[worst] = reflected, reflected_value
        return

    if reflected_value < values[second_worst]:
        vertices[worst], values[worst] = reflected, reflected_value
        return

    contraction = contracted_replacement(
        ContractionContext(
            centroid=centroid,
            worst_vertex=vertices[worst],
            worst_value=values[worst],
            reflected=reflected,
            reflected_value=reflected_value,
        ),
        evaluate,
    )
    if contraction is not None:
        vertices[worst], values[worst] = contraction.coordinates, contraction.value
        return

    shrink_towards_best(vertices, values, best, evaluate)


def minimise_by_simplex(evaluate: Callable[[list[float]], float], seed: list[float]) -> SimplexOutcome:
    vertices = [list(seed)]
    for axis in range(len(seed)):
        shifted = list(seed)
        shifted[axis] += SIMPLEX_INITIAL_STEP
        vertices.append(shifted)
    values = [evaluate(vertex) for vertex in vertices]

    for iteration in range(1, MAXIMUM_SIMPLEX_ITERATIONS + 1):
        order = simplex_vertex_order(vertices, values)
        if simplex_spread(vertices, order) <= SIMPLEX_SPREAD_TOLERANCE:
            best = order[0]
            return SimplexOutcome(vertices[best], values[best], iteration, True)
        advance_simplex(vertices, values, order, evaluate)

    order = simplex_vertex_order(vertices, values)
    best = order[0]
    return SimplexOutcome(vertices[best], values[best], MAXIMUM_SIMPLEX_ITERATIONS, False)
