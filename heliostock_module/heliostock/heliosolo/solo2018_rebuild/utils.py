from __future__ import annotations

import pandas as pd

from heliostock.heliosolo.solo2018_rebuild.defaults import DAYS_BY_MONTH


def weighted_mean(values: list[float], weights: list[float]) -> float:
    den = sum(weights)
    if den <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / den


def annual_sum_monthly(values: list[float], days: list[int] = DAYS_BY_MONTH) -> float:
    return sum(float(v) * int(d) for v, d in zip(values, days))


def fmt_num(value: float | int | str, digits: int = 1) -> str:
    if value == "":
        return "-"
    if isinstance(value, str):
        return value
    return f"{float(value):.{digits}f}".replace(".", ",")


def to_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(",", ".")
        if value == "":
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


