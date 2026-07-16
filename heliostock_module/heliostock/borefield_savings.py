from __future__ import annotations

import math
import time
from dataclasses import replace

import pandas as pd

from .engine import MonthlyDemand, SimulationConfig
from .hourly_engine import HourlyResult, HourlyWeather, simulate_hourly
from .postprocess import _hourly_results_to_dataframe, _mean_cop
from .simulation_cache import SimulationCache


def _final_year_screening_metrics(
    df: pd.DataFrame,
    *,
    t_min_c: float,
    gmi_t_min_c: float,
    gmi_t_max_c: float,
    demand_bt_kwh: float,
) -> dict[str, float]:
    final_year = int(df["simulation_year"].max()) if "simulation_year" in df and not df.empty else 1
    final_df = df[df["simulation_year"] == final_year].copy() if "simulation_year" in df else df
    heat_pac_kwh = float(final_df["heat_bt_from_pac_kwh"].sum())
    compressor_kwh = float(final_df["electricity_compressor_kwh"].sum())
    demand_bt = max(1e-9, float(final_df["demand_bt_kwh"].sum()) if not final_df.empty else demand_bt_kwh)
    return {
        "final_year": float(final_year),
        "final_cop": heat_pac_kwh / compressor_kwh if compressor_kwh > 0.0 else 0.0,
        "final_bt_pac_kwh": heat_pac_kwh,
        "final_bt_coverage": heat_pac_kwh / demand_bt,
        "final_t_source_min_c": float(final_df["T_source_PAC_C"].min()) if "T_source_PAC_C" in final_df else 0.0,
        "final_hours_under_tmin": float((final_df["T_source_PAC_C"] < t_min_c - 1e-6).sum()) if "T_source_PAC_C" in final_df else 0.0,
        "final_hours_under_gmi_tmin": (
            float((final_df["T_fluide_entree_echangeur_geo_C"] < gmi_t_min_c - 1e-6).sum())
            if "T_fluide_entree_echangeur_geo_C" in final_df
            else 0.0
        ),
        "final_hours_over_gmi_tmax": (
            float((final_df["T_fluide_injection_C"] > gmi_t_max_c + 1e-6).sum())
            if "T_fluide_injection_C" in final_df
            else 0.0
        ),
        "final_source_limited_hours": (
            float(final_df["Limite_temperature_source"].sum()) if "Limite_temperature_source" in final_df else 0.0
        ),
        "final_q_extraction_max_w_m": float(final_df["q_extraction_W_m"].max()) if "q_extraction_W_m" in final_df else 0.0,
        "final_q_injection_max_w_m": float(final_df["q_injection_W_m"].max()) if "q_injection_W_m" in final_df else 0.0,
        "final_extracted_ground_kwh": float(final_df["btes_extracted_by_pac_kwh"].sum())
        if "btes_extracted_by_pac_kwh" in final_df
        else 0.0,
        "final_injected_btes_kwh": float(final_df["solar_to_btes_kwh"].sum())
        if "solar_to_btes_kwh" in final_df
        else 0.0,
        "mean_pac_electricity_kwh": float(df["electricity_pac_total_kwh"].sum()) / max(1, int(final_year))
        if "electricity_pac_total_kwh" in df
        else 0.0,
        "mean_backup_total_kwh": float((df["unmet_ht_kwh"] + df["unmet_bt_kwh"]).sum()) / max(1, int(final_year))
        if {"unmet_ht_kwh", "unmet_bt_kwh"}.issubset(df.columns)
        else 0.0,
    }


def _mean_metrics(df: pd.DataFrame, years: int) -> tuple[float, float]:
    return _mean_cop(df), float(df["heat_bt_from_pac_kwh"].sum()) / max(1, int(years))


