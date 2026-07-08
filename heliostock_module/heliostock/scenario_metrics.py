from __future__ import annotations

import pandas as pd

from .hourly_engine import HourlyResult
from .postprocess import btes_efficiency_indicator, sign_change_diagnostics


def _results_by_year(results: list[HourlyResult]) -> dict[int, list[HourlyResult]]:
    grouped: dict[int, list[HourlyResult]] = {}
    for result in results:
        grouped.setdefault(int(result.simulation_year), []).append(result)
    return grouped


def _sum_attr(rows: list[HourlyResult], name: str) -> float:
    return sum(float(getattr(row, name)) for row in rows)


def _max_attr(rows: list[HourlyResult], name: str) -> float:
    return max((float(getattr(row, name)) for row in rows), default=0.0)


def _min_attr(rows: list[HourlyResult], name: str) -> float:
    return min((float(getattr(row, name)) for row in rows), default=0.0)


def _mean_attr(rows: list[HourlyResult], name: str) -> float:
    return _sum_attr(rows, name) / max(1, len(rows))


def _hourly_metrics_from_results(
    results: list[HourlyResult],
    *,
    annualization_years: int = 1,
) -> dict[str, float]:
    years = max(1, int(annualization_years))
    total_ht = _sum_attr(results, "demand_ht_kwh")
    total_bt = _sum_attr(results, "demand_bt_kwh")
    total_backup_ht = _sum_attr(results, "unmet_ht_kwh")
    total_backup_bt = _sum_attr(results, "unmet_bt_kwh")
    total_pac = _sum_attr(results, "heat_bt_from_pac_kwh")
    total_compressor = _sum_attr(results, "electricity_compressor_kwh")
    total_elec = _sum_attr(results, "electricity_pac_total_kwh")
    total_system_elec = _sum_attr(results, "electricity_system_total_kwh")
    total_solar_ht = _sum_attr(results, "solar_ht_from_buffer_kwh")
    total_solar_btes = _sum_attr(results, "solar_to_btes_kwh")
    backup_power_kw = max(
        (max(0.0, float(row.unmet_ht_kwh)) + max(0.0, float(row.unmet_bt_kwh)) for row in results),
        default=0.0,
    )
    reference_gas_power_kw = max(
        (max(0.0, float(row.demand_ht_kwh)) + max(0.0, float(row.demand_bt_kwh)) for row in results),
        default=0.0,
    )
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
        "reference_gas_power_kw": reference_gas_power_kw,
        "t_source_pac_min_c": _min_attr(results, "t_source_pac_c"),
        "t_source_pac_mean_c": _mean_attr(results, "t_source_pac_c"),
        "q_extraction_max_w_m": _max_attr(results, "q_extraction_w_m"),
        "q_injection_max_w_m": _max_attr(results, "q_injection_w_m"),
        "source_limited_hours": float(sum(1 for row in results if row.source_temp_limited)),
        "source_limited_unmet_mwh": _sum_attr(results, "source_temp_unmet_bt_kwh") / 1000.0,
    }


