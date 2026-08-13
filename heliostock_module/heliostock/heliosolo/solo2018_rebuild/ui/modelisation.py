from __future__ import annotations


import pandas as pd
import streamlit as st

import heliostock.heliosolo.solo2018_rebuild.core.solo_v0_engine as solo_v0_mod
import heliostock.heliosolo.solo2018_rebuild.meteo.epw_reader as epw_reader_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import (
    DAYS_BY_MONTH,
    MONTHS,
    SOLO_CI_ALGO_DEFAULT,
    SOLO_CI_COEFF0_DEFAULT,
    SOLO_CI_COEFF1_DEFAULT,
    SOLO_CI_COEFF3_DEFAULT,
    SOLO2018_T_ENV_STOCK_STRICT_C,
)
from heliostock.heliosolo.solo2018_rebuild.services.app_config import AppConfig
from heliostock.heliosolo.solo2018_rebuild.services.profiles import (
    apply_meteo_impose_to_rows as _apply_meteo_impose_to_rows,
    apply_profiles_to_rows as _apply_profiles_to_rows,
    calc_tef_series as _calc_tef_series,
    recompute_vecs_production_from_distribution as _recompute_vecs_production_from_distribution,
)
from heliostock.heliosolo.solo2018_rebuild.services.scenario import estimate_pertes_bouclage_mwh_an as _estimate_pertes_bouclage_mwh_an
from heliostock.heliosolo.solo2018_rebuild.ui.context import ModelisationContext, ResultatsContext, ResultatsSettings
from heliostock.heliosolo.solo2018_rebuild.ui.modelisation_besoins import render_besoins_block
from heliostock.heliosolo.solo2018_rebuild.ui.modelisation_bouclage import render_bouclage_block
from heliostock.heliosolo.solo2018_rebuild.ui.modelisation_capteurs import render_capteurs_block
from heliostock.heliosolo.solo2018_rebuild.ui.modelisation_hydraulique import render_hydraulique_block
from heliostock.heliosolo.solo2018_rebuild.ui.modelisation_stockage import render_stockage_block
from heliostock.heliosolo.solo2018_rebuild.utils import fmt_num as _fmt_num, to_float as _to_float, weighted_mean as _weighted_mean


def _ensure_session_option(key: str, options: list[str], default: str | None = None) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = default if default is not None else options[0]


