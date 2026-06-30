from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

import pandas as pd

from .economics import (
    annuity_average_factor,
    compute_heat_costs,
    compute_solar_thermal_economics,
    solar_energy_allocation,
    solar_recharge_value,
)
from .borefield_savings import borefield_equivalent_savings
from .engine import MonthlyDemand, SimulationConfig, cop_from_source_temperature
from .geothermal_design import predimension_borefield
from .hourly_engine import HourlyWeather, simulate_hourly
from .load_profiles import _estimate_capped_bt_heat_mwh
from .postprocess import (
    _annual_hourly_summary,
    _hourly_by_month_summary,
    _hourly_results_to_dataframe,
    _multiyear_btes_summary,
)


ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class ScenarioEconomicsConfig:
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
    config: SimulationConfig
    hourly_df: pd.DataFrame
    no_solar_hourly_df: pd.DataFrame
    multiyear_btes_df: pd.DataFrame
    no_solar_multiyear_btes_df: pd.DataFrame
    annual_df: pd.DataFrame
    hourly_by_month_df: pd.DataFrame
    savings: dict[str, float | bool]
    solar_economics: dict[str, float | pd.DataFrame]
    heat_costs: dict[str, float | pd.DataFrame]
    economic_comparison_df: pd.DataFrame
    economic_comparison_chart_df: pd.DataFrame
    economic_trajectory_df: pd.DataFrame
    recharge_value: dict[str, float | bool | str]
    solar_allocation: dict[str, float]
    total_ht_kwh: float
    total_bt_kwh: float
    total_preheat_ht_kwh: float
    total_charge_buffer_kwh: float
    total_to_btes_kwh: float
    total_solar_valued_kwh: float
    solar_productivity_valued_kwh_m2_year: float
    solar_direct_ht_economic_mwh: float
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


def _notify(progress: ProgressCallback | None, value: int, text: str) -> None:
    if progress is not None:
        progress(value, text)


