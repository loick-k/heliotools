from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import heliostock.heliosolo.solo2018_rebuild.meteo.epw_reader as epw_reader_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import (
    CITY_EPW_ZIP_PATHS,
    DAYS_BY_MONTH,
    HOTELLERIE_RATIOS_L_J_CHAMBRE,
    LOGEMENT_RATIOS_L_J_LOGEMENT,
    MONTHS,
    NANTES_ZIP_DEFAULT,
    TYPOLOGIE_RATIOS_L_J_UNITE,
)
from heliostock.heliosolo.solo2018_rebuild.services.profiles import meteo_verification_defaults as _meteo_verification_defaults
from heliostock.heliosolo.solo2018_rebuild.ui.context import DescriptionState
from heliostock.heliosolo.solo2018_rebuild.ui.editors import apply_editor_pending_edits as _apply_editor_pending_edits
from heliostock.heliosolo.solo2018_rebuild.utils import to_float as _to_float


METEO_MODE_EPW = "Station EPW de la ville choisie"
METEO_MODE_VERIFICATION = "Vérification moteur SOLO2018 avec données météo imposées"
METEO_MODE_VERIFICATION_LEGACY = "Verification moteur SOLO2018 avec donnees meteo imposees"
NB_UNITES_DEFAULT = "Valeur par défaut"
NB_UNITES_DEFAULT_LEGACY = "Valeur par defaut"
NB_UNITES_CUSTOM = "Indiquer le nombre"


def _ensure_session_option(key: str, options: list[str], default: str | None = None) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = default if default is not None else options[0]


def _read_epw_site_location(zip_path: str | Path) -> tuple[float, float, float]:
    try:
        header, _rows = epw_reader_mod._parse_epw_from_zip(Path(zip_path))
        lat_deg, lon_deg, tz_h = epw_reader_mod._parse_location(header[0])
        return float(lat_deg), float(lon_deg), float(tz_h)
    except Exception:
        return 47.2, 0.0, 1.0


