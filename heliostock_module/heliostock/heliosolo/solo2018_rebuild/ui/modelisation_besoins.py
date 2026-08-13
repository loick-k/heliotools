from __future__ import annotations

import pandas as pd
import streamlit as st

from heliostock.heliosolo.solo2018_rebuild.defaults import DAYS_BY_MONTH, MONTHS
from heliostock.heliosolo.solo2018_rebuild.services.profiles import calc_tef_series as _calc_tef_series
from heliostock.heliosolo.solo2018_rebuild.ui.context import BesoinsState
from heliostock.heliosolo.solo2018_rebuild.ui.editors import apply_editor_pending_edits as _apply_editor_pending_edits
from heliostock.heliosolo.solo2018_rebuild.utils import to_float as _to_float, weighted_mean as _weighted_mean


def _ensure_session_option(key: str, options: list[str], default: str | None = None) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = default if default is not None else options[0]


TEF_MODE_ESM2 = "Méthode ESM2"
TEF_MODE_ESM2_PLUS_3 = "Méthode ESM2+3"
TEF_MODE_ESM2_LEGACY = "Methode ESM2"
TEF_MODE_ESM2_PLUS_3_LEGACY = "Methode ESM2+3"
MODELE_VOLUME_PRODUCTION = "À température de production"
MODELE_VOLUME_DISTRIBUTION = "À température de distribution"
MODELE_VOLUME_PRODUCTION_LEGACY = "A temperature de production"
MODELE_VOLUME_DISTRIBUTION_LEGACY = "A temperature de distribution"


