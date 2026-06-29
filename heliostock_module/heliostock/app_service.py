from __future__ import annotations

import math
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


ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class ParametricRange:
    enabled: bool
    minimum: float
    maximum: float
    step: float


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

    warnings: list[str] = []
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
    scenario = run_hourly_scenario(
        weather=request.weather,
        demands=request.demands,
        config=config,
        economics=economics,
        hourly_demand_override=request.hourly_demand_override,
        progress=progress,
    )

    parametric_pac_df = pd.DataFrame()
    pac_fractions_pct, pac_warnings = _range_points(request.pac_parametric, "Etude PAC")
    warnings.extend(pac_warnings)
    if pac_fractions_pct:
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
            progress=progress,
        )

    parametric_surface_df = pd.DataFrame()
    surfaces_m2, surface_warnings = _range_points(request.solar_parametric, "Etude parametrique solaire")
    warnings.extend(surface_warnings)
    if surfaces_m2:
        parametric_surface_df = solar_surface_parametric_study(
            surfaces_m2=surfaces_m2,
            weather=request.weather,
            demands=request.demands,
            config=config,
            hourly_demand_override=request.hourly_demand_override,
            no_solar_cop=scenario.no_solar_cop,
            no_solar_total_pac_kwh=scenario.no_solar_total_pac_kwh,
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
            progress=progress,
        )

    return HourlyCalculationResult(
        scenario=scenario,
        parametric_pac_df=parametric_pac_df,
        parametric_surface_df=parametric_surface_df,
        peak_bt_power_kw=peak_bt_power_kw,
        pac_nominal_power_kw=scenario_inputs.pac_nominal_power_kw,
        pac_power_fraction_pct=float(request.pac_power_fraction_pct),
        btes_backend=config.btes.backend,
        warnings=tuple(warnings),
    )