def _multiyear_btes_summary_from_results(
    results: list[HourlyResult],
    *,
    t_min_c: float,
    gmi_t_min_c: float = -3.0,
    gmi_t_max_c: float = 40.0,
    gmi_check_enabled: bool = True,
) -> pd.DataFrame:
    grouped: dict[tuple[int, int], list[HourlyResult]] = {}
    for result in results:
        grouped.setdefault((int(result.simulation_year), int(result.month)), []).append(result)
    rows = []
    for (year, month), group in sorted(grouped.items()):
        elec_compressor = _sum_attr(group, "electricity_compressor_kwh")
        elec_total = _sum_attr(group, "electricity_pac_total_kwh")
        heat_pac = _sum_attr(group, "heat_bt_from_pac_kwh")
        extracted = _sum_attr(group, "btes_extracted_by_pac_kwh")
        injected = _sum_attr(group, "solar_to_btes_kwh")
        sign_diag = sign_change_diagnostics(row.q_net_w_m for row in group)
        rows.append(
            {
                "Annee": int(year),
                "Mois index": (int(year) - 1) * 12 + int(month),
                "Mois": f"A{int(year):02d}-{int(month):02d}",
                "T source PAC fin (C)": float(group[-1].t_source_pac_c),
                "T source PAC min (C)": _min_attr(group, "t_source_pac_c"),
                "T source PAC max (C)": _max_attr(group, "t_source_pac_c"),
                "T source PAC moyenne (C)": _mean_attr(group, "t_source_pac_c"),
                "T source PAC pour COP min (C)": _min_attr(group, "t_source_pac_for_cop_c"),
                "T source PAC pour COP moyenne (C)": _mean_attr(group, "t_source_pac_for_cop_c"),
                "T fluide entree echangeur geo min (C)": _min_attr(group, "t_fluide_entree_echangeur_geo_c"),
                "T fluide injection max (C)": _max_attr(group, "t_fluide_injection_c"),
                "T paroi forage fin (C)": float(group[-1].t_borehole_wall_c),
                "T paroi forage min (C)": _min_attr(group, "t_borehole_wall_c"),
                "T paroi forage max (C)": _max_attr(group, "t_borehole_wall_c"),
                "T evaporateur PAC min (C)": _min_attr(group, "t_evaporator_pac_c"),
                "Q net sol (MWh)": (extracted - injected) / 1000.0,
                "Injection BTES (MWh)": injected / 1000.0,
                "Extraction PAC (MWh)": extracted / 1000.0,
                "Ratio injection/extraction": injected / max(1e-9, extracted),
                "eta_BTES": btes_efficiency_indicator(extracted, injected),
                "Transitions injection/extraction": int(sign_diag["sign_changes"]),
                "Indice alternance charge": float(sign_diag["seasonal_load_variability_index"]),
                "Niveau alternance": str(sign_diag["alternance_level"]),
                "q extraction max (W/m)": _max_attr(group, "q_extraction_w_m"),
                "q injection max (W/m)": _max_attr(group, "q_injection_w_m"),
                "q net moyen (W/m)": _mean_attr(group, "q_net_w_m"),
                "COP machine": heat_pac / elec_compressor if elec_compressor > 0.0 else 0.0,
                "SPF PAC complet": heat_pac / elec_total if elec_total > 0.0 else 0.0,
                "Heures sous Tmin operationnelle": int(sum(1 for row in group if float(row.t_source_pac_for_cop_c) <= t_min_c + 1e-6)),
                "Heures sous Tmin source": int(sum(1 for row in group if float(row.t_source_pac_c) <= t_min_c + 1e-6)),
                "Heures sous Tmin GMI": int(sum(1 for row in group if float(row.t_fluide_entree_echangeur_geo_c) < gmi_t_min_c - 1e-6)),
                "Heures sur Tmax GMI": int(sum(1 for row in group if float(row.t_fluide_injection_c) > gmi_t_max_c + 1e-6)),
                "Conformite GMI": bool(
                    (not gmi_check_enabled)
                    or (
                        all(float(row.t_fluide_entree_echangeur_geo_c) >= gmi_t_min_c - 1e-6 for row in group)
                        and all(float(row.t_fluide_injection_c) <= gmi_t_max_c + 1e-6 for row in group)
                    )
                ),
                "Heures limite source": int(sum(1 for row in group if row.source_temp_limited)),
                "BT non couvert limite source (MWh)": _sum_attr(group, "source_temp_unmet_bt_kwh") / 1000.0,
                "Heures COP max": int(sum(1 for row in group if row.cop_limited_max)),
            }
        )
    return pd.DataFrame(rows)