def render_modelisation(context: ModelisationContext) -> ResultatsContext:
    description = context.description
    app_config = context.app_config
    mode_meteo_label = description.mode_meteo_label
    mode_meteo_verification = description.mode_meteo_verification
    ville_ref = description.ville_ref
    cas_verification_meteo = description.cas_verification_meteo
    profil_hz = description.profil_hz
    zip_path = description.zip_path
    site_lat_deg = description.site_lat_deg
    rdispo_monthly_map = description.rdispo_monthly_map
    meteo_impose_map = description.meteo_impose_map
    mode_rayonnement_label = description.mode_rayonnement_label
    mode_rdispo_impose = description.mode_rdispo_impose
    vecs_unite_ref_l_j = description.vecs_unite_ref_l_j
    besoins_state = render_besoins_block(mode_meteo_verification, meteo_impose_map)
    conso_mode = besoins_state.conso_mode
    tef_mode_label = besoins_state.tef_mode_label
    tef_mode = besoins_state.tef_mode
    tef_monthly_map = besoins_state.tef_monthly_map
    vecs_monthly_map = besoins_state.vecs_monthly_map
    tecs_mode = besoins_state.tecs_mode
    tecs_const_c = besoins_state.tecs_const_c
    tecs_monthly_map = besoins_state.tecs_monthly_map
    tef_manual_c = besoins_state.tef_manual_c
    modele_v_eau_chaude = besoins_state.modele_v_eau_chaude
    vecs_const_l_j = besoins_state.vecs_const_l_j
    tecs_dis_mode = besoins_state.tecs_dis_mode
    tecs_dis_const_c = besoins_state.tecs_dis_const_c
    tecs_dis_monthly_map = besoins_state.tecs_dis_monthly_map

    circuit_block_container = st.container()
    bouclage_block_container = st.container()
    stockage_block_container = st.container()

    bouclage_state = render_bouclage_block(bouclage_block_container, mode_meteo_verification)
    type_bouclage_label = bouclage_state.type_bouclage_label
    type_bouclage = bouclage_state.type_bouclage
    mode_pertes_boucle_label = bouclage_state.mode_pertes_boucle_label
    mode_pertes_boucle = bouclage_state.mode_pertes_boucle
    debit_bouclage_l_h = bouclage_state.debit_bouclage_l_h
    delta_tmax_bouclage_k = bouclage_state.delta_tmax_bouclage_k
    long_bouclage_m = bouclage_state.long_bouclage_m
    kl_bouclage_w_m_k = bouclage_state.kl_bouclage_w_m_k
    long1_boucle_bon_m_par_unite = bouclage_state.long1_boucle_bon_m_par_unite
    long1_boucle_moyen_m_par_unite = bouclage_state.long1_boucle_moyen_m_par_unite
    long1_boucle_mauvais_m_par_unite = bouclage_state.long1_boucle_mauvais_m_par_unite
    kl_boucle_bon_w_m_k = bouclage_state.kl_boucle_bon_w_m_k
    kl_boucle_moyen_w_m_k = bouclage_state.kl_boucle_moyen_w_m_k
    kl_boucle_mauvais_w_m_k = bouclage_state.kl_boucle_mauvais_w_m_k
    pertes_boucle_monthly_map = bouclage_state.pertes_boucle_monthly_map
    pertes_boucle_kwh_j = bouclage_state.pertes_boucle_kwh_j
    bouclage_pertes_placeholder = bouclage_state.bouclage_pertes_placeholder

    stockage_state = render_stockage_block(stockage_block_container)
    nb_ballons_stock = stockage_state.nb_ballons_stock
    v1_stock_solaire_l = stockage_state.v1_stock_solaire_l
    volume_stock_l = stockage_state.volume_stock_l
    modele_stock_label = stockage_state.modele_stock_label
    modele_stock_solaire = stockage_state.modele_stock_solaire
    tenv_mode = stockage_state.tenv_mode
    tenv_base_c = stockage_state.tenv_base_c
    tenv_monthly_map = stockage_state.tenv_monthly_map
    cr_stock_wh_l_k_j = stockage_state.cr_stock_wh_l_k_j
    tmax_stock_c = stockage_state.tmax_stock_c
    epais_iso_stock_solaire_cm = stockage_state.epais_iso_stock_solaire_cm
    lambda_iso_stock_solaire_w_m_k = stockage_state.lambda_iso_stock_solaire_w_m_k
    modele_geometrie_ballon = stockage_state.modele_geometrie_ballon
    algo_sballon = stockage_state.algo_sballon
    cr_stock_effectif_ui = stockage_state.cr_stock_effectif_ui
    t_env_stock_used_c = stockage_state.t_env_stock_used_c

    hydraulique_state = render_hydraulique_block(circuit_block_container)
    mode_schema_label = hydraulique_state.mode_schema_label
    mode_schema = hydraulique_state.mode_schema
    ratio_pointe_ecs_profile = hydraulique_state.ratio_pointe_ecs_profile
    ratio_ecs_max10_sur_j = hydraulique_state.ratio_ecs_max10_sur_j
    mode_kt_primaire = hydraulique_state.mode_kt_primaire
    long_primaire_m = hydraulique_state.long_primaire_m
    kl_primaire_w_m_k = hydraulique_state.kl_primaire_w_m_k
    type_installation_label = hydraulique_state.type_installation_label
    type_circulation = hydraulique_state.type_circulation
    type_echangeur = hydraulique_state.type_echangeur
    type_circulation_label = hydraulique_state.type_circulation_label
    type_echangeur_label = hydraulique_state.type_echangeur_label
    pech11_w_m2_k = hydraulique_state.pech11_w_m2_k
    kget_w_k = hydraulique_state.kget_w_k
    pech_et1_w_m2_k = hydraulique_state.pech_et1_w_m2_k
    mode_debit_et_label = hydraulique_state.mode_debit_et_label
    debit1_et_l_h_m2 = hydraulique_state.debit1_et_l_h_m2
    debit_et_total_m3_h_manual = hydraulique_state.debit_et_total_m3_h_manual

    capteurs_state = render_capteurs_block()
    surface_unitaire_capteur_m2 = capteurs_state.surface_unitaire_capteur_m2
    nb_capteurs = capteurs_state.nb_capteurs
    surface_capteurs_m2 = capteurs_state.surface_capteurs_m2
    n0 = capteurs_state.n0
    a1 = capteurs_state.a1
    a2 = capteurs_state.a2
    b_capteur = capteurs_state.b_capteur
    k_capteur = capteurs_state.k_capteur
    inclinaison_deg = capteurs_state.inclinaison_deg
    azimut_deg_sud = capteurs_state.azimut_deg_sud

    if mode_schema == "cescet":
        pech_et1_w_k = float(pech_et1_w_m2_k) * float(surface_capteurs_m2)
        if mode_debit_et_label == "Automatique":
            debit_et_m3_h = float(debit1_et_l_h_m2) * float(surface_capteurs_m2) / 1000.0
        else:
            debit_et_m3_h = float(debit_et_total_m3_h_manual)
    else:
        pech_et1_w_k = 0.0
        debit_et_m3_h = 0.0

    appliquer_corr_incidence = True
    algo_corr_incidence = SOLO_CI_ALGO_DEFAULT
    coeff0_ci = SOLO_CI_COEFF0_DEFAULT
    coeff1_ci = SOLO_CI_COEFF1_DEFAULT
    coeff3_ci = SOLO_CI_COEFF3_DEFAULT

    try:
        rows_preview = _apply_profiles_to_rows(
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
        if mode_meteo_verification:
            rows_preview = _apply_meteo_impose_to_rows(rows_preview, meteo_impose_map)
        if tef_mode in ("ESM2", "ESM2Plus3"):
            text_series_preview = [float(r["text_m"]) for r in rows_preview]
            days_series_preview = [int(r["days_m"]) for r in rows_preview]
            tef_series_preview = _calc_tef_series(
                text_m_series=text_series_preview,
                days_series=days_series_preview,
                mode=tef_mode,
            )
            for idx, _m in enumerate(MONTHS):
                rows_preview[idx]["tef_m"] = float(tef_series_preview[idx])
        if modele_v_eau_chaude == "distribution":
            rows_preview = _recompute_vecs_production_from_distribution(rows_preview)
        if mode_pertes_boucle == "saisie_kwh_j":
            for r in rows_preview:
                r["pertes_boucle_input_kwh_j"] = float(pertes_boucle_monthly_map.get(str(r["month"]), 0.0))

        installation_preview = solo_v0_mod.InstallationSoloV0(
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
            pertes_bouclage_preview_mwh_an = float(
                sum(float(pertes_boucle_monthly_map.get(m, 0.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH))
            ) / 1000.0
        else:
            pertes_bouclage_preview_mwh_an = _estimate_pertes_bouclage_mwh_an(
                rows=rows_preview,
                installation=installation_preview,
            )
        bouclage_pertes_placeholder.caption(
            f"Estimation pertes de bouclage: {_fmt_num(pertes_bouclage_preview_mwh_an, 3)} MWh/an"
        )
    except Exception:
        bouclage_pertes_placeholder.caption("Estimation pertes de bouclage: -")

    current_meteo_key = (
        str(mode_meteo_label),
        str(ville_ref),
        str(cas_verification_meteo),
        str(profil_hz),
        str(mode_rayonnement_label),
        tuple(
            (
                round(float(meteo_impose_map.get(m, {}).get("text", 0.0)), 6),
                round(float(meteo_impose_map.get(m, {}).get("tef", 0.0)), 6),
                round(float(meteo_impose_map.get(m, {}).get("gh", 0.0)), 6),
                round(float(meteo_impose_map.get(m, {}).get("cap", 0.0)), 6),
                round(float(meteo_impose_map.get(m, {}).get("dispo", 0.0)), 6),
            )
            for m in MONTHS
        ),
        round(float(inclinaison_deg), 3),
        round(float(azimut_deg_sud), 3),
    )
    if st.session_state.get("meteo_last_loaded_key") != current_meteo_key:
        try:
            base_rows = app_config.ecs_rows_df.to_dict(orient="records")
            meteo = (
                [None] * len(MONTHS)
                if mode_meteo_verification
                else epw_reader_mod.read_epw_monthly_irradiance_from_zip(
                    zip_path=zip_path,
                    tilt_deg=inclinaison_deg,
                    azimuth_deg_south=azimut_deg_sud,
                    albedo=0.2,
                )
            )
            row_map = {row["month"]: row for row in base_rows}
            text_series: list[float] = []
            days_series: list[int] = []
            for idx, month in enumerate(MONTHS):
                row = row_map[month]
                if mode_meteo_verification:
                    meteo_for_month = meteo_impose_map.get(month, {})
                    row["days_m"] = int(DAYS_BY_MONTH[idx])
                    hz_val = float(meteo_for_month.get("gh", 0.0))
                    r_plan = float(meteo_for_month.get("cap", 0.0))
                    r_dispo_input = float(meteo_for_month.get("dispo", 0.0))
                    row["text_m"] = float(meteo_for_month.get("text", 12.0))
                    row["tef_m"] = float(meteo_for_month.get("tef", 12.0))
                    row["tef_source_m"] = float(meteo_for_month.get("tef", 12.0))
                    row["r_disponible_kwh_m2_j_override"] = r_dispo_input
                    row["corr_incidence_m"] = (r_dispo_input / r_plan) if r_plan > 0 else 1.0
                else:
                    src = meteo[idx]
                    row["days_m"] = int(src.days_m)
                    epw_hz = (src.ghi_h_kwh_m2 / src.days_m) if hasattr(src, "ghi_h_kwh_m2") and src.days_m > 0 else 0.0
                    hz_val = epw_hz
                    row["text_m"] = float(src.tair_mean_c)
                    transpo_ratio = (src.r_global_plan_kwh_m2_j / epw_hz) if epw_hz > 0 else 1.0
                    r_plan = hz_val * transpo_ratio
                    row["r_disponible_kwh_m2_j_override"] = None
                    inst_tmp = solo_v0_mod.InstallationSoloV0(
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
                    corr = solo_v0_mod.correction_incidence_mensuelle(inst_tmp, idx + 1) if appliquer_corr_incidence else 1.0
                    row["corr_incidence_m"] = float(corr)

                row["r_global_hz_kwh_m2_j"] = float(hz_val)
                row["r_global_plan_kwh_m2_j"] = float(r_plan)
                row["g_tilt_kwh_m2"] = float(r_plan) * int(row["days_m"])
                text_series.append(float(row["text_m"]))
                days_series.append(int(row["days_m"]))
                if (row.get("r_disponible_kwh_m2_j_override") is not None and not pd.isna(row.get("r_disponible_kwh_m2_j_override"))):
                    row["r_disponible_kwh_m2_j"] = float(row["r_disponible_kwh_m2_j_override"])
                else:
                    row["r_disponible_kwh_m2_j"] = float(row["r_global_plan_kwh_m2_j"]) * float(row["corr_incidence_m"])

            if tef_mode in ("ESM2", "ESM2Plus3"):
                tef_series = _calc_tef_series(
                    text_m_series=text_series,
                    days_series=days_series,
                    mode=tef_mode,
                )
                for idx, month in enumerate(MONTHS):
                    row_map[month]["tef_m"] = float(tef_series[idx])
                    row_map[month]["tef_source_m"] = float(tef_series[idx])
            elif tef_mode == "Manual":
                for month in MONTHS:
                    row_map[month]["tef_m"] = float(tef_manual_c)
                    row_map[month]["tef_source_m"] = float(tef_manual_c)
            elif tef_mode == "ManualMonthly":
                for month in MONTHS:
                    row_map[month]["tef_m"] = float(tef_monthly_map.get(month, tef_manual_c))
                    row_map[month]["tef_source_m"] = float(tef_monthly_map.get(month, tef_manual_c))

            rows_after_meteo = [row_map[m] for m in MONTHS]
            if mode_meteo_verification:
                rows_after_meteo = _apply_meteo_impose_to_rows(rows_after_meteo, meteo_impose_map)
            st.session_state["rdispo_monthly_map_state"] = {
                str(r["month"]): float(r.get("r_disponible_kwh_m2_j", 0.0)) for r in rows_after_meteo
            }
            if modele_v_eau_chaude == "distribution":
                rows_after_meteo = _recompute_vecs_production_from_distribution(rows_after_meteo)
            st.session_state["ecs_rows_df"] = pd.DataFrame(rows_after_meteo)
            st.session_state["meteo_last_loaded_key"] = current_meteo_key
        except Exception as exc:
            st.error(f"Chargement meteo impossible: {exc}")

    calc_clicked = st.button("Calculer SOLO 2018", type="primary", width="stretch")
    if calc_clicked:
        st.session_state["results_visible"] = True
    fresh_app_config = AppConfig.from_session(st.session_state)
    return ResultatsContext(
        description=description,
        besoins=besoins_state,
        hydraulique=hydraulique_state,
        bouclage=bouclage_state,
        stockage=stockage_state,
        capteurs=capteurs_state,
        settings=ResultatsSettings(
            algo_corr_incidence=algo_corr_incidence,
            appliquer_corr_incidence=appliquer_corr_incidence,
            coeff0_ci=coeff0_ci,
            coeff1_ci=coeff1_ci,
            coeff3_ci=coeff3_ci,
            debit_et_m3_h=debit_et_m3_h,
            pech_et1_w_k=pech_et1_w_k,
        ),
        app_config=fresh_app_config,
    )


