from __future__ import annotations

import gc
import time
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
from .borefield_savings import (
    _final_year_screening_metrics,
    _final_year_screening_metrics_from_results,
    borefield_equivalent_savings,
)
from .engine import MonthlyDemand, SimulationConfig, cop_from_source_temperature
from .geothermal_design import predimension_borefield
from .hourly_engine import HourlyResult, HourlyWeather, simulate_hourly
from .load_profiles import _estimate_capped_bt_heat_mwh
from .postprocess import (
    _annual_hourly_summary,
    _hourly_by_month_summary,
    _hourly_results_to_dataframe,
    _multiyear_btes_summary,
    btes_efficiency_indicator,
    btes_load_diagnostics_from_results,
    sign_change_diagnostics,
)
from .scenario_compact import _simulate_hourly_compact
from .scenario_metrics import (
    _annual_metrics_trajectory_from_results,
    _hourly_metrics_from_results,
    _max_attr,
    _mean_attr,
    _min_attr,
    _multiyear_btes_summary_from_results,
    _results_by_year,
)
from .simulation_cache import SimulationCache


ProgressCallback = Callable[[int, str], None]
PYGFUNCTION_PARALLEL_ENABLED = False


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
    btes_diagnostics: dict[str, float | int | str | bool | None]


def _notify(progress: ProgressCallback | None, value: int, text: str) -> None:
    if progress is not None:
        progress(value, text)


def _simulate_hourly_cached(
    *,
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    simulation_years: int,
    simulation_cache: SimulationCache | None,
    cache_mode: str,
):
    if simulation_cache is not None:
        return simulation_cache.simulate(
            weather,
            demands,
            config,
            hourly_demand_override=hourly_demand_override,
            simulation_years=simulation_years,
            mode=cache_mode,
        )
    return simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=hourly_demand_override,
        simulation_years=simulation_years,
    )


def _simulate_hourly_dataframe(
    *,
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    simulation_years: int,
    simulation_cache: SimulationCache | None,
) -> pd.DataFrame:
    results = _simulate_hourly_cached(
        weather=weather,
        demands=demands,
        config=config,
        hourly_demand_override=hourly_demand_override,
        simulation_years=simulation_years,
        simulation_cache=simulation_cache,
        cache_mode="pygfunction",
    )
    started_at = time.perf_counter()
    df = _hourly_results_to_dataframe(results)
    elapsed = time.perf_counter() - started_at
    if simulation_cache is not None:
        simulation_cache.record_event(
            "postprocess:dataframe",
            "Conversion resultats horaires en DataFrame",
            {
                "Mode simulation": "pygfunction",
                "Annees simulees": int(simulation_years),
                "Pas meteo": int(len(weather)),
                "Heures simulees": int(len(results)),
                "Lignes DataFrame": int(len(df)),
                "Duree dataframe (s)": elapsed,
            },
        )
    del results
    return df


def _results_year_to_dataframe(
    results: list[HourlyResult],
    *,
    year: int,
    simulation_years: int,
    weather_len: int,
    simulation_cache: SimulationCache | None,
    label: str,
) -> pd.DataFrame:
    selected = [result for result in results if int(result.simulation_year) == int(year)]
    if not selected and results:
        selected = [result for result in results if int(result.simulation_year) == 1]
    started_at = time.perf_counter()
    df = _hourly_results_to_dataframe(selected)
    elapsed = time.perf_counter() - started_at
    if simulation_cache is not None:
        simulation_cache.record_event(
            "postprocess:dataframe",
            f"Conversion annee affichee en DataFrame ({label})",
            {
                "Mode simulation": "pygfunction",
                "Annees simulees": int(simulation_years),
                "Pas meteo": int(weather_len),
                "Heures simulees": int(len(selected)),
                "Lignes DataFrame": int(len(df)),
                "Duree dataframe (s)": elapsed,
            },
        )
    return df


