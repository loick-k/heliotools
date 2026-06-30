from __future__ import annotations

from dataclasses import asdict, is_dataclass
from threading import Lock
from typing import Any

from .engine import MonthlyDemand, SimulationConfig
from .hourly_engine import HourlyResult, HourlyWeather, simulate_hourly


def _freeze(value: Any) -> Any:
    if is_dataclass(value):
        return _freeze(asdict(value))
    if isinstance(value, dict):
        return tuple((key, _freeze(item)) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def _weather_signature(weather: list[HourlyWeather]) -> tuple[tuple[int, int, int, int, float, float], ...]:
    return tuple(
        (
            int(item.hour_index),
            int(item.month),
            int(item.day),
            int(item.hour),
            round(float(item.tair_c), 6),
            round(float(item.g_tilt_kwh_m2), 9),
        )
        for item in weather
    )


def _demands_signature(demands: list[MonthlyDemand]) -> tuple[tuple[int, float, float], ...]:
    return tuple(
        (
            int(item.month),
            round(float(item.process_ht_kwh), 6),
            round(float(item.process_bt_kwh), 6),
        )
        for item in demands
    )


def _override_signature(
    hourly_demand_override: dict[int, tuple[float, float]] | None,
) -> tuple[tuple[int, float, float], ...] | None:
    if hourly_demand_override is None:
        return None
    return tuple(
        (int(hour), round(float(values[0]), 6), round(float(values[1]), 6))
        for hour, values in sorted(hourly_demand_override.items())
    )


class SimulationCache:
    """In-memory cache for repeated hourly pygfunction simulations in one run."""

    def __init__(self) -> None:
        self._store: dict[tuple[Any, ...], tuple[HourlyResult, ...]] = {}
        self.hits = 0
        self.misses = 0
        self._lock = Lock()

    @property
    def entries(self) -> int:
        return len(self._store)

    def simulate(
        self,
        weather: list[HourlyWeather],
        demands: list[MonthlyDemand],
        config: SimulationConfig,
        *,
        hourly_demand_override: dict[int, tuple[float, float]] | None = None,
        simulation_years: int = 1,
        mode: str = "hourly",
    ) -> list[HourlyResult]:
        key = (
            str(mode),
            int(simulation_years),
            _weather_signature(weather),
            _demands_signature(demands),
            _override_signature(hourly_demand_override),
            _freeze(config),
        )
        with self._lock:
            cached = self._store.get(key)
            if cached is not None:
                self.hits += 1
                return list(cached)
            self.misses += 1

        results = tuple(
            simulate_hourly(
                weather,
                demands,
                config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=simulation_years,
            )
        )
        with self._lock:
            self._store[key] = results
        return list(results)

    def summary(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": int(self.hits),
                "misses": int(self.misses),
                "entries": int(self.entries),
            }
