from __future__ import annotations

import streamlit as st

from heliostock.heliosolo.solo2018_rebuild.defaults import RATIOS_POINTE_ECS_LABELS, RATIOS_POINTE_ECS_MOYENS
from heliostock.heliosolo.solo2018_rebuild.ui.context import HydrauliqueState


SCHEMA_CESC = "Schéma en eau sanitaire"
SCHEMA_CESCET = "Schéma en eau technique"
SCHEMA_CESC_LEGACY = "Schema en eau sanitaire"
SCHEMA_CESCET_LEGACY = "Schema en eau technique"


def _ensure_session_option(key: str, options: list[str], default: str | None = None) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = default if default is not None else options[0]


def render_hydraulique_block(circuit_block_container) -> HydrauliqueState:
    with circuit_block_container.expander("2) Circuit hydraulique", expanded=True):
        c_sch1, c_sch2, c_sch3 = st.columns(3)
        if st.session_state.get("mode_schema_label") == SCHEMA_CESC_LEGACY:
            st.session_state["mode_schema_label"] = SCHEMA_CESC
        if st.session_state.get("mode_schema_label") == SCHEMA_CESCET_LEGACY:
            st.session_state["mode_schema_label"] = SCHEMA_CESCET
        mode_schema_label = c_sch1.selectbox(
            "Schéma hydraulique",
            options=[SCHEMA_CESC, SCHEMA_CESCET],
            index=0,
            key="mode_schema_label",
        )
        mode_schema = "cesc" if mode_schema_label == SCHEMA_CESC else "cescet"
        ratio_profile_options = list(RATIOS_POINTE_ECS_MOYENS.keys())
        _ensure_session_option("ratio_pointe_ecs_profile", ratio_profile_options, "solo2018_defaut")
        ratio_pointe_ecs_profile = c_sch2.selectbox(
            "Profil débit de pointe ECS",
            options=ratio_profile_options,
            format_func=lambda key: RATIOS_POINTE_ECS_LABELS.get(key, key),
            key="ratio_pointe_ecs_profile",
            disabled=(mode_schema != "cescet"),
        )
        if st.session_state.get("ratio_pointe_ecs_profile_last") != ratio_pointe_ecs_profile:
            st.session_state["ratio_ecs_max10_sur_j"] = float(RATIOS_POINTE_ECS_MOYENS[ratio_pointe_ecs_profile])
            st.session_state["ratio_pointe_ecs_profile_last"] = ratio_pointe_ecs_profile
        ratio_ecs_max10_sur_j = c_sch3.number_input(
            "Ratio débit pointe ECS / conso journalière",
            min_value=0.01,
            max_value=5.0,
            value=float(RATIOS_POINTE_ECS_MOYENS[ratio_pointe_ecs_profile]),
            step=0.05,
            format="%.2f",
            disabled=(mode_schema != "cescet"),
            key="ratio_ecs_max10_sur_j",
        )

        c_h1, c_h2, c_h3 = st.columns(3)
        if st.session_state.get("mode_kt_label") == "Saisie longueur et perte lineique : KtPrimaire = KLprimaire x LongPrimaire":
            st.session_state["mode_kt_label"] = "Saisie longueur et perte linéique : KtPrimaire = KLprimaire x LongPrimaire"
        mode_kt_label = c_h1.selectbox(
            "Circuit primaire",
            options=[
                "Automatique",
                "Saisie longueur et perte linéique : KtPrimaire = KLprimaire x LongPrimaire",
            ],
            index=0,
            key="mode_kt_label",
        )
        mode_kt_primaire = "auto_simple" if mode_kt_label == "Automatique" else "lineaire"
        long_primaire_m = c_h2.number_input(
            "Longueur totale (m)",
            min_value=0.0,
            value=10.0,
            step=1.0,
            disabled=(mode_kt_primaire != "lineaire"),
            key="long_primaire_m",
        )
        kl_primaire_w_m_k = c_h3.number_input(
            "Perte linéique (W/m/degC)",
            min_value=0.0,
            value=0.3,
            step=0.01,
            format="%.2f",
            disabled=(mode_kt_primaire != "lineaire"),
            key="kl_primaire_w_m_k",
        )
        if mode_schema == "cescet":
            type_installation_options: dict[str, tuple[str, str]] = {
                "Échangeur externe - 2 pompes + 1 pompe": ("forcee", "externe"),
                "Échangeur noyé - 1 pompe + 1 pompe": ("forcee", "noye"),
                "Direct sans échangeur - 1 pompe + 1 pompe": ("forcee", "direct"),
            }
        else:
            type_installation_options = {
                "Échangeur externe - 2 pompes": ("forcee", "externe"),
                "Échangeur noyé - 1 pompe": ("forcee", "noye"),
                "Direct sans échangeur - 1 pompe": ("forcee", "direct"),
                "Échangeur noyé - thermosiphon": ("thermosiphon", "noye"),
                "Direct sans échangeur - thermosiphon": ("thermosiphon", "direct"),
            }
        type_installation_legacy = {
            "Echangeur externe - 2 pompes + 1 pompe": "Échangeur externe - 2 pompes + 1 pompe",
            "Echangeur noye - 1 pompe + 1 pompe": "Échangeur noyé - 1 pompe + 1 pompe",
            "Direct sans echangeur - 1 pompe + 1 pompe": "Direct sans échangeur - 1 pompe + 1 pompe",
            "Echangeur externe - 2 pompes": "Échangeur externe - 2 pompes",
            "Echangeur noye - 1 pompe": "Échangeur noyé - 1 pompe",
            "Direct sans echangeur - 1 pompe": "Direct sans échangeur - 1 pompe",
            "Echangeur noye - thermosiphon": "Échangeur noyé - thermosiphon",
            "Direct sans echangeur - thermosiphon": "Direct sans échangeur - thermosiphon",
        }
        if st.session_state.get("type_installation_label") in type_installation_legacy:
            st.session_state["type_installation_label"] = type_installation_legacy[
                st.session_state["type_installation_label"]
            ]
        if st.session_state.get("type_installation_label") not in type_installation_options:
            st.session_state["type_installation_label"] = list(type_installation_options.keys())[0]
        type_installation_label = st.selectbox(
            "Type installation",
            options=list(type_installation_options.keys()),
            index=0,
            key="type_installation_label",
        )
        type_circulation, type_echangeur = type_installation_options[type_installation_label]
        type_circulation_label = "Circulation forcee" if type_circulation == "forcee" else "Thermosiphon"
        type_echangeur_label = {
            "externe": "Échangeur externe",
            "noye": "Échangeur noyé",
            "direct": "Direct sans échangeur",
        }[type_echangeur]
        c_h6, c_h7 = st.columns(2)
        if st.session_state.get("mode_pech_label") == "Saisie puissance echangeur":
            st.session_state["mode_pech_label"] = "Saisie puissance échangeur"
        mode_pech_label = c_h6.selectbox(
            "Puissance échangeur",
            options=["Automatique", "Saisie puissance échangeur"],
            index=0,
            key="mode_pech_label",
        )
        pech11_w_m2_k_ui = c_h7.number_input(
            "Puissance échangeur (W/degC/m2)",
            min_value=0.0,
            value=100.0,
            step=5.0,
            disabled=(mode_pech_label != "Saisie puissance échangeur"),
            key="pech11_w_m2_k_ui",
        )
        pech11_w_m2_k = 100.0 if mode_pech_label == "Automatique" else float(pech11_w_m2_k_ui)

        mode_kget_label = "Automatique"
        klet_et_w_m_k = 0.3
        long_et_m = 10.0
        kget_w_k = float(klet_et_w_m_k) * float(long_et_m)
        mode_pech_et_label = "Automatique"
        pech_et1_w_m2_k = 100.0
        mode_debit_et_label = "Automatique"
        debit1_et_l_h_m2 = 40.0
        debit_et_total_m3_h_manual = 0.6
        if mode_schema == "cescet":
            st.markdown("**Paramètres eau technique**")
            c_et2, c_et3 = st.columns(2)
            mode_kget_label = c_et2.selectbox(
                "Pertes circuit eau technique",
                options=["Automatique", "Saisie KGET totale"],
                index=0,
                key="mode_kget_label",
            )
            if mode_kget_label == "Automatique":
                c_et3a, c_et3b = c_et3.columns(2)
                klet_et_w_m_k = c_et3a.number_input(
                    "KLEt (W/m/degC)",
                    min_value=0.0,
                    value=0.3,
                    step=0.01,
                    format="%.2f",
                    key="klet_et_w_m_k",
                )
                long_et_m = c_et3b.number_input(
                    "Longueur ET (m)",
                    min_value=0.0,
                    value=10.0,
                    step=1.0,
                    key="long_et_m",
                )
                kget_w_k = float(klet_et_w_m_k) * float(long_et_m)
            else:
                kget_w_k = c_et3.number_input(
                    "KGET totale (W/degC)",
                    min_value=0.0,
                    value=3.0,
                    step=0.1,
                    key="kget_w_k_manual",
                )
            st.number_input(
                "KGET retenue (W/degC)",
                min_value=0.0,
                value=float(kget_w_k),
                step=0.1,
                disabled=True,
                key="kget_retained_display",
            )

            c_et4, c_et5 = st.columns(2)
            mode_pech_et_label = c_et4.selectbox(
                "Puissance échangeur ET/ECS",
                options=["Automatique", "Saisie manuelle"],
                index=0,
                key="mode_pech_et_label",
            )
            pech_et1_w_m2_k = c_et5.number_input(
                "PEchET1 (W/m2/degC)",
                min_value=0.0,
                value=100.0,
                step=5.0,
                key="pech_et1_w_m2_k",
            )
            if mode_pech_et_label == "Automatique":
                pech_et1_w_m2_k = 100.0

            c_et6, c_et7 = st.columns(2)
            mode_debit_et_label = c_et6.selectbox(
                "Débit eau technique",
                options=["Automatique", "Saisie manuelle"],
                index=0,
                key="mode_debit_et_label",
            )
            if mode_debit_et_label == "Automatique":
                debit1_et_l_h_m2 = c_et7.number_input(
                    "Debit ET unitaire (L/h/m2)",
                    min_value=0.0,
                    value=40.0,
                    step=1.0,
                    key="debit1_et_l_h_m2",
                )
            else:
                debit_et_total_m3_h_manual = c_et7.number_input(
                    "Debit ET total (m3/h)",
                    min_value=0.0,
                    value=0.6,
                    step=0.01,
                    format="%.3f",
                    key="debit_et_total_m3_h_manual",
                )
    return HydrauliqueState(
        mode_schema_label=mode_schema_label,
        mode_schema=mode_schema,
        ratio_pointe_ecs_profile=ratio_pointe_ecs_profile,
        ratio_ecs_max10_sur_j=ratio_ecs_max10_sur_j,
        mode_kt_primaire=mode_kt_primaire,
        long_primaire_m=long_primaire_m,
        kl_primaire_w_m_k=kl_primaire_w_m_k,
        type_installation_label=type_installation_label,
        type_circulation=type_circulation,
        type_echangeur=type_echangeur,
        type_circulation_label=type_circulation_label,
        type_echangeur_label=type_echangeur_label,
        pech11_w_m2_k=pech11_w_m2_k,
        kget_w_k=kget_w_k,
        pech_et1_w_m2_k=pech_et1_w_m2_k,
        mode_debit_et_label=mode_debit_et_label,
        debit1_et_l_h_m2=debit1_et_l_h_m2,
        debit_et_total_m3_h_manual=debit_et_total_m3_h_manual,
    )