def _final_year_screening_metrics_from_results(
    results: list[HourlyResult] | tuple[HourlyResult, ...],
    *,
    t_min_c: float,
    gmi_t_min_c: float,
    gmi_t_max_c: float,
    demand_bt_kwh: float,
) -> dict[str, float]:
    if not results:
        return {
            "final_year": 1.0,
            "final_cop": 0.0,
            "final_bt_pac_kwh": 0.0,
            "final_bt_coverage": 0.0,
            "final_t_source_min_c": 0.0,
            "final_hours_under_tmin": 0.0,
            "final_hours_under_gmi_tmin": 0.0,
            "final_hours_over_gmi_tmax": 0.0,
            "final_source_limited_hours": 0.0,
            "final_q_extraction_max_w_m": 0.0,
            "final_q_injection_max_w_m": 0.0,
            "final_extracted_ground_kwh": 0.0,
            "final_injected_btes_kwh": 0.0,
            "mean_pac_electricity_kwh": 0.0,
            "mean_backup_total_kwh": 0.0,
        }

    final_year = max(int(result.simulation_year) for result in results)
    final_results = [result for result in results if int(result.simulation_year) == final_year]
    heat_pac_kwh = sum(float(result.heat_bt_from_pac_kwh) for result in final_results)
    compressor_kwh = sum(float(result.electricity_compressor_kwh) for result in final_results)
    demand_bt = sum(float(result.demand_bt_kwh) for result in final_results)
    demand_bt = max(1e-9, demand_bt if final_results else float(demand_bt_kwh))
    return {
        "final_year": float(final_year),
        "final_cop": heat_pac_kwh / compressor_kwh if compressor_kwh > 0.0 else 0.0,
        "final_bt_pac_kwh": heat_pac_kwh,
        "final_bt_coverage": heat_pac_kwh / demand_bt,
        "final_t_source_min_c": min(float(result.t_source_pac_c) for result in final_results),
        "final_hours_under_tmin": float(
            sum(1 for result in final_results if float(result.t_source_pac_c) < t_min_c - 1e-6)
        ),
        "final_hours_under_gmi_tmin": float(
            sum(
                1
                for result in final_results
                if float(result.t_fluide_entree_echangeur_geo_c) < gmi_t_min_c - 1e-6
            )
        ),
        "final_hours_over_gmi_tmax": float(
            sum(1 for result in final_results if float(result.t_fluide_injection_c) > gmi_t_max_c + 1e-6)
        ),
        "final_source_limited_hours": float(sum(1 for result in final_results if result.source_temp_limited)),
        "final_q_extraction_max_w_m": max(float(result.q_extraction_w_m) for result in final_results),
        "final_q_injection_max_w_m": max(float(result.q_injection_w_m) for result in final_results),
        "final_extracted_ground_kwh": sum(float(result.btes_extracted_by_pac_kwh) for result in final_results),
        "final_injected_btes_kwh": sum(float(result.solar_to_btes_kwh) for result in final_results),
        "mean_pac_electricity_kwh": sum(float(result.electricity_pac_total_kwh) for result in results)
        / max(1, int(final_year)),
        "mean_backup_total_kwh": sum(float(result.unmet_ht_kwh) + float(result.unmet_bt_kwh) for result in results)
        / max(1, int(final_year)),
    }


def _mean_metrics_from_results(
    results: list[HourlyResult] | tuple[HourlyResult, ...],
    years: int,
) -> tuple[float, float]:
    total_heat = sum(float(result.heat_bt_from_pac_kwh) for result in results)
    total_compressor = sum(float(result.electricity_compressor_kwh) for result in results)
    return (
        total_heat / total_compressor if total_compressor > 0.0 else 0.0,
        total_heat / max(1, int(years)),
    )


def _empty_compact_candidate_stats() -> dict[str, float | dict[int, dict[str, float]]]:
    return {"total_heat": 0.0, "total_compressor": 0.0, "total_pac_electricity": 0.0, "total_backup": 0.0, "years": {}}


