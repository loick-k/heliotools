from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .engine import MonthlyDemand, SimulationConfig
from .hourly_engine import HourlyWeather, simulate_hourly
from .postprocess import _hourly_results_to_dataframe, _mean_cop


def borefield_equivalent_savings(
    *,
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    reference_cop: float,
    reference_bt_pac_kwh: float,
    hourly_demand_override: dict[int, tuple[float, float]] | None = None,
    simulation_years: int = 1,
    min_scale: float = 0.05,
    iterations: int = 16,
) -> dict[str, float | bool]:
    """Estimate equivalent borefield length saving with solar recharge.

    The BTES model is capacitive, so the search scales `volume_factor`.
    With fixed spacing and borehole count, this is reported as an equivalent
    linear-meter saving, not a detailed borefield design.
    """

    tolerance_bt = max(1.0, 0.001 * reference_bt_pac_kwh)
    base_length_m = max(0.0, config.btes.boreholes * config.btes.depth_m)
    years = max(1, int(simulation_years))

    def run(scale: float) -> tuple[pd.DataFrame, float, float]:
        scaled_btes = replace(config.btes, volume_factor=config.btes.volume_factor * scale)
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
        return df, cop, bt_pac

    _, full_cop, full_bt = run(1.0)
    if full_cop + 1e-9 < reference_cop or full_bt + tolerance_bt < reference_bt_pac_kwh:
        return {
            "found": False,
            "scale": 1.0,
            "reference_length_m": base_length_m,
            "equivalent_length_m": base_length_m,
            "saved_length_m": 0.0,
            "saved_fraction": 0.0,
            "equivalent_cop": full_cop,
            "equivalent_bt_pac_kwh": full_bt,
        }

    low = min_scale
    high = 1.0
    best_scale = 1.0
    best_cop = full_cop
    best_bt = full_bt

    for _ in range(iterations):
        mid = (low + high) / 2.0
        _, cop, bt_pac = run(mid)
        ok = cop + 1e-9 >= reference_cop and bt_pac + tolerance_bt >= reference_bt_pac_kwh
        if ok:
            best_scale = mid
            best_cop = cop
            best_bt = bt_pac
            high = mid
        else:
            low = mid

    equivalent_length = base_length_m * best_scale
    saved_length = max(0.0, base_length_m - equivalent_length)
    return {
        "found": True,
        "scale": best_scale,
        "reference_length_m": base_length_m,
        "equivalent_length_m": equivalent_length,
        "saved_length_m": saved_length,
        "saved_fraction": saved_length / max(1e-9, base_length_m),
        "equivalent_cop": best_cop,
        "equivalent_bt_pac_kwh": best_bt,
    }
