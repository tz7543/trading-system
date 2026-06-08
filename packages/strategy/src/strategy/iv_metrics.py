from collections.abc import Iterable
from dataclasses import dataclass
from math import isnan


@dataclass(frozen=True)
class IVMetrics:
    current_iv: float
    iv_rank: float
    iv_percentile: float
    history_count: int


def valid_iv_values(values: Iterable[float | None]) -> list[float]:
    valid = []
    for value in values:
        if value is None or isnan(value) or value < 0:
            continue
        valid.append(float(value))
    return valid


def calculate_iv_rank(history: Iterable[float | None], current_iv: float) -> float:
    values = _valid_history(history)
    low = min(values)
    high = max(values)
    if high == low:
        return 100.0 if current_iv >= high else 0.0
    return ((current_iv - low) / (high - low)) * 100.0


def calculate_iv_percentile(
    history: Iterable[float | None],
    current_iv: float,
) -> float:
    values = _valid_history(history)
    count_at_or_below = sum(1 for value in values if value <= current_iv)
    return (count_at_or_below / len(values)) * 100.0


def calculate_iv_metrics(
    history: Iterable[float | None],
    current_iv: float,
) -> IVMetrics:
    values = _valid_history(history)
    return IVMetrics(
        current_iv=current_iv,
        iv_rank=calculate_iv_rank(values, current_iv),
        iv_percentile=calculate_iv_percentile(values, current_iv),
        history_count=len(values),
    )


def _valid_history(history: Iterable[float | None]) -> list[float]:
    values = valid_iv_values(history)
    if not values:
        raise ValueError("iv history is empty")
    return values