def _update_compact_candidate_stats(
    stats: dict[str, float | dict[int, dict[str, float]]],
    result: HourlyResult,
    *,
    t_min_c: float,
    gmi_t_min_c: float,
    gmi_t_max_c: float,
) -> None:
    stats["total_heat"] = float(stats["total_heat"]) + float(result.heat_bt_from_pac_kwh)
    stats["total_compressor"] = float(stats["total_compressor"]) + float(result.electricity_compressor_kwh)
    stats["total_pac_electricity"] = float(stats["total_pac_electricity"]) + float(result.electricity_pac_total_kwh)
    stats["total_backup"] = float(stats["total_backup"]) + float(result.unmet_ht_kwh) + float(result.unmet_bt_kwh)
    years = stats["years"]
    assert isinstance(years, dict)
    year_stats = years.setdefault(
        int(result.simulation_year),
        {
            "heat_pac_kwh": 0.0,
            "compressor_kwh": 0.0,
            "demand_bt_kwh": 0.0,
            "t_source_min_c": math.inf,
            "hours_under_tmin": 0.0,
            "hours_under_gmi_tmin": 0.0,
            "hours_over_gmi_tmax": 0.0,
            "source_limited_hours": 0.0,
            "q_extraction_max_w_m": 0.0,
            "q_injection_max_w_m": 0.0,
            "extracted_ground_kwh": 0.0,
            "injected_btes_kwh": 0.0,
        },
    )
    year_stats["heat_pac_kwh"] += float(result.heat_bt_from_pac_kwh)
    year_stats["compressor_kwh"] += float(result.electricity_compressor_kwh)
    year_stats["demand_bt_kwh"] += float(result.demand_bt_kwh)
    year_stats["t_source_min_c"] = min(float(year_stats["t_source_min_c"]), float(result.t_source_pac_c))
    year_stats["hours_under_tmin"] += 1.0 if float(result.t_source_pac_c) < t_min_c - 1e-6 else 0.0
    year_stats["hours_under_gmi_tmin"] += (
        1.0 if float(result.t_fluide_entree_echangeur_geo_c) < gmi_t_min_c - 1e-6 else 0.0
    )
    year_stats["hours_over_gmi_tmax"] += 1.0 if float(result.t_fluide_injection_c) > gmi_t_max_c + 1e-6 else 0.0
    year_stats["source_limited_hours"] += 1.0 if result.source_temp_limited else 0.0
    year_stats["q_extraction_max_w_m"] = max(float(year_stats["q_extraction_max_w_m"]), float(result.q_extraction_w_m))
    year_stats["q_injection_max_w_m"] = max(float(year_stats["q_injection_max_w_m"]), float(result.q_injection_w_m))
    year_stats["extracted_ground_kwh"] += float(result.btes_extracted_by_pac_kwh)
    year_stats["injected_btes_kwh"] += float(result.solar_to_btes_kwh)


def _compact_candidate_metrics(
    stats: dict[str, float | dict[int, dict[str, float]]],
    *,
    years_count: int,
    t_min_c: float,
    gmi_t_min_c: float,
    gmi_t_max_c: float,
    depth_m: float,
) -> tuple[float, float, dict[str, float]]:
    total_heat = float(stats["total_heat"])
    total_compressor = float(stats["total_compressor"])
    years = stats["years"]
    assert isinstance(years, dict)
    final_year = max(years.keys(), default=1)
    final = years.get(final_year, {})
    final_t_source_min = float(final.get("t_source_min_c", 0.0))
    if math.isinf(final_t_source_min):
        final_t_source_min = 0.0
    final_metrics = {
        "final_year": float(final_year),
        "final_cop": float(final.get("heat_pac_kwh", 0.0)) / float(final.get("compressor_kwh", 1e-9))
        if float(final.get("compressor_kwh", 0.0)) > 0.0
        else 0.0,
        "final_bt_pac_kwh": float(final.get("heat_pac_kwh", 0.0)),
        "final_bt_coverage": float(final.get("heat_pac_kwh", 0.0)) / max(1e-9, float(final.get("demand_bt_kwh", 0.0))),
        "final_t_source_min_c": final_t_source_min,
        "final_hours_under_tmin": float(final.get("hours_under_tmin", 0.0)),
        "final_hours_under_gmi_tmin": float(final.get("hours_under_gmi_tmin", 0.0)),
        "final_hours_over_gmi_tmax": float(final.get("hours_over_gmi_tmax", 0.0)),
        "final_source_limited_hours": float(final.get("source_limited_hours", 0.0)),
        "final_q_extraction_max_w_m": float(final.get("q_extraction_max_w_m", 0.0)),
        "final_q_injection_max_w_m": float(final.get("q_injection_max_w_m", 0.0)),
        "final_extracted_ground_kwh": float(final.get("extracted_ground_kwh", 0.0)),
        "final_injected_btes_kwh": float(final.get("injected_btes_kwh", 0.0)),
        "mean_pac_electricity_kwh": float(stats.get("total_pac_electricity", 0.0)) / max(1, int(years_count)),
        "mean_backup_total_kwh": float(stats.get("total_backup", 0.0)) / max(1, int(years_count)),
        "depth_m": float(depth_m),
    }
    return (
        total_heat / total_compressor if total_compressor > 0.0 else 0.0,
        total_heat / max(1, int(years_count)),
        final_metrics,
    )


