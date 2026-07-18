from __future__ import annotations

import time

import pandas as pd

from .engine import MonthlyDemand, SimulationConfig
from .hourly_engine import HourlyResult, HourlyWeather, simulate_hourly
from .simulation_cache import SimulationCache


def _new_compact_stats() -> dict[str, float]:
    return {
        "count": 0.0,
        "demand_ht_kwh": 0.0,
        "demand_bt_kwh": 0.0,
        "unmet_ht_kwh": 0.0,
        "unmet_bt_kwh": 0.0,
        "heat_bt_from_pac_kwh": 0.0,
        "electricity_compressor_kwh": 0.0,
        "electricity_pac_total_kwh": 0.0,
        "electricity_system_total_kwh": 0.0,
        "solar_ht_from_buffer_kwh": 0.0,
        "solar_to_btes_kwh": 0.0,
        "btes_extracted_by_pac_kwh": 0.0,
        "source_temp_unmet_bt_kwh": 0.0,
        "backup_power_kw": 0.0,
        "reference_gas_power_kw": 0.0,
        "t_source_pac_min_c": float("inf"),
        "t_source_pac_for_cop_min_c": float("inf"),
        "t_source_pac_sum_c": 0.0,
        "t_fluide_injection_max_c": float("-inf"),
        "q_extraction_max_w_m": 0.0,
        "q_injection_max_w_m": 0.0,
        "source_limited_hours": 0.0,
        "hours_under_tmin": 0.0,
        "hours_under_gmi_tmin": 0.0,
        "hours_over_gmi_tmax": 0.0,
    }


def _update_compact_stats(
    stats: dict[str, float],
    row: HourlyResult,
    *,
    t_min_c: float,
    gmi_t_min_c: float,
    gmi_t_max_c: float,
) -> None:
    stats["count"] += 1.0
    stats["demand_ht_kwh"] += float(row.demand_ht_kwh)
    stats["demand_bt_kwh"] += float(row.demand_bt_kwh)
    stats["unmet_ht_kwh"] += float(row.unmet_ht_kwh)
    stats["unmet_bt_kwh"] += float(row.unmet_bt_kwh)
    stats["heat_bt_from_pac_kwh"] += float(row.heat_bt_from_pac_kwh)
    stats["electricity_compressor_kwh"] += float(row.electricity_compressor_kwh)
    stats["electricity_pac_total_kwh"] += float(row.electricity_pac_total_kwh)
    stats["electricity_system_total_kwh"] += float(row.electricity_system_total_kwh)
    stats["solar_ht_from_buffer_kwh"] += float(row.solar_ht_from_buffer_kwh)
    stats["solar_to_btes_kwh"] += float(row.solar_to_btes_kwh)
    stats["btes_extracted_by_pac_kwh"] += float(row.btes_extracted_by_pac_kwh)
    stats["source_temp_unmet_bt_kwh"] += float(row.source_temp_unmet_bt_kwh)
    stats["backup_power_kw"] = max(
        stats["backup_power_kw"],
        max(0.0, float(row.unmet_ht_kwh)) + max(0.0, float(row.unmet_bt_kwh)),
    )
    stats["reference_gas_power_kw"] = max(
        stats["reference_gas_power_kw"],
        max(0.0, float(row.demand_ht_kwh)) + max(0.0, float(row.demand_bt_kwh)),
    )
    stats["t_source_pac_min_c"] = min(stats["t_source_pac_min_c"], float(row.t_source_pac_c))
    stats["t_source_pac_for_cop_min_c"] = min(
        stats["t_source_pac_for_cop_min_c"],
        float(row.t_source_pac_for_cop_c),
    )
    stats["t_source_pac_sum_c"] += float(row.t_source_pac_c)
    stats["t_fluide_injection_max_c"] = max(stats["t_fluide_injection_max_c"], float(row.t_fluide_injection_c))
    stats["q_extraction_max_w_m"] = max(stats["q_extraction_max_w_m"], float(row.q_extraction_w_m))
    stats["q_injection_max_w_m"] = max(stats["q_injection_max_w_m"], float(row.q_injection_w_m))
    if row.source_temp_limited:
        stats["source_limited_hours"] += 1.0
    if float(row.t_source_pac_c) < t_min_c - 1e-6:
        stats["hours_under_tmin"] += 1.0
    if float(row.t_fluide_entree_echangeur_geo_c) < gmi_t_min_c - 1e-6:
        stats["hours_under_gmi_tmin"] += 1.0
    if float(row.t_fluide_injection_c) > gmi_t_max_c + 1e-6:
        stats["hours_over_gmi_tmax"] += 1.0


def _safe_min_stat(stats: dict[str, float], key: str) -> float:
    value = float(stats.get(key, 0.0))
    return 0.0 if value == float("inf") else value


