from __future__ import annotations

import pandas as pd
import streamlit as st

import heliostock.heliosolo.solo2018_rebuild.core.solo_v0_engine as solo_v0_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import DAYS_BY_MONTH, DEFAULT_T_ENV_STOCK_C, MONTHS
from heliostock.heliosolo.solo2018_rebuild.ui.context import StockageState
from heliostock.heliosolo.solo2018_rebuild.ui.editors import apply_editor_pending_edits as _apply_editor_pending_edits
from heliostock.heliosolo.solo2018_rebuild.utils import fmt_num as _fmt_num, to_float as _to_float, weighted_mean as _weighted_mean


STOCK_MODE_GLOBAL = "Données globales du stock"
STOCK_MODE_DETAILLE = "Données détaillées du stock"
STOCK_MODE_GLOBAL_LEGACY = "Donnees globales du stock"
STOCK_MODE_DETAILLE_LEGACY = "Donnees detaillees du stock"


def render_stockage_block(stockage_block_container) -> StockageState:
    with stockage_block_container.expander("4) Stockage solaire", expanded=True):
        c_sv1, c_sv2, c_sv3 = st.columns(3)
        nb_ballons_stock = int(c_sv1.number_input("Nombre de ballons", min_value=1, value=1, step=1, key="nb_ballons_stock"))
        v1_stock_solaire_l = c_sv2.number_input("Volume unitaire ballon (L)", min_value=10.0, value=1000.0, step=10.0, key="v1_stock_solaire_l")
        volume_stock_l = float(nb_ballons_stock) * float(v1_stock_solaire_l)
        c_sv3.number_input(
            "Volume de stockage solaire total (L)",
            min_value=1.0,
            value=volume_stock_l,
            step=10.0,
            disabled=True,
        )

        if st.session_state.get("modele_stock_label") == STOCK_MODE_GLOBAL_LEGACY:
            st.session_state["modele_stock_label"] = STOCK_MODE_GLOBAL
        if st.session_state.get("modele_stock_label") == STOCK_MODE_DETAILLE_LEGACY:
            st.session_state["modele_stock_label"] = STOCK_MODE_DETAILLE
        modele_stock_label = st.selectbox(
            "Modèle de données du stock",
            options=[STOCK_MODE_GLOBAL, STOCK_MODE_DETAILLE],
            index=1,
            key="modele_stock_label",
        )
        modele_stock_solaire = "global" if modele_stock_label.startswith("Données globales") else "detaille"

        tenv_mode_label = st.selectbox(
            "Variation de la température autour du stockage",
            options=["Constante", "Variation mensuelle"],
            index=0,
            key="tenv_mode_label",
        )
        tenv_mode = "constant" if tenv_mode_label.startswith("Constante") else "monthly"
        tenv_base_fallback_c = float(st.session_state.get("tenv_base_c", DEFAULT_T_ENV_STOCK_C))
        tenv_monthly_df = st.session_state["ecs_rows_df"][["month", "t_env_stock_c"]].copy()
        tenv_monthly_map_src: dict[str, float] = {
            str(r["month"]): float(r["t_env_stock_c"]) if (r["t_env_stock_c"] is not None and not pd.isna(r["t_env_stock_c"])) else tenv_base_fallback_c
            for r in tenv_monthly_df.to_dict(orient="records")
        }
        tenv_monthly_map: dict[str, float] = {
            m: float(st.session_state["tenv_monthly_map_state"].get(m, tenv_monthly_map_src.get(m, tenv_base_fallback_c)))
            for m in MONTHS
        }
        tenv_editor_df = pd.DataFrame(
            {"Mois": MONTHS, "Tenv stockage (degC)": [float(tenv_monthly_map.get(m, tenv_base_fallback_c)) for m in MONTHS]}
        )
        if tenv_mode == "monthly":
            tenv_editor_df = _apply_editor_pending_edits(tenv_editor_df, "tenv_monthly_editor")
            tenv_preview_map = {
                str(r["Mois"]): _to_float(r["Tenv stockage (degC)"], tenv_base_fallback_c)
                for r in tenv_editor_df.to_dict(orient="records")
            }
            tenv_base_display_c = _weighted_mean(
                [float(tenv_preview_map.get(m, tenv_base_fallback_c)) for m in MONTHS],
                [float(d) for d in DAYS_BY_MONTH],
            )
        else:
            tenv_base_display_c = tenv_base_fallback_c

        c_s1, c_s2, c_s3 = st.columns(3)
        cr_stock_wh_l_k_j = c_s1.number_input(
            "Coefficient de refroidissement du stockage (Wh/L/K/j)",
            min_value=0.0,
            value=0.16,
            step=0.01,
            format="%.3f",
            disabled=(modele_stock_solaire != "global"),
            key="cr_stock_wh_l_k_j",
        )
        tmax_stock_c = c_s2.number_input("Temperature maximale de stockage (degC)", min_value=40.0, max_value=100.0, value=80.0, step=1.0, key="tmax_stock_c")
        if tenv_mode == "monthly":
            tenv_base_c = c_s3.number_input(
                "Temperature autour du stockage (degC)",
                min_value=-20.0,
                max_value=60.0,
                value=float(tenv_base_display_c),
                step=0.5,
                disabled=True,
                help="Moyenne annuelle calculée depuis le profil mensuel.",
                key="tenv_base_c_preview",
            )
        else:
            tenv_base_c = c_s3.number_input(
                "Temperature autour du stockage (degC)",
                min_value=-20.0,
                max_value=60.0,
                value=DEFAULT_T_ENV_STOCK_C,
                step=0.5,
                key="tenv_base_c",
            )
        epais_iso_stock_solaire_cm = 10.0
        lambda_iso_stock_solaire_w_m_k = 0.035
        modele_geometrie_ballon = "standard"
        algo_sballon = "SOLO2018"
        cr_stock_effectif_ui = cr_stock_wh_l_k_j
        if modele_stock_solaire == "detaille":
            c_sd1, c_sd2 = st.columns(2)
            epais_iso_stock_solaire_cm = c_sd1.number_input("Épaisseur isolant ballon (cm)", min_value=0.1, value=10.0, step=0.5, key="epais_iso_stock_solaire_cm")
            if st.session_state.get("type_isolant_stock") == "Polyurethane":
                st.session_state["type_isolant_stock"] = "Polyuréthane"
            type_isolant_stock = c_sd2.selectbox(
                "Type isolant ballon",
                options=["Laine de roche", "Polyuréthane", "Autre"],
                index=0,
                key="type_isolant_stock",
            )
            if type_isolant_stock == "Laine de roche":
                lambda_iso_stock_solaire_w_m_k = 0.04
                c_sd2.number_input(
                    "Lambda isolant (W/m/K)",
                    min_value=0.01,
                    value=lambda_iso_stock_solaire_w_m_k,
                    step=0.005,
                    format="%.3f",
                    disabled=True,
                    key="lambda_iso_stock_locked_laine",
                )
            elif type_isolant_stock == "Polyuréthane":
                lambda_iso_stock_solaire_w_m_k = 0.03
                c_sd2.number_input(
                    "Lambda isolant (W/m/K)",
                    min_value=0.01,
                    value=lambda_iso_stock_solaire_w_m_k,
                    step=0.005,
                    format="%.3f",
                    disabled=True,
                    key="lambda_iso_stock_locked_pur",
                )
            else:
                lambda_iso_stock_solaire_w_m_k = c_sd2.number_input(
                    "Lambda isolant (W/m/K)",
                    min_value=0.01,
                    value=0.035,
                    step=0.005,
                    format="%.3f",
                    key="lambda_iso_stock_custom",
                )
            modele_geometrie_ballon = "standard"
            algo_sballon = "SOLO2018"
            cr_stock_calc = solo_v0_mod.calc_cr_stock_solaire(
                solo_v0_mod.InstallationSoloV0(
                    surface_capteurs_m2=1.0,
                    volume_stock_l=volume_stock_l,
                    modele_stock_solaire="detaille",
                    v1_stock_solaire_l=v1_stock_solaire_l,
                    epais_iso_stock_solaire_cm=epais_iso_stock_solaire_cm,
                    lambda_iso_stock_solaire_w_m_k=lambda_iso_stock_solaire_w_m_k,
                    modele_geometrie_ballon=modele_geometrie_ballon,
                    algo_sballon=algo_sballon,
                )
            )
            cr_stock_effectif_ui = cr_stock_calc
            st.caption(f"CR stock calculé (mode détaillé): {_fmt_num(cr_stock_calc, 3)} Wh/L/K/j")
        if tenv_mode == "monthly":
            st.caption("Tenv stockage mensuelle (degC)")
            with st.form("tenv_monthly_form"):
                tenv_edit = st.data_editor(
                    tenv_editor_df,
                    num_rows="fixed",
                    width="stretch",
                    hide_index=True,
                    disabled=["Mois"],
                    column_config={
                        "Tenv stockage (degC)": st.column_config.NumberColumn("Tenv stockage (degC)", step=0.5),
                    },
                    key="tenv_monthly_editor",
                )
                tenv_submitted = st.form_submit_button("Appliquer le profil mensuel de stockage")
            if tenv_submitted:
                tenv_monthly_map = {
                    str(r["Mois"]): _to_float(r["Tenv stockage (degC)"], tenv_base_c)
                    for r in tenv_edit.to_dict(orient="records")
                }
                st.session_state["tenv_monthly_map_state"] = dict(tenv_monthly_map)
            t_env_stock_used_c = _weighted_mean(
                [float(tenv_monthly_map.get(m, tenv_base_c)) for m in MONTHS],
                [float(d) for d in DAYS_BY_MONTH],
            )
        else:
            t_env_stock_used_c = tenv_base_c
    return StockageState(
        nb_ballons_stock=nb_ballons_stock,
        v1_stock_solaire_l=v1_stock_solaire_l,
        volume_stock_l=volume_stock_l,
        modele_stock_label=modele_stock_label,
        modele_stock_solaire=modele_stock_solaire,
        tenv_mode=tenv_mode,
        tenv_base_c=tenv_base_c,
        tenv_monthly_map=tenv_monthly_map,
        cr_stock_wh_l_k_j=cr_stock_wh_l_k_j,
        tmax_stock_c=tmax_stock_c,
        epais_iso_stock_solaire_cm=epais_iso_stock_solaire_cm,
        lambda_iso_stock_solaire_w_m_k=lambda_iso_stock_solaire_w_m_k,
        modele_geometrie_ballon=modele_geometrie_ballon,
        algo_sballon=algo_sballon,
        cr_stock_effectif_ui=cr_stock_effectif_ui,
        t_env_stock_used_c=t_env_stock_used_c,
    )