def render_description() -> DescriptionState:
    if "project_name" not in st.session_state:
        st.session_state["project_name"] = ""
    project_name = st.text_input(
        "Nom du projet",
        placeholder="Ex. Residence Les Pins - Nantes",
        key="project_name",
    )
    villes = list(CITY_EPW_ZIP_PATHS.keys())
    if "ville_ref" not in st.session_state:
        st.session_state["ville_ref"] = "Nantes" if "Nantes" in villes else villes[0]
    if "mode_meteo_label" not in st.session_state:
        st.session_state["mode_meteo_label"] = METEO_MODE_EPW
    if st.session_state.get("mode_meteo_label") in {METEO_MODE_VERIFICATION_LEGACY}:
        st.session_state["mode_meteo_label"] = METEO_MODE_VERIFICATION
    if "cas_verification_meteo" not in st.session_state:
        st.session_state["cas_verification_meteo"] = "Angers"
    _ensure_session_option(
        "mode_meteo_label",
        [METEO_MODE_EPW, METEO_MODE_VERIFICATION],
        METEO_MODE_EPW,
    )
    _ensure_session_option("cas_verification_meteo", ["Angers", "Saint-Brieuc"], "Angers")
    mode_meteo_label = st.selectbox(
        "Mode données météo",
        options=[METEO_MODE_EPW, METEO_MODE_VERIFICATION],
        index=0,
        key="mode_meteo_label",
    )
    mode_meteo_verification = mode_meteo_label == METEO_MODE_VERIFICATION
    c_m1, c_m2 = st.columns(2)
    ville_ref = c_m1.selectbox(
        "Station météo",
        options=villes,
        key="ville_ref",
        disabled=mode_meteo_verification,
    )
    cas_verification_meteo = c_m2.selectbox(
        "Cas de vérification SOLO2018",
        options=["Angers", "Saint-Brieuc"],
        index=0,
        disabled=not mode_meteo_verification,
        key="cas_verification_meteo",
    )
    profil_hz = "EPW station"
    if mode_meteo_verification:
        profil_hz = f"SOLO2018 {cas_verification_meteo} (météo imposée)"
        ville_ref_effective = cas_verification_meteo
    else:
        ville_ref_effective = ville_ref

    zip_path = CITY_EPW_ZIP_PATHS.get(ville_ref_effective, CITY_EPW_ZIP_PATHS.get(ville_ref, NANTES_ZIP_DEFAULT))
    site_lat_deg, site_lon_deg, site_tz_h = _read_epw_site_location(zip_path)
    rdispo_monthly_map: dict[str, float] = {
        m: float(st.session_state["rdispo_monthly_map_state"].get(m, 0.0)) for m in MONTHS
    }
    meteo_impose_map: dict[str, dict[str, float]] = {}
    if mode_meteo_verification:
        if st.session_state.get("meteo_verification_last_case") != cas_verification_meteo:
            st.session_state["meteo_impose_rows_state"] = _meteo_verification_defaults(cas_verification_meteo)
            st.session_state["meteo_verification_last_case"] = cas_verification_meteo
        if "meteo_impose_rows_state" not in st.session_state:
            st.session_state["meteo_impose_rows_state"] = _meteo_verification_defaults(cas_verification_meteo)
        default_meteo_rows = _meteo_verification_defaults(cas_verification_meteo)
        meteo_state_by_month = {
            str(r.get("Mois", MONTHS[idx])): dict(r)
            for idx, r in enumerate(st.session_state["meteo_impose_rows_state"])
        }
        st.session_state["meteo_impose_rows_state"] = [
            {**default_row, **meteo_state_by_month.get(str(default_row["Mois"]), {})}
            for default_row in default_meteo_rows
        ]
        meteo_impose_df = _apply_editor_pending_edits(
            pd.DataFrame(st.session_state["meteo_impose_rows_state"]),
            "meteo_impose_editor",
        )
        meteo_impose_edit = st.data_editor(
            meteo_impose_df,
            num_rows="fixed",
            width="stretch",
            hide_index=True,
            disabled=["Mois"],
            column_config={
                "T ext (degC)": st.column_config.NumberColumn("T ext (degC)", step=0.1, format="%.2f"),
                "Temp EF (degC)": st.column_config.NumberColumn("Temp EF (degC)", min_value=0.0, step=0.1, format="%.2f"),
                "Global horiz (kWh/m2.j)": st.column_config.NumberColumn("Global horiz (kWh/m2.j)", min_value=0.0, step=0.001, format="%.3f"),
                "Global capteur (kWh/m2.j)": st.column_config.NumberColumn("Global capteur (kWh/m2.j)", min_value=0.0, step=0.001, format="%.3f"),
                "RDisponible (kWh/m2.j)": st.column_config.NumberColumn("RDisponible (kWh/m2.j)", min_value=0.0, step=0.001, format="%.3f"),
            },
            key="meteo_impose_editor",
        )
        meteo_rows_state = []
        for r in meteo_impose_edit.to_dict(orient="records"):
            month = str(r["Mois"])
            clean_row = {
                "Mois": month,
                "T ext (degC)": _to_float(r["T ext (degC)"], 0.0),
                "Temp EF (degC)": _to_float(r.get("Temp EF (degC)"), 12.0),
                "Global horiz (kWh/m2.j)": _to_float(r["Global horiz (kWh/m2.j)"], 0.0),
                "Global capteur (kWh/m2.j)": _to_float(r["Global capteur (kWh/m2.j)"], 0.0),
                "RDisponible (kWh/m2.j)": _to_float(r["RDisponible (kWh/m2.j)"], 0.0),
            }
            meteo_rows_state.append(clean_row)
            meteo_impose_map[month] = {
                "text": clean_row["T ext (degC)"],
                "tef": clean_row["Temp EF (degC)"],
                "gh": clean_row["Global horiz (kWh/m2.j)"],
                "cap": clean_row["Global capteur (kWh/m2.j)"],
                "dispo": clean_row["RDisponible (kWh/m2.j)"],
            }
        st.session_state["meteo_impose_rows_state"] = meteo_rows_state
        st.caption("Mode vérification: Text, Global capteur et RDisponible sont imposés directement au moteur.")

    mode_rayonnement_label = (
        "RDisponible impose directement"
        if mode_meteo_verification
        else "Global capteur brut + correction incidence SOLO2018"
    )
    mode_rdispo_impose = mode_meteo_verification
    st.session_state["mode_rayonnement_label"] = mode_rayonnement_label

    typologie_options = ["Logement collectif", "EHPAD", "Hopital", "Hotellerie"]
    if "typologie_batiment" not in st.session_state:
        st.session_state["typologie_batiment"] = "EHPAD"
    _ensure_session_option("typologie_batiment", typologie_options, "EHPAD")
    c_t1, c_t2 = st.columns(2)
    typologie_label = c_t1.selectbox(
        "Typologie du bâtiment",
        options=typologie_options,
        index=typologie_options.index(st.session_state["typologie_batiment"]),
        key="typologie_batiment",
    )
    _ensure_session_option(
        "categorie_hotellerie",
        list(HOTELLERIE_RATIOS_L_J_CHAMBRE.keys()),
        "Eco",
    )
    if typologie_label == "Hotellerie":
        categorie_hotellerie = c_t2.selectbox(
            "Catégorie hôtellerie",
            options=list(HOTELLERIE_RATIOS_L_J_CHAMBRE.keys()),
            index=0,
            key="categorie_hotellerie",
        )
    else:
        categorie_hotellerie = st.session_state.get("categorie_hotellerie", "Eco")

    unite_label_by_typologie = {
        "Logement collectif": "Nombre de logements",
        "EHPAD": "Nombre de residents",
        "Hopital": "Nombre de lits",
        "Hotellerie": "Nombre de chambres",
    }
    unite_label = unite_label_by_typologie[typologie_label]
    c_t3, c_t4 = st.columns(2)
    if st.session_state.get("mode_nb_unites_batiment") == NB_UNITES_DEFAULT_LEGACY:
        st.session_state["mode_nb_unites_batiment"] = NB_UNITES_DEFAULT
    mode_nb_unites = c_t3.selectbox(
        "Unités du bâtiment",
        options=[NB_UNITES_DEFAULT, NB_UNITES_CUSTOM],
        index=0,
        key="mode_nb_unites_batiment",
    )
    nb_unites_batiment = c_t4.number_input(
        unite_label,
        min_value=1.0,
        value=1.0,
        step=1.0,
        disabled=(mode_nb_unites != NB_UNITES_CUSTOM),
        key="nb_unites_batiment",
    )

    nb_logements_mix = 0.0
    vecs_total_mix_l_j = 0.0
    if typologie_label == "Logement collectif" and mode_nb_unites == NB_UNITES_DEFAULT:
        if "logement_mix_state" not in st.session_state:
            st.session_state["logement_mix_state"] = {
                typologie: 0.0 for typologie in LOGEMENT_RATIOS_L_J_LOGEMENT.keys()
            }
        logement_mix_df = pd.DataFrame(
            {
                "Typologie logement": list(LOGEMENT_RATIOS_L_J_LOGEMENT.keys()),
                "Ratio ECS à 60 degC (L/j/logement)": list(LOGEMENT_RATIOS_L_J_LOGEMENT.values()),
                "Nombre de logements": [
                    float(st.session_state["logement_mix_state"].get(typologie, 0.0))
                    for typologie in LOGEMENT_RATIOS_L_J_LOGEMENT.keys()
                ],
            }
        )
        with st.form("logement_mix_form"):
            logement_mix_edit = st.data_editor(
                logement_mix_df,
                num_rows="fixed",
                width="stretch",
                hide_index=True,
                disabled=["Typologie logement", "Ratio ECS à 60 degC (L/j/logement)"],
                column_config={
                    "Nombre de logements": st.column_config.NumberColumn(
                        "Nombre de logements",
                        min_value=0.0,
                        step=1.0,
                        format="%.0f",
                    ),
                },
                key="logement_mix_editor",
            )
            logement_mix_submitted = st.form_submit_button("Appliquer la composition logements")
        if logement_mix_submitted:
            st.session_state["logement_mix_state"] = {
                str(r["Typologie logement"]): _to_float(r["Nombre de logements"], 0.0)
                for r in logement_mix_edit.to_dict(orient="records")
            }
        logement_mix_state = dict(st.session_state["logement_mix_state"])
        nb_logements_mix = float(sum(logement_mix_state.values()))
        vecs_total_mix_l_j = float(
            sum(
                LOGEMENT_RATIOS_L_J_LOGEMENT[typologie] * float(logement_mix_state.get(typologie, 0.0))
                for typologie in LOGEMENT_RATIOS_L_J_LOGEMENT.keys()
            )
        )

    if typologie_label == "Logement collectif":
        default_vecs_unitaire_l_j = vecs_total_mix_l_j / nb_logements_mix if nb_logements_mix > 0 else 30.0
    elif typologie_label == "Hotellerie":
        default_vecs_unitaire_l_j = HOTELLERIE_RATIOS_L_J_CHAMBRE[categorie_hotellerie]
    elif typologie_label == "Hopital":
        default_vecs_unitaire_l_j = TYPOLOGIE_RATIOS_L_J_UNITE["Hopital"]
    else:
        default_vecs_unitaire_l_j = TYPOLOGIE_RATIOS_L_J_UNITE[typologie_label]

    modele_v_ui = st.session_state.get("ecs_modele_v_label", "À température de production")
    conso_mode_ui = st.session_state.get("ecs_conso_mode_label", "Annuel")
    vecs_src_col_ui = "vecs_l_j" if "production" in str(modele_v_ui).lower() else "vecs_dis_l_j"
    if conso_mode_ui == "Mensuel":
        vecs_monthly_map_state = st.session_state.get("vecs_monthly_map_state")
        if isinstance(vecs_monthly_map_state, dict):
            vecs_total_ref_l_j = float(
                sum(float(vecs_monthly_map_state.get(m, 0.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH))
                / max(1.0, float(sum(DAYS_BY_MONTH)))
            )
        else:
            rows_df_ui = st.session_state["ecs_rows_df"]
            vecs_total_ref_l_j = float(rows_df_ui.get(vecs_src_col_ui, pd.Series([1500.0] * 12)).mean())
    else:
        vecs_total_ref_l_j = float(st.session_state.get("vecs_const_input", 1500.0))

    if mode_nb_unites == NB_UNITES_CUSTOM:
        vecs_unite_ref_l_j = vecs_total_ref_l_j / float(nb_unites_batiment)
    elif typologie_label == "Logement collectif" and nb_logements_mix > 0:
        vecs_unite_ref_l_j = default_vecs_unitaire_l_j
        nb_unites_batiment = nb_logements_mix
        vecs_total_ref_l_j = vecs_total_mix_l_j
    else:
        vecs_unite_ref_l_j = default_vecs_unitaire_l_j

    c_t5, c_t6 = st.columns(2)
    ratio_default_label = {
        "Logement collectif": "Ratio par défaut (L/j/logement à 60 degC)",
        "EHPAD": "Ratio par défaut (L/j/résident à 60 degC)",
        "Hopital": "Ratio par défaut (L/j/lit à 60 degC)",
        "Hotellerie": "Ratio par défaut (L/j/chambre à 60 degC)",
    }[typologie_label]
    c_t5.number_input(
        ratio_default_label,
        min_value=0.0,
        value=round(float(default_vecs_unitaire_l_j), 2),
        step=0.1,
        disabled=True,
    )
    c_t6.number_input(
        "VECS unitaire calculé (L/j/unité)",
        min_value=0.0,
        value=round(float(vecs_unite_ref_l_j), 2),
        step=0.1,
        disabled=True,
    )
    if typologie_label == "Logement collectif" and nb_logements_mix > 0:
        st.caption(
            f"Composition logement collectif: {int(nb_logements_mix)} logements, "
            f"VECS de référence {round(float(vecs_total_mix_l_j), 1)} L/j à 60 degC."
        )
    return DescriptionState(
        project_name=project_name,
        mode_meteo_label=mode_meteo_label,
        mode_meteo_verification=mode_meteo_verification,
        ville_ref=ville_ref,
        cas_verification_meteo=cas_verification_meteo,
        profil_hz=profil_hz,
        ville_ref_effective=ville_ref_effective,
        zip_path=zip_path,
        site_lat_deg=site_lat_deg,
        site_lon_deg=site_lon_deg,
        site_tz_h=site_tz_h,
        rdispo_monthly_map=rdispo_monthly_map,
        meteo_impose_map=meteo_impose_map,
        mode_rayonnement_label=mode_rayonnement_label,
        mode_rdispo_impose=mode_rdispo_impose,
        typologie_label=typologie_label,
        categorie_hotellerie=categorie_hotellerie,
        unite_label=unite_label,
        mode_nb_unites=mode_nb_unites,
        nb_unites_batiment=nb_unites_batiment,
        nb_logements_mix=nb_logements_mix,
        vecs_total_mix_l_j=vecs_total_mix_l_j,
        default_vecs_unitaire_l_j=default_vecs_unitaire_l_j,
        vecs_total_ref_l_j=vecs_total_ref_l_j,
        vecs_unite_ref_l_j=vecs_unite_ref_l_j,
    )


