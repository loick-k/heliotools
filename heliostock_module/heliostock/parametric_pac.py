from __future__ import annotations

import gc
from dataclasses import replace
from typing import Callable

import pandas as pd

from .economic_scenarios import _capex_net_total, _multiyear_heat_cost
from .economics import compute_heat_costs, compute_solar_thermal_economics
from .engine import MonthlyDemand, SimulationConfig, cop_from_source_temperature
from .geothermal_design import predimension_borefield
from .hourly_engine import HourlyWeather
from .load_profiles import _estimate_capped_bt_heat_mwh
from .scenario_compact import _simulate_hourly_compact
from .scenario_outputs import ScenarioEconomicsConfig
from .simulation_cache import SimulationCache


ProgressCallback = Callable[[int, str], None]


def _notify(progress: ProgressCallback | None, value: int, text: str) -> None:
    if progress is not None:
        progress(value, text)


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
    """Run the PAC power parametric study for the geothermal-only case.

    Each variant is simulated on the technical duration and then aggregated for
    the multiannual economic indicators. The function avoids keeping hourly
    results longer than needed for each variant.
    """

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
        economic_metrics_variant, _full_case_metrics, variant_trajectory_df = _simulate_hourly_compact(
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
