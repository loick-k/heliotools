from __future__ import annotations

import pandas as pd

import heliostock.heliosolo.solo2018_rebuild.core.solo_v0_engine as solo_v0_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import DAYS_BY_MONTH, MONTHS


def run_solo_v0(
    rows: list[dict],
    installation: solo_v0_mod.InstallationSoloV0,
    pertes_boucle_kwh_j: float,
    mode_schema: str = "cesc",
    ratio_ecs_max10_sur_j: float = 0.5,
    kget_w_k: float = 0.0,
    pech_et1_w_k: float = 0.0,
    debit_et_m3_h: float = 0.0,
) -> tuple[pd.DataFrame, dict]:
    mois_data: list[solo_v0_mod.MoisSoloV0] = []
    for i, row in enumerate(rows, start=1):
        mois_data.append(
            solo_v0_mod.MoisSoloV0(
                mois=i,
                vecs_l_j=float(row["vecs_l_j"]),
                tecs_prod_c=float(row["tecs_m"]),
                tef_c=float(row["tef_m"]),
                text_c=float(row["text_m"]),
                r_global_plan_kwh_m2_j=float(row["r_global_plan_kwh_m2_j"]),
                r_disponible_kwh_m2_j_override=(
                    float(row["r_disponible_kwh_m2_j_override"])
                    if (
                        row.get("r_disponible_kwh_m2_j_override") is not None
                        and not pd.isna(row.get("r_disponible_kwh_m2_j_override"))
                    )
                    else None
                ),
                pertes_boucle_kwh_j=float(row.get("pertes_boucle_input_kwh_j", pertes_boucle_kwh_j)),
                t_env_stock_c=(
                    float(row["t_env_stock_c"])
                    if (row.get("t_env_stock_c") is not None and not pd.isna(row.get("t_env_stock_c")))
                    else None
                ),
            )
        )

    text_min_annuel_c = min((m.text_c for m in mois_data), default=0.0)
    if mode_schema == "cescet":
        results = solo_v0_mod.calcul_solo2018_annee_cescet(
            installation=installation,
            mois_data=mois_data,
            kget_w_k=float(kget_w_k),
            pech_et1_w_k=float(pech_et1_w_k),
            debit_et_m3_h=float(debit_et_m3_h),
            ratio_ecs_max10_sur_j=float(ratio_ecs_max10_sur_j),
        )
    else:
        results = solo_v0_mod.calcul_solo2018_annee(installation, mois_data)

    detail_rows: list[dict] = []
    total_days = 0
    for i, r in enumerate(results, start=1):
        row = rows[i - 1]
        days = int(row.get("days_m", DAYS_BY_MONTH[i - 1]))
        total_days += days
        r_global = float(row["r_global_plan_kwh_m2_j"])
        corr = (
            solo_v0_mod.correction_incidence_mensuelle(installation, i)
            if installation.appliquer_correction_incidence
            else 1.0
        )
        if row.get("r_disponible_kwh_m2_j_override") is not None and not pd.isna(row.get("r_disponible_kwh_m2_j_override")):
            r_dispo = float(row["r_disponible_kwh_m2_j_override"])
            corr = (r_dispo / r_global) if r_global > 0 else corr
        else:
            r_dispo = r_global * corr

        detail_rows.append(
            {
                "month": MONTHS[r.mois - 1],
                "days_m": days,
                "global_horiz_kwh_m2_j": float(row.get("r_global_hz_kwh_m2_j", 0.0)),
                "global_capteur_kwh_m2_j": r_global,
                "coeff_incidence": corr,
                "global_dispo_kwh_m2_j": r_dispo,
                "t_ext_c": float(row.get("text_m", installation.t_env_stock_c)),
                "t_env_stock_c": mois_data[i - 1].t_env_stock_c if mois_data[i - 1].t_env_stock_c is not None else installation.t_env_stock_c,
                "tef_source_c": float(row.get("tef_source_m", row.get("tef_m", 12.0))),
                "tef_c": float(getattr(r, "tef_calc_c", row.get("tef_m", 12.0))),
                "tecs_consigne_c": float(row.get("tecs_consigne_m", row.get("tecs_m", 60.0))),
                "tecs_c": float(getattr(r, "t_ref_calc_c", row.get("tecs_m", 60.0))),
                "tecs_etendu_c": float(getattr(r, "tecs_etendu_c", row.get("tecs_m", 60.0))),
                "delta_t_eq_boucle_c": float(getattr(r, "delta_t_eq_boucle_c", 0.0)),
                "vecs_l_j": float(row.get("vecs_l_j", 0.0)),
                "pertes_boucle_kwh_j": solo_v0_mod.pertes_bouclage_kwh_j(installation, mois_data[i - 1], text_min_annuel_c),
                "pertes_et_kwh_j": float(getattr(r, "pertes_eau_technique_kwh_j", 0.0)),
                "besoin_ref_kwh_j": float(getattr(r, "besoin_ref_kwh_j", 0.0)),
                "t_sortie_stock_solaire_c": float(getattr(r, "t_sortie_stock_solaire_c", row.get("tef_m", 12.0))),
                "pertes_stock_solaire_kwh_j": float(getattr(r, "pertes_stock_solaire_kwh_j", 0.0)),
                "production_primaire_kwh_j": float(getattr(r, "production_primaire_kwh_j", 0.0)),
                "besoin_primaire_kwh_j": float(getattr(r, "besoin_primaire_kwh_j", 0.0)),
                "prod_cesc_base_kwh_j": float(getattr(r, "prod_cesc_base_kwh_j", r.production_solaire_kwh_j)),
                "delta_t_corr_et_c": float(getattr(r, "delta_t_corr_et_c", 0.0)),
                "prod_cescet_avant_pertes_et_kwh_j": float(getattr(r, "prod_cescet_avant_pertes_et_kwh_j", r.production_solaire_kwh_j)),
                "volume_stock_l": installation.volume_stock_l,
                "besoin_prod_kwh_j": r.besoin_ecs_kwh_j,
                "besoin_total_kwh_j": r.besoin_total_kwh_j,
                "prod_solaire_kwh_j": r.production_solaire_kwh_j,
                "prod_cescet_finale_kwh_j": float(getattr(r, "prod_cescet_finale_kwh_j", r.production_solaire_kwh_j)),
                "becs_m": r.besoin_ecs_kwh_j * r.jours,
                "besoin_total_m": r.besoin_total_kwh_j * r.jours,
                "becs_etendu_m": float(getattr(r, "besoin_etendu_kwh_j", r.besoin_total_kwh_j)) * r.jours,
                "qstu_m": r.production_solaire_kwh_mois,
                "couvsol_m": r.taux_couverture_ecs if r.taux_couverture_ecs is not None else 0.0,
                "taux_eco_en_m": r.taux_economie_energie if r.taux_economie_energie is not None else 0.0,
                "kg1_primaire_w_m2_k": r.kg1_primaire_w_m2_k,
                "efficacite_transfert": r.efficacite_transfert,
                "productivite_kwh_m2_mois": r.productivite_kwh_m2_mois,
            }
        )

    detail_df = pd.DataFrame(detail_rows)
    summary = build_summary(detail_df)
    detail_df = append_solo_summary_rows(detail_df, rows, installation, summary, total_days)
    return detail_df, summary