def _selected_results_to_dataframe(
    results: list[HourlyResult] | tuple[HourlyResult, ...] | None,
    *,
    simulation_cache: SimulationCache | None,
    years: int,
    weather_len: int,
) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    started_at = time.perf_counter()
    df = _hourly_results_to_dataframe(results)
    elapsed = time.perf_counter() - started_at
    if simulation_cache is not None:
        simulation_cache.record_event(
            "postprocess:dataframe",
            "Conversion du candidat valide en DataFrame (economie sondes)",
            {
                "Mode simulation": "borefield_savings",
                "Annees simulees": int(years),
                "Pas meteo": int(weather_len),
                "Heures simulees": int(len(results)),
                "Lignes DataFrame": int(len(df)),
                "Duree dataframe (s)": elapsed,
            },
        )
    return df


def _base_return(
    *,
    found: bool,
    base_length_m: float,
    boreholes: int,
    equivalent_cop: float,
    equivalent_bt_pac_kwh: float,
    final_metrics: dict[str, float],
    estimated_length_m: float | None,
    simulations_count: int,
    hourly_df: pd.DataFrame | None = None,
) -> dict[str, float | bool | str | pd.DataFrame]:
    candidate_length = max(0.0, float(boreholes) * float(final_metrics.get("depth_m", 0.0)))
    if candidate_length <= 0.0:
        candidate_length = base_length_m if not found else 0.0
    candidate_saved_length = max(0.0, base_length_m - candidate_length)
    real_savings = bool(found) and candidate_saved_length > 1e-6 and candidate_length < base_length_m - 1e-6
    equivalent_length = candidate_length
    saved_length = candidate_saved_length if real_savings else 0.0
    if not real_savings:
        saved_length = 0.0
        equivalent_length = base_length_m
        boreholes = int(round(base_length_m / max(1e-9, float(final_metrics.get("depth_m", 0.0))))) if base_length_m > 0.0 else boreholes
    result: dict[str, float | bool | str | pd.DataFrame] = {
        "found": real_savings,
        "simulated": bool(candidate_length < base_length_m - 1e-6),
        "validated": real_savings,
        "scale": equivalent_length / max(1e-9, base_length_m),
        "reference_length_m": base_length_m,
        "candidate_length_m": candidate_length,
        "candidate_boreholes": int(round(candidate_length / max(1e-9, float(final_metrics.get("depth_m", 0.0))))) if candidate_length > 0.0 else int(boreholes),
        "candidate_saved_length_m": candidate_saved_length,
        "candidate_saved_fraction": candidate_saved_length / max(1e-9, base_length_m),
        "estimated_length_m": float(estimated_length_m if estimated_length_m is not None else equivalent_length),
        "verified_length_m": equivalent_length,
        "equivalent_length_m": equivalent_length,
        "equivalent_boreholes": int(boreholes),
        "saved_length_m": saved_length,
        "saved_fraction": saved_length / max(1e-9, base_length_m),
        "message": "Reduction de sondes validee" if real_savings else "Aucune réduction de sondes validée",
        "equivalent_cop": equivalent_cop,
        "equivalent_bt_pac_kwh": equivalent_bt_pac_kwh,
        "savings_simulations_count": int(simulations_count),
        **{f"candidate_{key}": value for key, value in final_metrics.items() if key != "depth_m"},
        **{f"equivalent_{key}": value for key, value in final_metrics.items() if key != "depth_m"},
    }
    if hourly_df is not None and not hourly_df.empty:
        result["_equivalent_hourly_df"] = hourly_df
        result["_candidate_hourly_df"] = hourly_df
    return result