def _annual_metrics_trajectory_from_results(
    results: list[HourlyResult],
    *,
    analysis_years: int,
    gmi_t_min_c: float = -3.0,
    gmi_t_max_c: float = 40.0,
    gmi_check_enabled: bool = True,
    pac_power_kw: float = 0.0,
) -> pd.DataFrame:
    years = max(1, int(analysis_years))
    grouped = _results_by_year(results)
    last_group = grouped[max(grouped)] if grouped else []
    rows: list[dict[str, float | int]] = []
    for year in range(1, years + 1):
        group = grouped.get(year, last_group)
        heat_pac = _sum_attr(group, "heat_bt_from_pac_kwh")
        elec_comp = _sum_attr(group, "electricity_compressor_kwh")
        total_ht = _sum_attr(group, "demand_ht_kwh")
        total_bt = _sum_attr(group, "demand_bt_kwh")
        backup_ht = _sum_attr(group, "unmet_ht_kwh")
        backup_bt = _sum_attr(group, "unmet_bt_kwh")
        elec_total = _sum_attr(group, "electricity_pac_total_kwh")
        solar_ht = _sum_attr(group, "solar_ht_from_buffer_kwh")
        non_ren = backup_ht + backup_bt + elec_total
        useful = total_ht + total_bt
        equivalent_power = pac_power_kw if pac_power_kw > 0.0 else _max_attr(group, "heat_bt_from_pac_kwh")
        rows.append(
            {
                "Annee": year,
                "E utile HT (MWh)": total_ht / 1000.0,
                "E utile BT (MWh)": total_bt / 1000.0,
                "E utile totale (MWh)": useful / 1000.0,
                "Solaire HT (MWh)": solar_ht / 1000.0,
                "Injection solaire BTES (MWh)": _sum_attr(group, "solar_to_btes_kwh") / 1000.0,
                "Chaleur PAC BT (MWh)": heat_pac / 1000.0,
                "Appoint gaz HT (MWh)": backup_ht / 1000.0,
                "Appoint gaz BT (MWh)": backup_bt / 1000.0,
                "Appoint gaz total (MWh)": (backup_ht + backup_bt) / 1000.0,
                "Electricite PAC (MWh)": elec_total / 1000.0,
                "COP moyen": heat_pac / elec_comp if elec_comp > 0.0 else 0.0,
                "SPF PAC complet": heat_pac / elec_total if elec_total > 0.0 else 0.0,
                "Couverture PAC BT (%)": heat_pac / max(1e-9, total_bt) * 100.0,
                "Heures equivalentes PAC BT": heat_pac / max(1e-9, equivalent_power),
                "T_source_PAC_min (C)": _min_attr(group, "t_source_pac_c"),
                "T_source_PAC_pour_COP_min (C)": _min_attr(group, "t_source_pac_for_cop_c"),
                "T_fluide_injection_max (C)": _max_attr(group, "t_fluide_injection_c"),
                "Heures sous Tmin GMI": int(sum(1 for row in group if float(row.t_fluide_entree_echangeur_geo_c) < gmi_t_min_c - 1e-6)),
                "Heures sur Tmax GMI": int(sum(1 for row in group if float(row.t_fluide_injection_c) > gmi_t_max_c + 1e-6)),
                "Conformite GMI": bool(
                    (not gmi_check_enabled)
                    or (
                        all(float(row.t_fluide_entree_echangeur_geo_c) >= gmi_t_min_c - 1e-6 for row in group)
                        and all(float(row.t_fluide_injection_c) <= gmi_t_max_c + 1e-6 for row in group)
                    )
                ),
                "Heures limite source": int(sum(1 for row in group if row.source_temp_limited)),
                "BT non couvert limite source (MWh)": _sum_attr(group, "source_temp_unmet_bt_kwh") / 1000.0,
                "T_source_PAC_moy (C)": _mean_attr(group, "t_source_pac_c"),
                "q_extraction_W_m_max": _max_attr(group, "q_extraction_w_m"),
                "q_injection_W_m_max": _max_attr(group, "q_injection_w_m"),
                "Taux EnR (%)": max(0.0, min(1.0, 1.0 - non_ren / max(1e-9, useful))) * 100.0,
            }
        )
    return pd.DataFrame(rows)