def _safe_max_stat(stats: dict[str, float], key: str) -> float:
    value = float(stats.get(key, 0.0))
    return 0.0 if value == float("-inf") else value


def _compact_metrics_from_stats(stats: dict[str, float], *, annualization_years: int) -> dict[str, float]:
    years = max(1, int(annualization_years))
    total_ht = float(stats["demand_ht_kwh"])
    total_bt = float(stats["demand_bt_kwh"])
    total_backup_ht = float(stats["unmet_ht_kwh"])
    total_backup_bt = float(stats["unmet_bt_kwh"])
    total_pac = float(stats["heat_bt_from_pac_kwh"])
    total_compressor = float(stats["electricity_compressor_kwh"])
    total_elec = float(stats["electricity_pac_total_kwh"])
    total_system_elec = float(stats["electricity_system_total_kwh"])
    total_solar_ht = float(stats["solar_ht_from_buffer_kwh"])
    total_solar_btes = float(stats["solar_to_btes_kwh"])
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
        "backup_power_kw": float(stats["backup_power_kw"]),
        "reference_gas_power_kw": float(stats["reference_gas_power_kw"]),
        "t_source_pac_min_c": _safe_min_stat(stats, "t_source_pac_min_c"),
        "t_source_pac_mean_c": float(stats["t_source_pac_sum_c"]) / max(1.0, float(stats["count"])),
        "q_extraction_max_w_m": float(stats["q_extraction_max_w_m"]),
        "q_injection_max_w_m": float(stats["q_injection_max_w_m"]),
        "source_limited_hours": float(stats["source_limited_hours"]),
        "source_limited_unmet_mwh": float(stats["source_temp_unmet_bt_kwh"]) / 1000.0,
    }


def _compact_final_year_metrics(
    stats: dict[str, float],
    *,
    final_year: int,
) -> dict[str, float]:
    heat_pac_kwh = float(stats["heat_bt_from_pac_kwh"])
    compressor_kwh = float(stats["electricity_compressor_kwh"])
    demand_bt = max(1e-9, float(stats["demand_bt_kwh"]))
    return {
        "final_year": float(final_year),
        "final_cop": heat_pac_kwh / compressor_kwh if compressor_kwh > 0.0 else 0.0,
        "final_bt_pac_kwh": heat_pac_kwh,
        "final_bt_coverage": heat_pac_kwh / demand_bt,
        "final_t_source_min_c": _safe_min_stat(stats, "t_source_pac_min_c"),
        "final_hours_under_tmin": float(stats["hours_under_tmin"]),
        "final_hours_under_gmi_tmin": float(stats["hours_under_gmi_tmin"]),
        "final_hours_over_gmi_tmax": float(stats["hours_over_gmi_tmax"]),
        "final_source_limited_hours": float(stats["source_limited_hours"]),
        "final_q_extraction_max_w_m": float(stats["q_extraction_max_w_m"]),
        "final_q_injection_max_w_m": float(stats["q_injection_max_w_m"]),
        "final_extracted_ground_kwh": float(stats["btes_extracted_by_pac_kwh"]),
        "final_injected_btes_kwh": float(stats["solar_to_btes_kwh"]),
    }


