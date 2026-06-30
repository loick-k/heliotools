from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from threading import Lock
from typing import Any, Callable

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

    def __init__(self, event_callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._store: dict[tuple[Any, ...], tuple[HourlyResult, ...]] = {}
        self.hits = 0
        self.misses = 0
        self._lock = Lock()
        self._event_callback = event_callback

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
        hours_simulated = int(len(weather) * max(1, int(simulation_years)))
        common_metrics = {
            "Mode simulation": str(mode),
            "Annees simulees": int(simulation_years),
            "Pas meteo": int(len(weather)),
            "Heures simulees": hours_simulated,
            "Surface solaire (m2)": float(config.collector.area_m2),
            "Sondes": int(config.btes.boreholes),
            "Lineaire sondes (ml)": float(config.btes.boreholes) * float(config.btes.depth_m),
        }
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
                self.record_event(
                    "simulate:cache_hit",
                    f"Simulation reutilisee depuis le cache ({mode})",
                    {
                        **common_metrics,
                        "Cache": "hit",
                        "Cache hits": int(self.hits),
                        "Cache misses": int(self.misses),
                        "Simulations lancees": 0,
                        "Duree pygfunction (s)": 0.0,
                    },
                )
                return list(cached)
            self.misses += 1

        started_at = time.perf_counter()
        results = tuple(
            simulate_hourly(
                weather,
                demands,
                config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=simulation_years,
            )
        )
        elapsed = time.perf_counter() - started_at
        with self._lock:
            self._store[key] = results
            hits = int(self.hits)
            misses = int(self.misses)
        self.record_event(
            "simulate:pygfunction",
            f"Simulation pygfunction calculee ({mode})",
            {
                **common_metrics,
                "Cache": "miss",
                "Cache hits": hits,
                "Cache misses": misses,
                "Simulations lancees": 1,
                "Duree pygfunction (s)": elapsed,
            },
        )
        return list(results)

    def record_event(self, tag: str, message: str, metrics: dict[str, Any] | None = None) -> None:
        if self._event_callback is not None:
            self._event_callback(
                {
                    "Etape": tag,
                    "Message": message,
                    **(metrics or {}),
                }
            )

    def summary(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": int(self.hits),
                "misses": int(self.misses),
                "entries": int(self.entries),
            }
