from __future__ import annotations

import streamlit as st

import heliostock.heliosolo.solo2018_rebuild.core.solo_v0_engine as solo_v0_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import CAPTEUR_LIBRARY
from heliostock.heliosolo.solo2018_rebuild.ui.context import CapteursState


def render_capteurs_block() -> CapteursState:
    with st.expander("5) Circuit capteurs solaires", expanded=True):
        if "capteur_surface_unitaire_m2" not in st.session_state:
            st.session_state["capteur_surface_unitaire_m2"] = 2.0
        if "capteur_n0" not in st.session_state:
            st.session_state["capteur_n0"] = 0.75
        if "capteur_a1" not in st.session_state:
            st.session_state["capteur_a1"] = 3.5
        if "capteur_a2" not in st.session_state:
            st.session_state["capteur_a2"] = 0.015
        if "capteur_selected_sig" not in st.session_state:
            st.session_state["capteur_selected_sig"] = ""
        if "capteur_force_init" not in st.session_state:
            st.session_state["capteur_force_init"] = True

        fabricants = ["Saisie manuelle"] + sorted(CAPTEUR_LIBRARY.keys())
        default_fabricant = "Eklor" if "Eklor" in CAPTEUR_LIBRARY else "Saisie manuelle"
        if "capteur_fabricant" not in st.session_state:
            st.session_state["capteur_fabricant"] = default_fabricant
        if "capteur_modele" not in st.session_state:
            if st.session_state["capteur_fabricant"] != "Saisie manuelle":
                st.session_state["capteur_modele"] = sorted(CAPTEUR_LIBRARY[st.session_state["capteur_fabricant"]].keys())[0]
            else:
                st.session_state["capteur_modele"] = "Saisie manuelle"

        c_lib1, c_lib2 = st.columns(2)
        if st.session_state["capteur_fabricant"] not in fabricants:
            st.session_state["capteur_fabricant"] = default_fabricant
        fabricant_capteur = c_lib1.selectbox("Fabricant", options=fabricants, key="capteur_fabricant")
        modele_capteur = "Saisie manuelle"
        if fabricant_capteur != "Saisie manuelle":
            modeles = sorted(CAPTEUR_LIBRARY[fabricant_capteur].keys())
            if st.session_state.get("capteur_modele") not in modeles:
                st.session_state["capteur_modele"] = modeles[0]
            modele_capteur = c_lib2.selectbox("Modèle de capteur", options=modeles, key="capteur_modele")
            capteur_sig = f"{fabricant_capteur}|{modele_capteur}"
            if st.session_state.get("capteur_selected_sig") != capteur_sig or st.session_state.get("capteur_force_init", False):
                cap = CAPTEUR_LIBRARY[fabricant_capteur][modele_capteur]
                st.session_state["capteur_surface_unitaire_m2"] = float(cap["surface_utile_m2"])
                st.session_state["capteur_n0"] = float(cap["n0"])
                st.session_state["capteur_a1"] = float(cap["a1"])
                st.session_state["capteur_a2"] = float(cap["a2"])
                st.session_state["capteur_selected_sig"] = capteur_sig
                st.session_state["capteur_force_init"] = False
        else:
            st.session_state["capteur_selected_sig"] = "Saisie manuelle"
            st.session_state["capteur_modele"] = "Saisie manuelle"

        c_c1, c_c2, c_c3 = st.columns(3)
        surface_unitaire_capteur_m2 = c_c1.number_input(
            "Surface unitaire d'un capteur (m2)",
            min_value=0.1,
            step=0.1,
            key="capteur_surface_unitaire_m2",
        )
        nb_capteurs = c_c2.number_input("Nombre de capteurs", min_value=1, value=15, step=1)
        surface_capteurs_m2 = c_c3.number_input(
            "Surface totale déduite (m2)",
            min_value=0.1,
            value=float(surface_unitaire_capteur_m2 * float(nb_capteurs)),
            step=0.1,
            disabled=True,
        )
        c_c4, c_c5, c_c6 = st.columns(3)
        n0 = c_c4.number_input("n0", min_value=0.0, max_value=1.0, step=0.001, format="%.3f", key="capteur_n0")
        a1 = c_c5.number_input("a1 (W/m2.K)", min_value=0.0, max_value=20.0, step=0.001, format="%.3f", key="capteur_a1")
        a2 = c_c6.number_input("a2 (W/m2.K2)", min_value=0.0, max_value=0.2, step=0.001, format="%.3f", key="capteur_a2")
        b_capteur, k_capteur = solo_v0_mod.convertir_eta_a1_a2_vers_b_k(n0, a1, a2)
        c_c7, c_c8 = st.columns(2)
        inclinaison_deg = c_c7.number_input("Inclinaison des capteurs (deg)", min_value=0.0, max_value=90.0, value=45.0, step=1.0)
        azimut_deg_sud = c_c8.number_input("Orientation des capteurs vs sud (deg)", min_value=-180.0, max_value=180.0, value=0.0, step=5.0)
    return CapteursState(
        surface_unitaire_capteur_m2=surface_unitaire_capteur_m2,
        nb_capteurs=nb_capteurs,
        surface_capteurs_m2=surface_capteurs_m2,
        n0=n0,
        a1=a1,
        a2=a2,
        b_capteur=b_capteur,
        k_capteur=k_capteur,
        inclinaison_deg=inclinaison_deg,
        azimut_deg_sud=azimut_deg_sud,
    )


