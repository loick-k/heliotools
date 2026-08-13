from __future__ import annotations

import pandas as pd
import streamlit as st

import heliostock.heliosolo.solo2018_rebuild.core.solo_v0_engine as solo_v0_mod
from heliostock.heliosolo.solo2018_rebuild.defaults import MONTHS
from heliostock.heliosolo.solo2018_rebuild.ui.context import BouclageState
from heliostock.heliosolo.solo2018_rebuild.ui.editors import apply_editor_pending_edits as _apply_editor_pending_edits
from heliostock.heliosolo.solo2018_rebuild.utils import to_float as _to_float


PERTES_BOUCLE_LABELS_LEGACY = {
    "Debit et delta T connus": "Débit et delta T connus",
    "Boucle courte bien isolee": "Boucle courte bien isolée",
    "Boucle qualite moyenne": "Boucle qualité moyenne",
    "Boucle longue mal isolee": "Boucle longue mal isolée",
}


def render_bouclage_block(bouclage_block_container, mode_meteo_verification: bool) -> BouclageState:
    with bouclage_block_container.expander("3) Bouclage sanitaire", expanded=True):
        st.caption(
            "Sans calibration de cette référence au type de bâtiment, les pertes de bouclage "
            "peuvent être fortement biaisées."
        )

        c_b1, c_b2 = st.columns(2)
        type_bouclage_label = c_b1.selectbox(
            "Type de bouclage",
            options=["Sans apport solaire au bouclage", "Avec apport solaire indirect au bouclage"],
            index=0 if mode_meteo_verification else 1,
            key="type_bouclage_label",
        )
        type_bouclage = "aucun_apport" if type_bouclage_label.startswith("Sans") else "apport_indirect"
        if st.session_state.get("mode_pertes_boucle_label") in PERTES_BOUCLE_LABELS_LEGACY:
            st.session_state["mode_pertes_boucle_label"] = PERTES_BOUCLE_LABELS_LEGACY[
                st.session_state["mode_pertes_boucle_label"]
            ]
        mode_pertes_boucle_label = c_b2.selectbox(
            "Calcul des pertes de bouclage",
            options=[
                "Pas de pertes de bouclage",
                "Saisie pertes (kWh/j)",
                "Débit et delta T connus",
                "Longueur et isolation connues",
                "Boucle courte bien isolée",
                "Boucle qualité moyenne",
                "Boucle longue mal isolée",
            ],
            index=0,
            key="mode_pertes_boucle_label",
        )
        mode_pertes_boucle = {
            "Pas de pertes de bouclage": "aucune",
            "Saisie pertes (kWh/j)": "saisie_kwh_j",
            "Débit et delta T connus": "debit_delta",
            "Longueur et isolation connues": "long_kl",
            "Boucle courte bien isolée": "bon",
            "Boucle qualité moyenne": "moyen",
            "Boucle longue mal isolée": "mauvais",
        }[mode_pertes_boucle_label]

        debit_bouclage_l_h = 0.0
        delta_tmax_bouclage_k = 0.0
        long_bouclage_m = 0.0
        kl_bouclage_w_m_k = 0.0
        long1_boucle_bon_m_par_unite = solo_v0_mod.LONG1_BOUCLE_BON_M_PAR_LGT
        long1_boucle_moyen_m_par_unite = solo_v0_mod.LONG1_BOUCLE_MOYEN_M_PAR_LGT
        long1_boucle_mauvais_m_par_unite = solo_v0_mod.LONG1_BOUCLE_MAUVAIS_M_PAR_LGT
        kl_boucle_bon_w_m_k = solo_v0_mod.KL_BOUCLE_BON_W_M_K
        kl_boucle_moyen_w_m_k = solo_v0_mod.KL_BOUCLE_MOYEN_W_M_K
        kl_boucle_mauvais_w_m_k = solo_v0_mod.KL_BOUCLE_MAUVAIS_W_M_K
        pertes_boucle_mode_saisie = "annuelle"
        pertes_boucle_annuelle_kwh_an = 0.0
        pertes_boucle_monthly_map: dict[str, float] = {
            m: float(st.session_state["pertes_boucle_monthly_map_state"].get(m, 0.0)) for m in MONTHS
        }
        if mode_pertes_boucle == "saisie_kwh_j":
            c_bs1, c_bs2 = st.columns(2)
            pertes_boucle_mode_saisie = c_bs1.selectbox(
                "Mode de saisie des pertes",
                options=["Saisie annuelle", "Saisie mensuelle"],
                index=0,
                key="pertes_boucle_mode_saisie",
            )
            if pertes_boucle_mode_saisie == "Saisie annuelle":
                pertes_boucle_annuelle_kwh_an = c_bs2.number_input(
                    "Pertes bouclage annuelles (kWh/an)",
                    min_value=0.0,
                    value=0.0,
                    step=100.0,
                    key="pertes_boucle_annuelle_kwh_an",
                )
                pertes_j_const = float(pertes_boucle_annuelle_kwh_an) / 365.0
                pertes_boucle_monthly_map = {m: pertes_j_const for m in MONTHS}
            else:
                pertes_df = _apply_editor_pending_edits(
                    pd.DataFrame({"Mois": MONTHS, "Pertes bouclage (kWh/j)": [float(pertes_boucle_monthly_map.get(m, 0.0)) for m in MONTHS]}),
                    "pertes_boucle_monthly_editor",
                )
                pertes_edit = st.data_editor(
                    pertes_df,
                    num_rows="fixed",
                    width="stretch",
                    hide_index=True,
                    disabled=["Mois"],
                    column_config={
                        "Pertes bouclage (kWh/j)": st.column_config.NumberColumn("Pertes bouclage (kWh/j)", min_value=0.0, step=0.1),
                    },
                    key="pertes_boucle_monthly_editor",
                )
                pertes_boucle_monthly_map = {
                    str(r["Mois"]): _to_float(r["Pertes bouclage (kWh/j)"], 0.0)
                    for r in pertes_edit.to_dict(orient="records")
                }
            st.session_state["pertes_boucle_monthly_map_state"] = dict(pertes_boucle_monthly_map)
        if mode_pertes_boucle == "debit_delta":
            c_bd1, c_bd2 = st.columns(2)
            debit_bouclage_l_h = c_bd1.number_input("Débit de bouclage (L/h)", min_value=0.0, value=300.0, step=10.0)
            delta_tmax_bouclage_k = c_bd2.number_input("Delta T max bouclage (degC)", min_value=0.0, value=5.0, step=0.5)
        elif mode_pertes_boucle == "long_kl":
            c_bl1, c_bl2 = st.columns(2)
            long_bouclage_m = c_bl1.number_input("Longueur de boucle (m)", min_value=0.0, value=120.0, step=5.0)
            kl_bouclage_w_m_k = c_bl2.number_input("Perte linéique boucle (W/m/degC)", min_value=0.0, value=0.3, step=0.01, format="%.2f")
        elif mode_pertes_boucle == "bon":
            c_bb1, c_bb2 = st.columns(2)
            long1_boucle_bon_m_par_unite = c_bb1.number_input("Longueur boucle par unité (m/unité)", min_value=0.0, value=solo_v0_mod.LONG1_BOUCLE_BON_M_PAR_LGT, step=0.1)
            kl_boucle_bon_w_m_k = c_bb2.number_input("Perte linéique boucle (W/m/degC)", min_value=0.0, value=solo_v0_mod.KL_BOUCLE_BON_W_M_K, step=0.01, format="%.2f")
        elif mode_pertes_boucle == "moyen":
            c_bm1, c_bm2 = st.columns(2)
            long1_boucle_moyen_m_par_unite = c_bm1.number_input("Longueur boucle par unité (m/unité)", min_value=0.0, value=solo_v0_mod.LONG1_BOUCLE_MOYEN_M_PAR_LGT, step=0.1)
            kl_boucle_moyen_w_m_k = c_bm2.number_input("Perte linéique boucle (W/m/degC)", min_value=0.0, value=solo_v0_mod.KL_BOUCLE_MOYEN_W_M_K, step=0.01, format="%.2f")
        elif mode_pertes_boucle == "mauvais":
            c_bv1, c_bv2 = st.columns(2)
            long1_boucle_mauvais_m_par_unite = c_bv1.number_input("Longueur boucle par unité (m/unité)", min_value=0.0, value=solo_v0_mod.LONG1_BOUCLE_MAUVAIS_M_PAR_LGT, step=0.1)
            kl_boucle_mauvais_w_m_k = c_bv2.number_input("Perte linéique boucle (W/m/degC)", min_value=0.0, value=solo_v0_mod.KL_BOUCLE_MAUVAIS_W_M_K, step=0.01, format="%.2f")

        pertes_boucle_kwh_j = 0.0
        bouclage_pertes_placeholder = st.empty()
    return BouclageState(
        type_bouclage_label=type_bouclage_label,
        type_bouclage=type_bouclage,
        mode_pertes_boucle_label=mode_pertes_boucle_label,
        mode_pertes_boucle=mode_pertes_boucle,
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
        pertes_boucle_monthly_map=pertes_boucle_monthly_map,
        pertes_boucle_kwh_j=pertes_boucle_kwh_j,
        bouclage_pertes_placeholder=bouclage_pertes_placeholder,
    )


