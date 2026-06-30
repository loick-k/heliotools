from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .engine import MonthlyDemand
from .hourly_engine import HourlyWeather
from .inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, ScenarioInputs, SolarInputs
from .load_profiles import _peak_bt_power_kw
from .scenarios import (
    ScenarioResult,
    pac_power_parametric_study,
    run_hourly_scenario,
    solar_surface_parametric_study,
)
from .simulation_cache import SimulationCache


ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class ParametricRange:
    enabled: bool
    minimum: float
    maximum: float
    step: float


@dataclass(frozen=True)
class CalculationSelection:
    quick_preview: bool = False
    run_multiyear: bool = True
    technical_simulation_years: int = 25
    display_year_mode: str = "finale"
    custom_display_year: int = 25
    run_geo_only: bool = True
    run_reduced_borefield: bool = False
    savings_search_mode: str = "fast"
    recharge_credit: float = 0.6
    reduced_borefield_safety_factor: float = 1.10


@dataclass(frozen=True)
class HourlyCalculationRequest:
    weather: list[HourlyWeather]
    demands: list[MonthlyDemand]
    hourly_demand_override: dict[int, tuple[float, float]] | None
    solar: SolarInputs
    btes: BtesInputs
    heat_pump: HeatPumpInputs
    economics: EconomicsInputs
    pac_power_fraction_pct: float
    use_probe_predesign: bool
    probe_power_ratio_w_m: float
    probe_energy_ratio_kwh_m: float
    probe_unit_depth_m: float
    calculation_selection: CalculationSelection
    pac_parametric: ParametricRange
    solar_parametric: ParametricRange


@dataclass(frozen=True)
class HourlyCalculationResult:
    scenario: ScenarioResult
    parametric_pac_df: pd.DataFrame
    parametric_surface_df: pd.DataFrame
    peak_bt_power_kw: float
    pac_nominal_power_kw: float
    pac_power_fraction_pct: float
    btes_backend: str
    warnings: tuple[str, ...]
    performance_log_df: pd.DataFrame


def _range_points(param_range: ParametricRange, label: str) -> tuple[list[float], list[str]]:
    if not param_range.enabled:
        return [], []
    if param_range.maximum < param_range.minimum:
        return [], [f"{label} non lancee : la valeur max doit etre superieure ou egale a la valeur min."]
    if param_range.step <= 0.0:
        return [], [f"{label} non lancee : le pas doit etre strictement positif."]

    point_count = int(math.floor((param_range.maximum - param_range.minimum) / param_range.step)) + 1
    if point_count > 25:
        return [], [
            f"{label} non lancee : {point_count} points demandes. "
            "Augmente le pas ou reduis la plage pour rester a 25 points maximum."
        ]

    points = [float(param_range.minimum + idx * param_range.step) for idx in range(max(1, point_count))]
    if points and points[-1] < param_range.maximum - 1e-9 and len(points) < 25:
        points.append(float(param_range.maximum))
    return points, []


