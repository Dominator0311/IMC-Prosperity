from __future__ import annotations

from collections.abc import Sequence


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def bounded_append(values: list[float], value: float, maxlen: int) -> None:
    values.append(value)
    if len(values) > maxlen:
        del values[: len(values) - maxlen]


def weighted_average(values: Sequence[float], weights: Sequence[float]) -> float:
    if len(values) != len(weights):
        raise ValueError("values and weights must have the same length")
    total_weight = float(sum(weights))
    if total_weight == 0:
        raise ValueError("weights must not sum to zero")
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight

