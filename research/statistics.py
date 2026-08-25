from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

EULER_MASCHERONI: Final[float] = 0.5772156649015329
SQUARE_ROOT_OF_TWO: Final[float] = 1.4142135623730951
QUANTILE_BISECTION_PASSES: Final[int] = 200
QUANTILE_UPPER_BRACKET: Final[float] = 40.0
MINIMUM_TAIL_PROBABILITY: Final[float] = 1e-300
MEDIAN_TAIL_PROBABILITY: Final[float] = 0.5
MINIMUM_TRIALS: Final[int] = 1
MINIMUM_SAMPLE_LENGTH: Final[int] = 2
MINIMUM_RETURN_VARIANCE: Final[float] = 1e-300
NORMAL_KURTOSIS: Final[float] = 3.0


class InvalidStatisticsInputsError(ValueError):
    pass


@dataclass(frozen=True)
class SharpeSample:
    sharpe_ratio: float
    sample_length: int
    skewness: float
    excess_kurtosis: float


@dataclass(frozen=True)
class DeflatedSharpe:
    sharpe_ratio: float
    expected_maximum_under_null: float
    deflated_probability: float
    trial_count: int
    clears_threshold: bool


def standard_normal_upper_tail(x: float) -> float:
    return 0.5 * math.erfc(x / SQUARE_ROOT_OF_TWO)


def standard_normal_cumulative_distribution(x: float) -> float:
    return 0.5 * math.erfc(-x / SQUARE_ROOT_OF_TWO)


def upper_tail_quantile(tail_probability: float) -> float:
    if not 0.0 < tail_probability < 1.0:
        raise InvalidStatisticsInputsError(
            f"a tail probability must lie strictly inside (0, 1), got {tail_probability}"
        )
    if tail_probability == MEDIAN_TAIL_PROBABILITY:
        return 0.0
    if tail_probability > MEDIAN_TAIL_PROBABILITY:
        return -upper_tail_quantile(1.0 - tail_probability)

    lower = 0.0
    upper = QUANTILE_UPPER_BRACKET
    for _ in range(QUANTILE_BISECTION_PASSES):
        middle = 0.5 * (lower + upper)
        if standard_normal_upper_tail(middle) > tail_probability:
            lower = middle
        else:
            upper = middle
    return 0.5 * (lower + upper)


def expected_maximum_sharpe_ratio(trial_count: int, sharpe_standard_error: float) -> float:
    if trial_count < MINIMUM_TRIALS:
        raise InvalidStatisticsInputsError(f"trial_count must be at least 1, got {trial_count}")
    if sharpe_standard_error <= 0.0:
        raise InvalidStatisticsInputsError(
            f"sharpe_standard_error must be positive, got {sharpe_standard_error}"
        )
    if trial_count == MINIMUM_TRIALS:
        return 0.0

    tail = 1.0 / trial_count
    damped_tail = max(tail / math.e, MINIMUM_TAIL_PROBABILITY)
    first = upper_tail_quantile(tail)
    second = upper_tail_quantile(damped_tail)
    return sharpe_standard_error * ((1.0 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second)


def sharpe_standard_error(sample: SharpeSample) -> float:
    if sample.sample_length < MINIMUM_SAMPLE_LENGTH:
        raise InvalidStatisticsInputsError(
            f"sample_length must be at least {MINIMUM_SAMPLE_LENGTH}, got {sample.sample_length}"
        )
    variance = (
        1.0
        - sample.skewness * sample.sharpe_ratio
        + 0.25 * sample.excess_kurtosis * sample.sharpe_ratio * sample.sharpe_ratio
    )
    if variance <= 0.0:
        raise InvalidStatisticsInputsError(f"the estimated Sharpe variance is not positive, got {variance}")
    return math.sqrt(variance / (sample.sample_length - 1))


def deflated_sharpe_ratio(sample: SharpeSample, trial_count: int, threshold: float) -> DeflatedSharpe:
    if not 0.0 < threshold < 1.0:
        raise InvalidStatisticsInputsError(f"the threshold must lie strictly inside (0, 1), got {threshold}")
    standard_error = sharpe_standard_error(sample)
    expected_maximum = expected_maximum_sharpe_ratio(trial_count, standard_error)
    probability = standard_normal_cumulative_distribution(
        (sample.sharpe_ratio - expected_maximum) / standard_error
    )
    return DeflatedSharpe(
        sharpe_ratio=sample.sharpe_ratio,
        expected_maximum_under_null=expected_maximum,
        deflated_probability=probability,
        trial_count=trial_count,
        clears_threshold=probability >= threshold,
    )


def sharpe_ratio_needed_for(sample: SharpeSample, trial_count: int, threshold: float) -> float:
    standard_error = sharpe_standard_error(sample)
    expected_maximum = expected_maximum_sharpe_ratio(trial_count, standard_error)
    return expected_maximum + standard_error * upper_tail_quantile(1.0 - threshold)


def central_moment(deviations: list[float], order: int) -> float:
    return math.fsum(deviation**order for deviation in deviations) / len(deviations)


def sharpe_sample_of(returns: list[float]) -> SharpeSample:
    if len(returns) < MINIMUM_SAMPLE_LENGTH:
        raise InvalidStatisticsInputsError(
            f"a sample needs at least {MINIMUM_SAMPLE_LENGTH} returns, got {len(returns)}"
        )
    mean = math.fsum(returns) / len(returns)
    deviations = [value - mean for value in returns]
    variance = math.fsum(deviation * deviation for deviation in deviations) / (len(returns) - 1)
    if variance < MINIMUM_RETURN_VARIANCE:
        raise InvalidStatisticsInputsError(
            f"a constant return series has no Sharpe ratio, variance was {variance}"
        )
    deviation = math.sqrt(variance)
    return SharpeSample(
        sharpe_ratio=mean / deviation,
        sample_length=len(returns),
        skewness=central_moment(deviations, 3) / (deviation**3),
        excess_kurtosis=central_moment(deviations, 4) / (deviation**4) - NORMAL_KURTOSIS,
    )
