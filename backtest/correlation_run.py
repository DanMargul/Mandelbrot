#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.implied_correlation import (  # noqa: E402
    BasketConstituent,
    CorrelationReport,
    imply_correlation,
)
from volarb_py.implied_vol import (  # noqa: E402
    ImpliedVolatilityInputs,
    invert_black_implied_volatility,
)
from volarb_py.market_data import (  # noqa: E402
    AsOfChainReader,
    ChainQuery,
    ContractQuote,
    KnowledgeHorizon,
    open_chain_dataset,
)

CORRELATION_TRUTH_FILENAME: Final[str] = "correlation_truth.json"
DAYS_PER_YEAR: Final[float] = 365.0
LADDER_POINTS: Final[int] = 3
QUADRATIC_TERMS: Final[int] = 3
MINIMUM_PIVOT: Final[float] = 1e-14
QUOTED_EXPIRY: Final[int] = 1
DOWNSIDE_MONEYNESS: Final[float] = -0.06
UPSIDE_MONEYNESS: Final[float] = 0.06
AT_THE_MONEY: Final[float] = 0.0
EXIT_OK: Final[int] = 0


@dataclass(frozen=True)
class BasketDefinition:
    index_symbol: str
    weights: dict[str, float]
    risk_free_rate: float
    observation_hour_utc: int
    settlement_hour_utc: int
    expiry_dates: list[date]
    observations: list[dict[str, Any]]


def basket_definition(dataset_root: Path) -> BasketDefinition:
    truth = json.loads((dataset_root / CORRELATION_TRUTH_FILENAME).read_text(encoding="utf-8"))
    return BasketDefinition(
        index_symbol=str(truth["index_symbol"]),
        weights={str(symbol): float(weight) for symbol, weight in truth["weights"].items()},
        risk_free_rate=float(truth["risk_free_rate"]),
        observation_hour_utc=int(truth["observation_hour_utc"]),
        settlement_hour_utc=int(truth["expiry_settlement_hour_utc"]),
        expiry_dates=[date.fromisoformat(str(entry)) for entry in truth["expiry_dates"]],
        observations=list(truth["observations"]),
    )


class MissingSurfaceError(ValueError):
    pass


@dataclass(frozen=True)
class SlicePoint:
    log_moneyness: float
    log_volatility: float


@dataclass(frozen=True)
class DayCorrelation:
    observation_date: str
    planted: float
    reports: dict[float, CorrelationReport]
    targets_inside_quoted_range: int


@dataclass(frozen=True)
class SliceRequest:
    quotes: list[ContractQuote]
    moment: datetime
    expiry: date
    settlement_hour_utc: int
    risk_free_rate: float


def slice_points(request: SliceRequest) -> list[SlicePoint]:
    settlement = datetime(
        request.expiry.year,
        request.expiry.month,
        request.expiry.day,
        request.settlement_hour_utc,
        tzinfo=UTC,
    )
    years = (settlement - request.moment).total_seconds() / (DAYS_PER_YEAR * 24.0 * 3600.0)
    discount = math.exp(-request.risk_free_rate * years)
    points: list[SlicePoint] = []
    for quote in request.quotes:
        if quote.expiry_date != request.expiry or quote.option_type != "call":
            continue
        forward = quote.underlying_price / discount
        inverted = invert_black_implied_volatility(
            ImpliedVolatilityInputs(
                forward,
                quote.strike,
                years,
                discount,
                0.5 * (quote.bid_price + quote.ask_price),
                quote.option_type,
            )
        )
        if inverted.status != "converged" or inverted.volatility <= 0.0:
            continue
        points.append(SlicePoint(math.log(quote.strike / forward), math.log(inverted.volatility)))
    points.sort(key=lambda point: point.log_moneyness)
    return points


def normal_equations(points: list[SlicePoint]) -> tuple[list[list[float]], list[float]]:
    left = [[0.0] * QUADRATIC_TERMS for _ in range(QUADRATIC_TERMS)]
    right = [0.0] * QUADRATIC_TERMS
    for point in points:
        powers = [1.0, point.log_moneyness, point.log_moneyness * point.log_moneyness]
        for row in range(QUADRATIC_TERMS):
            right[row] += powers[row] * point.log_volatility
            for column in range(QUADRATIC_TERMS):
                left[row][column] += powers[row] * powers[column]
    return left, right


def solved(left: list[list[float]], right: list[float]) -> list[float]:
    size = len(right)
    for pivot in range(size):
        chosen = max(range(pivot, size), key=lambda row: abs(left[row][pivot]))
        if abs(left[chosen][pivot]) < MINIMUM_PIVOT:
            raise MissingSurfaceError("the quoted strikes do not determine a quadratic slice")
        left[pivot], left[chosen] = left[chosen], left[pivot]
        right[pivot], right[chosen] = right[chosen], right[pivot]
        for row in range(size):
            if row == pivot:
                continue
            factor = left[row][pivot] / left[pivot][pivot]
            for column in range(pivot, size):
                left[row][column] -= factor * left[pivot][column]
            right[row] -= factor * right[pivot]
    return [right[index] / left[index][index] for index in range(size)]