def solar_surface_parametric_study(
    *,
    surfaces_m2: list[float],
    weather,
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    no_solar_cop: float,
    no_solar_total_pac_kwh: float,
    no_solar_bt_coverage: float,
    no_solar_source_limited_hours: float,
    pac_nominal_power_kw: float,
    full_borefield_length_m: float,
    reference_gas_power_kw: float,
    reference_heat_mwh: float,
    analysis_years: int,
    technical_simulation_years: int | None = None,
    reference_energy_cost_eur_mwh: float,
    reference_energy_inflation_pct: float,
    eta_appoint_eco: float,
    backup_p2_eur_kw_year: float,
    auxiliary_electricity_ratio_pct: float,
    electricity_cost_eur_mwh: float,
    maintenance_cost_eur_m2_year: float,
    ademe_eur_mwh_year: float,
    other_public_aid_eur: float,
    savings_search_mode: str = "fast",
    recharge_credit: float = 0.6,
    reduced_borefield_safety_factor: float = 1.10,
    full_case_reference: dict[str, object] | None = None,
    simulation_cache: SimulationCache | None = None,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    rows = []
    total_points = max(1, len(surfaces_m2))
    simulation_years = max(1, int(technical_simulation_years or analysis_years))
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
            f"Etude parametrique surface {index}/{total_points} : {surface_m2:.0f} m2",
        )

        variant_config = replace(config, collector=replace(config.collector, area_m2=float(surface_m2)))
        can_reuse_full_case = (
            full_case_reference is not None
            and abs(float(full_case_reference.get("surface_m2", -1.0)) - float(surface_m2)) <= 1e-9
            and int(full_case_reference.get("boreholes", -1)) == int(variant_config.btes.boreholes)
            and abs(float(full_case_reference.get("depth_m", -1.0)) - float(variant_config.btes.depth_m)) <= 1e-9
            and int(full_case_reference.get("simulation_years", -1)) == int(simulation_years)
        )
        if can_reuse_full_case:
            if simulation_cache is not None:
                simulation_cache.record_reuse(
                    "simulate:reuse_summary",
                    "Scenario principal reutilise pour le point solaire parametrique",
                    {
                        "Mode simulation": "solar_parametric_reuse",
                        "Annees simulees": int(simulation_years),
                        "Pas meteo": int(len(weather)),
                        "Heures simulees": int(len(weather) * simulation_years),
                        "Surface solaire (m2)": float(surface_m2),
                        "Sondes": int(variant_config.btes.boreholes),
                        "Lineaire sondes (ml)": float(variant_config.btes.boreholes) * float(variant_config.btes.depth_m),
                    },
                )
            economic_metrics_variant = dict(full_case_reference.get("metrics", {}))
            full_case_metrics = dict(full_case_reference.get("full_case_metrics", {}))
            variant_trajectory_df = full_case_reference.get("trajectory_df", pd.DataFrame())
            if isinstance(variant_trajectory_df, pd.DataFrame):
                variant_trajectory_df = variant_trajectory_df.copy()
            else:
                variant_trajectory_df = pd.DataFrame()
        else:
            economic_metrics_variant, full_case_metrics, variant_trajectory_df = _simulate_hourly_compact(
                weather=weather,
                demands=demands,
                config=variant_config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=simulation_years,
                simulation_cache=simulation_cache,
                cache_mode="solar_parametric_compact",
            )

        final_row = (
            variant_trajectory_df[variant_trajectory_df["Annee"] == simulation_years].iloc[-1]
            if not variant_trajectory_df.empty and "Annee" in variant_trajectory_df
            else pd.Series(dtype=float)
        )
        total_ht_variant = float(final_row.get("E utile HT (MWh)", 0.0)) * 1000.0
        total_bt_variant = float(final_row.get("E utile BT (MWh)", 0.0)) * 1000.0
        total_preheat_ht_variant = float(final_row.get("Solaire HT (MWh)", 0.0)) * 1000.0
        total_to_btes_variant = float(final_row.get("Injection solaire BTES (MWh)", 0.0)) * 1000.0
        total_backup_ht_variant = float(final_row.get("Appoint gaz HT (MWh)", 0.0)) * 1000.0
        total_backup_bt_variant = float(final_row.get("Appoint gaz BT (MWh)", 0.0)) * 1000.0
        total_elec_variant = float(final_row.get("Electricite PAC (MWh)", 0.0)) * 1000.0
        total_pac_variant = float(final_row.get("Chaleur PAC BT (MWh)", 0.0)) * 1000.0
        final_cop_variant = float(full_case_metrics.get("final_cop", 0.0))
        global_ren_rate_variant = float(final_row.get("Taux EnR (%)", 0.0)) / 100.0
        annual_ht_solar_coverage_variant = total_preheat_ht_variant / max(1e-9, total_ht_variant)

        savings_variant = borefield_equivalent_savings(
            weather=weather,
            demands=demands,
            config=variant_config,
            reference_final_cop=no_solar_cop,
            reference_final_bt_pac_kwh=no_solar_total_pac_kwh,
            reference_final_bt_coverage=no_solar_bt_coverage,
            reference_final_source_limited_hours=no_solar_source_limited_hours,
            hourly_demand_override=hourly_demand_override,
            simulation_years=simulation_years,
            iterations=8,
            search_mode=savings_search_mode,
            full_case_metrics=full_case_metrics,
            recharge_credit=recharge_credit,
            reduced_borefield_safety_factor=reduced_borefield_safety_factor,
            simulation_cache=simulation_cache,
            include_hourly_df=False,
        )
        economic_borefield_length_m_variant = (
            float(savings_variant["equivalent_length_m"])
            if bool(savings_variant["found"])
            else full_borefield_length_m
        )
        reduced_economic_metrics_variant = dict(economic_metrics_variant)
        if bool(savings_variant["found"]):
            reduced_economic_metrics_variant["pac_heat_mwh"] = (
                float(savings_variant.get("equivalent_bt_pac_kwh", economic_metrics_variant["pac_heat_mwh"] * 1000.0))
                / 1000.0
            )
            reduced_economic_metrics_variant["pac_electricity_mwh"] = (
                float(
                    savings_variant.get(
                        "equivalent_mean_pac_electricity_kwh",
                        economic_metrics_variant["pac_electricity_mwh"] * 1000.0,
                    )
                )
                / 1000.0
            )
            reduced_economic_metrics_variant["backup_total_mwh"] = (
                float(
                    savings_variant.get(
                        "equivalent_mean_backup_total_kwh",
                        economic_metrics_variant["backup_total_mwh"] * 1000.0,
                    )
                )
                / 1000.0
            )

        solar_ht_from_buffer_mwh_variant = economic_metrics_variant["solar_ht_mwh"]
        solar_total_mwh_variant = economic_metrics_variant["solar_ht_mwh"] + economic_metrics_variant["solar_btes_mwh"]
        solar_economics_variant = compute_solar_thermal_economics(
            surface_m2=float(surface_m2),
            annual_solar_valued_mwh=solar_ht_from_buffer_mwh_variant,
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
        same_heat_costs_variant = compute_heat_costs(
            solar_economics=solar_economics_variant,
            annual_solar_mwh=solar_ht_from_buffer_mwh_variant,
            annual_pac_heat_mwh=economic_metrics_variant["pac_heat_mwh"],
            annual_pac_electricity_mwh=economic_metrics_variant["pac_electricity_mwh"],
            pac_power_kw=pac_nominal_power_kw,
            borefield_length_m=full_borefield_length_m,
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
        heat_costs_variant = compute_heat_costs(
            solar_economics=solar_economics_variant,
            annual_solar_mwh=solar_ht_from_buffer_mwh_variant,
            annual_pac_heat_mwh=reduced_economic_metrics_variant["pac_heat_mwh"],
            annual_pac_electricity_mwh=reduced_economic_metrics_variant["pac_electricity_mwh"],
            pac_power_kw=pac_nominal_power_kw,
            borefield_length_m=economic_borefield_length_m_variant,
            full_borefield_length_m=full_borefield_length_m,
            annual_backup_heat_mwh=reduced_economic_metrics_variant["backup_total_mwh"],
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
        same_capex_variant = _capex_net_total(same_heat_costs_variant, ["Solaire thermique", "Geothermie PAC", "Appoint gaz"])
        same_multiyear_cost_variant = _multiyear_heat_cost(
            trajectory_df=variant_trajectory_df,
            heat_costs=same_heat_costs_variant,
            economics=economics_config,
            capex_net_eur=same_capex_variant,
        )
        reduced_trajectory_variant = variant_trajectory_df.copy()
        if bool(savings_variant["found"]) and not reduced_trajectory_variant.empty:
            reduced_trajectory_variant["Chaleur PAC BT (MWh)"] = reduced_economic_metrics_variant["pac_heat_mwh"]
            reduced_trajectory_variant["Electricite PAC (MWh)"] = reduced_economic_metrics_variant[
                "pac_electricity_mwh"
            ]
            original_backup_total = (
                pd.to_numeric(
                    reduced_trajectory_variant["Appoint gaz total (MWh)"],
                    errors="coerce",
                ).replace(0.0, pd.NA)
                if "Appoint gaz total (MWh)" in reduced_trajectory_variant
                else pd.Series(dtype=float)
            )
            if not original_backup_total.empty and "Appoint gaz HT (MWh)" in reduced_trajectory_variant:
                original_backup_total = pd.to_numeric(original_backup_total, errors="coerce")
                original_backup_ht = pd.to_numeric(
                    reduced_trajectory_variant["Appoint gaz HT (MWh)"],
                    errors="coerce",
                )
                ht_share = (
                    original_backup_ht
                    / original_backup_total
                ).fillna(0.0)
                reduced_trajectory_variant["Appoint gaz HT (MWh)"] = (
                    reduced_economic_metrics_variant["backup_total_mwh"] * ht_share
                )
                reduced_trajectory_variant["Appoint gaz BT (MWh)"] = (
                    reduced_economic_metrics_variant["backup_total_mwh"] * (1.0 - ht_share)
                )
            reduced_trajectory_variant["Appoint gaz total (MWh)"] = reduced_economic_metrics_variant[
                "backup_total_mwh"
            ]
        capex_variant = _capex_net_total(heat_costs_variant, ["Solaire thermique", "Geothermie PAC", "Appoint gaz"])
        multiyear_cost_variant = _multiyear_heat_cost(
            trajectory_df=reduced_trajectory_variant,
            heat_costs=heat_costs_variant,
            economics=economics_config,
            capex_net_eur=capex_variant,
        )

        rows.append(
            {
                "Surface solaire (m²)": float(surface_m2),
                "Coût chaleur Mix ENR (EUR/MWh)": float(multiyear_cost_variant["multiyear_heat_cost_eur_mwh"]),
                "Coût chaleur même linéaire (EUR/MWh)": float(same_multiyear_cost_variant["multiyear_heat_cost_eur_mwh"]),
                "Coût chaleur avec économie sondes (EUR/MWh)": float(multiyear_cost_variant["multiyear_heat_cost_eur_mwh"]),
                "Taux EnR global (%)": global_ren_rate_variant * 100.0,
                "Couverture solaire HT (%)": annual_ht_solar_coverage_variant * 100.0,
                "Préchauffage HT solaire (MWh/an)": total_preheat_ht_variant / 1000.0,
                "Injection BTES (MWh/an)": total_to_btes_variant / 1000.0,
                "COP PAC moyen": final_cop_variant,
                "COP PAC final": full_case_metrics["final_cop"],
                "Chaleur PAC BT finale (MWh)": full_case_metrics["final_bt_pac_kwh"] / 1000.0,
                "Couverture PAC BT finale (%)": full_case_metrics["final_bt_coverage"] * 100.0,
                "T source PAC min finale (C)": full_case_metrics["final_t_source_min_c"],
                "q extraction max finale (W/m)": full_case_metrics["final_q_extraction_max_w_m"],
                "q injection max finale (W/m)": full_case_metrics["final_q_injection_max_w_m"],
                "Extraction sol finale (MWh)": full_case_metrics["final_extracted_ground_kwh"] / 1000.0,
                "Injection BTES finale (MWh)": full_case_metrics["final_injected_btes_kwh"] / 1000.0,
                "Heures limite source finale": full_case_metrics["final_source_limited_hours"],
                "Heures hors GMI finale": full_case_metrics["final_hours_under_gmi_tmin"] + full_case_metrics["final_hours_over_gmi_tmax"],
                "Economie sondes trouvee": bool(savings_variant["found"]),
                "Mode economie sondes": str(savings_search_mode),
                "Lineaire estime (ml)": float(savings_variant.get("estimated_length_m", full_borefield_length_m)),
                "Lineaire verifie (ml)": float(savings_variant.get("verified_length_m", economic_borefield_length_m_variant)),
                "Simulations economie sondes": int(savings_variant.get("savings_simulations_count", 0)),
                "Scenario principal reutilise": bool(can_reuse_full_case),
                "Linéaire sondes retenu éco (ml)": economic_borefield_length_m_variant,
                "CAPEX solaire net (kEUR)": float(solar_economics_variant["net_capex_eur"]) / 1000.0,
            }
        )
        if simulation_cache is not None:
            simulation_cache.clear_entries(
                reason=f"Nettoyage memoire apres surface solaire {index}/{total_points}"
            )
        del variant_trajectory_df
        del reduced_trajectory_variant
        gc.collect()

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
    technical_simulation_years: int | None = None,
    reference_energy_cost_eur_mwh: float,
    reference_energy_inflation_pct: float,
    eta_appoint_eco: float,
    backup_p2_eur_kw_year: float,
    auxiliary_electricity_ratio_pct: float,
    electricity_cost_eur_mwh: float,
    maintenance_cost_eur_m2_year: float,
    ademe_eur_mwh_year: float,
    other_public_aid_eur: float,
    simulation_cache: SimulationCache | None = None,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    rows = []
    total_points = max(1, len(pac_power_fractions_pct))
    simulation_years = max(1, int(technical_simulation_years or analysis_years))
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
            f"Etude parametrique PAC {index}/{total_points} : {fraction_pct:.0f} % Pmax",
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
        economic_metrics_variant, full_case_metrics, variant_trajectory_df = _simulate_hourly_compact(
            weather=weather,
            demands=demands,
            config=variant_config,
            hourly_demand_override=hourly_demand_override,
            simulation_years=simulation_years,
            simulation_cache=simulation_cache,
            cache_mode="pac_parametric_compact",
        )

        final_row = (
            variant_trajectory_df[variant_trajectory_df["Annee"] == simulation_years].iloc[-1]
            if not variant_trajectory_df.empty and "Annee" in variant_trajectory_df
            else pd.Series(dtype=float)
        )
        total_ht_variant = float(final_row.get("E utile HT (MWh)", 0.0)) * 1000.0
        total_bt_variant = float(final_row.get("E utile BT (MWh)", 0.0)) * 1000.0
        total_backup_ht_variant = float(final_row.get("Appoint gaz HT (MWh)", 0.0)) * 1000.0
        total_backup_bt_variant = float(final_row.get("Appoint gaz BT (MWh)", 0.0)) * 1000.0
        total_pac_variant = float(final_row.get("Chaleur PAC BT (MWh)", 0.0)) * 1000.0
        total_elec_variant = float(final_row.get("Electricite PAC (MWh)", 0.0)) * 1000.0
        final_cop_variant = float(final_row.get("COP moyen", 0.0))
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
            trajectory_df=variant_trajectory_df,
            heat_costs=heat_costs_variant,
            economics=economics_config,
            capex_net_eur=capex_variant,
        )

        rows.append(
            {
                "P PAC (% Pmax BT)": float(fraction_pct),
                "P PAC (kW)": pac_kw,
                "Coût chaleur géothermie + appoint gaz (EUR/MWh)": float(multiyear_cost_variant["multiyear_heat_cost_eur_mwh"]),
                "Taux EnR global (%)": global_ren_rate_variant * 100.0,
                "Couverture PAC BT (%)": pac_bt_coverage * 100.0,
                "Besoin HT gaz (MWh/an)": total_backup_ht_variant / 1000.0,
                "Complément BT gaz (MWh/an)": total_backup_bt_variant / 1000.0,
                "Appoint total (MWh/an)": (total_backup_ht_variant + total_backup_bt_variant) / 1000.0,
                "COP PAC moyen": final_cop_variant,
                "Linéaire sondes retenu éco (ml)": economic_borefield_length_m_variant,
                "Nombre sondes predim": predesign_variant.boreholes if predesign_variant else btes_variant.boreholes,
            }
        )
        if simulation_cache is not None:
            simulation_cache.clear_entries(
                reason=f"Nettoyage memoire apres point PAC {index}/{total_points}"
            )
        del variant_trajectory_df
        gc.collect()

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
    total_solar_ht = float(df["solar_ht_from_buffer_kwh"].sum())
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
        "source_limited_hours": float(df["Limite_temperature_source"].sum()) if "Limite_temperature_source" in df else 0.0,
        "source_limited_unmet_mwh": (
            float(df["BT_non_couvert_limite_source_kWh"].sum()) / 1000.0
            if "BT_non_couvert_limite_source_kWh" in df
            else 0.0
        ),
    }


def _annual_metrics_trajectory(
    df: pd.DataFrame,
    *,
    analysis_years: int,
    gmi_t_min_c: float = -3.0,
    gmi_t_max_c: float = 40.0,
    gmi_check_enabled: bool = True,
) -> pd.DataFrame:
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
        solar_ht = float(group["solar_ht_from_buffer_kwh"].sum())
        source_limited_hours = int(group["Limite_temperature_source"].sum()) if "Limite_temperature_source" in group else 0
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
                "SPF PAC complet": heat_pac / elec_total if elec_total > 0.0 else 0.0,
                "Couverture PAC BT (%)": heat_pac / max(1e-9, total_bt) * 100.0,
                "Heures equivalentes PAC BT": heat_pac / max(
                    1e-9,
                    float(group["puissance_pac_kw"].max())
                    if "puissance_pac_kw" in group
                    else float(group["heat_bt_from_pac_kwh"].max()),
                ),
                "T_source_PAC_min (C)": float(group["T_source_PAC_C"].min()) if "T_source_PAC_C" in group else 0.0,
                "T_source_PAC_pour_COP_min (C)": float(group["T_source_PAC_pour_COP_C"].min()) if "T_source_PAC_pour_COP_C" in group else 0.0,
                "T_fluide_injection_max (C)": float(group["T_fluide_injection_C"].max()) if "T_fluide_injection_C" in group else 0.0,
                "Heures sous Tmin GMI": (
                    int((group["T_fluide_entree_echangeur_geo_C"] < gmi_t_min_c - 1e-6).sum())
                    if "T_fluide_entree_echangeur_geo_C" in group
                    else 0
                ),
                "Heures sur Tmax GMI": (
                    int((group["T_fluide_injection_C"] > gmi_t_max_c + 1e-6).sum())
                    if "T_fluide_injection_C" in group
                    else 0
                ),
                "Conformite GMI": bool(
                    (not gmi_check_enabled)
                    or (
                        (
                            "T_fluide_entree_echangeur_geo_C" in group
                            and (group["T_fluide_entree_echangeur_geo_C"] >= gmi_t_min_c - 1e-6).all()
                        )
                        and (
                            "T_fluide_injection_C" in group
                            and (group["T_fluide_injection_C"] <= gmi_t_max_c + 1e-6).all()
                        )
                    )
                ),
                "Heures limite source": source_limited_hours,
                "BT non couvert limite source (MWh)": (
                    float(group["BT_non_couvert_limite_source_kWh"].sum()) / 1000.0
                    if "BT_non_couvert_limite_source_kWh" in group
                    else 0.0
                ),
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
    reference_df["SPF PAC complet"] = 0.0
    reference_df["Couverture PAC BT (%)"] = 0.0
    reference_df["Heures equivalentes PAC BT"] = 0.0
    reference_df["T_source_PAC_min (C)"] = 0.0
    reference_df["T_source_PAC_moy (C)"] = 0.0
    reference_df["T_source_PAC_pour_COP_min (C)"] = 0.0
    reference_df["T_fluide_injection_max (C)"] = 0.0
    reference_df["q_extraction_W_m_max"] = 0.0
    reference_df["q_injection_W_m_max"] = 0.0
    reference_df["Heures sous Tmin GMI"] = 0
    reference_df["Heures sur Tmax GMI"] = 0
    reference_df["Conformite GMI"] = True
    reference_df["Heures limite source"] = 0
    reference_df["BT non couvert limite source (MWh)"] = 0.0
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
        "p1_cumulative_eur": p1_total_nominal,
        "p2_cumulative_eur": p2_total_nominal,
        "p4_cumulative_eur": p4_total_nominal,
        "backup_gas_cumulative_mwh": float(trajectory_df["Appoint gaz total (MWh)"].sum()),
        "pac_electricity_cumulative_mwh": float(trajectory_df["Electricite PAC (MWh)"].sum()),
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
    if df.empty or not {"Generateur", "Poste", "EUR/MWh"}.issubset(df.columns):
        return 0.0
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
    technical_simulation_years: int | None = None,
    display_year_mode: str = "finale",
    custom_display_year: int | None = None,
    run_geo_only: bool = True,
    run_reduced_borefield: bool = False,
    savings_search_mode: str = "fast",
    simulation_cache: SimulationCache | None = None,
    progress: ProgressCallback | None = None,
) -> ScenarioResult:
    multiyear_years = max(1, int(technical_simulation_years or 25)) if run_multiyear else 1
    _notify(
        progress,
        15,
        f"Projection multiannuelle avec solaire ({multiyear_years} ans)..."
        if run_multiyear
        else "Calcul horaire avec solaire (1 an)...",
    )
    no_solar_config = replace(config, collector=replace(config.collector, area_m2=0.0))
    display_mode = str(display_year_mode).lower()
    if display_mode in {"annee 1", "annÃ©e 1", "year 1"}:
        simulation_year_displayed = 1
    elif display_mode in {"personnalisee", "personnalisÃ©e", "custom"}:
        simulation_year_displayed = max(1, min(multiyear_years, int(custom_display_year or multiyear_years)))
    else:
        simulation_year_displayed = multiyear_years
    if run_geo_only:
        _notify(
            progress,
            16,
            f"Simulation solaire {multiyear_years} ans - demarrage",
        )
        multiyear_results = _simulate_hourly_cached(
            weather=weather,
            demands=demands,
            config=config,
            hourly_demand_override=hourly_demand_override,
            simulation_years=multiyear_years,
            simulation_cache=simulation_cache,
            cache_mode="pygfunction",
        )
        _notify(
            progress,
            30,
            f"Simulation solaire {multiyear_years} ans - agregation",
        )
        hourly_df = _results_year_to_dataframe(
            multiyear_results,
            year=simulation_year_displayed,
            simulation_years=multiyear_years,
            weather_len=len(weather),
            simulation_cache=simulation_cache,
            label="solaire",
        )
        if hourly_df.empty and simulation_year_displayed != 1:
            simulation_year_displayed = 1
        _notify(
            progress,
            35,
            f"Simulation sans solaire {multiyear_years} ans - demarrage",
        )
        no_solar_results = _simulate_hourly_cached(
            weather=weather,
            demands=demands,
            config=no_solar_config,
            hourly_demand_override=hourly_demand_override,
            simulation_years=multiyear_years,
            simulation_cache=simulation_cache,
            cache_mode="pygfunction",
        )
        _notify(
            progress,
            45,
            f"Simulation sans solaire {multiyear_years} ans - agregation",
        )
        no_solar_hourly_df = _results_year_to_dataframe(
            no_solar_results,
            year=simulation_year_displayed,
            simulation_years=multiyear_years,
            weather_len=len(weather),
            simulation_cache=simulation_cache,
            label="sans solaire",
        )
        _notify(progress, 48, "Nettoyage memoire")
        gc.collect()
    else:
        _notify(
            progress,
            16,
            f"Simulation solaire {multiyear_years} ans - demarrage",
        )
        multiyear_results = _simulate_hourly_cached(
            weather=weather,
            demands=demands,
            config=config,
            hourly_demand_override=hourly_demand_override,
            simulation_years=multiyear_years,
            simulation_cache=simulation_cache,
            cache_mode="pygfunction",
        )
        _notify(
            progress,
            35,
            f"Simulation solaire {multiyear_years} ans - agregation",
        )
        hourly_df = _results_year_to_dataframe(
            multiyear_results,
            year=simulation_year_displayed,
            simulation_years=multiyear_years,
            weather_len=len(weather),
            simulation_cache=simulation_cache,
            label="solaire",
        )
        no_solar_hourly_df = hourly_df.iloc[0:0].copy()
        no_solar_results: list[HourlyResult] = []
        _notify(progress, 48, "Nettoyage memoire")
        gc.collect()

    _notify(progress, 50, "Agrégation des résultats horaires...")
    multiyear_btes_df = _multiyear_btes_summary_from_results(
        multiyear_results,
        t_min_c=config.btes.t_min_c,
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        gmi_check_enabled=config.btes.gmi_check_enabled,
    )
    if run_geo_only:
        no_solar_multiyear_btes_df = _multiyear_btes_summary_from_results(
            no_solar_results,
            t_min_c=config.btes.t_min_c,
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            gmi_check_enabled=config.btes.gmi_check_enabled,
        )
    else:
        no_solar_multiyear_btes_df = pd.DataFrame()

    display_mode = str(display_year_mode).lower()
    if display_mode in {"annee 1", "année 1", "year 1"}:
        simulation_year_displayed = 1
    elif display_mode in {"personnalisee", "personnalisée", "custom"}:
        simulation_year_displayed = max(1, min(multiyear_years, int(custom_display_year or multiyear_years)))
    else:
        simulation_year_displayed = multiyear_years
    displayed_hourly_df = hourly_df.copy()
    displayed_hourly_df["simulation_year_displayed"] = simulation_year_displayed
    displayed_hourly_df["simulation_years_total"] = multiyear_years
    displayed_hourly_df["scenario"] = "Geothermie + solaire meme sondes"
    displayed_hourly_df["surface_solaire_m2"] = float(config.collector.area_m2)
    displayed_hourly_df["solaire_actif"] = bool(config.collector.area_m2 > 0.0)
    displayed_hourly_df["puissance_pac_kw"] = float(config.heat_pump.max_thermal_power_kw or 0.0)
    displayed_hourly_df["lineaire_sondes_m"] = float(config.btes.boreholes) * float(config.btes.depth_m)
    displayed_hourly_df["tmin_source_operationnelle_c"] = float(config.btes.t_min_c)
    displayed_hourly_df["critere_gmi_active"] = bool(config.btes.gmi_check_enabled)

    no_solar_displayed_hourly_df = no_solar_hourly_df.copy()
    if not no_solar_displayed_hourly_df.empty:
        no_solar_displayed_hourly_df["simulation_year_displayed"] = simulation_year_displayed
        no_solar_displayed_hourly_df["simulation_years_total"] = multiyear_years
        no_solar_displayed_hourly_df["scenario"] = "Geothermie seule"
        no_solar_displayed_hourly_df["surface_solaire_m2"] = 0.0
        no_solar_displayed_hourly_df["solaire_actif"] = False
        no_solar_displayed_hourly_df["puissance_pac_kw"] = float(no_solar_config.heat_pump.max_thermal_power_kw or 0.0)
        no_solar_displayed_hourly_df["lineaire_sondes_m"] = float(no_solar_config.btes.boreholes) * float(no_solar_config.btes.depth_m)
        no_solar_displayed_hourly_df["tmin_source_operationnelle_c"] = float(no_solar_config.btes.t_min_c)
        no_solar_displayed_hourly_df["critere_gmi_active"] = bool(no_solar_config.btes.gmi_check_enabled)
    hourly_df = displayed_hourly_df
    no_solar_hourly_df = no_solar_displayed_hourly_df
    annual_df = _annual_hourly_summary(hourly_df)
    hourly_by_month_df = _hourly_by_month_summary(hourly_df)

    total_ht = float(hourly_df["demand_ht_kwh"].sum())
    total_bt = float(hourly_df["demand_bt_kwh"].sum())
    total_preheat_ht = float(hourly_df["solar_ht_from_buffer_kwh"].sum())
    total_charge_buffer = float(hourly_df["solar_ht_to_buffer_kwh"].sum())
    total_to_btes = float(hourly_df["solar_to_btes_kwh"].sum())
    total_solar_valued = total_preheat_ht + total_to_btes
    solar_productivity_valued = total_solar_valued / max(1e-9, config.collector.area_m2)
    solar_ht_from_buffer_economic_mwh = total_preheat_ht / 1000.0
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

    no_solar_total_pac = float(no_solar_displayed_hourly_df["heat_bt_from_pac_kwh"].sum()) if not no_solar_displayed_hourly_df.empty else 0.0
    no_solar_total_compressor = (
        float(no_solar_displayed_hourly_df["electricity_compressor_kwh"].sum()) if not no_solar_displayed_hourly_df.empty else 0.0
    )
    no_solar_total_elec = float(no_solar_displayed_hourly_df["electricity_pac_total_kwh"].sum()) if not no_solar_displayed_hourly_df.empty else 0.0
    no_solar_cop = no_solar_total_pac / no_solar_total_compressor if no_solar_total_compressor > 0 else 0.0
    same_metrics = _hourly_metrics_from_results(multiyear_results, annualization_years=multiyear_years)
    geo_only_metrics = (
        _hourly_metrics_from_results(no_solar_results, annualization_years=multiyear_years)
        if run_geo_only
        else None
    )
    full_case_metrics = _final_year_screening_metrics_from_results(
        multiyear_results,
        t_min_c=config.btes.t_min_c,
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        demand_bt_kwh=float(hourly_df["demand_bt_kwh"].sum()) if not hourly_df.empty else 0.0,
    )
    full_case_metrics["mean_cop"] = same_metrics["mean_cop"]
    full_case_metrics["mean_bt_pac_kwh"] = same_metrics["pac_heat_mwh"] * 1000.0
    no_solar_economic_metrics = geo_only_metrics if run_geo_only and run_reduced_borefield else None
    no_solar_reference_coverage = no_solar_total_pac / max(1e-9, float(no_solar_displayed_hourly_df["demand_bt_kwh"].sum())) if not no_solar_displayed_hourly_df.empty else 0.0
    no_solar_reference_limited_hours = (
        float(no_solar_displayed_hourly_df["Limite_temperature_source"].sum())
        if not no_solar_displayed_hourly_df.empty and "Limite_temperature_source" in no_solar_displayed_hourly_df
        else 0.0
    )

    _notify(progress, 70, "Calcul de l'économie équivalente de sondes...")
    if no_solar_economic_metrics is not None:
        try:
            savings = borefield_equivalent_savings(
                weather=weather,
                demands=demands,
                config=config,
                reference_final_cop=no_solar_cop,
                reference_final_bt_pac_kwh=no_solar_total_pac,
                reference_final_bt_coverage=no_solar_reference_coverage,
                reference_final_source_limited_hours=no_solar_reference_limited_hours,
                hourly_demand_override=hourly_demand_override,
                simulation_years=multiyear_years,
                search_mode=savings_search_mode if run_reduced_borefield else "none",
                full_case_metrics=full_case_metrics,
                simulation_cache=simulation_cache,
                include_hourly_df=False,
            )
        except Exception as exc:
            if simulation_cache is not None:
                simulation_cache.record_event(
                    "borefield_savings:error",
                    "Economie de sondes non determinee",
                    {
                        "Mode economie sondes": str(savings_search_mode),
                        "Erreur": f"{type(exc).__name__}: {exc}",
                        "Simulations lancees": 0,
                    },
                )
            savings = {
                "found": False,
                "saved_length_m": 0.0,
                "saved_fraction": 0.0,
                "equivalent_length_m": float(config.btes.boreholes) * float(config.btes.depth_m),
                "equivalent_boreholes": int(config.btes.boreholes),
                "equivalent_cop": same_metrics["mean_cop"],
                "equivalent_bt_pac_kwh": same_metrics["pac_heat_mwh"] * 1000.0,
                "savings_simulations_count": 0,
                "message": "Economie de sondes non determinee : le calcul expert a echoue.",
            }
    else:
        savings = {"found": False, "saved_length_m": 0.0, "equivalent_length_m": 0.0}
    _notify(progress, 85, "Calcul économique solaire thermique...")
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
    candidate_borefield_length_m = (
        float(savings.get("candidate_length_m", savings.get("equivalent_length_m", full_borefield_length_m)))
        if run_reduced_borefield and bool(savings.get("simulated", False))
        else full_borefield_length_m
    )
    economic_borefield_length_m = (
        float(savings["equivalent_length_m"]) if bool(savings["found"]) else full_borefield_length_m
    )
    reference_gas_power_kw = same_metrics["reference_gas_power_kw"]
    pac_power_kw = float(config.heat_pump.max_thermal_power_kw or 0.0)
    reference_heat_mwh = same_metrics["total_need_mwh"]

    candidate_hourly_df = savings.get("_candidate_hourly_df") if run_reduced_borefield else None
    equivalent_hourly_df = savings.get("_equivalent_hourly_df") if run_reduced_borefield else None
    exploratory_reduced_available = run_reduced_borefield and bool(savings.get("simulated", False))
    if run_reduced_borefield and (bool(savings["found"]) or exploratory_reduced_available):
        reduced_source_df = candidate_hourly_df if isinstance(candidate_hourly_df, pd.DataFrame) and not candidate_hourly_df.empty else equivalent_hourly_df
        if isinstance(reduced_source_df, pd.DataFrame) and not reduced_source_df.empty:
            _notify(progress, 88, "Reuse simulation multiannuelle avec sondes reduites...")
            reduced_results = []
            reduced_metrics = _hourly_metrics(reduced_source_df, annualization_years=multiyear_years)
        else:
            _notify(progress, 88, "Simulation multiannuelle avec sondes reduites...")
            borehole_key = "candidate_boreholes" if exploratory_reduced_available and not bool(savings["found"]) else "equivalent_boreholes"
            reduced_boreholes = max(1, int(round(float(savings.get(borehole_key, config.btes.boreholes)))))
            reduced_btes = replace(config.btes, boreholes=reduced_boreholes)
            reduced_config = replace(config, btes=reduced_btes)
            try:
                reduced_results = _simulate_hourly_cached(
                    weather=weather,
                    demands=demands,
                    config=reduced_config,
                    hourly_demand_override=hourly_demand_override,
                    simulation_years=multiyear_years,
                    simulation_cache=simulation_cache,
                    cache_mode="pygfunction",
                )
                reduced_metrics = _hourly_metrics_from_results(reduced_results, annualization_years=multiyear_years)
            except Exception as exc:
                if simulation_cache is not None:
                    simulation_cache.record_event(
                        "reduced_borefield:error",
                        "Simulation sondes reduites non disponible",
                        {
                            "Sondes": int(reduced_boreholes),
                            "Annees simulees": int(multiyear_years),
                            "Erreur": f"{type(exc).__name__}: {exc}",
                            "Simulations lancees": 0,
                        },
                    )
                savings = {
                    **savings,
                    "found": False,
                    "saved_length_m": 0.0,
                    "saved_fraction": 0.0,
                    "equivalent_length_m": full_borefield_length_m,
                    "equivalent_boreholes": int(config.btes.boreholes),
                    "message": "Economie de sondes non determinee : la simulation sondes reduites a echoue.",
                }
                reduced_results = []
                reduced_metrics = same_metrics
    else:
        reduced_results = []
        reduced_metrics = same_metrics

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

    same_trajectory_df = _annual_metrics_trajectory_from_results(
        multiyear_results,
        analysis_years=int(economics.analysis_years),
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        gmi_check_enabled=config.btes.gmi_check_enabled,
        pac_power_kw=float(config.heat_pump.max_thermal_power_kw or 0.0),
    )
    geo_only_trajectory_df = (
        _annual_metrics_trajectory_from_results(
            no_solar_results,
            analysis_years=int(economics.analysis_years),
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            gmi_check_enabled=config.btes.gmi_check_enabled,
            pac_power_kw=float(no_solar_config.heat_pump.max_thermal_power_kw or 0.0),
        )
        if run_geo_only
        else pd.DataFrame()
    )
    equivalent_hourly_df_for_trajectory = None
    if run_reduced_borefield:
        candidate_df_for_trajectory = savings.get("_candidate_hourly_df")
        equivalent_df_for_trajectory = savings.get("_equivalent_hourly_df")
        equivalent_hourly_df_for_trajectory = (
            candidate_df_for_trajectory
            if isinstance(candidate_df_for_trajectory, pd.DataFrame) and not candidate_df_for_trajectory.empty
            else equivalent_df_for_trajectory
        )
    if (
        run_reduced_borefield
        and (bool(savings["found"]) or bool(savings.get("simulated", False)))
        and isinstance(equivalent_hourly_df_for_trajectory, pd.DataFrame)
        and not equivalent_hourly_df_for_trajectory.empty
    ):
        reduced_multiyear_btes_df = _multiyear_btes_summary(
            equivalent_hourly_df_for_trajectory,
            t_min_c=config.btes.t_min_c,
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            gmi_check_enabled=config.btes.gmi_check_enabled,
        )
        reduced_trajectory_df = _annual_metrics_trajectory(
            equivalent_hourly_df_for_trajectory,
            analysis_years=int(economics.analysis_years),
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            gmi_check_enabled=config.btes.gmi_check_enabled,
        )
    elif run_reduced_borefield and (bool(savings["found"]) or bool(savings.get("simulated", False))) and reduced_results:
        reduced_multiyear_btes_df = _multiyear_btes_summary_from_results(
            reduced_results,
            t_min_c=config.btes.t_min_c,
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            gmi_check_enabled=config.btes.gmi_check_enabled,
        )
        reduced_trajectory_df = _annual_metrics_trajectory_from_results(
            reduced_results,
            analysis_years=int(economics.analysis_years),
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            gmi_check_enabled=config.btes.gmi_check_enabled,
            pac_power_kw=float(config.heat_pump.max_thermal_power_kw or 0.0),
        )
    else:
        reduced_multiyear_btes_df = pd.DataFrame()
        reduced_trajectory_df = same_trajectory_df.copy()
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
                borefield_length_m=candidate_borefield_length_m if bool(savings.get("simulated", False)) else economic_borefield_length_m,
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
        economic_comparison_df.loc[index, "P1 cumule (EUR)"] = costs["p1_cumulative_eur"]
        economic_comparison_df.loc[index, "P2 cumule (EUR)"] = costs["p2_cumulative_eur"]
        economic_comparison_df.loc[index, "P4 cumule (EUR)"] = costs["p4_cumulative_eur"]
        economic_comparison_df.loc[index, "Appoint gaz cumule (MWh)"] = costs["backup_gas_cumulative_mwh"]
        economic_comparison_df.loc[index, "Electricite PAC cumulee (MWh)"] = costs["pac_electricity_cumulative_mwh"]
        trajectory = economic_trajectory_df[economic_trajectory_df["Scenario"] == scenario_name]
        if not trajectory.empty:
            final_row = trajectory.sort_values("Annee").iloc[-1]
            economic_comparison_df.loc[index, "COP annee finale"] = float(final_row.get("COP moyen", 0.0))
            economic_comparison_df.loc[index, "Couverture PAC BT annee finale (%)"] = float(final_row.get("Couverture PAC BT (%)", 0.0))
            economic_comparison_df.loc[index, "Appoint gaz annee finale (MWh)"] = float(final_row.get("Appoint gaz total (MWh)", 0.0))
            economic_comparison_df.loc[index, "T source min annee finale (C)"] = float(final_row.get("T_source_PAC_min (C)", 0.0))
            economic_comparison_df.loc[index, "Heures limite source annee finale"] = float(final_row.get("Heures limite source", 0.0))
            economic_comparison_df.loc[index, "Conformite GMI annee finale"] = bool(final_row.get("Conformite GMI", True))
            economic_comparison_df.loc[index, "Heures hors GMI annee finale"] = (
                float(final_row.get("Heures sous Tmin GMI", 0.0)) + float(final_row.get("Heures sur Tmax GMI", 0.0))
            )
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
    solar_parametric_reference = {
        "surface_m2": float(config.collector.area_m2),
        "boreholes": int(config.btes.boreholes),
        "depth_m": float(config.btes.depth_m),
        "simulation_years": int(economics.analysis_years),
        "metrics": dict(same_metrics),
        "full_case_metrics": dict(full_case_metrics),
        "trajectory_df": same_trajectory_df.copy(),
    }
    btes_diagnostics = btes_load_diagnostics_from_results(
        multiyear_results,
        simulation_years=multiyear_years,
        depth_m=float(config.btes.depth_m),
        spacing_m=float(config.btes.spacing_m),
        surface_insulation_considered=bool(config.btes.surface_insulation_considered),
    )
    del multiyear_results
    del no_solar_results
    del reduced_results
    gc.collect()
    public_savings = {
        key: value
        for key, value in savings.items()
        if not str(key).startswith("_")
    }

    result = ScenarioResult(
        config=config,
        hourly_df=hourly_df,
        no_solar_hourly_df=no_solar_hourly_df,
        multiyear_btes_df=multiyear_btes_df,
        no_solar_multiyear_btes_df=no_solar_multiyear_btes_df,
        reduced_multiyear_btes_df=reduced_multiyear_btes_df,
        annual_df=annual_df,
        hourly_by_month_df=hourly_by_month_df,
        savings=public_savings,
        solar_economics=solar_economics,
        heat_costs=heat_costs,
        economic_comparison_df=economic_comparison_df,
        economic_comparison_chart_df=economic_comparison_chart_df,
        economic_trajectory_df=economic_trajectory_df,
        solar_parametric_reference=solar_parametric_reference,
        recharge_value=recharge_value,
        solar_allocation=solar_allocation,
        total_ht_kwh=total_ht,
        total_bt_kwh=total_bt,
        total_preheat_ht_kwh=total_preheat_ht,
        total_charge_buffer_kwh=total_charge_buffer,
        total_to_btes_kwh=total_to_btes,
        total_solar_valued_kwh=total_solar_valued,
        solar_productivity_valued_kwh_m2_year=solar_productivity_valued,
        solar_ht_from_buffer_economic_mwh=solar_ht_from_buffer_economic_mwh,
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
        simulation_year_displayed=simulation_year_displayed,
        simulation_years_total=multiyear_years,
        economic_years_used=int(economics.analysis_years),
        gmi_check_enabled=bool(config.btes.gmi_check_enabled),
        btes_diagnostics=btes_diagnostics,
    )
    if simulation_cache is not None:
        simulation_cache.clear_entries(reason="Nettoyage memoire apres scenario principal")
    gc.collect()
    return result



