from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .engine import MonthlyDemand, SimulationConfig
from .hourly_engine import HourlyWeather, simulate_hourly
from .postprocess import _hourly_results_to_dataframe, _mean_cop


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
    }


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
    iterations: int = 16,
) -> dict[str, float | bool]:
    """Estimate equivalent borefield length saving with solar recharge.

    The search varies the actual number of boreholes and reruns the hourly
    pygfunction backend. It is still a screening indicator, not a detailed
    borefield design, but it only varies pygfunction borefield geometry.
    """

    tolerance_bt = max(1.0, 0.001 * reference_final_bt_pac_kwh)
    base_length_m = max(0.0, config.btes.boreholes * config.btes.depth_m)
    years = max(1, int(simulation_years))

    def run(scale: float) -> tuple[pd.DataFrame, float, float, int, dict[str, float]]:
        boreholes = max(1, int(round(config.btes.boreholes * scale)))
        scaled_btes = replace(config.btes, boreholes=boreholes)
        scaled_config = replace(config, btes=scaled_btes)
        df = _hourly_results_to_dataframe(
            simulate_hourly(
                weather,
                demands,
                scaled_config,
                hourly_demand_override=hourly_demand_override,
                simulation_years=years,
            )
        )
        cop = _mean_cop(df)
        bt_pac = float(df["heat_bt_from_pac_kwh"].sum()) / years
        final_metrics = _final_year_screening_metrics(
            df,
            t_min_c=config.btes.t_min_c,
            gmi_t_min_c=config.btes.gmi_t_min_c,
            gmi_t_max_c=config.btes.gmi_t_max_c,
            demand_bt_kwh=sum(max(0.0, bt) for _, bt in (hourly_demand_override or {}).values()),
        )
        return df, cop, bt_pac, boreholes, final_metrics

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
            **{f"equivalent_{key}": value for key, value in full_final.items()},
        }

    low = min_scale
    high = 1.0
    best_scale = 1.0
    best_cop = full_cop
    best_bt = full_bt
    best_boreholes = full_boreholes
    best_final = full_final

    for _ in range(iterations):
        mid = (low + high) / 2.0
        _, cop, bt_pac, boreholes, final_metrics = run(mid)
        ok = (
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
        if ok:
            best_scale = mid
            best_cop = cop
            best_bt = bt_pac
            best_boreholes = boreholes
            best_final = final_metrics
            high = mid
        else:
            low = mid

    equivalent_length = max(0.0, best_boreholes * config.btes.depth_m)
    saved_length = max(0.0, base_length_m - equivalent_length)
    return {
        "found": True,
        "scale": equivalent_length / max(1e-9, base_length_m),
        "reference_length_m": base_length_m,
        "equivalent_length_m": equivalent_length,
        "equivalent_boreholes": best_boreholes,
        "saved_length_m": saved_length,
        "saved_fraction": saved_length / max(1e-9, base_length_m),
        "equivalent_cop": best_cop,
        "equivalent_bt_pac_kwh": best_bt,
        **{f"equivalent_{key}": value for key, value in best_final.items()},
    }