def borefield_equivalent_savings(
    *,
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    reference_final_cop: float,
    reference_final_bt_pac_kwh: float,
    reference_final_bt_coverage: float,
    reference_final_source_limited_hours: float,
    hourly_demand_override: dict[int, tuple[float, float]] | None = None,
    simulation_years: int = 1,
    min_scale: float = 0.05,
    iterations: int = 8,
    search_mode: str = "expert",
    full_case_df: pd.DataFrame | None = None,
    full_case_metrics: dict[str, float] | None = None,
    recharge_credit: float = 0.6,
    reduced_borefield_safety_factor: float = 1.10,
    simulation_cache: SimulationCache | None = None,
    include_hourly_df: bool = True,
) -> dict[str, float | bool | str | pd.DataFrame]:
    """Estimate equivalent borefield length saving with solar recharge.

    The search varies the actual number of boreholes and reruns the hourly
    pygfunction backend. It is still a screening indicator, not a detailed
    borefield design, but it only varies pygfunction borefield geometry.
    """

    tolerance_bt = max(1.0, 0.001 * reference_final_bt_pac_kwh)
    base_length_m = max(0.0, config.btes.boreholes * config.btes.depth_m)
    years = max(1, int(simulation_years))
    simulations_count = 0
    mode = str(search_mode or "expert").lower()

    def run(scale: float) -> tuple[list[HourlyResult] | None, float, float, int, dict[str, float]]:
        nonlocal simulations_count
        boreholes = max(1, int(round(config.btes.boreholes * scale)))
        scaled_btes = replace(config.btes, boreholes=boreholes)
        scaled_config = replace(config, btes=scaled_btes)
        simulations_count += 1
        if include_hourly_df:
            results = (
                simulation_cache.simulate(
                    weather,
                    demands,
                    scaled_config,
                    hourly_demand_override=hourly_demand_override,
                    simulation_years=years,
                    mode="pygfunction",
                )
                if simulation_cache is not None
                else simulate_hourly(
                    weather,
                    demands,
                    scaled_config,
                    hourly_demand_override=hourly_demand_override,
                    simulation_years=years,
                )
            )
            cop, bt_pac = _mean_metrics_from_results(results, years)
            final_metrics = _final_year_screening_metrics_from_results(
                results,
                t_min_c=config.btes.t_min_c,
                gmi_t_min_c=config.btes.gmi_t_min_c,
                gmi_t_max_c=config.btes.gmi_t_max_c,
                demand_bt_kwh=sum(max(0.0, bt) for _, bt in (hourly_demand_override or {}).values()),
            )
        else:
            stats = _empty_compact_candidate_stats()

            def collect(result: HourlyResult) -> None:
                _update_compact_candidate_stats(
                    stats,
                    result,
                    t_min_c=config.btes.t_min_c,
                    gmi_t_min_c=config.btes.gmi_t_min_c,
                    gmi_t_max_c=config.btes.gmi_t_max_c,
                )

            simulate_hourly(
                weather,
                demands,
                scaled_config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=years,
                result_sink=collect,
                store_results=False,
            )
            if simulation_cache is not None:
                simulation_cache.record_event(
                    "simulate:compact",
                    "Simulation compacte economie sondes",
                    {
                        "Mode simulation": "borefield_savings_compact",
                        "Annees simulees": int(years),
                        "Pas meteo": int(len(weather)),
                        "Heures simulees": int(len(weather) * years),
                        "Sondes": int(boreholes),
                    },
                )
            results = None
            cop, bt_pac, final_metrics = _compact_candidate_metrics(
                stats,
                years_count=years,
                t_min_c=config.btes.t_min_c,
                gmi_t_min_c=config.btes.gmi_t_min_c,
                gmi_t_max_c=config.btes.gmi_t_max_c,
                depth_m=float(config.btes.depth_m),
            )
        final_metrics["depth_m"] = float(config.btes.depth_m)
        return results, cop, bt_pac, boreholes, final_metrics

    if mode in {"none", "off", "disabled", "desactivee", "désactivée"}:
        empty_final = dict(full_case_metrics or {})
        empty_final["depth_m"] = float(config.btes.depth_m)
        return _base_return(
            found=False,
            base_length_m=base_length_m,
            boreholes=config.btes.boreholes,
            equivalent_cop=0.0,
            equivalent_bt_pac_kwh=0.0,
            final_metrics=empty_final,
            estimated_length_m=base_length_m,
            simulations_count=0,
        )

    if full_case_df is not None and not full_case_df.empty:
        full_df = full_case_df
        full_cop, full_bt = _mean_metrics(full_df, years)
        full_boreholes = int(config.btes.boreholes)
        full_final = dict(
            full_case_metrics
            or _final_year_screening_metrics(
                full_df,
                t_min_c=config.btes.t_min_c,
                gmi_t_min_c=config.btes.gmi_t_min_c,
                gmi_t_max_c=config.btes.gmi_t_max_c,
                demand_bt_kwh=sum(max(0.0, bt) for _, bt in (hourly_demand_override or {}).values()),
            )
        )
        full_final["depth_m"] = float(config.btes.depth_m)
    elif full_case_metrics is not None:
        full_cop = float(full_case_metrics.get("mean_cop", full_case_metrics.get("final_cop", 0.0)))
        full_bt = float(full_case_metrics.get("mean_bt_pac_kwh", full_case_metrics.get("final_bt_pac_kwh", 0.0)))
        full_boreholes = int(config.btes.boreholes)
        full_final = dict(full_case_metrics)
        full_final["depth_m"] = float(config.btes.depth_m)
    else:
        _, full_cop, full_bt, full_boreholes, full_final = run(1.0)
    required_final_cop = min(full_final["final_cop"], max(reference_final_cop, 0.0))
    required_final_bt = min(full_final["final_bt_pac_kwh"], max(reference_final_bt_pac_kwh, 0.0))
    required_final_coverage = min(full_final["final_bt_coverage"], max(reference_final_bt_coverage, 0.0))
    required_source_limited_hours = max(0.0, reference_final_source_limited_hours)
    full_final_valid = (
        full_final["final_hours_under_tmin"] <= 1e-9
        and full_final["final_hours_under_gmi_tmin"] <= 1e-9
        and full_final["final_hours_over_gmi_tmax"] <= 1e-9
        and full_final["final_t_source_min_c"] >= config.btes.t_min_c - 1e-6
        and full_final["final_q_extraction_max_w_m"] <= config.btes.max_extraction_w_m + 1e-6
        and full_final["final_q_injection_max_w_m"] <= config.btes.max_injection_w_m + 1e-6
    )
    if (
        full_final["final_cop"] + 1e-9 < required_final_cop
        or full_final["final_bt_pac_kwh"] + tolerance_bt < required_final_bt
        or full_final["final_bt_coverage"] + 1e-9 < required_final_coverage
        or full_final["final_source_limited_hours"] > required_source_limited_hours + 1e-9
        or not full_final_valid
    ):
        return {
            "found": False,
            "scale": 1.0,
            "reference_length_m": base_length_m,
            "equivalent_length_m": base_length_m,
            "equivalent_boreholes": full_boreholes,
            "saved_length_m": 0.0,
            "saved_fraction": 0.0,
            "equivalent_cop": full_cop,
            "equivalent_bt_pac_kwh": full_bt,
            "estimated_length_m": base_length_m,
            "verified_length_m": base_length_m,
            "savings_simulations_count": simulations_count,
            **{f"equivalent_{key}": value for key, value in full_final.items()},
        }

    def final_ok(final_metrics: dict[str, float]) -> bool:
        return (
            final_metrics["final_cop"] + 1e-9 >= required_final_cop
            and final_metrics["final_bt_pac_kwh"] + tolerance_bt >= required_final_bt
            and final_metrics["final_bt_coverage"] + 1e-9 >= required_final_coverage
            and final_metrics["final_hours_under_tmin"] <= full_final["final_hours_under_tmin"] + 1e-9
            and final_metrics["final_hours_under_gmi_tmin"] <= 1e-9
            and final_metrics["final_hours_over_gmi_tmax"] <= 1e-9
            and final_metrics["final_source_limited_hours"] <= required_source_limited_hours + 1e-9
            and final_metrics["final_t_source_min_c"] >= config.btes.t_min_c - 1e-6
            and final_metrics["final_q_extraction_max_w_m"] <= config.btes.max_extraction_w_m + 1e-6
            and final_metrics["final_q_injection_max_w_m"] <= config.btes.max_injection_w_m + 1e-6
        )

    if mode == "fast":
        ratio_recharge = float(full_final.get("final_injected_btes_kwh", 0.0)) / max(
            1e-9, float(full_final.get("final_extracted_ground_kwh", reference_final_bt_pac_kwh))
        )
        gain_fraction = max(0.0, min(0.85, float(recharge_credit) * ratio_recharge))
        estimated_length = base_length_m * (1.0 - gain_fraction)
        q_extract_peak_w = float(full_final.get("final_q_extraction_max_w_m", 0.0)) * base_length_m
        q_inject_peak_w = float(full_final.get("final_q_injection_max_w_m", 0.0)) * base_length_m
        min_extract = q_extract_peak_w / max(1e-9, float(config.btes.max_extraction_w_m))
        min_inject = q_inject_peak_w / max(1e-9, float(config.btes.max_injection_w_m))
        test_length = max(estimated_length, min_extract, min_inject, base_length_m * max(0.0, float(min_scale)))
        test_length *= max(1.0, float(reduced_borefield_safety_factor))
        evaluated_by_boreholes: dict[int, tuple[list[HourlyResult] | None, float, float, int, dict[str, float]]] = {}

        def run_length(length_m: float):
            boreholes = max(1, min(config.btes.boreholes, int(math.ceil(length_m / max(1e-9, config.btes.depth_m)))))
            if boreholes >= int(config.btes.boreholes) and full_case_metrics is not None:
                return None, full_cop, full_bt, full_boreholes, full_final
            if boreholes in evaluated_by_boreholes:
                return evaluated_by_boreholes[boreholes]
            scale = boreholes / max(1, config.btes.boreholes)
            evaluated_by_boreholes[boreholes] = run(scale)
            return evaluated_by_boreholes[boreholes]

        results, cop, bt_pac, boreholes, final_metrics = run_length(test_length)
        if final_ok(final_metrics):
            best_results = results
            best_cop, best_bt, best_boreholes, best_final = cop, bt_pac, boreholes, final_metrics
            smaller_length = max(base_length_m * max(0.0, float(min_scale)), boreholes * config.btes.depth_m * 0.90)
            results2, cop2, bt2, boreholes2, final2 = run_length(smaller_length)
            if final_ok(final2):
                best_results = results2
                best_cop, best_bt, best_boreholes, best_final = cop2, bt2, boreholes2, final2
            best_df = pd.DataFrame()
            if include_hourly_df:
                best_df = (
                    full_case_df.copy()
                    if best_results is None and full_case_df is not None
                    else _selected_results_to_dataframe(
                        best_results,
                        simulation_cache=simulation_cache,
                        years=years,
                        weather_len=len(weather),
                    )
                )
            return _base_return(
            found=True,
                base_length_m=base_length_m,
                boreholes=best_boreholes,
                equivalent_cop=best_cop,
                equivalent_bt_pac_kwh=best_bt,
                final_metrics=best_final,
                estimated_length_m=estimated_length,
                simulations_count=simulations_count,
                hourly_df=best_df,
            )

        larger_length = min(base_length_m, max(test_length * 1.20, test_length + config.btes.depth_m))
        results3, cop3, bt3, boreholes3, final3 = run_length(larger_length)
        if final_ok(final3):
            df3 = pd.DataFrame()
            if include_hourly_df:
                df3 = (
                    full_case_df.copy()
                    if results3 is None and full_case_df is not None
                    else _selected_results_to_dataframe(
                        results3,
                        simulation_cache=simulation_cache,
                        years=years,
                        weather_len=len(weather),
                    )
                )
            return _base_return(
            found=True,
                base_length_m=base_length_m,
                boreholes=boreholes3,
                equivalent_cop=cop3,
                equivalent_bt_pac_kwh=bt3,
                final_metrics=final3,
                estimated_length_m=estimated_length,
                simulations_count=simulations_count,
                hourly_df=df3,
            )
        return _base_return(
            found=False,
            base_length_m=base_length_m,
            boreholes=full_boreholes,
            equivalent_cop=full_cop,
            equivalent_bt_pac_kwh=full_bt,
            final_metrics=full_final,
            estimated_length_m=estimated_length,
            simulations_count=simulations_count,
        )

    low = min_scale
    high = 1.0
    best_scale = 1.0
    best_cop = full_cop
    best_bt = full_bt
    best_boreholes = full_boreholes
    best_final = full_final
    best_results: list[HourlyResult] | None = None
    best_uses_full_case_df = "full_df" in locals() and isinstance(full_df, pd.DataFrame)
    candidate_cop = full_cop
    candidate_bt = full_bt
    candidate_boreholes = full_boreholes
    candidate_final = full_final
    candidate_results: list[HourlyResult] | None = None
    candidate_uses_full_case_df = best_uses_full_case_df

    for _ in range(iterations):
        mid = (low + high) / 2.0
        results, cop, bt_pac, boreholes, final_metrics = run(mid)
        ok = final_ok(final_metrics)
        if boreholes < candidate_boreholes:
            candidate_results = results
            candidate_uses_full_case_df = False
            candidate_cop = cop
            candidate_bt = bt_pac
            candidate_boreholes = boreholes
            candidate_final = final_metrics
        if ok:
            best_scale = mid
            best_results = results
            best_uses_full_case_df = False
            best_cop = cop
            best_bt = bt_pac
            best_boreholes = boreholes
            best_final = final_metrics
            high = mid
        else:
            low = mid

    equivalent_length = max(0.0, best_boreholes * config.btes.depth_m)
    saved_length = max(0.0, base_length_m - equivalent_length)
    real_savings = saved_length > 1e-6 and best_boreholes < int(config.btes.boreholes)
    if not real_savings:
        best_boreholes = candidate_boreholes
        equivalent_length = max(0.0, candidate_boreholes * config.btes.depth_m)
        saved_length = 0.0
        best_cop = candidate_cop
        best_bt = candidate_bt
        best_final = candidate_final
        best_results = candidate_results
        best_uses_full_case_df = candidate_uses_full_case_df
    result: dict[str, float | bool | str | pd.DataFrame] = {
        "found": real_savings,
        "simulated": bool(equivalent_length < base_length_m - 1e-6),
        "validated": real_savings,
        "scale": equivalent_length / max(1e-9, base_length_m) if real_savings else 1.0,
        "reference_length_m": base_length_m,
        "candidate_length_m": equivalent_length,
        "candidate_boreholes": int(best_boreholes),
        "candidate_saved_length_m": max(0.0, base_length_m - equivalent_length),
        "candidate_saved_fraction": max(0.0, base_length_m - equivalent_length) / max(1e-9, base_length_m),
        "equivalent_length_m": equivalent_length if real_savings else base_length_m,
        "equivalent_boreholes": best_boreholes if real_savings else full_boreholes,
        "saved_length_m": saved_length,
        "saved_fraction": saved_length / max(1e-9, base_length_m),
        "message": "Reduction de sondes validee" if real_savings else "Aucune réduction de sondes validée",
        "equivalent_cop": best_cop,
        "equivalent_bt_pac_kwh": best_bt,
        "estimated_length_m": equivalent_length,
        "verified_length_m": equivalent_length if real_savings else base_length_m,
        "savings_simulations_count": simulations_count,
        **{f"candidate_{key}": value for key, value in best_final.items()},
        **{f"equivalent_{key}": value for key, value in best_final.items()},
    }
    best_df = pd.DataFrame()
    if include_hourly_df:
        best_df = (
            full_df.copy()
            if best_uses_full_case_df and "full_df" in locals() and isinstance(full_df, pd.DataFrame)
            else _selected_results_to_dataframe(
                best_results,
                simulation_cache=simulation_cache,
                years=years,
                weather_len=len(weather),
            )
        )
    if not best_df.empty:
        result["_equivalent_hourly_df"] = best_df
        result["_candidate_hourly_df"] = best_df
    return result
