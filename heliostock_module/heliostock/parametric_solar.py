from __future__ import annotations

import gc
from dataclasses import replace
from typing import Callable

import pandas as pd

from .borefield_savings import borefield_equivalent_savings
from .economic_scenarios import _capex_net_total, _multiyear_heat_cost
from .economics import compute_heat_costs, compute_solar_thermal_economics
from .engine import MonthlyDemand, SimulationConfig
from .hourly_engine import HourlyWeather
from .scenario_compact import _simulate_hourly_compact
from .scenario_outputs import ScenarioEconomicsConfig
from .simulation_cache import SimulationCache


ProgressCallback = Callable[[int, str], None]


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
    """Run the solar-surface parametric study.

    Physical variants use `technical_simulation_years`; `analysis_years` is
    only used for economics. `full_case_reference` avoids rerunning the already
    simulated main surface and full borefield when it matches the variant.
    """

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
        total_preheat_ht_variant = float(final_row.get("Solaire HT (MWh)", 0.0)) * 1000.0
        total_to_btes_variant = float(final_row.get("Injection solaire BTES (MWh)", 0.0)) * 1000.0
        annual_ht_solar_coverage_variant = total_preheat_ht_variant / max(1e-9, total_ht_variant)
        final_cop_variant = float(full_case_metrics.get("final_cop", 0.0))
        global_ren_rate_variant = float(final_row.get("Taux EnR (%)", 0.0)) / 100.0

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
