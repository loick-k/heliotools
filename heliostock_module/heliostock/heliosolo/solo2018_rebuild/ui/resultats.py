from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import heliostock.heliosolo.solo2018_rebuild.core.solo_v0_engine as solo_v0_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import DAYS_BY_MONTH, MONTHS, RATIOS_POINTE_ECS_LABELS
from heliostock.heliosolo.solo2018_rebuild.services.profiles import (
    apply_meteo_impose_to_rows as _apply_meteo_impose_to_rows,
    apply_profiles_to_rows as _apply_profiles_to_rows,
    calc_tef_series as _calc_tef_series,
    recompute_vecs_production_from_distribution as _recompute_vecs_production_from_distribution,
)
from heliostock.heliosolo.solo2018_rebuild.services.scenario import (
    build_solo_display_df as _build_solo_display_df,
    estimate_pertes_bouclage_mwh_an as _estimate_pertes_bouclage_mwh_an,
    run_solo_scenario as _run_solo_scenario,
)
from heliostock.heliosolo.solo2018_rebuild.ui.charts import (
    build_besoins_production_chart,
    build_couverture_chart,
    build_rayonnement_chart,
    build_tsortie_chart,
    build_tsortie_dataframe,
)
from heliostock.heliosolo.solo2018_rebuild.ui.components import render_kv_table as _render_kv_table
from heliostock.heliosolo.solo2018_rebuild.ui.context import ResultatsContext
from heliostock.heliosolo.solo2018_rebuild.utils import annual_sum_monthly as _annual_sum_monthly, fmt_num as _fmt_num


