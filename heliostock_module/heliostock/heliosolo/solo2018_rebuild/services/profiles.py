from __future__ import annotations

import pandas as pd

from heliostock.heliosolo.solo2018_rebuild.defaults import (
    DAYS_BY_MONTH,
    MONTHS,
    SOLO_ANGERS_TEXT_C,
    SOLO_NANTES_CAP_KWH_M2_J,
    SOLO_NANTES_DISPO_KWH_M2_J,
    SOLO_NANTES_GH_KWH_M2_J,
    SOLO_STBRIEUC_CAP_KWH_M2_J,
    SOLO_STBRIEUC_DISPO_KWH_M2_J,
    SOLO_STBRIEUC_GH_KWH_M2_J,
    SOLO_STBRIEUC_TEXT_C,
)
from heliostock.heliosolo.solo2018_rebuild.utils import weighted_mean


def calc_tef_series(
    text_m_series: list[float],
    days_series: list[int],
    mode: str,
) -> list[float]:
    text_a = weighted_mean(text_m_series, [float(d) for d in days_series])
    if mode == "ESM2":
        return [0.5 * (text_m + text_a) for text_m in text_m_series]
    if mode == "ESM2Plus3":
        return [3.0 + 0.5 * (text_m + text_a) for text_m in text_m_series]
    return list(text_m_series)


def default_rows() -> list[dict]:
    return [
        {
            "month": month,
            "days_m": DAYS_BY_MONTH[idx],
            "vecs_l_j": 1500.0,
            "vecs_dis_l_j": 1500.0,
            "tecs_m": 60.0,
            "tecs_consigne_m": 60.0,
            "tecs_dis_m": 55.0,
            "tef_m": 12.0,
            "tef_source_m": 12.0,
            "text_m": 12.0,
            "t_env_stock_c": None,
            "r_global_hz_kwh_m2_j": 0.0,
            "r_global_plan_kwh_m2_j": 0.0,
            "corr_incidence_m": 1.0,
            "r_disponible_kwh_m2_j": 0.0,
            "r_disponible_kwh_m2_j_override": None,
            "g_tilt_kwh_m2": 0.0,
            "pertes_boucle_input_kwh_j": 0.0,
        }
        for idx, month in enumerate(MONTHS)
    ]


def meteo_verification_defaults(cas: str) -> list[dict]:
    if cas == "Saint-Brieuc":
        text = SOLO_STBRIEUC_TEXT_C
        gh = SOLO_STBRIEUC_GH_KWH_M2_J
        cap = SOLO_STBRIEUC_CAP_KWH_M2_J
        dispo = SOLO_STBRIEUC_DISPO_KWH_M2_J
        tef = calc_tef_series(text, DAYS_BY_MONTH, "ESM2")
    else:
        text = SOLO_ANGERS_TEXT_C
        gh = SOLO_NANTES_GH_KWH_M2_J
        cap = SOLO_NANTES_CAP_KWH_M2_J
        dispo = SOLO_NANTES_DISPO_KWH_M2_J
        tef = [12.0 for _ in MONTHS]

    return [
        {
            "Mois": month,
            "T ext (degC)": float(text[idx]),
            "Temp EF (degC)": float(tef[idx]),
            "Global horiz (kWh/m2.j)": float(gh[idx]),
            "Global capteur (kWh/m2.j)": float(cap[idx]),
            "RDisponible (kWh/m2.j)": float(dispo[idx]),
        }
        for idx, month in enumerate(MONTHS)
    ]


def ensure_rows_schema(df: pd.DataFrame) -> pd.DataFrame:
    ref_df = pd.DataFrame(default_rows())
    out = df.copy()
    for col in ref_df.columns:
        if col not in out.columns:
            out[col] = ref_df[col]
    return out[ref_df.columns]