def solar_surface_parametric_study(
    *,
    surfaces_m2: list[float],
    weather,
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    no_solar_cop: float,
    no_solar_total_pac_kwh: float,
    pac_nominal_power_kw: float,
    full_borefield_length_m: float,
    reference_gas_power_kw: float,
    reference_heat_mwh: float,
    analysis_years: int,
    reference_energy_cost_eur_mwh: float,
    reference_energy_inflation_pct: float,
    eta_appoint_eco: float,
    backup_p2_eur_kw_year: float,
    auxiliary_electricity_ratio_pct: float,
    electricity_cost_eur_mwh: float,
    maintenance_cost_eur_m2_year: float,
    ademe_eur_mwh_year: float,
    other_public_aid_eur: float,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    rows = []
    total_points = max(1, len(surfaces_m2))
    simulation_years = max(1, int(analysis_years))
    economics_config = ScenarioEconomicsConfig(
        reference_energy_cost_eur_mwh=reference_energy_cost_eur_mwh,
        reference_energy_inflation_pct=reference_energy_inflation_pct,
        eta_appoint_eco=eta_appoint_eco,
        analysis_years=int(analysis_years),
        auxiliary_electricity_ratio_pct=auxiliary_electricity_ratio_pct,
        electricity_cost_eur_mwh=electricity_cost_eur_mwh,
        maintenance_cost_eur_m2_year=maintenance_cost_eur_m2_year,
        ademe_eur_mwh_year=ademe_eur_mwh_year,
        other_public_aid_eur=other_public_aid_eur,
        backup_p2_eur_kw_year=backup_p2_eur_kw_year,
    )

    for index, surface_m2 in enumerate(surfaces_m2, start=1):
        _notify(
            progress,
            min(99, 85 + int(14 * index / total_points)),
            f"Etude parametrique solaire : {surface_m2:.0f} m2 ({index}/{total_points})...",
        )

        variant_config = replace(config, collector=replace(config.collector, area_m2=float(surface_m2)))
        variant_multiyear_df = _hourly_results_to_dataframe(
            simulate_hourly(
                weather,
                demands,
                variant_config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=simulation_years,
            )
        )
        variant_df = variant_multiyear_df[variant_multiyear_df["simulation_year"] == simulation_years].copy()
        economic_metrics_variant = _hourly_metrics(variant_multiyear_df, annualization_years=simulation_years)

        total_ht_variant = float(variant_df["demand_ht_kwh"].sum())
        total_bt_variant = float(variant_df["demand_bt_kwh"].sum())
        total_preheat_ht_variant = float(variant_df["solar_ht_direct_kwh"].sum())
        total_to_btes_variant = float(variant_df["solar_to_btes_kwh"].sum())
        total_backup_ht_variant = float(variant_df["unmet_ht_kwh"].sum())
        total_backup_bt_variant = float(variant_df["unmet_bt_kwh"].sum())
        total_pac_variant = float(variant_df["heat_bt_from_pac_kwh"].sum())
        total_compressor_variant = float(variant_df["electricity_compressor_kwh"].sum())
        total_elec_variant = float(variant_df["electricity_pac_total_kwh"].sum())
        backup_power_kw_variant = float(
            (variant_df["unmet_ht_kwh"].clip(lower=0.0) + variant_df["unmet_bt_kwh"].clip(lower=0.0)).max()
        )
        global_ren_rate_variant = max(
            0.0,
            min(
                1.0,
                1.0
                - (total_backup_ht_variant + total_backup_bt_variant + total_elec_variant)
                / max(1e-9, total_ht_variant + total_bt_variant),
            ),
        )
        annual_ht_solar_coverage_variant = total_preheat_ht_variant / max(1e-9, total_ht_variant)

        savings_variant = borefield_equivalent_savings(
            weather=weather,
            demands=demands,
            config=variant_config,
            reference_cop=no_solar_cop,
            reference_bt_pac_kwh=no_solar_total_pac_kwh,
            hourly_demand_override=hourly_demand_override,
            simulation_years=simulation_years,
            iterations=12,
        )
        economic_borefield_length_m_variant = (
            float(savings_variant["equivalent_length_m"])
            if bool(savings_variant["found"])
            else full_borefield_length_m
        )

        solar_direct_ht_mwh_variant = economic_metrics_variant["solar_ht_mwh"]
        solar_total_mwh_variant = economic_metrics_variant["solar_ht_mwh"] + economic_metrics_variant["solar_btes_mwh"]
        solar_economics_variant = compute_solar_thermal_economics(
            surface_m2=float(surface_m2),
            annual_solar_valued_mwh=solar_direct_ht_mwh_variant,
            reference_energy_cost_eur_mwh=reference_energy_cost_eur_mwh,
            reference_energy_inflation_rate=reference_energy_inflation_pct / 100.0,
            analysis_years=int(analysis_years),
            eta_appoint=eta_appoint_eco,
            auxiliary_electricity_ratio=auxiliary_electricity_ratio_pct / 100.0,
            electricity_cost_eur_mwh=electricity_cost_eur_mwh,
            maintenance_cost_eur_m2_year=maintenance_cost_eur_m2_year,
            ademe_eur_mwh_year=ademe_eur_mwh_year,
            other_public_aid_eur=other_public_aid_eur,
            annual_solar_total_mwh=solar_total_mwh_variant,
        )
        heat_costs_variant = compute_heat_costs(
            solar_economics=solar_economics_variant,
            annual_solar_mwh=solar_direct_ht_mwh_variant,
            annual_pac_heat_mwh=economic_metrics_variant["pac_heat_mwh"],
            annual_pac_electricity_mwh=economic_metrics_variant["pac_electricity_mwh"],
            pac_power_kw=pac_nominal_power_kw,
            borefield_length_m=economic_borefield_length_m_variant,
            full_borefield_length_m=full_borefield_length_m,
            annual_backup_heat_mwh=economic_metrics_variant["backup_total_mwh"],
            backup_power_kw=economic_metrics_variant["backup_power_kw"],
            reference_heat_mwh=reference_heat_mwh,
            reference_power_kw=reference_gas_power_kw,
            analysis_years=int(analysis_years),
            gas_reference_p1_eur_mwh_pci=reference_energy_cost_eur_mwh,
            gas_reference_efficiency=eta_appoint_eco,
            gas_reference_inflation_rate=reference_energy_inflation_pct / 100.0,
            geothermal_p1_eur_mwh=electricity_cost_eur_mwh,
            backup_p2_eur_kw_year=backup_p2_eur_kw_year,
        )
        capex_variant = _capex_net_total(heat_costs_variant, ["Solaire thermique", "Geothermie PAC", "Appoint gaz"])
        multiyear_cost_variant = _multiyear_heat_cost(
            trajectory_df=_annual_metrics_trajectory(variant_multiyear_df, analysis_years=simulation_years),
            heat_costs=heat_costs_variant,
            economics=economics_config,
            capex_net_eur=capex_variant,
        )

        rows.append(
            {
                "Surface solaire (m²)": float(surface_m2),
                "Coût chaleur Mix ENR (EUR/MWh)": float(multiyear_cost_variant["multiyear_heat_cost_eur_mwh"]),
                "Taux EnR global (%)": global_ren_rate_variant * 100.0,
                "Couverture solaire HT (%)": annual_ht_solar_coverage_variant * 100.0,
                "Préchauffage HT solaire (MWh/an)": total_preheat_ht_variant / 1000.0,
                "Injection BTES (MWh/an)": total_to_btes_variant / 1000.0,
                "COP PAC moyen": total_pac_variant / total_compressor_variant if total_compressor_variant > 0.0 else 0.0,
                "Linéaire sondes retenu éco (ml)": economic_borefield_length_m_variant,
                "CAPEX solaire net (kEUR)": float(solar_economics_variant["net_capex_eur"]) / 1000.0,
            }
        )

    return pd.DataFrame(rows)


def pac_power_parametric_study(
    *,
    pac_power_fractions_pct: list[float],
    weather,
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    peak_bt_power_kw: float,
    use_probe_predesign: bool,
    probe_power_ratio_w_m: float,
    probe_energy_ratio_kwh_m: float,
    probe_unit_depth_m: float,
    full_borefield_length_m: float,
    reference_gas_power_kw: float,
    reference_heat_mwh: float,
    analysis_years: int,
    reference_energy_cost_eur_mwh: float,
    reference_energy_inflation_pct: float,
    eta_appoint_eco: float,
    backup_p2_eur_kw_year: float,
    auxiliary_electricity_ratio_pct: float,
    electricity_cost_eur_mwh: float,
    maintenance_cost_eur_m2_year: float,
    ademe_eur_mwh_year: float,
    other_public_aid_eur: float,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    rows = []
    total_points = max(1, len(pac_power_fractions_pct))
    simulation_years = max(1, int(analysis_years))
    economics_config = ScenarioEconomicsConfig(
        reference_energy_cost_eur_mwh=reference_energy_cost_eur_mwh,
        reference_energy_inflation_pct=reference_energy_inflation_pct,
        eta_appoint_eco=eta_appoint_eco,
        analysis_years=int(analysis_years),
        auxiliary_electricity_ratio_pct=auxiliary_electricity_ratio_pct,
        electricity_cost_eur_mwh=electricity_cost_eur_mwh,
        maintenance_cost_eur_m2_year=maintenance_cost_eur_m2_year,
        ademe_eur_mwh_year=ademe_eur_mwh_year,
        other_public_aid_eur=other_public_aid_eur,
        backup_p2_eur_kw_year=backup_p2_eur_kw_year,
    )

    for index, fraction_pct in enumerate(pac_power_fractions_pct, start=1):
        _notify(
            progress,
            min(99, 85 + int(14 * index / total_points)),
            f"Etude parametrique PAC : {fraction_pct:.0f} % Pmax ({index}/{total_points})...",
        )

        pac_kw = max(0.0, peak_bt_power_kw) * max(0.0, float(fraction_pct)) / 100.0
        hp_variant = replace(config.heat_pump, max_thermal_power_kw=pac_kw)
        collector_no_solar = replace(config.collector, area_m2=0.0)
        btes_variant = config.btes
        predesign_variant = None
        if use_probe_predesign:
            design_cop = cop_from_source_temperature(config.btes.t_initial_c, hp_variant)
            heat_pac_mwh_year = _estimate_capped_bt_heat_mwh(
                weather,
                demands,
                hourly_demand_override,
                pac_kw,
            )
            predesign_variant = predimension_borefield(
                pac_power_kw=pac_kw,
                cop=design_cop,
                heat_pac_mwh_year=heat_pac_mwh_year,
                power_ratio_w_per_m=probe_power_ratio_w_m,
                energy_ratio_kwh_per_m_year=probe_energy_ratio_kwh_m,
                unit_depth_m=probe_unit_depth_m,
            )
            btes_variant = replace(
                btes_variant,
                boreholes=predesign_variant.boreholes,
                depth_m=predesign_variant.unit_depth_m,
            )

        variant_config = replace(
            config,
            collector=collector_no_solar,
            heat_pump=hp_variant,
            btes=btes_variant,
        )
        variant_multiyear_df = _hourly_results_to_dataframe(
            simulate_hourly(
                weather,
                demands,
                variant_config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=simulation_years,
            )
        )
        variant_df = variant_multiyear_df[variant_multiyear_df["simulation_year"] == simulation_years].copy()
        economic_metrics_variant = _hourly_metrics(variant_multiyear_df, annualization_years=simulation_years)

        total_ht_variant = float(variant_df["demand_ht_kwh"].sum())
        total_bt_variant = float(variant_df["demand_bt_kwh"].sum())
        total_backup_ht_variant = float(variant_df["unmet_ht_kwh"].sum())
        total_backup_bt_variant = float(variant_df["unmet_bt_kwh"].sum())
        total_pac_variant = float(variant_df["heat_bt_from_pac_kwh"].sum())
        total_compressor_variant = float(variant_df["electricity_compressor_kwh"].sum())
        total_elec_variant = float(variant_df["electricity_pac_total_kwh"].sum())
        backup_power_kw_variant = float(
            (variant_df["unmet_ht_kwh"].clip(lower=0.0) + variant_df["unmet_bt_kwh"].clip(lower=0.0)).max()
        )
        global_ren_rate_variant = max(
            0.0,
            min(
                1.0,
                1.0
                - (total_backup_ht_variant + total_backup_bt_variant + total_elec_variant)
                / max(1e-9, total_ht_variant + total_bt_variant),
            ),
        )
        pac_bt_coverage = total_pac_variant / max(1e-9, total_bt_variant)

        base_length_variant = float(btes_variant.boreholes) * float(btes_variant.depth_m)
        economic_borefield_length_m_variant = base_length_variant

        solar_economics_variant = compute_solar_thermal_economics(
            surface_m2=0.0,
            annual_solar_valued_mwh=0.0,
            reference_energy_cost_eur_mwh=reference_energy_cost_eur_mwh,
            reference_energy_inflation_rate=reference_energy_inflation_pct / 100.0,
            analysis_years=int(analysis_years),
            eta_appoint=eta_appoint_eco,
            auxiliary_electricity_ratio=auxiliary_electricity_ratio_pct / 100.0,
            electricity_cost_eur_mwh=electricity_cost_eur_mwh,
            maintenance_cost_eur_m2_year=maintenance_cost_eur_m2_year,
            ademe_eur_mwh_year=ademe_eur_mwh_year,
            other_public_aid_eur=other_public_aid_eur,
        )
        heat_costs_variant = compute_heat_costs(
            solar_economics=solar_economics_variant,
            annual_solar_mwh=0.0,
            annual_pac_heat_mwh=economic_metrics_variant["pac_heat_mwh"],
            annual_pac_electricity_mwh=economic_metrics_variant["pac_electricity_mwh"],
            pac_power_kw=pac_kw,
            borefield_length_m=economic_borefield_length_m_variant,
            full_borefield_length_m=base_length_variant,
            annual_backup_heat_mwh=economic_metrics_variant["backup_total_mwh"],
            backup_power_kw=economic_metrics_variant["backup_power_kw"],
            reference_heat_mwh=reference_heat_mwh,
            reference_power_kw=reference_gas_power_kw,
            analysis_years=int(analysis_years),
            gas_reference_p1_eur_mwh_pci=reference_energy_cost_eur_mwh,
            gas_reference_efficiency=eta_appoint_eco,
            gas_reference_inflation_rate=reference_energy_inflation_pct / 100.0,
            geothermal_p1_eur_mwh=electricity_cost_eur_mwh,
            backup_p2_eur_kw_year=backup_p2_eur_kw_year,
        )
        capex_variant = _capex_net_total(heat_costs_variant, ["Geothermie PAC", "Appoint gaz"])
        multiyear_cost_variant = _multiyear_heat_cost(
            trajectory_df=_annual_metrics_trajectory(variant_multiyear_df, analysis_years=simulation_years),
            heat_costs=heat_costs_variant,
            economics=economics_config,
            capex_net_eur=capex_variant,
        )

        rows.append(
            {
                "P PAC (% Pmax BT)": float(fraction_pct),
                "P PAC (kW)": pac_kw,
                "Coût chaleur Mix ENR (EUR/MWh)": float(multiyear_cost_variant["multiyear_heat_cost_eur_mwh"]),
                "Taux EnR global (%)": global_ren_rate_variant * 100.0,
                "Couverture PAC BT (%)": pac_bt_coverage * 100.0,
                "Besoin HT gaz (MWh/an)": total_backup_ht_variant / 1000.0,
                "Complément BT gaz (MWh/an)": total_backup_bt_variant / 1000.0,
                "Appoint total (MWh/an)": (total_backup_ht_variant + total_backup_bt_variant) / 1000.0,
                "COP PAC moyen": total_pac_variant / total_compressor_variant if total_compressor_variant > 0.0 else 0.0,
                "Linéaire sondes retenu éco (ml)": economic_borefield_length_m_variant,
                "Nombre sondes predim": predesign_variant.boreholes if predesign_variant else btes_variant.boreholes,
            }
        )

    return pd.DataFrame(rows)


def _hourly_metrics(df: pd.DataFrame, *, annualization_years: int = 1) -> dict[str, float]:
    years = max(1, int(annualization_years))
    total_ht = float(df["demand_ht_kwh"].sum())
    total_bt = float(df["demand_bt_kwh"].sum())
    total_backup_ht = float(df["unmet_ht_kwh"].sum())
    total_backup_bt = float(df["unmet_bt_kwh"].sum())
    total_pac = float(df["heat_bt_from_pac_kwh"].sum())
    total_compressor = float(df["electricity_compressor_kwh"].sum())
    total_elec = float(df["electricity_pac_total_kwh"].sum())
    total_system_elec = float(df["electricity_system_total_kwh"].sum())
    total_solar_ht = float(df["solar_ht_direct_kwh"].sum())
    total_solar_btes = float(df["solar_to_btes_kwh"].sum())
    backup_power_kw = float((df["unmet_ht_kwh"].clip(lower=0.0) + df["unmet_bt_kwh"].clip(lower=0.0)).max())
    total_need = total_ht + total_bt
    non_ren_input = total_backup_ht + total_backup_bt + total_system_elec
    annual = 1.0 / years
    return {
        "total_ht_kwh": total_ht * annual,
        "total_bt_kwh": total_bt * annual,
        "total_need_mwh": total_need / 1000.0 * annual,
        "backup_ht_mwh": total_backup_ht / 1000.0 * annual,
        "backup_bt_mwh": total_backup_bt / 1000.0 * annual,
        "backup_total_mwh": (total_backup_ht + total_backup_bt) / 1000.0 * annual,
        "pac_heat_mwh": total_pac / 1000.0 * annual,
        "pac_compressor_mwh": total_compressor / 1000.0 * annual,
        "pac_electricity_mwh": total_elec / 1000.0 * annual,
        "system_electricity_mwh": total_system_elec / 1000.0 * annual,
        "solar_ht_mwh": total_solar_ht / 1000.0 * annual,
        "solar_btes_mwh": total_solar_btes / 1000.0 * annual,
        "solar_ht_coverage": total_solar_ht / max(1e-9, total_ht),
        "pac_bt_coverage": total_pac / max(1e-9, total_bt),
        "mean_cop": total_pac / total_compressor if total_compressor > 0.0 else 0.0,
        "spf_pac_total": total_pac / total_elec if total_elec > 0.0 else 0.0,
        "spf_system": (total_pac + total_solar_ht) / total_system_elec if total_system_elec > 0.0 else 0.0,
        "global_ren_rate": max(0.0, min(1.0, 1.0 - non_ren_input / max(1e-9, total_need))),
        "backup_power_kw": backup_power_kw,
        "reference_gas_power_kw": float((df["demand_ht_kwh"].clip(lower=0.0) + df["demand_bt_kwh"].clip(lower=0.0)).max()),
        "t_source_pac_min_c": float(df["T_source_PAC_C"].min()) if "T_source_PAC_C" in df else 0.0,
        "t_source_pac_mean_c": float(df["T_source_PAC_C"].mean()) if "T_source_PAC_C" in df else 0.0,
        "q_extraction_max_w_m": float(df["q_extraction_W_m"].max()) if "q_extraction_W_m" in df else 0.0,
        "q_injection_max_w_m": float(df["q_injection_W_m"].max()) if "q_injection_W_m" in df else 0.0,
    }


def _annual_metrics_trajectory(df: pd.DataFrame, *, analysis_years: int) -> pd.DataFrame:
    """Build one technical/economic row per analysis year.

    If the economic horizon is longer than the simulated period, the final
    simulated year is repeated as a stabilized year.
    """

    years = max(1, int(analysis_years))
    rows: list[dict[str, float | int]] = []
    grouped = {int(year): group for year, group in df.groupby("simulation_year", sort=True)}
    last_group = grouped[max(grouped)] if grouped else df
    for year in range(1, years + 1):
        group = grouped.get(year, last_group)
        heat_pac = float(group["heat_bt_from_pac_kwh"].sum())
        elec_comp = float(group["electricity_compressor_kwh"].sum())
        total_ht = float(group["demand_ht_kwh"].sum())
        total_bt = float(group["demand_bt_kwh"].sum())
        backup_ht = float(group["unmet_ht_kwh"].sum())
        backup_bt = float(group["unmet_bt_kwh"].sum())
        elec_total = float(group["electricity_pac_total_kwh"].sum())
        solar_ht = float(group["solar_ht_direct_kwh"].sum())
        non_ren = backup_ht + backup_bt + elec_total
        useful = total_ht + total_bt
        rows.append(
            {
                "Annee": year,
                "E utile HT (MWh)": total_ht / 1000.0,
                "E utile BT (MWh)": total_bt / 1000.0,
                "E utile totale (MWh)": useful / 1000.0,
                "Solaire HT (MWh)": solar_ht / 1000.0,
                "Injection solaire BTES (MWh)": float(group["solar_to_btes_kwh"].sum()) / 1000.0,
                "Chaleur PAC BT (MWh)": heat_pac / 1000.0,
                "Appoint gaz HT (MWh)": backup_ht / 1000.0,
                "Appoint gaz BT (MWh)": backup_bt / 1000.0,
                "Appoint gaz total (MWh)": (backup_ht + backup_bt) / 1000.0,
                "Electricite PAC (MWh)": elec_total / 1000.0,
                "COP moyen": heat_pac / elec_comp if elec_comp > 0.0 else 0.0,
                "T_source_PAC_min (C)": float(group["T_source_PAC_C"].min()) if "T_source_PAC_C" in group else 0.0,
                "T_source_PAC_moy (C)": float(group["T_source_PAC_C"].mean()) if "T_source_PAC_C" in group else 0.0,
                "q_extraction_W_m_max": float(group["q_extraction_W_m"].max()) if "q_extraction_W_m" in group else 0.0,
                "q_injection_W_m_max": float(group["q_injection_W_m"].max()) if "q_injection_W_m" in group else 0.0,
                "Taux EnR (%)": max(0.0, min(1.0, 1.0 - non_ren / max(1e-9, useful))) * 100.0,
            }
        )
    return pd.DataFrame(rows)


def _reference_gas_trajectory_from(trajectory_df: pd.DataFrame) -> pd.DataFrame:
    reference_df = trajectory_df.copy()
    reference_df["Solaire HT (MWh)"] = 0.0
    reference_df["Injection solaire BTES (MWh)"] = 0.0
    reference_df["Chaleur PAC BT (MWh)"] = 0.0
    reference_df["Appoint gaz HT (MWh)"] = reference_df["E utile HT (MWh)"]
    reference_df["Appoint gaz BT (MWh)"] = reference_df["E utile BT (MWh)"]
    reference_df["Appoint gaz total (MWh)"] = reference_df["E utile totale (MWh)"]
    reference_df["Electricite PAC (MWh)"] = 0.0
    reference_df["COP moyen"] = 0.0
    reference_df["T_source_PAC_min (C)"] = 0.0
    reference_df["T_source_PAC_moy (C)"] = 0.0
    reference_df["q_extraction_W_m_max"] = 0.0
    reference_df["q_injection_W_m_max"] = 0.0
    reference_df["Taux EnR (%)"] = 0.0
    return reference_df


def _multiyear_heat_cost(
    *,
    trajectory_df: pd.DataFrame,
    heat_costs: dict[str, float | pd.DataFrame],
    economics: ScenarioEconomicsConfig,
    capex_net_eur: float,
    reference: bool = False,
) -> dict[str, float]:
    gas_inflation = max(0.0, float(economics.reference_energy_inflation_pct)) / 100.0
    gas_useful_year_1 = max(0.0, economics.reference_energy_cost_eur_mwh) / max(1e-9, economics.eta_appoint_eco)
    geo_p1_eur_mwh = max(0.0, float(economics.electricity_cost_eur_mwh))
    solar_p1_eur_mwh = _unit_cost(heat_costs, "Solaire thermique", "P1")
    p2_annual = 0.0
    capex_df = heat_costs.get("capex_summary", pd.DataFrame())
    p_table = heat_costs.get("p1_p2_p4", pd.DataFrame())
    if isinstance(p_table, pd.DataFrame) and not p_table.empty:
        if reference:
            delivered_ref = float(trajectory_df["E utile totale (MWh)"].mean())
            p2_annual = float(heat_costs["reference_p2_eur_mwh"]) * delivered_ref
        else:
            solar_p2_total = float(heat_costs.get("solar_p2_total_annual_eur", 0.0))
            if solar_p2_total > 0.0:
                p2_annual = (
                    solar_p2_total
                    + float(heat_costs.get("geo_p2_base_annual_eur", 0.0))
                    + _unit_cost(heat_costs, "Appoint gaz", "P2") * float(trajectory_df["Appoint gaz total (MWh)"].mean())
                )
            else:
                p2_annual = 0.0
                for generator in ["Solaire thermique", "Geothermie PAC", "Appoint gaz"]:
                    match = p_table[(p_table["Generateur"] == generator) & (p_table["Poste"] == "P2")]
                    if not match.empty:
                        if generator == "Solaire thermique":
                            energy = trajectory_df["Solaire HT (MWh)"].mean()
                        elif generator == "Geothermie PAC":
                            energy = trajectory_df["Chaleur PAC BT (MWh)"].mean()
                        else:
                            energy = trajectory_df["Appoint gaz total (MWh)"].mean()
                        p2_annual += float(match["EUR/MWh"].iloc[0]) * float(energy)
    if isinstance(capex_df, pd.DataFrame) and not capex_df.empty:
        pass

    total_cost = max(0.0, capex_net_eur)
    total_useful = 0.0
    p1_total_nominal = 0.0
    p2_total_nominal = 0.0
    p4_total_nominal = 0.0
    for _, row in trajectory_df.iterrows():
        year = int(row["Annee"])
        gas_price = gas_useful_year_1 * ((1.0 + gas_inflation) ** max(0, year - 1))
        if reference:
            p1 = float(row["E utile totale (MWh)"]) * gas_price
        else:
            p1 = (
                float(row["Appoint gaz total (MWh)"]) * gas_price
                + float(row["Electricite PAC (MWh)"]) * geo_p1_eur_mwh
                + float(row["Solaire HT (MWh)"]) * solar_p1_eur_mwh
            )
        p2 = p2_annual
        p4 = max(0.0, capex_net_eur) / max(1, int(economics.analysis_years))
        total_cost += p1 + p2
        total_useful += float(row["E utile totale (MWh)"])
        p1_total_nominal += p1
        p2_total_nominal += p2
        p4_total_nominal += p4
    return {
        "multiyear_heat_cost_eur_mwh": total_cost / max(1e-9, total_useful),
        "p1_annual_eur": p1_total_nominal / max(1, len(trajectory_df)),
        "p2_annual_eur": p2_total_nominal / max(1, len(trajectory_df)),
        "p4_annual_eur": p4_total_nominal / max(1, len(trajectory_df)),
    }


def _zero_solar_economics(economics: ScenarioEconomicsConfig) -> dict[str, float | pd.DataFrame]:
    return compute_solar_thermal_economics(
        surface_m2=0.0,
        annual_solar_valued_mwh=0.0,
        reference_energy_cost_eur_mwh=economics.reference_energy_cost_eur_mwh,
        reference_energy_inflation_rate=economics.reference_energy_inflation_pct / 100.0,
        analysis_years=int(economics.analysis_years),
        eta_appoint=economics.eta_appoint_eco,
        auxiliary_electricity_ratio=economics.auxiliary_electricity_ratio_pct / 100.0,
        electricity_cost_eur_mwh=economics.electricity_cost_eur_mwh,
        maintenance_cost_eur_m2_year=economics.maintenance_cost_eur_m2_year,
        ademe_eur_mwh_year=economics.ademe_eur_mwh_year,
        other_public_aid_eur=0.0,
    )


def _scenario_heat_costs(
    *,
    metrics: dict[str, float],
    economics: ScenarioEconomicsConfig,
    solar_economics: dict[str, float | pd.DataFrame],
    solar_mwh: float,
    pac_power_kw: float,
    borefield_length_m: float,
    full_borefield_length_m: float,
    reference_heat_mwh: float,
    reference_power_kw: float,
) -> dict[str, float | pd.DataFrame]:
    return compute_heat_costs(
        solar_economics=solar_economics,
        annual_solar_mwh=solar_mwh,
        annual_pac_heat_mwh=metrics["pac_heat_mwh"],
        annual_pac_electricity_mwh=metrics["pac_electricity_mwh"],
        pac_power_kw=pac_power_kw,
        borefield_length_m=borefield_length_m,
        full_borefield_length_m=full_borefield_length_m,
        annual_backup_heat_mwh=metrics["backup_total_mwh"],
        backup_power_kw=metrics["backup_power_kw"],
        reference_heat_mwh=reference_heat_mwh,
        reference_power_kw=reference_power_kw,
        analysis_years=int(economics.analysis_years),
        gas_reference_p1_eur_mwh_pci=economics.reference_energy_cost_eur_mwh,
        gas_reference_efficiency=economics.eta_appoint_eco,
        gas_reference_inflation_rate=economics.reference_energy_inflation_pct / 100.0,
        geothermal_p1_eur_mwh=economics.electricity_cost_eur_mwh,
        backup_p2_eur_kw_year=economics.backup_p2_eur_kw_year,
    )


def _capex_net_total(heat_costs: dict[str, float | pd.DataFrame], generators: list[str]) -> float:
    df = heat_costs["capex_summary"]
    assert isinstance(df, pd.DataFrame)
    return float(df[df["Generateur"].isin(generators)]["CAPEX net (EUR)"].sum())


def _unit_cost(heat_costs: dict[str, float | pd.DataFrame], generator: str, poste: str) -> float:
    df = heat_costs["p1_p2_p4"]
    assert isinstance(df, pd.DataFrame)
    match = df[(df["Generateur"] == generator) & (df["Poste"] == poste)]
    return float(match["EUR/MWh"].iloc[0]) if not match.empty else 0.0


def _comparison_row(
    *,
    name: str,
    heat_costs: dict[str, float | pd.DataFrame],
    metrics: dict[str, float],
    delivered_mwh: float,
    borefield_length_m: float,
    saved_borefield_length_m: float,
    capex_net_eur: float,
    reference: bool = False,
    solar_area_m2: float,
) -> dict[str, float | str]:
    delivered = max(1e-9, delivered_mwh)
    if reference:
        p1 = float(heat_costs["reference_p1_eur_mwh"])
        p2 = float(heat_costs["reference_p2_eur_mwh"])
        p4 = float(heat_costs["reference_p4_eur_mwh"])
        cost = float(heat_costs["reference_heat_cost_eur_mwh"])
        backup_mwh = delivered_mwh
        elec_mwh = 0.0
        cop = 0.0
        ren = 0.0
        solar_cov = 0.0
        pac_cov = 0.0
        line = 0.0
        saved = 0.0
        p1_solar = 0.0
        p1_geo = 0.0
        p1_backup = p1 * delivered
        p2_solar = 0.0
        p2_geo = 0.0
        p2_backup = p2 * delivered
        p4_solar = 0.0
        p4_geo = 0.0
        p4_backup = p4 * delivered
    else:
        p1 = float(heat_costs["mix_p1_eur_mwh"])
        p2 = float(heat_costs["mix_p2_eur_mwh"])
        p4 = float(heat_costs["mix_p4_eur_mwh"])
        cost = float(heat_costs["combined_heat_cost_eur_mwh"])
        backup_mwh = metrics["backup_total_mwh"]
        elec_mwh = metrics["pac_electricity_mwh"]
        cop = metrics["mean_cop"]
        ren = metrics["global_ren_rate"]
        solar_cov = metrics["solar_ht_coverage"]
        pac_cov = metrics["pac_bt_coverage"]
        line = borefield_length_m
        saved = saved_borefield_length_m
        p1_solar = _unit_cost(heat_costs, "Solaire thermique", "P1") * metrics["solar_ht_mwh"]
        p1_geo = _unit_cost(heat_costs, "Geothermie PAC", "P1") * metrics["pac_heat_mwh"]
        p1_backup = _unit_cost(heat_costs, "Appoint gaz", "P1") * metrics["backup_total_mwh"]
        p2_solar = float(
            heat_costs.get(
                "solar_p2_ht_annual_eur",
                _unit_cost(heat_costs, "Solaire thermique", "P2") * metrics["solar_ht_mwh"],
            )
        )
        p2_geo = float(
            heat_costs.get(
                "geo_p2_base_annual_eur",
                _unit_cost(heat_costs, "Geothermie PAC", "P2") * metrics["pac_heat_mwh"],
            )
        ) + float(heat_costs.get("solar_p2_recharge_annual_eur", 0.0))
        p2_backup = _unit_cost(heat_costs, "Appoint gaz", "P2") * metrics["backup_total_mwh"]
        p4_solar = _unit_cost(heat_costs, "Solaire thermique", "P4") * metrics["solar_ht_mwh"]
        p4_geo = _unit_cost(heat_costs, "Geothermie PAC", "P4") * metrics["pac_heat_mwh"]
        p4_backup = _unit_cost(heat_costs, "Appoint gaz", "P4") * metrics["backup_total_mwh"]
    return {
        "Scenario": name,
        "Cout chaleur global (EUR/MWh)": cost,
        "CAPEX net (EUR)": capex_net_eur,
        "P1 annuel (EUR/an)": p1 * delivered,
        "P1 solaire (EUR/an)": p1_solar,
        "P1 geothermie (EUR/an)": p1_geo,
        "P1 appoint gaz (EUR/an)": p1_backup,
        "P2 annuel (EUR/an)": p2 * delivered,
        "P2 solaire (EUR/an)": p2_solar,
        "P2 geothermie (EUR/an)": p2_geo,
        "P2 appoint gaz (EUR/an)": p2_backup,
        "P4 annuel (EUR/an)": p4 * delivered,
        "P4 solaire (EUR/an)": p4_solar,
        "P4 geothermie (EUR/an)": p4_geo,
        "P4 appoint gaz (EUR/an)": p4_backup,
        "Appoint gaz (MWh/an)": backup_mwh,
        "Electricite PAC (MWh/an)": elec_mwh,
        "COP PAC moyen": cop,
        "Taux EnR global (%)": ren * 100.0,
        "Couverture solaire HT (%)": solar_cov * 100.0,
        "Couverture PAC BT (%)": pac_cov * 100.0,
        "Lineaire sondes (ml)": line,
        "Lineaire sondes economise (ml)": saved,
        "Surface solaire (m2)": solar_area_m2,
    }


def run_hourly_scenario(
    *,
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    economics: ScenarioEconomicsConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None = None,
    run_multiyear: bool = True,
    run_geo_only: bool = True,
    run_reduced_borefield: bool = True,
    progress: ProgressCallback | None = None,
) -> ScenarioResult:
    _notify(progress, 15, "Calcul horaire avec solaire...")
    hourly_df = _hourly_results_to_dataframe(
        simulate_hourly(
            weather,
            demands,
            config,
            hourly_demand_override=hourly_demand_override,
        )
    )

    no_solar_config = replace(config, collector=replace(config.collector, area_m2=0.0))
    if run_geo_only:
        _notify(progress, 35, "Calcul horaire sans solaire...")
        no_solar_hourly_df = _hourly_results_to_dataframe(
            simulate_hourly(
                weather,
                demands,
                no_solar_config,
                hourly_demand_override=hourly_demand_override,
            )
        )
    else:
        no_solar_hourly_df = hourly_df.iloc[0:0].copy()

    _notify(progress, 50, "Agrégation des résultats horaires...")
    annual_df = _annual_hourly_summary(hourly_df)
    hourly_by_month_df = _hourly_by_month_summary(hourly_df)

    multiyear_years = max(1, int(economics.analysis_years)) if run_multiyear else 1
    if run_multiyear:
        _notify(progress, 55, f"Projection multiannuelle avec solaire ({multiyear_years} ans)...")
        multiyear_df = _hourly_results_to_dataframe(
            simulate_hourly(
                weather,
                demands,
                config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=multiyear_years,
            )
        )
    else:
        _notify(progress, 55, "Projection multiannuelle desactivee : economie basee sur l'annee 1.")
        multiyear_df = hourly_df.copy()
    multiyear_btes_df = _multiyear_btes_summary(multiyear_df, t_min_c=config.btes.t_min_c)
    if run_geo_only:
        if run_multiyear:
            _notify(progress, 62, f"Projection multiannuelle sans solaire ({multiyear_years} ans)...")
            no_solar_multiyear_df = _hourly_results_to_dataframe(
                simulate_hourly(
                    weather,
                    demands,
                    no_solar_config,
                    hourly_demand_override=hourly_demand_override,
                    simulation_years=multiyear_years,
                )
            )
        else:
            no_solar_multiyear_df = no_solar_hourly_df.copy()
        no_solar_multiyear_btes_df = _multiyear_btes_summary(no_solar_multiyear_df, t_min_c=config.btes.t_min_c)
    else:
        no_solar_multiyear_df = hourly_df.iloc[0:0].copy()
        no_solar_multiyear_btes_df = pd.DataFrame()

    total_ht = float(hourly_df["demand_ht_kwh"].sum())
    total_bt = float(hourly_df["demand_bt_kwh"].sum())
    total_preheat_ht = float(hourly_df["solar_ht_direct_kwh"].sum())
    total_charge_buffer = float(hourly_df["solar_ht_to_buffer_kwh"].sum())
    total_to_btes = float(hourly_df["solar_to_btes_kwh"].sum())
    total_solar_valued = total_preheat_ht + total_to_btes
    solar_productivity_valued = total_solar_valued / max(1e-9, config.collector.area_m2)
    solar_direct_ht_economic_mwh = total_preheat_ht / 1000.0
    total_backup_ht = float(hourly_df["unmet_ht_kwh"].sum())
    total_backup_bt = float(hourly_df["unmet_bt_kwh"].sum())
    annual_ht_solar_coverage = total_preheat_ht / max(1e-9, total_ht)
    total_pac = float(hourly_df["heat_bt_from_pac_kwh"].sum())
    total_compressor = float(hourly_df["electricity_compressor_kwh"].sum())
    total_auxiliaries = float(hourly_df["electricity_pac_auxiliaries_kwh"].sum())
    total_standby = float(hourly_df["electricity_standby_kwh"].sum())
    total_elec = float(hourly_df["electricity_pac_total_kwh"].sum())
    total_system_elec = float(hourly_df["electricity_system_total_kwh"].sum())
    mean_cop = total_pac / total_compressor if total_compressor > 0 else 0.0
    spf_pac_total = total_pac / total_elec if total_elec > 0 else 0.0
    spf_system = (total_pac + total_preheat_ht) / total_system_elec if total_system_elec > 0 else 0.0
    non_ren_input = total_backup_ht + total_backup_bt + total_system_elec
    global_ren_rate = max(0.0, min(1.0, 1.0 - non_ren_input / max(1e-9, total_ht + total_bt)))

    no_solar_total_pac = float(no_solar_hourly_df["heat_bt_from_pac_kwh"].sum()) if not no_solar_hourly_df.empty else 0.0
    no_solar_total_compressor = (
        float(no_solar_hourly_df["electricity_compressor_kwh"].sum()) if not no_solar_hourly_df.empty else 0.0
    )
    no_solar_total_elec = float(no_solar_hourly_df["electricity_pac_total_kwh"].sum()) if not no_solar_hourly_df.empty else 0.0
    no_solar_cop = no_solar_total_pac / no_solar_total_compressor if no_solar_total_compressor > 0 else 0.0
    if run_geo_only and run_reduced_borefield:
        no_solar_economic_metrics = _hourly_metrics(no_solar_multiyear_df, annualization_years=multiyear_years)
    else:
        no_solar_economic_metrics = None

    _notify(progress, 70, "Calcul de l'économie équivalente de sondes...")
    if no_solar_economic_metrics is not None:
        savings = borefield_equivalent_savings(
            weather=weather,
            demands=demands,
            config=config,
            reference_cop=no_solar_economic_metrics["mean_cop"],
            reference_bt_pac_kwh=no_solar_economic_metrics["pac_heat_mwh"] * 1000.0,
            hourly_demand_override=hourly_demand_override,
            simulation_years=multiyear_years,
        )
    else:
        savings = {"found": False, "saved_length_m": 0.0, "equivalent_length_m": 0.0}

    _notify(progress, 85, "Calcul économique solaire thermique...")
    same_metrics = _hourly_metrics(multiyear_df, annualization_years=multiyear_years)
    geo_only_metrics = _hourly_metrics(no_solar_multiyear_df, annualization_years=multiyear_years) if run_geo_only else None
    economic_solar_ht_mwh = same_metrics["solar_ht_mwh"]
    economic_solar_btes_mwh = same_metrics["solar_btes_mwh"]
    economic_solar_total_mwh = economic_solar_ht_mwh + economic_solar_btes_mwh

    solar_economics = compute_solar_thermal_economics(
        surface_m2=config.collector.area_m2,
        annual_solar_valued_mwh=economic_solar_ht_mwh,
        reference_energy_cost_eur_mwh=economics.reference_energy_cost_eur_mwh,
        reference_energy_inflation_rate=economics.reference_energy_inflation_pct / 100.0,
        analysis_years=int(economics.analysis_years),
        eta_appoint=economics.eta_appoint_eco,
        auxiliary_electricity_ratio=economics.auxiliary_electricity_ratio_pct / 100.0,
        electricity_cost_eur_mwh=economics.electricity_cost_eur_mwh,
        maintenance_cost_eur_m2_year=economics.maintenance_cost_eur_m2_year,
        ademe_eur_mwh_year=economics.ademe_eur_mwh_year,
        other_public_aid_eur=economics.other_public_aid_eur,
        annual_solar_total_mwh=economic_solar_total_mwh,
    )

    zero_solar_economics = _zero_solar_economics(economics)
    backup_power_kw = same_metrics["backup_power_kw"]
    full_borefield_length_m = float(config.btes.boreholes) * float(config.btes.depth_m)
    economic_borefield_length_m = (
        float(savings["equivalent_length_m"]) if bool(savings["found"]) else full_borefield_length_m
    )
    reference_gas_power_kw = same_metrics["reference_gas_power_kw"]
    pac_power_kw = float(config.heat_pump.max_thermal_power_kw or 0.0)
    reference_heat_mwh = same_metrics["total_need_mwh"]

    if run_reduced_borefield and bool(savings["found"]):
        _notify(progress, 88, "Simulation multiannuelle avec sondes reduites...")
        reduced_boreholes = max(1, int(round(float(savings.get("equivalent_boreholes", config.btes.boreholes)))))
        reduced_btes = replace(config.btes, boreholes=reduced_boreholes)
        reduced_config = replace(config, btes=reduced_btes)
        reduced_hourly_df = _hourly_results_to_dataframe(
            simulate_hourly(
                weather,
                demands,
                reduced_config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=multiyear_years,
            )
        )
    else:
        reduced_hourly_df = multiyear_df.copy()
    reduced_metrics = _hourly_metrics(reduced_hourly_df, annualization_years=multiyear_years)

    _notify(progress, 90, "Construction des couts par scenario...")
    geo_only_heat_costs = (
        _scenario_heat_costs(
            metrics=geo_only_metrics,
            economics=economics,
            solar_economics=zero_solar_economics,
            solar_mwh=0.0,
            pac_power_kw=pac_power_kw,
            borefield_length_m=full_borefield_length_m,
            full_borefield_length_m=full_borefield_length_m,
            reference_heat_mwh=reference_heat_mwh,
            reference_power_kw=reference_gas_power_kw,
        )
        if geo_only_metrics is not None
        else None
    )
    same_borefield_heat_costs = _scenario_heat_costs(
        metrics=same_metrics,
        economics=economics,
        solar_economics=solar_economics,
        solar_mwh=economic_solar_ht_mwh,
        pac_power_kw=pac_power_kw,
        borefield_length_m=full_borefield_length_m,
        full_borefield_length_m=full_borefield_length_m,
        reference_heat_mwh=reference_heat_mwh,
        reference_power_kw=reference_gas_power_kw,
    )
    heat_costs = _scenario_heat_costs(
        metrics=reduced_metrics,
        economics=economics,
        solar_economics=solar_economics,
        solar_mwh=economic_solar_ht_mwh,
        pac_power_kw=pac_power_kw,
        borefield_length_m=economic_borefield_length_m,
        full_borefield_length_m=full_borefield_length_m,
        reference_heat_mwh=reference_heat_mwh,
        reference_power_kw=reference_gas_power_kw,
    )

    solar_allocation = solar_energy_allocation(
        solar_ht_mwh=economic_solar_ht_mwh,
        solar_btes_mwh=economic_solar_btes_mwh,
        solar_net_capex_eur=float(solar_economics["net_capex_eur"]),
        solar_p2_annual_eur=float(solar_economics["p2_annual_eur"]),
        solar_p4_annual_eur=float(solar_economics["p4_annual_eur"]),
    )
    average_electricity_cost = max(0.0, economics.electricity_cost_eur_mwh) * annuity_average_factor(
        economics.reference_energy_inflation_pct / 100.0,
        int(economics.analysis_years),
    )
    recharge_value = solar_recharge_value(
        allocation=solar_allocation,
        saved_borefield_length_m=float(savings["saved_length_m"]) if bool(savings["found"]) else 0.0,
        borefield_unit_cost_eur_m=100.0,
        saved_borefield_net_capex_eur=(
            max(0.0, float(geo_only_heat_costs["geo_net_capex_eur"]) - float(heat_costs["geo_net_capex_eur"]))
            if geo_only_heat_costs is not None and bool(savings["found"])
            else 0.0
        ),
        electricity_savings_mwh=(
            max(0.0, geo_only_metrics["pac_electricity_mwh"] - reduced_metrics["pac_electricity_mwh"])
            if geo_only_metrics is not None
            else 0.0
        ),
        average_electricity_cost_eur_mwh=average_electricity_cost,
        analysis_years=int(economics.analysis_years),
    )
    if not run_reduced_borefield:
        recharge_value["status"] = "desactive"
    elif not bool(savings["found"]):
        recharge_value["status"] = "non determine"

    same_trajectory_df = _annual_metrics_trajectory(multiyear_df, analysis_years=int(economics.analysis_years))
    geo_only_trajectory_df = (
        _annual_metrics_trajectory(no_solar_multiyear_df, analysis_years=int(economics.analysis_years))
        if run_geo_only
        else pd.DataFrame()
    )
    reduced_trajectory_df = _annual_metrics_trajectory(reduced_hourly_df, analysis_years=int(economics.analysis_years))
    reference_trajectory_df = _reference_gas_trajectory_from(same_trajectory_df)

    geo_only_capex = _capex_net_total(geo_only_heat_costs, ["Geothermie PAC", "Appoint gaz"]) if geo_only_heat_costs is not None else 0.0
    same_capex = _capex_net_total(same_borefield_heat_costs, ["Solaire thermique", "Geothermie PAC", "Appoint gaz"])
    reduced_capex = _capex_net_total(heat_costs, ["Solaire thermique", "Geothermie PAC", "Appoint gaz"])
    reference_capex = float(heat_costs["reference_capex_eur"])
    multiyear_costs_by_scenario = {
        "Reference 100 % gaz": _multiyear_heat_cost(
            trajectory_df=reference_trajectory_df,
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=reference_capex,
            reference=True,
        ),
        "Geothermie + solaire meme sondes": _multiyear_heat_cost(
            trajectory_df=same_trajectory_df,
            heat_costs=same_borefield_heat_costs,
            economics=economics,
            capex_net_eur=same_capex,
        ),
        "Geothermie + solaire sondes reduites": _multiyear_heat_cost(
            trajectory_df=reduced_trajectory_df,
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=reduced_capex,
        ),
    }
    if geo_only_heat_costs is not None:
        multiyear_costs_by_scenario["Geothermie seule"] = _multiyear_heat_cost(
            trajectory_df=geo_only_trajectory_df,
            heat_costs=geo_only_heat_costs,
            economics=economics,
            capex_net_eur=geo_only_capex,
        )
    if not run_reduced_borefield:
        multiyear_costs_by_scenario.pop("Geothermie + solaire sondes reduites", None)
    trajectory_frames = [
        reference_trajectory_df.assign(Scenario="Reference 100 % gaz"),
        same_trajectory_df.assign(Scenario="Geothermie + solaire meme sondes"),
    ]
    if run_geo_only:
        trajectory_frames.insert(1, geo_only_trajectory_df.assign(Scenario="Geothermie seule"))
    if run_reduced_borefield:
        trajectory_frames.append(reduced_trajectory_df.assign(Scenario="Geothermie + solaire sondes reduites"))
    economic_trajectory_df = pd.concat(trajectory_frames, ignore_index=True)

    _notify(progress, 95, "Construction des tableaux economiques...")
    comparison_rows = [
        _comparison_row(
            name="Reference 100 % gaz",
            heat_costs=heat_costs,
            metrics=same_metrics,
            delivered_mwh=reference_heat_mwh,
            borefield_length_m=0.0,
            saved_borefield_length_m=0.0,
            capex_net_eur=reference_capex,
            reference=True,
            solar_area_m2=0.0,
        ),
        _comparison_row(
            name="Geothermie + solaire meme sondes",
            heat_costs=same_borefield_heat_costs,
            metrics=same_metrics,
            delivered_mwh=reference_heat_mwh,
            borefield_length_m=full_borefield_length_m,
            saved_borefield_length_m=0.0,
            capex_net_eur=same_capex,
            solar_area_m2=config.collector.area_m2,
        ),
    ]
    if geo_only_heat_costs is not None and geo_only_metrics is not None:
        comparison_rows.insert(
            1,
            _comparison_row(
                name="Geothermie seule",
                heat_costs=geo_only_heat_costs,
                metrics=geo_only_metrics,
                delivered_mwh=reference_heat_mwh,
                borefield_length_m=full_borefield_length_m,
                saved_borefield_length_m=0.0,
                capex_net_eur=geo_only_capex,
                solar_area_m2=0.0,
            ),
        )
    if run_reduced_borefield:
        comparison_rows.append(
            _comparison_row(
                name="Geothermie + solaire sondes reduites",
                heat_costs=heat_costs,
                metrics=reduced_metrics,
                delivered_mwh=reference_heat_mwh,
                borefield_length_m=economic_borefield_length_m,
                saved_borefield_length_m=float(savings["saved_length_m"]) if bool(savings["found"]) else 0.0,
                capex_net_eur=reduced_capex,
                solar_area_m2=config.collector.area_m2,
            )
        )
    economic_comparison_df = pd.DataFrame(comparison_rows)
    for index, row in economic_comparison_df.iterrows():
        scenario_name = str(row["Scenario"])
        costs = multiyear_costs_by_scenario[scenario_name]
        economic_comparison_df.loc[index, "Cout chaleur global (EUR/MWh)"] = costs["multiyear_heat_cost_eur_mwh"]
        economic_comparison_df.loc[index, "P1 annuel (EUR/an)"] = costs["p1_annual_eur"]
        economic_comparison_df.loc[index, "P2 annuel (EUR/an)"] = costs["p2_annual_eur"]
        economic_comparison_df.loc[index, "P4 annuel (EUR/an)"] = costs["p4_annual_eur"]
    economic_comparison_df["Méthode coût chaleur"] = "Multiannuel nominal" if run_multiyear else "Annuel nominal"
    economic_comparison_chart_df = economic_comparison_df.melt(
        id_vars=["Scenario"],
        value_vars=[
            "Cout chaleur global (EUR/MWh)",
            "Taux EnR global (%)",
            "Lineaire sondes (ml)",
            "Electricite PAC (MWh/an)",
        ],
        var_name="Indicateur",
        value_name="Valeur",
    )

    return ScenarioResult(
        config=config,
        hourly_df=hourly_df,
        no_solar_hourly_df=no_solar_hourly_df,
        multiyear_btes_df=multiyear_btes_df,
        no_solar_multiyear_btes_df=no_solar_multiyear_btes_df,
        annual_df=annual_df,
        hourly_by_month_df=hourly_by_month_df,
        savings=savings,
        solar_economics=solar_economics,
        heat_costs=heat_costs,
        economic_comparison_df=economic_comparison_df,
        economic_comparison_chart_df=economic_comparison_chart_df,
        economic_trajectory_df=economic_trajectory_df,
        recharge_value=recharge_value,
        solar_allocation=solar_allocation,
        total_ht_kwh=total_ht,
        total_bt_kwh=total_bt,
        total_preheat_ht_kwh=total_preheat_ht,
        total_charge_buffer_kwh=total_charge_buffer,
        total_to_btes_kwh=total_to_btes,
        total_solar_valued_kwh=total_solar_valued,
        solar_productivity_valued_kwh_m2_year=solar_productivity_valued,
        solar_direct_ht_economic_mwh=solar_direct_ht_economic_mwh,
        total_backup_ht_kwh=total_backup_ht,
        total_backup_bt_kwh=total_backup_bt,
        annual_ht_solar_coverage=annual_ht_solar_coverage,
        total_pac_kwh=total_pac,
        total_compressor_kwh=total_compressor,
        total_pac_auxiliaries_kwh=total_auxiliaries,
        total_standby_kwh=total_standby,
        total_elec_kwh=total_elec,
        total_system_elec_kwh=total_system_elec,
        mean_cop=mean_cop,
        spf_pac_total=spf_pac_total,
        spf_system=spf_system,
        global_ren_rate=global_ren_rate,
        no_solar_total_pac_kwh=no_solar_total_pac,
        no_solar_total_compressor_kwh=no_solar_total_compressor,
        no_solar_total_elec_kwh=no_solar_total_elec,
        no_solar_cop=no_solar_cop,
        backup_power_kw=backup_power_kw,
        full_borefield_length_m=full_borefield_length_m,
        economic_borefield_length_m=economic_borefield_length_m,
        reference_gas_power_kw=reference_gas_power_kw,
    )