def render_resultats(context: ResultatsContext) -> None:
    description = context.description
    besoins = context.besoins
    hydraulique = context.hydraulique
    bouclage = context.bouclage
    stockage = context.stockage
    capteurs = context.capteurs
    settings = context.settings
    app_config = context.app_config

    a1 = capteurs.a1
    a2 = capteurs.a2
    algo_corr_incidence = settings.algo_corr_incidence
    algo_sballon = stockage.algo_sballon
    appliquer_corr_incidence = settings.appliquer_corr_incidence
    azimut_deg_sud = capteurs.azimut_deg_sud
    b_capteur = capteurs.b_capteur
    cas_verification_meteo = description.cas_verification_meteo
    project_name = str(description.project_name).strip()
    coeff0_ci = settings.coeff0_ci
    coeff1_ci = settings.coeff1_ci
    coeff3_ci = settings.coeff3_ci
    conso_mode = besoins.conso_mode
    cr_stock_effectif_ui = stockage.cr_stock_effectif_ui
    cr_stock_wh_l_k_j = stockage.cr_stock_wh_l_k_j
    debit_bouclage_l_h = bouclage.debit_bouclage_l_h
    debit_et_m3_h = settings.debit_et_m3_h
    delta_tmax_bouclage_k = bouclage.delta_tmax_bouclage_k
    epais_iso_stock_solaire_cm = stockage.epais_iso_stock_solaire_cm
    inclinaison_deg = capteurs.inclinaison_deg
    k_capteur = capteurs.k_capteur
    kget_w_k = hydraulique.kget_w_k
    kl_bouclage_w_m_k = bouclage.kl_bouclage_w_m_k
    kl_boucle_bon_w_m_k = bouclage.kl_boucle_bon_w_m_k
    kl_boucle_mauvais_w_m_k = bouclage.kl_boucle_mauvais_w_m_k
    kl_boucle_moyen_w_m_k = bouclage.kl_boucle_moyen_w_m_k
    kl_primaire_w_m_k = hydraulique.kl_primaire_w_m_k
    lambda_iso_stock_solaire_w_m_k = stockage.lambda_iso_stock_solaire_w_m_k
    long1_boucle_bon_m_par_unite = bouclage.long1_boucle_bon_m_par_unite
    long1_boucle_mauvais_m_par_unite = bouclage.long1_boucle_mauvais_m_par_unite
    long1_boucle_moyen_m_par_unite = bouclage.long1_boucle_moyen_m_par_unite
    long_bouclage_m = bouclage.long_bouclage_m
    long_primaire_m = hydraulique.long_primaire_m
    meteo_impose_map = description.meteo_impose_map
    mode_kt_primaire = hydraulique.mode_kt_primaire
    mode_meteo_label = description.mode_meteo_label
    mode_meteo_verification = description.mode_meteo_verification
    mode_pertes_boucle = bouclage.mode_pertes_boucle
    mode_pertes_boucle_label = bouclage.mode_pertes_boucle_label
    mode_rdispo_impose = description.mode_rdispo_impose
    mode_schema = hydraulique.mode_schema
    mode_schema_label = hydraulique.mode_schema_label
    modele_geometrie_ballon = stockage.modele_geometrie_ballon
    modele_stock_label = stockage.modele_stock_label
    modele_stock_solaire = stockage.modele_stock_solaire
    modele_v_eau_chaude = besoins.modele_v_eau_chaude
    n0 = capteurs.n0
    nb_ballons_stock = stockage.nb_ballons_stock
    pech11_w_m2_k = hydraulique.pech11_w_m2_k
    pech_et1_w_k = settings.pech_et1_w_k
    pertes_boucle_kwh_j = bouclage.pertes_boucle_kwh_j
    pertes_boucle_monthly_map = bouclage.pertes_boucle_monthly_map
    profil_hz = description.profil_hz
    ratio_ecs_max10_sur_j = hydraulique.ratio_ecs_max10_sur_j
    ratio_pointe_ecs_profile = hydraulique.ratio_pointe_ecs_profile
    site_lat_deg = description.site_lat_deg
    surface_capteurs_m2 = capteurs.surface_capteurs_m2
    t_env_stock_used_c = stockage.t_env_stock_used_c
    tecs_const_c = besoins.tecs_const_c
    tecs_dis_const_c = besoins.tecs_dis_const_c
    tecs_dis_mode = besoins.tecs_dis_mode
    tecs_dis_monthly_map = besoins.tecs_dis_monthly_map
    tecs_mode = besoins.tecs_mode
    tecs_monthly_map = besoins.tecs_monthly_map
    tef_manual_c = besoins.tef_manual_c
    tef_mode = besoins.tef_mode
    tef_mode_label = besoins.tef_mode_label
    tef_monthly_map = besoins.tef_monthly_map
    tenv_base_c = stockage.tenv_base_c
    tenv_mode = stockage.tenv_mode
    tenv_monthly_map = stockage.tenv_monthly_map
    tmax_stock_c = stockage.tmax_stock_c
    type_bouclage = bouclage.type_bouclage
    type_bouclage_label = bouclage.type_bouclage_label
    type_circulation = hydraulique.type_circulation
    type_circulation_label = hydraulique.type_circulation_label
    type_echangeur = hydraulique.type_echangeur
    type_echangeur_label = hydraulique.type_echangeur_label
    type_installation_label = hydraulique.type_installation_label
    v1_stock_solaire_l = stockage.v1_stock_solaire_l
    vecs_const_l_j = besoins.vecs_const_l_j
    vecs_monthly_map = besoins.vecs_monthly_map
    vecs_unite_ref_l_j = description.vecs_unite_ref_l_j
    ville_ref = description.ville_ref
    volume_stock_l = stockage.volume_stock_l
    zip_path = description.zip_path
    if st.session_state.get("results_visible", False):
        try:
            profiled_rows = _apply_profiles_to_rows(
                rows=app_config.ecs_rows_df.to_dict(orient="records"),
                modele_v_eau_chaude=modele_v_eau_chaude,
                conso_mode=conso_mode,
                vecs_const_l_j=vecs_const_l_j,
                vecs_monthly_map=vecs_monthly_map,
                tecs_dis_mode=tecs_dis_mode,
                tecs_dis_const_c=tecs_dis_const_c,
                tecs_dis_monthly_map=tecs_dis_monthly_map,
                tecs_mode=tecs_mode,
                tecs_const_c=tecs_const_c,
                tecs_monthly_map=tecs_monthly_map,
                tef_mode=tef_mode,
                tef_manual_c=tef_manual_c,
                tef_monthly_map=tef_monthly_map,
                tenv_mode=tenv_mode,
                tenv_base_c=tenv_base_c,
                tenv_monthly_map=tenv_monthly_map,
            )
            rows_for_calc = profiled_rows
            if mode_meteo_verification:
                rows_for_calc = _apply_meteo_impose_to_rows(rows_for_calc, meteo_impose_map)
            if tef_mode in ("ESM2", "ESM2Plus3"):
                text_series_calc = [float(r["text_m"]) for r in rows_for_calc]
                days_series_calc = [int(r["days_m"]) for r in rows_for_calc]
                tef_series_calc = _calc_tef_series(
                    text_m_series=text_series_calc,
                    days_series=days_series_calc,
                    mode=tef_mode,
                )
                for idx, m in enumerate(MONTHS):
                    rows_for_calc[idx]["tef_m"] = float(tef_series_calc[idx])
                    rows_for_calc[idx]["tef_source_m"] = float(tef_series_calc[idx])
            else:
                for idx, _m in enumerate(MONTHS):
                    rows_for_calc[idx]["tef_source_m"] = float(rows_for_calc[idx].get("tef_m", tef_manual_c))
            if modele_v_eau_chaude == "distribution":
                rows_for_calc = _recompute_vecs_production_from_distribution(rows_for_calc)
            if mode_pertes_boucle == "saisie_kwh_j":
                for r in rows_for_calc:
                    r["pertes_boucle_input_kwh_j"] = float(pertes_boucle_monthly_map.get(str(r["month"]), 0.0))
            else:
                for r in rows_for_calc:
                    r["pertes_boucle_input_kwh_j"] = float(pertes_boucle_kwh_j)
            st.session_state["ecs_rows_df"] = pd.DataFrame(rows_for_calc)

            installation = solo_v0_mod.InstallationSoloV0(
                surface_capteurs_m2=surface_capteurs_m2,
                volume_stock_l=volume_stock_l,
                b_capteur=float(b_capteur),
                k_capteur_w_m2_k=float(k_capteur),
                pech11_w_m2_k=pech11_w_m2_k,
                latitude_deg=site_lat_deg,
                inclinaison_deg=inclinaison_deg,
                azimut_deg=azimut_deg_sud,
                type_circulation=type_circulation,
                type_echangeur=type_echangeur,
                type_bouclage=type_bouclage,
                mode_kt_primaire=mode_kt_primaire,
                long_primaire_m=long_primaire_m,
                kl_primaire_w_m_k=kl_primaire_w_m_k,
                modele_stock_solaire=modele_stock_solaire,
                cr_stock_wh_l_k_j=cr_stock_wh_l_k_j,
                v1_stock_solaire_l=v1_stock_solaire_l,
                epais_iso_stock_solaire_cm=epais_iso_stock_solaire_cm,
                lambda_iso_stock_solaire_w_m_k=lambda_iso_stock_solaire_w_m_k,
                modele_geometrie_ballon=modele_geometrie_ballon,
                algo_sballon=algo_sballon,
                tmax_stock_c=tmax_stock_c,
                t_env_stock_c=t_env_stock_used_c,
                mode_pertes_bouclage=mode_pertes_boucle,
                vecs_unite_ref_l_j=vecs_unite_ref_l_j,
                debit_bouclage_l_h=debit_bouclage_l_h,
                delta_tmax_bouclage_k=delta_tmax_bouclage_k,
                long_bouclage_m=long_bouclage_m,
                kl_bouclage_w_m_k=kl_bouclage_w_m_k,
                long1_boucle_bon_m_par_unite=long1_boucle_bon_m_par_unite,
                long1_boucle_moyen_m_par_unite=long1_boucle_moyen_m_par_unite,
                long1_boucle_mauvais_m_par_unite=long1_boucle_mauvais_m_par_unite,
                kl_boucle_bon_w_m_k=kl_boucle_bon_w_m_k,
                kl_boucle_moyen_w_m_k=kl_boucle_moyen_w_m_k,
                kl_boucle_mauvais_w_m_k=kl_boucle_mauvais_w_m_k,
                appliquer_correction_incidence=appliquer_corr_incidence,
                coeff0_ci=coeff0_ci,
                coeff1_ci=coeff1_ci,
                coeff3_ci=coeff3_ci,
                algo_corr_incidence=algo_corr_incidence,
            )
            if mode_pertes_boucle == "saisie_kwh_j":
                pertes_bouclage_est_mwh_an = float(
                    sum(float(pertes_boucle_monthly_map.get(m, 0.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH))
                ) / 1000.0
            else:
                pertes_bouclage_est_mwh_an = _estimate_pertes_bouclage_mwh_an(
                    rows=rows_for_calc,
                    installation=installation,
                )
            detail_df, summary = _run_solo_scenario(
                rows_for_calc=rows_for_calc,
                installation=installation,
                pertes_boucle_kwh_j=pertes_boucle_kwh_j,
                mode_schema=mode_schema,
                ratio_ecs_max10_sur_j=float(ratio_ecs_max10_sur_j),
                kget_w_k=float(kget_w_k),
                pech_et1_w_k=float(pech_et1_w_k),
                debit_et_m3_h=float(debit_et_m3_h),
            )
        except Exception as exc:
            st.error(f"Erreur de calcul: {exc}")
        else:
            ville_label = cas_verification_meteo if mode_meteo_verification else ville_ref

            monthly_df = detail_df[detail_df["month"].isin(MONTHS)].copy()
            ann_hz = float((monthly_df["global_horiz_kwh_m2_j"] * monthly_df["days_m"]).sum())
            ann_cap = float((monthly_df["global_capteur_kwh_m2_j"] * monthly_df["days_m"]).sum())
            ann_dispo = float((monthly_df["global_dispo_kwh_m2_j"] * monthly_df["days_m"]).sum())
            days_tot = float(monthly_df["days_m"].sum())
            text_moy = float((monthly_df["t_ext_c"] * monthly_df["days_m"]).sum() / days_tot) if days_tot > 0 else 0.0
            tef_moy = float((monthly_df["tef_c"] * monthly_df["days_m"]).sum() / days_tot) if days_tot > 0 else 0.0
            tecs_moy = float((monthly_df["tecs_c"] * monthly_df["days_m"]).sum() / days_tot) if days_tot > 0 else 0.0
            tecs_dis_moy = (
                float(
                    sum(float(r.get("tecs_dis_m", r.get("tecs_m", 55.0))) * int(r["days_m"]) for r in rows_for_calc)
                    / max(1, sum(int(r["days_m"]) for r in rows_for_calc))
                )
                if rows_for_calc
                else 0.0
            )
            vecs_moy = (
                float(
                    sum(float(r["vecs_l_j"]) * int(r["days_m"]) for r in rows_for_calc)
                    / max(1, sum(int(r["days_m"]) for r in rows_for_calc))
                )
                if rows_for_calc
                else 0.0
            )

            besoins_rows = [
                ("Consommation définie", "À température de production" if modele_v_eau_chaude == "production" else "À température de distribution"),
                ("VECS moyen retenu", f"{_fmt_num(vecs_moy, 0)} L/j"),
                ("Température EF moyenne", f"{_fmt_num(tef_moy, 1)} degC"),
                ("Température ECS production", f"{_fmt_num(tecs_moy, 1)} degC"),
                ("Modélisation eau froide", tef_mode_label),
            ]
            if modele_v_eau_chaude == "distribution":
                besoins_rows.insert(4, ("Température ECS distribuée", f"{_fmt_num(tecs_dis_moy, 1)} degC"))

            circuit_rows = [
                ("Schéma ECS", "collectif"),
                ("Schéma calcul", mode_schema_label),
                ("Type installation", type_installation_label),
                ("Circuit primaire", type_circulation_label),
                ("Échangeur", type_echangeur_label),
                ("Puissance échangeur", f"{_fmt_num(pech11_w_m2_k, 0)} W/degC/m2"),
            ]
            if mode_kt_primaire == "lineaire":
                circuit_rows.extend([
                    ("Mode Kt primaire", "Saisie longueur et perte linéique"),
                    ("Longueur primaire", f"{_fmt_num(long_primaire_m, 1)} m"),
                    ("Perte linéique primaire", f"{_fmt_num(kl_primaire_w_m_k, 2)} W/m/degC"),
                ])
            if mode_schema == "cescet":
                circuit_rows.extend([
                    ("Profil pointe ECS", RATIOS_POINTE_ECS_LABELS.get(ratio_pointe_ecs_profile, ratio_pointe_ecs_profile)),
                    ("Ratio pointe ECS", f"{_fmt_num(ratio_ecs_max10_sur_j, 2)}"),
                    ("KGET", f"{_fmt_num(kget_w_k, 2)} W/degC"),
                    ("PEchET1 total", f"{_fmt_num(pech_et1_w_k, 0)} W/degC"),
                    ("Débit ET", f"{_fmt_num(debit_et_m3_h, 3)} m3/h"),
                ])

            if mode_pertes_boucle == "saisie_kwh_j":
                pertes_boucle_aff_kwh_j = float(
                    sum(float(pertes_boucle_monthly_map.get(m, 0.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH))
                ) / float(sum(DAYS_BY_MONTH))
            else:
                pertes_boucle_aff_kwh_j = float(pertes_boucle_kwh_j)
            bouclage_rows = [
                ("Type de bouclage", type_bouclage_label),
                ("Calcul des pertes", mode_pertes_boucle_label),
                ("Pertes boucle moyennes", f"{_fmt_num(pertes_boucle_aff_kwh_j, 2)} kWh/j"),
            ]

            stock_desc = f"{nb_ballons_stock} x {_fmt_num(v1_stock_solaire_l, 0)} L"
            stock_rows = [
                ("Volume stockage", f"{_fmt_num(volume_stock_l, 0)} L"),
                ("Composition stock", stock_desc),
                ("Modèle stock", modele_stock_label),
                ("T env stockage", f"{_fmt_num(t_env_stock_used_c, 1)} degC"),
                ("Tmax stockage", f"{_fmt_num(tmax_stock_c, 0)} degC"),
                ("CR stock", f"{_fmt_num(cr_stock_effectif_ui, 3)} Wh/L.j.degC"),
            ]

            capteur_rows = [
                ("Surface", f"{_fmt_num(surface_capteurs_m2, 0)} m2"),
                ("Inclinaison", f"{_fmt_num(inclinaison_deg, 0)} deg"),
                ("Orientation", f"{_fmt_num(azimut_deg_sud, 0)} deg / Sud"),
                ("n0 / a1 / a2", f"{_fmt_num(n0, 3)} / {_fmt_num(a1, 3)} / {_fmt_num(a2, 3)}"),
                ("Global capteur annuel", f"{_fmt_num(ann_cap, 1)} kWh/m2/an"),
            ]
            station_rows = [
                ("Source", profil_hz),
                ("Mode rayonnement", "RDisponible imposé" if mode_rdispo_impose else "Global capteur + incidence"),
                ("Station", ville_label),
                ("Fichier EPW", Path(zip_path).name),
                ("Global horiz annuel", f"{_fmt_num(ann_hz, 1)} kWh/m2/an"),
                ("Global dispo annuel", f"{_fmt_num(ann_dispo, 1)} kWh/m2/an"),
            ]

            bbouclage_annuel_kwh = float((monthly_df["pertes_boucle_kwh_j"] * monthly_df["days_m"]).sum())
            pertes_et_annuel_kwh = float((monthly_df.get("pertes_et_kwh_j", 0.0) * monthly_df["days_m"]).sum())
            besoins_thermiques_totaux_kwh = float(summary["besoin_total_year"])
            besoins_etendus_solarisables_kwh = float(summary.get("becs_etendu_year", summary["besoin_total_year"]))
            stockage_specifique_l_m2 = float(volume_stock_l) / float(surface_capteurs_m2) if float(surface_capteurs_m2) > 0 else 0.0
            conso_specifique_l_j_m2 = float(vecs_moy) / float(surface_capteurs_m2) if float(surface_capteurs_m2) > 0 else 0.0
            productivite_annuelle_kwh_m2_an = float(summary["qstu_year"]) / float(surface_capteurs_m2) if float(surface_capteurs_m2) > 0 else 0.0
            summer_df = monthly_df[monthly_df["month"].isin(["Mai", "Jun", "Jul", "Aou", "Sep"])]
            couvsol_max_estivale = float(summer_df["couvsol_m"].max()) if not summer_df.empty else 0.0
            mois_max_ete = str(monthly_df.loc[summer_df["couvsol_m"].idxmax(), "month"]) if not summer_df.empty else "-"

            esol_base_kwh_an: float | None = None
            esol_etendu_kwh_an: float | None = None
            gain_bouclage_indirect_kwh_an: float | None = None
            if type_bouclage == "apport_indirect":
                try:
                    installation_base = replace(installation, type_bouclage="aucun_apport")
                    _detail_base, summary_base = _run_solo_scenario(
                        rows_for_calc=rows_for_calc,
                        installation=installation_base,
                        pertes_boucle_kwh_j=pertes_boucle_kwh_j,
                        mode_schema=mode_schema,
                        ratio_ecs_max10_sur_j=float(ratio_ecs_max10_sur_j),
                        kget_w_k=float(kget_w_k),
                        pech_et1_w_k=float(pech_et1_w_k),
                        debit_et_m3_h=float(debit_et_m3_h),
                    )
                    esol_base_kwh_an = float(summary_base["qstu_year"])
                    esol_etendu_kwh_an = float(summary["qstu_year"])
                    gain_bouclage_indirect_kwh_an = esol_etendu_kwh_an - esol_base_kwh_an
                except Exception:
                    esol_base_kwh_an = None
                    esol_etendu_kwh_an = None
                    gain_bouclage_indirect_kwh_an = None

            chart_besoins_prod = build_besoins_production_chart(detail_df, MONTHS)
            chart_couverture = build_couverture_chart(detail_df, MONTHS)
            chart_tsol = build_tsortie_dataframe(
                detail_df=detail_df,
                months=MONTHS,
                cp_wh_l_k=solo_v0_mod.CP_EAU_WH_L_K,
                tecs_moy_c=float(tecs_moy),
                tmax_stock_c=float(tmax_stock_c),
            )
            chart_tsortie = build_tsortie_chart(chart_tsol, MONTHS)
            chart_rayonnement = build_rayonnement_chart(detail_df, MONTHS)

            display_df = _build_solo_display_df(detail_df)
            csv_detail = detail_df.copy()
            csv_detail.insert(0, "mode_meteo", mode_meteo_label)
            csv_detail.insert(1, "station_ou_cas", ville_label)
            csv_detail.insert(2, "schema_hydraulique", mode_schema_label)
            csv_detail.insert(3, "type_bouclage", type_bouclage_label)
            csv_detail.insert(4, "mode_pertes_bouclage", mode_pertes_boucle_label)
            csv_detail.insert(5, "param_surface_capteurs_m2", float(surface_capteurs_m2))
            csv_detail.insert(6, "param_volume_stock_l", float(volume_stock_l))
            csv_detail.insert(7, "param_n0", float(n0))
            csv_detail.insert(8, "param_a1", float(a1))
            csv_detail.insert(9, "param_a2", float(a2))
            csv_bytes = csv_detail.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")

            controles: list[tuple[str, str]] = []
            if type_bouclage == "apport_indirect" and bbouclage_annuel_kwh <= 1e-6:
                controles.append(("warning", "Bouclage avec apport indirect, mais pertes de bouclage nulles : ce choix ne modifie pas la production."))
            if float(tmax_stock_c) < float(tecs_moy):
                controles.append(("warning", "Tmax stockage est inférieure à la température ECS moyenne : vérifier l'interprétation des températures."))
            if stockage_specifique_l_m2 < 50.0:
                controles.append(("info", f"Ratio V/S inférieur à 50 L/m2 : {_fmt_num(stockage_specifique_l_m2, 1)} L/m2."))
            if couvsol_max_estivale > 0.85:
                controles.append(("info", f"Couverture estivale maximale supérieure à 85 % : {_fmt_num(couvsol_max_estivale * 100.0, 1)} %."))
            if mode_schema == "cescet":
                controles.append(("info", "Mode CESCET détaillé actif : la production peut différer d'une sortie SOLO2018 stricte."))

            mode_schema_badge = "CESCET détaillé" if mode_schema == "cescet" else "CESC"
            header_prefix = f"{project_name} | " if project_name else ""
            header_detail = (
                f"{header_prefix}{ville_label} | {mode_schema_badge} | {_fmt_num(surface_capteurs_m2, 1)} m2 | "
                f"{_fmt_num(vecs_moy, 0)} L/j | Stockage {_fmt_num(volume_stock_l, 0)} L | "
                f"{date.today().strftime('%d/%m/%Y')}"
            )
            st.markdown(
                f"""
                <div class="solo-header">
                  <span>Heliopilot - Moteur SOLO2018</span>
                  <span>{header_detail}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            res_tabs = st.tabs(["Synthèse", "Analyse mensuelle", "Configuration"])

            with res_tabs[0]:
                st.subheader("Synthèse des résultats")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Besoins thermiques totaux", f"{besoins_thermiques_totaux_kwh / 1000.0:,.1f} MWh/an".replace(",", " "))
                k2.metric("Besoins ECS", f"{summary['becs_year'] / 1000.0:,.1f} MWh/an".replace(",", " "))
                if type_bouclage_label == "Aucun bouclage sanitaire":
                    k3.metric("Production solaire annuelle", f"{summary['qstu_year'] / 1000.0:,.1f} MWh/an".replace(",", " "))
                else:
                    k3.metric("Besoins bouclage", f"{bbouclage_annuel_kwh / 1000.0:,.1f} MWh/an".replace(",", " "))
                    k4.metric("Production solaire annuelle", f"{summary['qstu_year'] / 1000.0:,.1f} MWh/an".replace(",", " "))
                k5, k6, k7, k8 = st.columns(4)
                k5.metric("Productivité annuelle", f"{productivite_annuelle_kwh_m2_an:,.0f} kWh/m2.an".replace(",", " "))
                k6.metric("Ratio V/S", f"{stockage_specifique_l_m2:,.1f} L/m2".replace(",", " "))
                k7.metric("Taux de couverture annuel", f"{summary['couvsol_year']:.1%}")
                k8.metric("Couverture max été", f"{couvsol_max_estivale:.1%}")
                if type_bouclage == "apport_indirect":
                    st.metric(
                        "Gain lié au bouclage indirect",
                        "-"
                        if gain_bouclage_indirect_kwh_an is None
                        else f"{gain_bouclage_indirect_kwh_an / 1000.0:,.1f} MWh/an".replace(",", " "),
                    )

                if controles:
                    with st.container(border=True):
                        st.markdown("### Contrôles de cohérence")
                        for level, message in controles:
                            if level == "warning":
                                st.warning(message)
                            else:
                                st.info(message)

                g1, g2 = st.columns(2)
                with g1:
                    st.markdown("### Besoins et production mensuelle")
                    st.altair_chart(chart_besoins_prod, width="stretch")
                with g2:
                    st.markdown("### Taux de couverture mensuel")
                    st.caption(f"Max été : {_fmt_num(couvsol_max_estivale * 100.0, 1)} % ({mois_max_ete})")
                    st.altair_chart(chart_couverture, width="stretch")
                g3, g4 = st.columns(2)
                with g3:
                    st.markdown("### Température solaire équivalente")
                    st.caption("Température reconstruite à partir de la production mensuelle : ce n'est pas une température maximale réelle du stock.")
                    st.altair_chart(chart_tsortie, width="stretch")
                with g4:
                    st.markdown("### Rayonnement disponible")
                    st.altair_chart(chart_rayonnement, width="stretch")


            with res_tabs[1]:
                st.subheader("Analyse mensuelle")
                if mode_meteo_verification:
                    ann_hz_impose = _annual_sum_monthly([meteo_impose_map.get(m, {}).get("gh", 0.0) for m in MONTHS])
                    ann_cap_impose = _annual_sum_monthly([meteo_impose_map.get(m, {}).get("cap", 0.0) for m in MONTHS])
                    ann_dispo_impose = _annual_sum_monthly([meteo_impose_map.get(m, {}).get("dispo", 0.0) for m in MONTHS])
                    with st.expander("Contrôle comparaison SOLO2018", expanded=False):
                        _render_kv_table("Points de contrôle", [
                            ("Table imposée Global horiz", f"{_fmt_num(ann_hz_impose, 1)} kWh/m2/an"),
                            ("Table imposée Global capteur", f"{_fmt_num(ann_cap_impose, 1)} kWh/m2/an"),
                            ("Table imposée RDisponible", f"{_fmt_num(ann_dispo_impose, 1)} kWh/m2/an"),
                            ("Global capteur moteur", f"{_fmt_num(ann_cap, 1)} kWh/m2/an"),
                            ("RDisponible moteur", f"{_fmt_num(ann_dispo, 1)} kWh/m2/an"),
                            ("Écart RDisponible", f"{_fmt_num(ann_dispo - ann_dispo_impose, 3)} kWh/m2/an"),
                        ])

                display_export_df = display_df.copy()
                optional_cols = [
                    "Global Horiz (Wh/m2.jour)",
                    "Global Capteur (Wh/m2.jour)",
                    "Global dispo (Wh/m2.jour)",
                    "T° env stock (°C)",
                    "Production primaire (kWh/jour)",
                    "Pertes bouclage (kWh/jour)",
                    "Besoins totaux (kWh/jour)",
                    "Taux économie energie (%)",
                ]
                default_optional_cols = []
                if bbouclage_annuel_kwh > 1e-6:
                    default_optional_cols = [
                        "Pertes bouclage (kWh/jour)",
                        "Taux économie energie (%)",
                    ]
                shown_optional_cols = st.multiselect(
                    "Colonnes optionnelles à afficher",
                    options=optional_cols,
                    default=default_optional_cols,
                )
                hidden_optional_cols = [c for c in optional_cols if c not in shown_optional_cols]
                display_export_df = display_export_df.drop(columns=hidden_optional_cols, errors="ignore")
                st.caption("Ligne Total An : Volume en m3/an ; besoins et productions en kWh/an.")
                display_fmt = display_export_df.copy()
                for c in display_fmt.columns:
                    if c == "Mois":
                        continue
                    if c.endswith("(%)"):
                        display_fmt[c] = display_fmt[c].apply(lambda x: "" if pd.isna(x) else _fmt_num(x, 1))
                    elif "Wh/m2.jour" in c:
                        display_fmt[c] = display_fmt[c].apply(lambda x: "" if pd.isna(x) else _fmt_num(x, 0))
                    elif "°C" in c or "degC" in c:
                        display_fmt[c] = display_fmt[c].apply(lambda x: "" if pd.isna(x) else _fmt_num(x, 1))
                    elif "Volume" in c:
                        display_fmt[c] = display_fmt[c].apply(lambda x: "" if pd.isna(x) else _fmt_num(x, 0))
                    else:
                        display_fmt[c] = display_fmt[c].apply(lambda x: "" if pd.isna(x) else _fmt_num(x, 1))
                month_index = {m: i for i, m in enumerate(MONTHS)}

                def _row_style(row: pd.Series) -> list[str]:
                    mois = str(row.get("Mois", ""))
                    if mois in month_index:
                        bg = "#f7f9fc" if (month_index[mois] % 2 == 0) else "#eef3f9"
                        return [f"background-color: {bg}"] * len(row)
                    if mois == "Total An":
                        return ["background-color: #f2d7d5; font-weight: 600;"] * len(row)
                    if mois == "Moyenne An":
                        return ["background-color: #f9ebea; font-weight: 600;"] * len(row)
                    return [""] * len(row)

                st.dataframe(display_fmt.style.apply(_row_style, axis=1), width="stretch")
                st.download_button(
                    "Télécharger le CSV détaillé des valeurs calculées",
                    data=csv_bytes,
                    file_name=f"solo2018_detail_calcul_{date.today().strftime('%Y-%m-%d')}.csv",
                    mime="text/csv",
                )

            with res_tabs[2]:
                st.subheader("Configuration")
                st.caption(f"{ville_label} | {_fmt_num(surface_capteurs_m2, 1)} m2 | {_fmt_num(volume_stock_l, 0)} L | ECS {_fmt_num(tecs_moy, 1)} degC | {_fmt_num(vecs_moy, 0)} L/j | {mode_schema_label} | {type_bouclage_label}")
                with st.expander("Station météo", expanded=False):
                    _render_kv_table("Station météo", station_rows)
                with st.expander("Besoins ECS", expanded=False):
                    _render_kv_table("Besoins ECS", besoins_rows)
                with st.expander("Capteurs solaires", expanded=False):
                    _render_kv_table("Capteurs solaires", capteur_rows)
                with st.expander("Circuit hydraulique", expanded=False):
                    _render_kv_table("Circuit hydraulique", circuit_rows)
                if type_bouclage_label != "Aucun bouclage sanitaire":
                    with st.expander("Bouclage sanitaire", expanded=False):
                        _render_kv_table("Bouclage sanitaire", bouclage_rows)
                with st.expander("Stockage solaire", expanded=False):
                    _render_kv_table("Stockage solaire", stock_rows)
                if mode_schema == "cescet":
                    with st.expander("Eau technique", expanded=False):
                        _render_kv_table("Eau technique", [
                            ("KGET", f"{_fmt_num(kget_w_k, 2)} W/degC"),
                            ("PEchET1 total", f"{_fmt_num(pech_et1_w_k, 0)} W/degC"),
                            ("Débit ET", f"{_fmt_num(debit_et_m3_h, 3)} m3/h"),
                            ("Pertes ET annuelles", f"{_fmt_num(pertes_et_annuel_kwh / 1000.0, 2)} MWh/an"),
                        ])

    else:
        st.info("Lance le calcul depuis l'onglet 2) Modelisation pour afficher les resultats.")


