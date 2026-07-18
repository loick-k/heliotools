from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .engine import SimulationConfig


@dataclass(frozen=True)
class ScenarioEconomicsConfig:
    """Economic assumptions shared by scenario and parametric calculations."""

    reference_energy_cost_eur_mwh: float
    reference_energy_inflation_pct: float
    eta_appoint_eco: float
    analysis_years: int
    auxiliary_electricity_ratio_pct: float
    electricity_cost_eur_mwh: float
    maintenance_cost_eur_m2_year: float
    ademe_eur_mwh_year: float
    other_public_aid_eur: float
    backup_p2_eur_kw_year: float


@dataclass(frozen=True)
class ScenarioResult:
    """Complete output consumed by the Streamlit result views.

    Hourly DataFrames are kept only for the main displayed scenario. Heavy
    parametric and savings loops should pass compact metrics instead.
    """

    config: SimulationConfig
    hourly_df: pd.DataFrame
    no_solar_hourly_df: pd.DataFrame
    multiyear_btes_df: pd.DataFrame
    no_solar_multiyear_btes_df: pd.DataFrame
    reduced_multiyear_btes_df: pd.DataFrame
    annual_df: pd.DataFrame
    hourly_by_month_df: pd.DataFrame
    savings: dict[str, float | bool]
    solar_economics: dict[str, float | pd.DataFrame]
    heat_costs: dict[str, float | pd.DataFrame]
    economic_comparison_df: pd.DataFrame
    economic_comparison_chart_df: pd.DataFrame
    economic_trajectory_df: pd.DataFrame
    solar_parametric_reference: dict[str, object]
    recharge_value: dict[str, float | bool | str]
    solar_allocation: dict[str, float]
    total_ht_kwh: float
    total_bt_kwh: float
    total_preheat_ht_kwh: float
    total_charge_buffer_kwh: float
    total_to_btes_kwh: float
    total_solar_valued_kwh: float
    solar_productivity_valued_kwh_m2_year: float
    solar_ht_from_buffer_economic_mwh: float
    total_backup_ht_kwh: float
    total_backup_bt_kwh: float
    annual_ht_solar_coverage: float
    total_pac_kwh: float
    total_compressor_kwh: float
    total_pac_auxiliaries_kwh: float
    total_standby_kwh: float
    total_elec_kwh: float
    total_system_elec_kwh: float
    mean_cop: float
    spf_pac_total: float
    spf_system: float
    global_ren_rate: float
    no_solar_total_pac_kwh: float
    no_solar_total_compressor_kwh: float
    no_solar_total_elec_kwh: float
    no_solar_cop: float
    backup_power_kw: float
    full_borefield_length_m: float
    economic_borefield_length_m: float
    reference_gas_power_kw: float
    simulation_year_displayed: int
    simulation_years_total: int
    economic_years_used: int
    gmi_check_enabled: bool
