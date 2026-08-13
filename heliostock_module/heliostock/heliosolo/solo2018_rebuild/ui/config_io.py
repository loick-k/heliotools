from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from heliostock.heliosolo.solo2018_rebuild.services.profiles import ensure_rows_schema


CONFIG_SESSION_KEYS = [
    "project_name",
    "ville_ref",
    "mode_meteo_label",
    "cas_verification_meteo",
    "typologie_batiment",
    "categorie_hotellerie",
    "mode_nb_unites_batiment",
    "nb_unites_batiment",
    "tef_mode_label",
    "tef_manual_input",
    "ecs_modele_v_label",
    "ecs_conso_mode_label",
    "tecs_mode_label",
    "tecs_const_input",
    "vecs_const_input",
    "tecs_dis_mode_label",
    "tecs_dis_const_input",
    "type_bouclage_label",
    "mode_pertes_boucle_label",
    "pertes_boucle_mode_saisie",
    "pertes_boucle_annuelle_kwh_an",
    "modele_stock_label",
    "nb_ballons_stock",
    "v1_stock_solaire_l",
    "cr_stock_wh_l_k_j",
    "tmax_stock_c",
    "tenv_base_c",
    "epais_iso_stock_solaire_cm",
    "type_isolant_stock",
    "lambda_iso_stock_custom",
    "tenv_mode_label",
    "mode_schema_label",
    "ratio_pointe_ecs_profile",
    "ratio_ecs_max10_sur_j",
    "mode_kt_label",
    "long_primaire_m",
    "kl_primaire_w_m_k",
    "type_installation_label",
    "mode_pech_label",
    "pech11_w_m2_k_ui",
    "mode_kget_label",
    "klet_et_w_m_k",
    "long_et_m",
    "kget_w_k_manual",
    "mode_pech_et_label",
    "pech_et1_w_m2_k",
    "mode_debit_et_label",
    "debit1_et_l_h_m2",
    "debit_et_total_m3_h_manual",
    "capteur_fabricant",
    "capteur_modele",
    "capteur_surface_unitaire_m2",
    "capteur_n0",
    "capteur_a1",
    "capteur_a2",
]

CONFIG_MAP_KEYS = [
    "vecs_monthly_map_state",
    "tecs_monthly_map_state",
    "tecs_dis_monthly_map_state",
    "tef_monthly_map_state",
    "logement_mix_state",
    "tenv_monthly_map_state",
    "pertes_boucle_monthly_map_state",
]

CONFIG_EDITOR_WIDGET_KEYS = [
    "meteo_impose_editor",
    "vecs_monthly_editor",
    "tecs_monthly_editor",
    "tecs_dis_monthly_editor",
    "tef_monthly_editor",
    "monthly_profiles_editor",
    "logement_mix_editor",
    "pertes_boucle_monthly_editor",
    "tenv_monthly_editor",
]


def json_default(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.to_list()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def build_config_payload() -> dict:
    return {
        "schema": "solo2018_rebuild_config",
        "version": 1,
        "saved_on": date.today().isoformat(),
        "session_values": {
            key: st.session_state.get(key)
            for key in CONFIG_SESSION_KEYS
            if key in st.session_state
        },
        "monthly_maps": {
            key: st.session_state.get(key, {})
            for key in CONFIG_MAP_KEYS
        },
        "meteo_impose_rows_state": st.session_state.get("meteo_impose_rows_state", []),
        "ecs_rows_df": (
            st.session_state["ecs_rows_df"].to_dict(orient="records")
            if "ecs_rows_df" in st.session_state
            else []
        ),
    }


def apply_config_payload(payload: dict) -> None:
    if payload.get("schema") != "solo2018_rebuild_config":
        raise ValueError("Fichier de configuration SOLO2018 non reconnu.")

    for key, value in payload.get("session_values", {}).items():
        if key in CONFIG_SESSION_KEYS:
            st.session_state[key] = value

    for key, value in payload.get("monthly_maps", {}).items():
        if key in CONFIG_MAP_KEYS and isinstance(value, dict):
            st.session_state[key] = value

    meteo_rows = payload.get("meteo_impose_rows_state", [])
    if isinstance(meteo_rows, list):
        st.session_state["meteo_impose_rows_state"] = meteo_rows

    ecs_rows = payload.get("ecs_rows_df", [])
    if isinstance(ecs_rows, list) and ecs_rows:
        st.session_state["ecs_rows_df"] = ensure_rows_schema(pd.DataFrame(ecs_rows))

    for key in CONFIG_EDITOR_WIDGET_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("meteo_last_loaded_key", None)
    st.session_state["results_visible"] = False