def volatility_at(points: list[SlicePoint], target: float) -> float:
    if len(points) < LADDER_POINTS:
        raise MissingSurfaceError(f"a slice needs at least {LADDER_POINTS} points, got {len(points)}")
    left, right = normal_equations(points)
    constant, slope, curvature = solved(left, right)
    return math.exp(constant + slope * target + curvature * target * target)


def slice_for(
    reader: AsOfChainReader, symbol: str, moment: datetime, definition: BasketDefinition, expiry: date
) -> list[SlicePoint]:
    quotes = reader.chain_as_of(ChainQuery(underlying_symbol=symbol, observation_time=moment))
    return slice_points(
        SliceRequest(quotes, moment, expiry, definition.settlement_hour_utc, definition.risk_free_rate)
    )


def within_range(points: list[SlicePoint], target: float) -> bool:
    return points[0].log_moneyness <= target <= points[-1].log_moneyness


def day_correlations(dataset_root: Path, expiry_index: int) -> list[DayCorrelation]:
    definition = basket_definition(dataset_root)
    expiry = definition.expiry_dates[expiry_index]
    targets = (DOWNSIDE_MONEYNESS, AT_THE_MONEY, UPSIDE_MONEYNESS)
    days: list[DayCorrelation] = []
    for observation in definition.observations:
        moment = datetime.strptime(str(observation["observation_date"]), "%Y-%m-%d").replace(
            hour=definition.observation_hour_utc, tzinfo=UTC
        )
        reader = open_chain_dataset(dataset_root, KnowledgeHorizon(as_of=moment))
        index_slice = slice_for(reader, definition.index_symbol, moment, definition, expiry)
        name_slices = {
            symbol: slice_for(reader, symbol, moment, definition, expiry)
            for symbol in sorted(definition.weights)
        }
        reports: dict[float, CorrelationReport] = {}
        inside = 0
        for target in targets:
            constituents = [
                BasketConstituent(symbol, weight, volatility_at(name_slices[symbol], target))
                for symbol, weight in sorted(definition.weights.items())
            ]
            reports[target] = imply_correlation(constituents, volatility_at(index_slice, target))
            if within_range(index_slice, target) and all(
                within_range(points, target) for points in name_slices.values()
            ):
                inside += 1
        days.append(
            DayCorrelation(
                str(observation["observation_date"]),
                float(observation["correlation"]),
                reports,
                inside,
            )
        )
    return days


def root_mean_square(values: list[float]) -> float:
    total = 0.0
    for value in values:
        total += value * value
    return math.sqrt(total / len(values))


def mean_of(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def report_recovery(days: list[DayCorrelation]) -> None:
    errors = [day.reports[AT_THE_MONEY].clean_correlation - day.planted for day in days]
    dirty = [day.reports[AT_THE_MONEY].dirty_correlation - day.planted for day in days]
    print(f"observations:                        {len(days)}")
    print(f"planted correlation, mean:           {mean_of([day.planted for day in days]):>10.5f}")
    print(f"recovered at the money, mean error:  {mean_of(errors):>+10.6f}")
    print(f"recovered at the money, worst error: {max(errors, key=abs):>+10.6f}")
    print(f"recovered at the money, rms error:   {root_mean_square(errors):>10.6f}")
    print(f"dropping the diagonal, mean error:   {mean_of(dirty):>+10.5f}")
    print(f"dropping the diagonal, worst error:  {max(dirty, key=abs):>+10.5f}")


def report_skew(days: list[DayCorrelation]) -> None:
    down, up = DOWNSIDE_MONEYNESS, UPSIDE_MONEYNESS
    slopes = [
        (day.reports[down].clean_correlation - day.reports[up].clean_correlation) / (up - down)
        for day in days
    ]
    print()
    for target in (down, AT_THE_MONEY, up):
        values = [day.reports[target].clean_correlation for day in days]
        admissible = sum(1 for day in days if day.reports[target].is_admissible)
        print(
            f"log-moneyness {target:>+6.3f}: mean implied correlation {mean_of(values):>8.5f}   "
            f"admissible on {admissible}/{len(days)} days"
        )
    covered = sum(day.targets_inside_quoted_range for day in days)
    print(f"targets inside the quoted range:     {covered}/{3 * len(days)}")
    print(f"correlation skew, d(rho)/d(-k):      {mean_of(slopes):>+10.4f}")
    print(f"                        smallest:    {min(slopes):>+10.4f}")
    print(f"                         largest:    {max(slopes):>+10.4f}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="correlation-report")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--expiry-index", type=int, default=QUOTED_EXPIRY)
    arguments = parser.parse_args(argv)
    days = day_correlations(arguments.dataset, arguments.expiry_index)
    report_recovery(days)
    report_skew(days)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
