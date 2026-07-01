"""HelioStock - hourly solar thermal + BTES + heat pump model."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "BtesConfig": (".engine", "BtesConfig"),
    "CollectorConfig": (".engine", "CollectorConfig"),
    "HeatPumpConfig": (".engine", "HeatPumpConfig"),
    "MonthlyDemand": (".engine", "MonthlyDemand"),
    "SimulationConfig": (".engine", "SimulationConfig"),
    "HourlyResult": (".hourly_engine", "HourlyResult"),
    "HourlyWeather": (".hourly_engine", "HourlyWeather"),
    "aggregate_hourly_results_monthly": (".hourly_engine", "aggregate_hourly_results_monthly"),
    "simulate_hourly": (".hourly_engine", "simulate_hourly"),
    "BorefieldPreDesign": (".geothermal_design", "BorefieldPreDesign"),
    "predimension_borefield": (".geothermal_design", "predimension_borefield"),
    "borefield_equivalent_savings": (".borefield_savings", "borefield_equivalent_savings"),
    "BtesInputs": (".inputs", "BtesInputs"),
    "EconomicsInputs": (".inputs", "EconomicsInputs"),
    "HeatPumpInputs": (".inputs", "HeatPumpInputs"),
    "ScenarioInputs": (".inputs", "ScenarioInputs"),
    "SolarInputs": (".inputs", "SolarInputs"),
    "CalculationSelection": (".app_service", "CalculationSelection"),
    "HourlyCalculationRequest": (".app_service", "HourlyCalculationRequest"),
    "HourlyCalculationResult": (".app_service", "HourlyCalculationResult"),
    "ParametricRange": (".app_service", "ParametricRange"),
    "run_hourly_calculation": (".app_service", "run_hourly_calculation"),
    "ScenarioEconomicsConfig": (".scenarios", "ScenarioEconomicsConfig"),
    "ScenarioResult": (".scenarios", "ScenarioResult"),
    "pac_power_parametric_study": (".scenarios", "pac_power_parametric_study"),
    "run_hourly_scenario": (".scenarios", "run_hourly_scenario"),
    "solar_surface_parametric_study": (".scenarios", "solar_surface_parametric_study"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_EXPORTS])