def build_summary(detail_df: pd.DataFrame) -> dict:
    becs_year = float(detail_df["becs_m"].sum())
    besoin_total_year = float(detail_df["besoin_total_m"].sum())
    becs_etendu_year = float(detail_df["becs_etendu_m"].sum())
    qstu_year = float(detail_df["qstu_m"].sum())
    pertes_et_year = float((pd.to_numeric(detail_df["pertes_et_kwh_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum())
    couvsol_year = qstu_year / becs_year if becs_year > 0 else 0.0
    taux_eco_year = qstu_year / besoin_total_year if besoin_total_year > 0 else 0.0
    return {
        "becs_year": becs_year,
        "besoin_total_year": besoin_total_year,
        "becs_etendu_year": becs_etendu_year,
        "qstu_year": qstu_year,
        "pertes_et_year": pertes_et_year,
        "couvsol_year": couvsol_year,
        "taux_eco_year": taux_eco_year,
    }


def append_solo_summary_rows(
    detail_df: pd.DataFrame,
    rows: list[dict],
    installation: solo_v0_mod.InstallationSoloV0,
    summary: dict,
    total_days: int,
) -> pd.DataFrame:
    becs_year = float(summary["becs_year"])
    besoin_total_year = float(summary["besoin_total_year"])
    becs_etendu_year = float(summary["becs_etendu_year"])
    qstu_year = float(summary["qstu_year"])
    prod_cesc_base_year = float((pd.to_numeric(detail_df["prod_cesc_base_kwh_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum())
    prod_cescet_avant_pertes_et_year = float((pd.to_numeric(detail_df["prod_cescet_avant_pertes_et_kwh_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum())
    prod_cescet_finale_year = float((pd.to_numeric(detail_df["prod_cescet_finale_kwh_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum())
    prod_primaire_year = float((pd.to_numeric(detail_df["production_primaire_kwh_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum())
    vecs_year_m3 = float((pd.to_numeric(detail_df["vecs_l_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum()) / 1000.0
    pertes_boucle_year = float((pd.to_numeric(detail_df["pertes_boucle_kwh_j"], errors="coerce").fillna(0.0) * detail_df["days_m"]).sum())

    ann_horiz = float((detail_df["global_horiz_kwh_m2_j"] * detail_df["days_m"]).sum())
    ann_cap = float((detail_df["global_capteur_kwh_m2_j"] * detail_df["days_m"]).sum())
    ann_dispo = float((detail_df["global_dispo_kwh_m2_j"] * detail_df["days_m"]).sum())
    avg_horiz_wh = (ann_horiz * 1000.0 / total_days) if total_days > 0 else 0.0
    avg_cap_wh = (ann_cap * 1000.0 / total_days) if total_days > 0 else 0.0
    avg_dispo_wh = (ann_dispo * 1000.0 / total_days) if total_days > 0 else 0.0

    avg_text = float((detail_df["t_ext_c"] * detail_df["days_m"]).sum() / total_days) if total_days > 0 else 0.0
    avg_tenv = float((detail_df["t_env_stock_c"] * detail_df["days_m"]).sum() / total_days) if total_days > 0 else 0.0
    avg_tef_source = float((detail_df["tef_source_c"] * detail_df["days_m"]).sum() / total_days) if total_days > 0 else 0.0
    avg_tef = float((detail_df["tef_c"] * detail_df["days_m"]).sum() / total_days) if total_days > 0 else 0.0
    avg_tecs_consigne = float((detail_df["tecs_consigne_c"] * detail_df["days_m"]).sum() / total_days) if total_days > 0 else 0.0
    avg_tecs = float((detail_df["tecs_c"] * detail_df["days_m"]).sum() / total_days) if total_days > 0 else 0.0
    avg_vecs = float((pd.Series([float(r["vecs_l_j"]) for r in rows]) * pd.Series(detail_df["days_m"])).sum() / total_days) if total_days > 0 else 0.0
    avg_besoin_j = becs_year / total_days if total_days > 0 else 0.0
    avg_prod_j = qstu_year / total_days if total_days > 0 else 0.0

    total_row = {
        "month": "Total An",
        "days_m": total_days,
        "global_horiz_kwh_m2_j": ann_horiz,
        "global_capteur_kwh_m2_j": ann_cap,
        "coeff_incidence": "",
        "global_dispo_kwh_m2_j": ann_dispo,
        "t_ext_c": "",
        "t_env_stock_c": "",
        "tef_source_c": "",
        "tef_c": "",
        "tecs_consigne_c": "",
        "tecs_c": "",
        "vecs_l_j": vecs_year_m3,
        "besoin_ref_kwh_j": "",
        "t_sortie_stock_solaire_c": "",
        "pertes_stock_solaire_kwh_j": "",
        "production_primaire_kwh_j": prod_primaire_year,
        "besoin_primaire_kwh_j": "",
        "prod_cesc_base_kwh_j": prod_cesc_base_year,
        "delta_t_corr_et_c": "",
        "prod_cescet_avant_pertes_et_kwh_j": prod_cescet_avant_pertes_et_year,
        "volume_stock_l": "",
        "besoin_prod_kwh_j": becs_year,
        "besoin_total_kwh_j": besoin_total_year,
        "prod_solaire_kwh_j": qstu_year,
        "prod_cescet_finale_kwh_j": prod_cescet_finale_year,
        "becs_m": becs_year,
        "besoin_total_m": besoin_total_year,
        "becs_etendu_m": becs_etendu_year,
        "qstu_m": qstu_year,
        "couvsol_m": "",
        "pertes_boucle_kwh_j": pertes_boucle_year,
        "pertes_et_kwh_j": "",
        "taux_eco_en_m": summary["taux_eco_year"],
        "kg1_primaire_w_m2_k": "",
        "efficacite_transfert": "",
        "productivite_kwh_m2_mois": "",
    }
    avg_row = {
        "month": "Moyenne An",
        "days_m": "",
        "global_horiz_kwh_m2_j": avg_horiz_wh,
        "global_capteur_kwh_m2_j": avg_cap_wh,
        "coeff_incidence": "",
        "global_dispo_kwh_m2_j": avg_dispo_wh,
        "t_ext_c": avg_text,
        "t_env_stock_c": avg_tenv,
        "tef_source_c": avg_tef_source,
        "tef_c": avg_tef,
        "tecs_consigne_c": avg_tecs_consigne,
        "tecs_c": avg_tecs,
        "vecs_l_j": avg_vecs,
        "besoin_ref_kwh_j": "",
        "t_sortie_stock_solaire_c": "",
        "pertes_stock_solaire_kwh_j": "",
        "production_primaire_kwh_j": (prod_primaire_year / total_days) if total_days > 0 else 0.0,
        "besoin_primaire_kwh_j": "",
        "prod_cesc_base_kwh_j": (prod_cesc_base_year / total_days) if total_days > 0 else 0.0,
        "delta_t_corr_et_c": "",
        "prod_cescet_avant_pertes_et_kwh_j": (prod_cescet_avant_pertes_et_year / total_days) if total_days > 0 else 0.0,
        "volume_stock_l": avg_vecs,
        "besoin_prod_kwh_j": avg_besoin_j,
        "besoin_total_kwh_j": (besoin_total_year / total_days) if total_days > 0 else 0.0,
        "prod_solaire_kwh_j": avg_prod_j,
        "prod_cescet_finale_kwh_j": (prod_cescet_finale_year / total_days) if total_days > 0 else 0.0,
        "becs_m": avg_besoin_j,
        "besoin_total_m": (besoin_total_year / total_days) if total_days > 0 else 0.0,
        "becs_etendu_m": (becs_etendu_year / total_days) if total_days > 0 else 0.0,
        "qstu_m": avg_prod_j,
        "couvsol_m": summary["couvsol_year"],
        "pertes_boucle_kwh_j": "",
        "pertes_et_kwh_j": "",
        "taux_eco_en_m": summary["taux_eco_year"],
        "kg1_primaire_w_m2_k": "",
        "efficacite_transfert": "",
        "productivite_kwh_m2_mois": qstu_year / installation.surface_capteurs_m2 if installation.surface_capteurs_m2 > 0 else 0.0,
    }
    return pd.concat([detail_df, pd.DataFrame([total_row, avg_row])], ignore_index=True)


def build_solo_display_df(detail_df: pd.DataFrame) -> pd.DataFrame:
    if "pertes_et_kwh_j" not in detail_df.columns:
        detail_df = detail_df.copy()
        detail_df["pertes_et_kwh_j"] = pd.NA
    if "production_primaire_kwh_j" not in detail_df.columns:
        detail_df = detail_df.copy()
        detail_df["production_primaire_kwh_j"] = pd.NA
    cols = [
        "month",
        "global_horiz_kwh_m2_j",
        "global_capteur_kwh_m2_j",
        "global_dispo_kwh_m2_j",
        "t_ext_c",
        "t_env_stock_c",
        "tef_c",
        "vecs_l_j",
        "tecs_consigne_c",
        "besoin_prod_kwh_j",
        "production_primaire_kwh_j",
        "prod_solaire_kwh_j",
        "couvsol_m",
        "pertes_boucle_kwh_j",
        "besoin_total_kwh_j",
        "taux_eco_en_m",
    ]
    df = detail_df[cols].copy()
    df.columns = [
        "Mois",
        "Global Horiz (Wh/m2.jour)",
        "Global Capteur (Wh/m2.jour)",
        "Global dispo (Wh/m2.jour)",
        "T° extérieure (°C)",
        "T° env stock (°C)",
        "Temp EF",
        "Volume",
        "Temp ECS",
        "Besoins production (kWh/jour)",
        "Production primaire (kWh/jour)",
        "Production solaire (kWh/jour)",
        "Taux couv solaire(%)",
        "Pertes bouclage (kWh/jour)",
        "Besoins totaux (kWh/jour)",
        "Taux économie energie (%)",
    ]
    monthly_mask = df["Mois"].isin(MONTHS)
    for c in ["Global Horiz (Wh/m2.jour)", "Global Capteur (Wh/m2.jour)", "Global dispo (Wh/m2.jour)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[monthly_mask, c] = df.loc[monthly_mask, c] * 1000.0
    for c in ["Taux couv solaire(%)", "Taux économie energie (%)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce") * 100.0
    for c in [c for c in df.columns if c != "Mois"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def estimate_pertes_bouclage_mwh_an(
    rows: list[dict],
    installation: solo_v0_mod.InstallationSoloV0,
) -> float:
    mois_data = [
        solo_v0_mod.MoisSoloV0(
            mois=i + 1,
            vecs_l_j=float(r.get("vecs_l_j", 0.0)),
            tecs_prod_c=float(r.get("tecs_m", 60.0)),
            tef_c=float(r.get("tef_m", 12.0)),
            text_c=float(r.get("text_m", 0.0)),
            r_global_plan_kwh_m2_j=float(r.get("r_global_plan_kwh_m2_j", 0.0)),
            pertes_boucle_kwh_j=0.0,
        )
        for i, r in enumerate(rows)
    ]
    text_min = min((m.text_c for m in mois_data), default=0.0)
    total_kwh = 0.0
    for i, m in enumerate(mois_data):
        jours = int(rows[i].get("days_m", DAYS_BY_MONTH[i]))
        pertes_kwh_j = solo_v0_mod.pertes_bouclage_kwh_j(installation, m, text_min)
        total_kwh += pertes_kwh_j * jours
    return total_kwh / 1000.0


def run_solo_scenario(
    rows_for_calc: list[dict],
    installation: solo_v0_mod.InstallationSoloV0,
    pertes_boucle_kwh_j: float,
    mode_schema: str,
    ratio_ecs_max10_sur_j: float,
    kget_w_k: float,
    pech_et1_w_k: float,
    debit_et_m3_h: float,
) -> tuple[pd.DataFrame, dict]:
    return run_solo_v0(
        rows=rows_for_calc,
        installation=installation,
        pertes_boucle_kwh_j=pertes_boucle_kwh_j,
        mode_schema=mode_schema,
        ratio_ecs_max10_sur_j=ratio_ecs_max10_sur_j,
        kget_w_k=kget_w_k,
        pech_et1_w_k=pech_et1_w_k,
        debit_et_m3_h=debit_et_m3_h,
    )