def run_hourly_calculation(
    request: HourlyCalculationRequest,
    *,
    progress: ProgressCallback | None = None,
) -> HourlyCalculationResult:
    """Run the HelioStock calculation layer independently from Streamlit rendering."""

    started_at = time.perf_counter()
    last_at = started_at
    performance_events: list[dict[str, float | int | str | None]] = []

    def mark(tag: str, message: str, progress_value: int | None = None) -> None:
        nonlocal last_at
        now = time.perf_counter()
        performance_events.append(
            {
                "Etape": tag,
                "Message": message,
                "Progression (%)": float(progress_value) if progress_value is not None else None,
                "Duree depuis etape precedente (s)": now - last_at,
                "Duree cumulee (s)": now - started_at,
            }
        )
        last_at = now

    def progress_with_log(value: int, text: str) -> None:
        mark("progress", text, value)
        if progress is not None:
            progress(value, text)

    mark("start", "Demarrage du calcul HelioStock")
    warnings: list[str] = []
    mark("inputs:start", "Calcul Pmax BT et construction des configurations")
    peak_bt_power_kw = _peak_bt_power_kw(
        request.weather,
        request.demands,
        request.hourly_demand_override,
    )
    heat_pump = HeatPumpInputs(
        air_target_bt_c=request.heat_pump.air_target_bt_c,
        condenser_approach_k=request.heat_pump.condenser_approach_k,
        evaporator_approach_k=request.heat_pump.evaporator_approach_k,
        carnot_efficiency=request.heat_pump.carnot_efficiency,
        cop_min=request.heat_pump.cop_min,
        cop_max=request.heat_pump.cop_max,
        pac_power_fraction_pct=request.pac_power_fraction_pct,
        peak_bt_power_kw=peak_bt_power_kw,
        aux_pac_ratio=request.heat_pump.aux_pac_ratio,
        standby_power_kw=request.heat_pump.standby_power_kw,
    )
    scenario_inputs = ScenarioInputs(
        solar=request.solar,
        btes=request.btes,
        heat_pump=heat_pump,
        economics=request.economics,
    )
    warnings.extend(scenario_inputs.validate())

    config = scenario_inputs.to_simulation_config()
    economics = scenario_inputs.to_economics_config()
    mark("inputs:end", "Configurations physique et economique pretes")
    simulation_cache = SimulationCache()
    quick_preview = bool(request.calculation_selection.quick_preview)
    if quick_preview:
        warnings.append(
            "Mode previsualisation rapide actif : simulation 1 an, economie de sondes et etudes parametriques desactivees."
        )
    mark("scenario:start", "Scenario principal : annuel, multiannuel, economie")
    scenario = run_hourly_scenario(
        weather=request.weather,
        demands=request.demands,
        config=config,
        economics=economics,
        hourly_demand_override=request.hourly_demand_override,
        run_multiyear=False if quick_preview else request.calculation_selection.run_multiyear,
        technical_simulation_years=1 if quick_preview else request.calculation_selection.technical_simulation_years,
        display_year_mode="finale" if quick_preview else request.calculation_selection.display_year_mode,
        custom_display_year=1 if quick_preview else request.calculation_selection.custom_display_year,
        run_geo_only=request.calculation_selection.run_geo_only,
        run_reduced_borefield=False if quick_preview else request.calculation_selection.run_reduced_borefield,
        savings_search_mode="none" if quick_preview else request.calculation_selection.savings_search_mode,
        simulation_cache=simulation_cache,
        progress=progress_with_log,
    )
    mark("scenario:end", "Scenario principal termine")

    parametric_pac_df = pd.DataFrame()
    mark("param_pac:prepare", "Preparation de l'etude parametrique PAC")
    pac_fractions_pct, pac_warnings = (
        ([], []) if quick_preview else _range_points(request.pac_parametric, "Etude PAC")
    )
    warnings.extend(pac_warnings)
    if pac_fractions_pct:
        mark("param_pac:start", f"Etude parametrique PAC : {len(pac_fractions_pct)} points")
        parametric_pac_df = pac_power_parametric_study(
            pac_power_fractions_pct=pac_fractions_pct,
            weather=request.weather,
            demands=request.demands,
            config=config,
            hourly_demand_override=request.hourly_demand_override,
            peak_bt_power_kw=peak_bt_power_kw,
            use_probe_predesign=request.use_probe_predesign,
            probe_power_ratio_w_m=request.probe_power_ratio_w_m,
            probe_energy_ratio_kwh_m=request.probe_energy_ratio_kwh_m,
            probe_unit_depth_m=request.probe_unit_depth_m,
            full_borefield_length_m=scenario.full_borefield_length_m,
            reference_gas_power_kw=scenario.reference_gas_power_kw,
            reference_heat_mwh=(scenario.total_ht_kwh + scenario.total_bt_kwh) / 1000.0,
            analysis_years=int(request.economics.analysis_years),
            reference_energy_cost_eur_mwh=request.economics.reference_energy_cost_eur_mwh,
            reference_energy_inflation_pct=request.economics.reference_energy_inflation_pct,
            eta_appoint_eco=request.economics.eta_appoint_eco,
            backup_p2_eur_kw_year=request.economics.backup_p2_eur_kw_year,
            auxiliary_electricity_ratio_pct=request.economics.auxiliary_electricity_ratio_pct,
            electricity_cost_eur_mwh=request.economics.electricity_cost_eur_mwh,
            maintenance_cost_eur_m2_year=request.economics.maintenance_cost_eur_m2_year,
            ademe_eur_mwh_year=request.economics.ademe_eur_mwh_year,
            other_public_aid_eur=request.economics.other_public_aid_eur,
            simulation_cache=simulation_cache,
            progress=progress_with_log,
        )
        mark("param_pac:end", "Etude parametrique PAC terminee")
    else:
        mark("param_pac:skip", "Etude parametrique PAC inactive")

    parametric_surface_df = pd.DataFrame()
    mark("param_solar:prepare", "Preparation de l'etude parametrique solaire")
    surfaces_m2, surface_warnings = (
        ([], []) if quick_preview else _range_points(request.solar_parametric, "Etude parametrique solaire")
    )
    warnings.extend(surface_warnings)
    if surfaces_m2:
        mark("param_solar:start", f"Etude parametrique solaire : {len(surfaces_m2)} points")
        parametric_surface_df = solar_surface_parametric_study(
            surfaces_m2=surfaces_m2,
            weather=request.weather,
            demands=request.demands,
            config=config,
            hourly_demand_override=request.hourly_demand_override,
            no_solar_cop=scenario.no_solar_cop,
            no_solar_total_pac_kwh=scenario.no_solar_total_pac_kwh,
            no_solar_bt_coverage=scenario.no_solar_total_pac_kwh
            / max(1e-9, float(scenario.no_solar_hourly_df["demand_bt_kwh"].sum())),
            no_solar_source_limited_hours=(
                float(scenario.no_solar_hourly_df["Limite_temperature_source"].sum())
                if "Limite_temperature_source" in scenario.no_solar_hourly_df
                else 0.0
            ),
            pac_nominal_power_kw=scenario_inputs.pac_nominal_power_kw,
            full_borefield_length_m=scenario.full_borefield_length_m,
            reference_gas_power_kw=scenario.reference_gas_power_kw,
            reference_heat_mwh=(scenario.total_ht_kwh + scenario.total_bt_kwh) / 1000.0,
            analysis_years=int(request.economics.analysis_years),
            reference_energy_cost_eur_mwh=request.economics.reference_energy_cost_eur_mwh,
            reference_energy_inflation_pct=request.economics.reference_energy_inflation_pct,
            eta_appoint_eco=request.economics.eta_appoint_eco,
            backup_p2_eur_kw_year=request.economics.backup_p2_eur_kw_year,
            auxiliary_electricity_ratio_pct=request.economics.auxiliary_electricity_ratio_pct,
            electricity_cost_eur_mwh=request.economics.electricity_cost_eur_mwh,
            maintenance_cost_eur_m2_year=request.economics.maintenance_cost_eur_m2_year,
            ademe_eur_mwh_year=request.economics.ademe_eur_mwh_year,
            other_public_aid_eur=request.economics.other_public_aid_eur,
            savings_search_mode=request.calculation_selection.savings_search_mode,
            recharge_credit=request.calculation_selection.recharge_credit,
            reduced_borefield_safety_factor=request.calculation_selection.reduced_borefield_safety_factor,
            simulation_cache=simulation_cache,
            progress=progress_with_log,
        )
        mark("param_solar:end", "Etude parametrique solaire terminee")
    else:
        mark("param_solar:skip", "Etude parametrique solaire inactive")

    cache_summary = simulation_cache.summary()
    mark(
        "cache:summary",
        "Cache simulations : "
        f"{cache_summary['hits']} reutilisations, "
        f"{cache_summary['misses']} calculs, "
        f"{cache_summary['entries']} entrees",
    )
    mark("end", "Calcul HelioStock termine")

    performance_log_df = pd.DataFrame(performance_events)
    if not performance_log_df.empty:
        performance_log_df["Etape"] = performance_log_df["Etape"].astype("string")
        performance_log_df["Message"] = performance_log_df["Message"].astype("string")
        performance_log_df["Progression (%)"] = pd.to_numeric(
            performance_log_df["Progression (%)"],
            errors="coerce",
        ).astype("Float64")
        for column in ["Duree depuis etape precedente (s)", "Duree cumulee (s)"]:
            performance_log_df[column] = pd.to_numeric(performance_log_df[column], errors="coerce").astype(float)

    return HourlyCalculationResult(
        scenario=scenario,
        parametric_pac_df=parametric_pac_df,
        parametric_surface_df=parametric_surface_df,
        peak_bt_power_kw=peak_bt_power_kw,
        pac_nominal_power_kw=scenario_inputs.pac_nominal_power_kw,
        pac_power_fraction_pct=float(request.pac_power_fraction_pct),
        btes_backend=config.btes.backend,
        warnings=tuple(warnings),
        performance_log_df=performance_log_df,
    )