def render_besoins_block(mode_meteo_verification: bool, meteo_impose_map: dict) -> BesoinsState:
    with st.expander("1) Estimation des besoins ECS", expanded=True):
        st.markdown("**Profils annuels/mensuels**")
        c_prof1, c_prof2, c_prof3 = st.columns(3)
        conso_mode_label = c_prof1.selectbox(
            "Profil volume ECS",
            options=["Annuel", "Mensuel"],
            index=0,
            key="ecs_conso_mode_label",
        )
        conso_mode = "constant" if conso_mode_label == "Annuel" else "monthly"

        if mode_meteo_verification:
            tef_mode_label = "TEF imposée par le tableau de vérification"
            tef_mode = "Imposée"
            st.session_state["tef_mode_label"] = tef_mode_label
            c_prof2.text_input(
                "Profil température eau froide",
                value=tef_mode_label,
                disabled=True,
            )
        else:
            if st.session_state.get("tef_mode_label") == "Saisie manuelle":
                st.session_state["tef_mode_label"] = "Saisie annuelle"
            if st.session_state.get("tef_mode_label") == TEF_MODE_ESM2_LEGACY:
                st.session_state["tef_mode_label"] = TEF_MODE_ESM2
            if st.session_state.get("tef_mode_label") == TEF_MODE_ESM2_PLUS_3_LEGACY:
                st.session_state["tef_mode_label"] = TEF_MODE_ESM2_PLUS_3
            _ensure_session_option(
                "tef_mode_label",
                ["Saisie annuelle", "Saisie mensuelle", TEF_MODE_ESM2, TEF_MODE_ESM2_PLUS_3],
                TEF_MODE_ESM2_PLUS_3,
            )
            tef_mode_label = c_prof2.selectbox(
                "Profil température eau froide",
                options=[
                    "Saisie annuelle",
                    "Saisie mensuelle",
                    TEF_MODE_ESM2,
                    TEF_MODE_ESM2_PLUS_3,
                ],
                index=3,
                key="tef_mode_label",
            )
            if tef_mode_label == "Saisie annuelle":
                tef_mode = "Manual"
            elif tef_mode_label == "Saisie mensuelle":
                tef_mode = "ManualMonthly"
            else:
                tef_mode = "ESM2Plus3" if tef_mode_label.endswith("ESM2+3") else "ESM2"

        tecs_mode_label = c_prof3.selectbox(
            "Profil température ECS",
            options=["Annuel", "Mensuel"],
            index=0,
            key="tecs_mode_label",
        )
        tecs_mode = "constant" if tecs_mode_label == "Annuel" else "monthly"

        tef_monthly_df = st.session_state["ecs_rows_df"][["month", "tef_m"]].copy()
        tef_monthly_map_src: dict[str, float] = dict(zip(tef_monthly_df["month"], tef_monthly_df["tef_m"]))
        tef_monthly_map: dict[str, float] = {
            m: float(st.session_state["tef_monthly_map_state"].get(m, tef_monthly_map_src.get(m, 12.0)))
            for m in MONTHS
        }

        if st.session_state.get("ecs_modele_v_label") == MODELE_VOLUME_PRODUCTION_LEGACY:
            st.session_state["ecs_modele_v_label"] = MODELE_VOLUME_PRODUCTION
        if st.session_state.get("ecs_modele_v_label") == MODELE_VOLUME_DISTRIBUTION_LEGACY:
            st.session_state["ecs_modele_v_label"] = MODELE_VOLUME_DISTRIBUTION
        vecs_src_col_ui = "vecs_l_j" if str(st.session_state.get("ecs_modele_v_label", MODELE_VOLUME_PRODUCTION)).startswith("À température de production") else "vecs_dis_l_j"
        vecs_monthly_df = st.session_state["ecs_rows_df"][["month", "days_m", vecs_src_col_ui]].copy()
        vecs_monthly_map_src: dict[str, float] = dict(zip(vecs_monthly_df["month"], vecs_monthly_df[vecs_src_col_ui]))
        vecs_monthly_map: dict[str, float] = {
            m: float(st.session_state["vecs_monthly_map_state"].get(m, vecs_monthly_map_src.get(m, 1500.0)))
            for m in MONTHS
        }

        tecs_monthly_df = st.session_state["ecs_rows_df"][["month", "tecs_m"]].copy()
        tecs_monthly_map_src: dict[str, float] = dict(zip(tecs_monthly_df["month"], tecs_monthly_df["tecs_m"]))
        tecs_monthly_map: dict[str, float] = {
            m: float(st.session_state["tecs_monthly_map_state"].get(m, tecs_monthly_map_src.get(m, 60.0)))
            for m in MONTHS
        }

        monthly_profile_columns: dict[str, list[float] | list[str]] = {"Mois": MONTHS}
        if conso_mode == "monthly":
            monthly_profile_columns["VECS (L/j)"] = [float(vecs_monthly_map.get(m, 1500.0)) for m in MONTHS]
        if tef_mode == "ManualMonthly":
            monthly_profile_columns["Temperature EF (degC)"] = [float(tef_monthly_map.get(m, 12.0)) for m in MONTHS]
        if tecs_mode == "monthly":
            monthly_profile_columns["Temperature ECS (degC)"] = [float(tecs_monthly_map.get(m, 60.0)) for m in MONTHS]

        if len(monthly_profile_columns) > 1:
            st.caption("Tableau mensuel des données variables")
            monthly_profiles_df = pd.DataFrame(monthly_profile_columns)
            monthly_column_config = {}
            if "Temperature EF (degC)" in monthly_profiles_df.columns:
                monthly_column_config["Temperature EF (degC)"] = st.column_config.NumberColumn(
                    "Temperature EF (degC)",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                )
            if "VECS (L/j)" in monthly_profiles_df.columns:
                monthly_column_config["VECS (L/j)"] = st.column_config.NumberColumn(
                    "VECS (L/j)",
                    min_value=0.0,
                    step=1.0,
                    format="%.0f",
                )
            if "Temperature ECS (degC)" in monthly_profiles_df.columns:
                monthly_column_config["Temperature ECS (degC)"] = st.column_config.NumberColumn(
                    "Temperature ECS (degC)",
                    min_value=0.0,
                    step=0.5,
                    format="%.1f",
                )
            monthly_profiles_df = _apply_editor_pending_edits(
                monthly_profiles_df,
                "monthly_profiles_editor",
            )
            monthly_profiles_edit = st.data_editor(
                monthly_profiles_df,
                num_rows="fixed",
                width="stretch",
                hide_index=True,
                disabled=["Mois"],
                column_config=monthly_column_config,
                key="monthly_profiles_editor",
            )
            monthly_records = monthly_profiles_edit.to_dict(orient="records")
            if "Temperature EF (degC)" in monthly_profiles_edit.columns:
                tef_monthly_map = {
                    str(r["Mois"]): _to_float(r["Temperature EF (degC)"], 12.0)
                    for r in monthly_records
                }
                st.session_state["tef_monthly_map_state"] = dict(tef_monthly_map)
            if "VECS (L/j)" in monthly_profiles_edit.columns:
                vecs_monthly_map = {
                    str(r["Mois"]): _to_float(r["VECS (L/j)"], 1500.0)
                    for r in monthly_records
                }
                st.session_state["vecs_monthly_map_state"] = dict(vecs_monthly_map)
            if "Temperature ECS (degC)" in monthly_profiles_edit.columns:
                tecs_monthly_map = {
                    str(r["Mois"]): _to_float(r["Temperature ECS (degC)"], 60.0)
                    for r in monthly_records
                }
                st.session_state["tecs_monthly_map_state"] = dict(tecs_monthly_map)

        st.markdown("**Eau froide**")
        c_ef1, c_ef2 = st.columns(2)
        tef_auto_mean_c = 12.0
        try:
            if mode_meteo_verification:
                text_series_ui = [float(meteo_impose_map.get(m, {}).get("tef", 12.0)) for m in MONTHS]
                days_series_ui = [int(d) for d in DAYS_BY_MONTH]
            else:
                rows_ui = st.session_state["ecs_rows_df"].to_dict(orient="records")
                text_series_ui = [float(r.get("text_m", 12.0)) for r in rows_ui]
                days_series_ui = [int(r.get("days_m", DAYS_BY_MONTH[i])) for i, r in enumerate(rows_ui)]
            if tef_mode == "Imposée":
                tef_auto_mean_c = _weighted_mean(text_series_ui, [float(d) for d in days_series_ui])
            elif tef_mode in ("ESM2", "ESM2Plus3"):
                tef_series_ui = _calc_tef_series(
                    text_m_series=text_series_ui,
                    days_series=days_series_ui,
                    mode=tef_mode,
                )
                tef_auto_mean_c = _weighted_mean(tef_series_ui, [float(d) for d in days_series_ui])
            elif tef_mode == "ManualMonthly":
                tef_auto_mean_c = _weighted_mean(
                    [float(tef_monthly_map.get(m, 12.0)) for m in MONTHS],
                    [float(d) for d in DAYS_BY_MONTH],
                )
        except Exception:
            tef_auto_mean_c = 12.0

        if tef_mode == "Manual":
            tef_manual_c = c_ef1.number_input(
                "Temperature d'eau froide manuelle (degC)",
                min_value=0.0,
                value=12.0,
                step=0.5,
                key="tef_manual_input",
            )
        elif tef_mode == "ManualMonthly":
            tef_auto_mean_c = _weighted_mean(
                [float(tef_monthly_map.get(m, 12.0)) for m in MONTHS],
                [float(d) for d in DAYS_BY_MONTH],
            )
            tef_manual_c = float(tef_auto_mean_c)
            st.session_state["tef_monthly_mean_display"] = round(float(tef_auto_mean_c), 2)
            c_ef1.number_input(
                "Temperature EF moyenne (degC)",
                min_value=0.0,
                value=st.session_state["tef_monthly_mean_display"],
                step=0.1,
                disabled=True,
                key="tef_monthly_mean_display",
            )
        elif tef_mode == "Imposée":
            tef_manual_c = float(tef_auto_mean_c)
            c_ef1.number_input(
                "Température EF moyenne imposée (degC)",
                min_value=0.0,
                value=round(float(tef_auto_mean_c), 2),
                step=0.1,
                disabled=True,
                key="tef_imposee_moy_display",
            )
        else:
            tef_manual_c = float(tef_auto_mean_c)
            st.session_state["tef_manual_auto_display"] = round(float(tef_auto_mean_c), 2)
            c_ef1.number_input(
                "Température d'eau froide manuelle (degC)",
                min_value=0.0,
                value=st.session_state["tef_manual_auto_display"],
                step=0.5,
                disabled=True,
                key="tef_manual_auto_display",
            )

        st.markdown("**Eau chaude sanitaire**")
        c_ecs1, c_ecs2 = st.columns(2)
        modele_v_eau_chaude_label = c_ecs1.selectbox(
            "Consommation ECS définie :",
            options=[MODELE_VOLUME_PRODUCTION, MODELE_VOLUME_DISTRIBUTION],
            index=0,
            key="ecs_modele_v_label",
        )
        modele_v_eau_chaude = "production" if modele_v_eau_chaude_label.startswith("À température de production") else "distribution"
        if tecs_mode == "monthly":
            tecs_mean = float(sum(float(tecs_monthly_map.get(m, 60.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH)) / max(1.0, float(sum(DAYS_BY_MONTH))))
            st.session_state["tecs_const_input"] = round(tecs_mean, 2)
        tecs_const_c = c_ecs2.number_input(
            "Température ECS constante (degC)",
            min_value=0.0,
            value=float(st.session_state.get("tecs_const_input", 60.0)),
            step=0.5,
            disabled=(tecs_mode == "monthly"),
            key="tecs_const_input",
        )
        if tecs_mode == "monthly":
            c_ecs2.caption("Moyenne annuelle du tableau mensuel.")

        vecs_input_label = (
            "Volume ECS production constant (L/jour)"
            if modele_v_eau_chaude == "production"
            else "Volume ECS distribué constant (L/jour)"
        )
        vecs_src_col = "vecs_l_j" if modele_v_eau_chaude == "production" else "vecs_dis_l_j"
        if "vecs_const_input" not in st.session_state:
            st.session_state["vecs_const_input"] = 1500.0

        vecs_const_disabled = conso_mode == "monthly"
        if vecs_const_disabled and conso_mode == "monthly":
            total_days_vecs = float(sum(DAYS_BY_MONTH))
            if total_days_vecs > 0:
                vecs_mean = float(sum(float(vecs_monthly_map.get(m, 0.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH)) / total_days_vecs)
                st.session_state["vecs_const_input"] = round(vecs_mean, 2)

        c_ecs3, c_ecs4 = st.columns(2)
        c_ecs3.number_input(
            vecs_input_label,
            min_value=0.0,
            step=50.0,
            disabled=vecs_const_disabled,
            key="vecs_const_input",
        )
        vecs_const_l_j = float(st.session_state.get("vecs_const_input", 1500.0))
        if vecs_const_disabled:
            st.caption("Volume constant grisé: conserve comme valeur de référence annuelle.")

        if conso_mode == "monthly":
            ecs_total_l_an = float(sum(float(vecs_monthly_map.get(m, 0.0)) * d for m, d in zip(MONTHS, DAYS_BY_MONTH)))
        else:
            ecs_total_l_an = float(vecs_const_l_j) * float(sum(DAYS_BY_MONTH))
        ecs_total_m3_an = ecs_total_l_an / 1000.0
        c_ecs4.number_input(
            "ECS total estimé (m3/an)",
            min_value=0.0,
            value=round(ecs_total_m3_an, 2),
            step=0.1,
            disabled=True,
        )

        tecs_dis_mode = "constant"
        tecs_dis_const_c = 55.0
        tecs_dis_monthly_df = st.session_state["ecs_rows_df"][["month", "tecs_dis_m"]].copy()
        tecs_dis_monthly_map_src: dict[str, float] = dict(zip(tecs_dis_monthly_df["month"], tecs_dis_monthly_df["tecs_dis_m"]))
        tecs_dis_monthly_map: dict[str, float] = {
            m: float(st.session_state["tecs_dis_monthly_map_state"].get(m, tecs_dis_monthly_map_src.get(m, tecs_dis_const_c)))
            for m in MONTHS
        }
        if modele_v_eau_chaude == "distribution":
            st.caption("En mode distribution, VECS production est calculé automatiquement à partir de VECS distribué, TECS distribuée, TECS production et TEF.")
            c_ecs8, c_ecs9 = st.columns(2)
            tecs_dis_mode_label = c_ecs8.selectbox(
                "Profil de température ECS distribuée",
                options=["Annuel", "Mensuel"],
                index=0,
                key="tecs_dis_mode_label",
            )
            tecs_dis_mode = "constant" if tecs_dis_mode_label == "Annuel" else "monthly"
            tecs_dis_const_c = c_ecs9.number_input(
                "Température ECS distribuée constante (degC)",
                min_value=0.0,
                value=55.0,
                step=0.5,
                key="tecs_dis_const_input",
            )
            if tecs_dis_mode == "monthly":
                st.caption("Variation mensuelle température ECS distribuée (degC)")
                tecs_dis_df = _apply_editor_pending_edits(
                    pd.DataFrame({"Mois": MONTHS, "Temperature distribuee (degC)": [float(tecs_dis_monthly_map.get(m, tecs_dis_const_c)) for m in MONTHS]}),
                    "tecs_dis_monthly_editor",
                )
                tecs_dis_edit = st.data_editor(
                    tecs_dis_df,
                    num_rows="fixed",
                    width="stretch",
                    hide_index=True,
                    disabled=["Mois"],
                    column_config={
                        "Temperature distribuee (degC)": st.column_config.NumberColumn("Temperature distribuee (degC)", min_value=0.0, step=0.5),
                    },
                    key="tecs_dis_monthly_editor",
                )
                tecs_dis_monthly_map = {str(r["Mois"]): _to_float(r["Temperature distribuee (degC)"], tecs_dis_const_c) for r in tecs_dis_edit.to_dict(orient="records")}
                st.session_state["tecs_dis_monthly_map_state"] = dict(tecs_dis_monthly_map)
    return BesoinsState(
        conso_mode=conso_mode,
        tef_mode_label=tef_mode_label,
        tef_mode=tef_mode,
        tef_monthly_map=tef_monthly_map,
        vecs_monthly_map=vecs_monthly_map,
        tecs_mode=tecs_mode,
        tecs_const_c=tecs_const_c,
        tecs_monthly_map=tecs_monthly_map,
        tef_manual_c=tef_manual_c,
        modele_v_eau_chaude=modele_v_eau_chaude,
        vecs_const_l_j=vecs_const_l_j,
        tecs_dis_mode=tecs_dis_mode,
        tecs_dis_const_c=tecs_dis_const_c,
        tecs_dis_monthly_map=tecs_dis_monthly_map,
    )