def _compact_trajectory_from_year_stats(
    year_stats: dict[int, dict[str, float]],
    *,
    analysis_years: int,
    gmi_check_enabled: bool,
    pac_power_kw: float = 0.0,
) -> pd.DataFrame:
    years = max(1, int(analysis_years))
    last_group = year_stats[max(year_stats)] if year_stats else _new_compact_stats()
    rows: list[dict[str, float | int | bool]] = []
    for year in range(1, years + 1):
        group = year_stats.get(year, last_group)
        heat_pac = float(group["heat_bt_from_pac_kwh"])
        elec_comp = float(group["electricity_compressor_kwh"])
        total_ht = float(group["demand_ht_kwh"])
        total_bt = float(group["demand_bt_kwh"])
        backup_ht = float(group["unmet_ht_kwh"])
        backup_bt = float(group["unmet_bt_kwh"])
        elec_total = float(group["electricity_pac_total_kwh"])
        solar_ht = float(group["solar_ht_from_buffer_kwh"])
        non_ren = backup_ht + backup_bt + elec_total
        useful = total_ht + total_bt
        equivalent_power = pac_power_kw if pac_power_kw > 0.0 else heat_pac
        rows.append(
            {
                "Annee": year,
                "E utile HT (MWh)": total_ht / 1000.0,
                "E utile BT (MWh)": total_bt / 1000.0,
                "E utile totale (MWh)": useful / 1000.0,
                "Solaire HT (MWh)": solar_ht / 1000.0,
                "Injection solaire BTES (MWh)": float(group["solar_to_btes_kwh"]) / 1000.0,
                "Chaleur PAC BT (MWh)": heat_pac / 1000.0,
                "Appoint gaz HT (MWh)": backup_ht / 1000.0,
                "Appoint gaz BT (MWh)": backup_bt / 1000.0,
                "Appoint gaz total (MWh)": (backup_ht + backup_bt) / 1000.0,
                "Electricite PAC (MWh)": elec_total / 1000.0,
                "COP moyen": heat_pac / elec_comp if elec_comp > 0.0 else 0.0,
                "SPF PAC complet": heat_pac / elec_total if elec_total > 0.0 else 0.0,
                "Couverture PAC BT (%)": heat_pac / max(1e-9, total_bt) * 100.0,
                "Heures equivalentes PAC BT": heat_pac / max(1e-9, equivalent_power),
                "T_source_PAC_min (C)": _safe_min_stat(group, "t_source_pac_min_c"),
                "T_source_PAC_pour_COP_min (C)": _safe_min_stat(group, "t_source_pac_for_cop_min_c"),
                "T_fluide_injection_max (C)": _safe_max_stat(group, "t_fluide_injection_max_c"),
                "Heures sous Tmin GMI": int(group["hours_under_gmi_tmin"]),
                "Heures sur Tmax GMI": int(group["hours_over_gmi_tmax"]),
                "Conformite GMI": bool(
                    (not gmi_check_enabled)
                    or (group["hours_under_gmi_tmin"] <= 0.0 and group["hours_over_gmi_tmax"] <= 0.0)
                ),
                "Heures limite source": int(group["source_limited_hours"]),
                "BT non couvert limite source (MWh)": float(group["source_temp_unmet_bt_kwh"]) / 1000.0,
                "T_source_PAC_moy (C)": float(group["t_source_pac_sum_c"]) / max(1.0, float(group["count"])),
                "q_extraction_W_m_max": float(group["q_extraction_max_w_m"]),
                "q_injection_W_m_max": float(group["q_injection_max_w_m"]),
                "Taux EnR (%)": max(0.0, min(1.0, 1.0 - non_ren / max(1e-9, useful))) * 100.0,
            }
        )
    return pd.DataFrame(rows)


def _simulate_hourly_compact(
    *,
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    simulation_years: int,
    simulation_cache: SimulationCache | None,
    cache_mode: str,
) -> tuple[dict[str, float], dict[str, float], pd.DataFrame]:
    """Simulate and aggregate without storing the full hourly result list.

    The returned tuple contains total compact metrics, final-year metrics and
    an annual trajectory DataFrame. This path is intended for parametric loops
    and borefield checks where retaining every `HourlyResult` would be too
    heavy.
    """

    total_stats = _new_compact_stats()
    year_stats: dict[int, dict[str, float]] = {}

    def collect(row: HourlyResult) -> None:
        _update_compact_stats(
            total_stats,
            row,
            t_min_c=config.btes.t_min_c,
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
        )
        stats = year_stats.setdefault(int(row.simulation_year), _new_compact_stats())
        _update_compact_stats(
            stats,
            row,
            t_min_c=config.btes.t_min_c,
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
        )

    started_at = time.perf_counter()
    results = simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=hourly_demand_override,
        simulation_years=simulation_years,
        result_sink=collect,
        store_results=False,
    )
    elapsed = time.perf_counter() - started_at
    if simulation_cache is not None:
        simulation_cache.record_event(
            "simulate:pygfunction_compact",
            f"Simulation pygfunction compacte calculee ({cache_mode})",
            {
                "Mode simulation": str(cache_mode),
                "Annees simulees": int(simulation_years),
                "Pas meteo": int(len(weather)),
                "Heures simulees": int(len(weather) * max(1, int(simulation_years))),
                "Surface solaire (m2)": float(config.collector.area_m2),
                "Sondes": int(config.btes.boreholes),
                "Lineaire sondes (ml)": float(config.btes.boreholes) * float(config.btes.depth_m),
                "Lignes horaires conservees": int(len(results)),
                "Simulations lancees": 1,
                "Duree pygfunction (s)": elapsed,
            },
        )
    final_year = max(year_stats) if year_stats else 1
    final_stats = year_stats.get(final_year, _new_compact_stats())
    economic_metrics = _compact_metrics_from_stats(total_stats, annualization_years=simulation_years)
    final_metrics = _compact_final_year_metrics(final_stats, final_year=final_year)
    final_metrics["mean_cop"] = economic_metrics["mean_cop"]
    final_metrics["mean_bt_pac_kwh"] = economic_metrics["pac_heat_mwh"] * 1000.0
    trajectory_df = _compact_trajectory_from_year_stats(
        year_stats,
        analysis_years=simulation_years,
        gmi_check_enabled=config.btes.gmi_check_enabled,
        pac_power_kw=float(config.heat_pump.max_thermal_power_kw or 0.0),
    )
    return economic_metrics, final_metrics, trajectory_df