def apply_profiles_to_rows(
    rows: list[dict],
    modele_v_eau_chaude: str,
    conso_mode: str,
    vecs_const_l_j: float,
    vecs_monthly_map: dict[str, float],
    tecs_dis_mode: str,
    tecs_dis_const_c: float,
    tecs_dis_monthly_map: dict[str, float],
    tecs_mode: str,
    tecs_const_c: float,
    tecs_monthly_map: dict[str, float],
    tef_mode: str,
    tef_manual_c: float,
    tef_monthly_map: dict[str, float],
    tenv_mode: str,
    tenv_base_c: float,
    tenv_monthly_map: dict[str, float],
) -> list[dict]:
    out = [dict(r) for r in rows]
    for r in out:
        month = str(r["month"])
        if conso_mode == "constant":
            vecs_input = float(vecs_const_l_j)
        else:
            vecs_input = float(vecs_monthly_map.get(month, r.get("vecs_l_j", vecs_const_l_j)))

        if conso_mode == "constant":
            r["vecs_dis_l_j"] = float(r.get("vecs_dis_l_j", vecs_input))
        else:
            r["vecs_dis_l_j"] = float(vecs_monthly_map.get(month, r.get("vecs_dis_l_j", vecs_input)))

        if tecs_mode == "constant":
            r["tecs_m"] = float(tecs_const_c)
        else:
            r["tecs_m"] = float(tecs_monthly_map.get(month, r.get("tecs_m", tecs_const_c)))
        r["tecs_consigne_m"] = float(r["tecs_m"])

        if tecs_dis_mode == "constant":
            r["tecs_dis_m"] = float(tecs_dis_const_c)
        else:
            r["tecs_dis_m"] = float(tecs_dis_monthly_map.get(month, r.get("tecs_dis_m", tecs_dis_const_c)))

        if tef_mode == "Manual":
            r["tef_m"] = float(tef_manual_c)
        elif tef_mode == "ManualMonthly":
            r["tef_m"] = float(tef_monthly_map.get(month, r.get("tef_m", tef_manual_c)))
        r["tef_source_m"] = float(r.get("tef_m", tef_manual_c))

        if modele_v_eau_chaude == "production":
            r["vecs_l_j"] = vecs_input
        else:
            tef = float(r.get("tef_m", tef_manual_c))
            tecs_pro = float(r.get("tecs_m", tecs_const_c))
            tecs_dis = float(r.get("tecs_dis_m", tecs_dis_const_c))
            vecs_dis = float(r.get("vecs_dis_l_j", vecs_input))
            delta_pro = tecs_pro - tef
            delta_dis = tecs_dis - tef
            r["vecs_l_j"] = 0.0 if delta_pro <= 1e-9 else max(0.0, vecs_dis * delta_dis / delta_pro)

        if tenv_mode == "constant":
            r["t_env_stock_c"] = float(tenv_base_c)
        else:
            r["t_env_stock_c"] = float(tenv_monthly_map.get(month, tenv_base_c))
    return out


def apply_meteo_impose_to_rows(
    rows: list[dict],
    meteo_impose_map: dict[str, dict[str, float]],
) -> list[dict]:
    out = [dict(r) for r in rows]
    for idx, r in enumerate(out):
        month = str(r.get("month", MONTHS[idx] if idx < len(MONTHS) else ""))
        imposed = meteo_impose_map.get(month)
        if not imposed:
            continue
        days_m = int(DAYS_BY_MONTH[idx]) if idx < len(DAYS_BY_MONTH) else int(r.get("days_m", 30))
        r_plan = float(imposed.get("cap", r.get("r_global_plan_kwh_m2_j", 0.0)))
        r_dispo = float(imposed.get("dispo", r.get("r_disponible_kwh_m2_j", 0.0)))
        r["days_m"] = days_m
        r["text_m"] = float(imposed.get("text", r.get("text_m", 12.0)))
        r["tef_m"] = float(imposed.get("tef", r.get("tef_m", 12.0)))
        r["tef_source_m"] = float(imposed.get("tef", r.get("tef_source_m", r.get("tef_m", 12.0))))
        r["r_global_hz_kwh_m2_j"] = float(imposed.get("gh", r.get("r_global_hz_kwh_m2_j", 0.0)))
        r["r_global_plan_kwh_m2_j"] = r_plan
        r["r_disponible_kwh_m2_j_override"] = r_dispo
        r["r_disponible_kwh_m2_j"] = r_dispo
        r["corr_incidence_m"] = (r_dispo / r_plan) if r_plan > 0 else 1.0
        r["g_tilt_kwh_m2"] = r_plan * days_m
    return out


def recompute_vecs_production_from_distribution(rows: list[dict]) -> list[dict]:
    out = [dict(r) for r in rows]
    for r in out:
        tef = float(r.get("tef_m", 12.0))
        tecs_pro = float(r.get("tecs_m", 60.0))
        tecs_dis = float(r.get("tecs_dis_m", 55.0))
        vecs_dis = float(r.get("vecs_dis_l_j", r.get("vecs_l_j", 0.0)))
        delta_pro = tecs_pro - tef
        delta_dis = tecs_dis - tef
        r["vecs_l_j"] = 0.0 if delta_pro <= 1e-9 else max(0.0, vecs_dis * delta_dis / delta_pro)
    return out


