from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

MINIMUM_CONSTITUENTS: Final[int] = 2
MINIMUM_WEIGHT_TOTAL: Final[float] = 1e-12
MINIMUM_OFF_DIAGONAL: Final[float] = 1e-18
PERFECT_CORRELATION: Final[float] = 1.0
WEIGHT_TOTAL_TOLERANCE: Final[float] = 1e-9


class InvalidBasketError(ValueError):
    pass


@dataclass(frozen=True)
class BasketConstituent:
    symbol: str
    weight: float
    volatility: float


@dataclass(frozen=True)
class BasketMoments:
    weighted_volatility: float
    diagonal_variance: float
    off_diagonal_variance: float
    concentration: float


@dataclass(frozen=True)
class CorrelationReport:
    constituent_count: int
    index_volatility: float
    weighted_volatility: float
    concentration: float
    clean_correlation: float
    diagonal_bias: float
    dirty_correlation: float
    lowest_admissible_correlation: float
    is_admissible: bool
    exceeds_perfect_correlation: bool


def validate_basket(constituents: list[BasketConstituent]) -> None:
    if len(constituents) < MINIMUM_CONSTITUENTS:
        raise InvalidBasketError(
            f"a basket needs at least {MINIMUM_CONSTITUENTS} constituents, got {len(constituents)}"
        )
    total = 0.0
    for constituent in constituents:
        if constituent.weight <= 0.0:
            raise InvalidBasketError(
                f"{constituent.symbol} carries a weight of {constituent.weight}, which is not positive"
            )
        if constituent.volatility <= 0.0:
            raise InvalidBasketError(
                f"{constituent.symbol} carries a volatility of {constituent.volatility}, "
                f"which is not positive"
            )
        total += constituent.weight
    if abs(total - 1.0) > WEIGHT_TOTAL_TOLERANCE:
        raise InvalidBasketError(f"the constituent weights sum to {total} rather than one")


def moments_of(constituents: list[BasketConstituent]) -> BasketMoments:
    weighted = 0.0
    diagonal = 0.0
    for constituent in constituents:
        contribution = constituent.weight * constituent.volatility
        weighted += contribution
        diagonal += contribution * contribution
    off_diagonal = weighted * weighted - diagonal
    return BasketMoments(
        weighted_volatility=weighted,
        diagonal_variance=diagonal,
        off_diagonal_variance=off_diagonal,
        concentration=diagonal / (weighted * weighted),
    )


def lowest_admissible_correlation(constituent_count: int) -> float:
    return -1.0 / (constituent_count - 1)


def basket_volatility(constituents: list[BasketConstituent], correlation: float) -> float:
    validate_basket(constituents)
    floor = lowest_admissible_correlation(len(constituents))
    if correlation < floor or correlation > PERFECT_CORRELATION:
        raise InvalidBasketError(
            f"a correlation of {correlation} is outside the admissible range "
            f"[{floor}, {PERFECT_CORRELATION}] for {len(constituents)} constituents"
        )
    moments = moments_of(constituents)
    variance = moments.diagonal_variance + correlation * moments.off_diagonal_variance
    return math.sqrt(max(variance, 0.0))


def imply_correlation(constituents: list[BasketConstituent], index_volatility: float) -> CorrelationReport:
    validate_basket(constituents)
    if index_volatility <= 0.0:
        raise InvalidBasketError(f"the index volatility must be positive, got {index_volatility}")
    moments = moments_of(constituents)
    if moments.off_diagonal_variance < MINIMUM_OFF_DIAGONAL:
        raise InvalidBasketError(
            "the off diagonal variance is nothing, so no correlation can be implied from it"
        )
    index_variance = index_volatility * index_volatility
    clean = (index_variance - moments.diagonal_variance) / moments.off_diagonal_variance
    bias = moments.concentration * (PERFECT_CORRELATION - clean)
    floor = lowest_admissible_correlation(len(constituents))
    return CorrelationReport(
        constituent_count=len(constituents),
        index_volatility=index_volatility,
        weighted_volatility=moments.weighted_volatility,
        concentration=moments.concentration,
        clean_correlation=clean,
        diagonal_bias=bias,
        dirty_correlation=clean + bias,
        lowest_admissible_correlation=floor,
        is_admissible=floor <= clean <= PERFECT_CORRELATION,
        exceeds_perfect_correlation=clean > PERFECT_CORRELATION,
    )


def index_sensitivities(constituents: list[BasketConstituent], correlation: float) -> list[float]:
    index_volatility = basket_volatility(constituents, correlation)
    moments = moments_of(constituents)
    sensitivities: list[float] = []
    for constituent in constituents:
        contribution = constituent.weight * constituent.volatility
        others = moments.weighted_volatility - contribution
        sensitivities.append(constituent.weight * (contribution + correlation * others) / index_volatility)
    return sensitivities


def dispersion_vega_weights(
    constituents: list[BasketConstituent], correlation: float, index_vega: float
) -> list[float]:
    return [index_vega * sensitivity for sensitivity in index_sensitivities(constituents, correlation)]
