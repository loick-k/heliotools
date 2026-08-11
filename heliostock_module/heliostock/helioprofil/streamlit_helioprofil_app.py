from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from .profile_generator import (
    GeneratorConfig,
    MONTHS_FR,
    build_excel_bytes,
    daily_summary,
    generate_profile,
    normalized_hourly_profile,
    weekly_distribution,
)


APP_DIR = Path(__file__).resolve().parent
PROFILE_LIBRARY = {
    "Station de lavage poids lourds": APP_DIR / "profiles" / "station_lavage_poids_lourds.csv",
}


def _default_input_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mois_num": range(1, 13),
            "mois": MONTHS_FR,
            "gaz_mesure": [0.0] * 12,
            "vehicules": [0.0] * 12,
        }
    )


def _niort_demo_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mois_num": range(1, 13),
            "mois": MONTHS_FR,
            "gaz_mesure": [
                23551.296003,
                19115.0405982,
                15918.7214889,
                13571.9837821125,
                12559.8703914,
                10025.3476602,
                10853.3712312,
                8827.8984945,
                12707.7554871,
                14979.9368655,
                19102.195431,
                23998.9675266,
            ],
            "vehicules": [0.0] * 12,
        }
    )


def _input_mode_from_label(label: str) -> str:
    return {
        "Relevés mensuels gaz": "gaz_mensuel",
        "Véhicules mensuels": "vehicules_mensuels",
        "Véhicules annuels / véhicules par jour": "vehicules_annuels",
        "Hybride": "hybride",
    }[label]


def render_helioprofil_app() -> None:
    """Render HelioProfil inside the HelioTools portal."""

    st.title("HelioProfil")
    st.caption(
        "Générateur de profils horaires 8760 h pour créer un fichier Excel de besoins process "
        "compatible avec HelioDyn."
    )

    left, right = st.columns([1, 2], gap="large")

    with left:
        st.subheader("Paramètres")
        year = st.number_input("Année", min_value=2000, max_value=2100, value=2025, step=1)
        profile_name = st.selectbox("Profil type", list(PROFILE_LIBRARY.keys()), index=0)
        demand_temperature_c = st.number_input(
            "Température de besoin (°C)",
            min_value=20.0,
            max_value=95.0,
            value=60.0,
            step=1.0,
        )
        mode_label = st.radio(
            "Mode de recalage",
            [
                "Relevés mensuels gaz",
                "Véhicules mensuels",
                "Véhicules annuels / véhicules par jour",
                "Hybride",
            ],
            index=0,
        )
        input_mode = _input_mode_from_label(mode_label)

        gas_efficiency = st.number_input(
            "Rendement gaz estimé",
            min_value=0.1,
            max_value=1.2,
            value=0.75,
            step=0.01,
            format="%.2f",
        )
        gas_unit = st.selectbox("Unité des relevés gaz", ["kWh", "MWh", "m3 gaz"], index=0)
        gas_conversion = st.number_input("Conversion m³ gaz vers kWh", min_value=5.0, max_value=15.0, value=11.2, step=0.1)
        kwh_per_vehicle = st.number_input("kWh utile / véhicule", min_value=1.0, max_value=500.0, value=45.0, step=1.0)
        vehicles_per_day = st.number_input("Véhicules / jour ouvert", min_value=0.0, max_value=500.0, value=13.0, step=0.5)

        with st.expander("Fermetures", expanded=False):
            close_weekends = st.checkbox("Week-ends fermés", value=True)
            close_holidays = st.checkbox("Jours fériés France fermés", value=True)
            st.checkbox(
                "Conserver la cible mensuelle et compenser sur les jours ouverts",
                value=True,
                disabled=True,
            )
            custom_closures = st.text_area(
                "Fermetures spécifiques",
                value="",
                placeholder="2025-08-01:2025-08-15\n2025-12-24\n2025-12-31",
                help="Une date par ligne ou une plage YYYY-MM-DD:YYYY-MM-DD.",
            )

    with right:
        st.subheader("Données mensuelles")
        if st.button("Charger l'exemple Niort 2025", type="secondary"):
            st.session_state["helioprofil_input_table"] = _niort_demo_table()

        if "helioprofil_input_table" not in st.session_state:
            st.session_state["helioprofil_input_table"] = _default_input_table()

        input_table = st.data_editor(
            st.session_state["helioprofil_input_table"],
            num_rows="fixed",
            width="stretch",
            column_config={
                "mois_num": st.column_config.NumberColumn("N°", disabled=True),
                "mois": st.column_config.TextColumn("Mois", disabled=True),
                "gaz_mesure": st.column_config.NumberColumn(
                    "Gaz mesuré",
                    help="Selon l'unité choisie dans les paramètres.",
                    format="%.2f",
                ),
                "vehicules": st.column_config.NumberColumn(
                    "Véhicules",
                    help="Nombre mensuel de véhicules, si mode véhicules ou hybride.",
                    format="%.2f",
                ),
            },
            hide_index=True,
        )
        st.session_state["helioprofil_input_table"] = input_table

    config = GeneratorConfig(
        year=int(year),
        profile_name=profile_name,
        demand_temperature_c=float(demand_temperature_c),
        gas_efficiency=float(gas_efficiency),
        gas_unit=gas_unit,
        gas_conversion_kwh_per_m3=float(gas_conversion),
        kwh_per_vehicle=float(kwh_per_vehicle),
        vehicles_per_day=float(vehicles_per_day),
        input_mode=input_mode,
        close_weekends=bool(close_weekends),
        close_french_holidays=bool(close_holidays),
        compensate_closed_days=True,
        remove_feb_29=True,
        output_all_in_ht=True,
    )

    try:
        monthly_gas = input_table["gaz_mesure"].tolist()
        monthly_vehicles = input_table["vehicules"].tolist()
        if input_mode == "gaz_mensuel":
            monthly_vehicles = None
        elif input_mode == "vehicules_mensuels":
            monthly_gas = None
        elif input_mode == "vehicules_annuels":
            monthly_gas = None
            monthly_vehicles = None

        profile_df, bilan_mensuel, profile_type = generate_profile(
            config=config,
            profile_csv=PROFILE_LIBRARY[profile_name],
            monthly_gas_values=monthly_gas,
            monthly_vehicle_values=monthly_vehicles,
            custom_closure_text=custom_closures,
        )

        if len(profile_df) != 8760:
            st.error(f"Le profil contient {len(profile_df)} heures. HelioDyn attend 8760 lignes.")
        else:
            st.success("Profil 8760 h généré et compatible avec le format d'import HelioDyn.")

        total_mwh = profile_df["E_total_kWh"].sum() / 1000.0
        peak_kw = profile_df["E_total_kWh"].max()
        open_days = profile_df.loc[~profile_df["is_closed"], "date"].nunique()
        closed_days = profile_df.loc[profile_df["is_closed"], "date"].nunique()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Besoin annuel", f"{total_mwh:.1f} MWh")
        c2.metric("Pic horaire", f"{peak_kw:.0f} kW")
        c3.metric("Jours ouverts", f"{open_days}")
        c4.metric("Jours fermés", f"{closed_days}")

        st.subheader("Graphiques de contrôle")
        selected_section = st.radio(
            "Vue",
            [
                "Profil type journalier",
                "Répartition mensuelle",
                "Répartition semaine",
                "Profil journalier / puissance",
            ],
            horizontal=True,
            label_visibility="collapsed",
        )

        if selected_section == "Profil type journalier":
            hourly_norm = normalized_hourly_profile(profile_type)
            fig = px.line(
                hourly_norm,
                x="hour",
                y="part_journaliere_pct",
                markers=True,
                title="Profil type normalisé journalier par heure",
                labels={"hour": "Heure", "part_journaliere_pct": "Part du besoin journalier (%)"},
            )
            fig.update_xaxes(dtick=1)
            st.plotly_chart(fig, width="stretch")
            st.caption("Profil type issu de la station de lavage poids lourds d'Angers, normalisé en répartition horaire.")

        elif selected_section == "Répartition mensuelle":
            bm = bilan_mensuel.copy()
            bm["MWh"] = bm["E_total_generee_kWh"] / 1000
            fig = px.bar(
                bm,
                x="mois",
                y="MWh",
                title="Répartition annuelle du besoin énergétique par mois",
                labels={"mois": "Mois", "MWh": "Besoin utile (MWh/mois)"},
            )
            st.plotly_chart(fig, width="stretch")
            st.dataframe(
                bm[
                    [
                        "mois",
                        "cible_besoin_utile_kWh",
                        "E_total_generee_kWh",
                        "ecart_cible_kWh",
                        "jours_ouverts",
                        "jours_fermes",
                        "pic_horaire_kW",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )

        elif selected_section == "Répartition semaine":
            week = weekly_distribution(profile_df)
            week["MWh"] = week["E_total_kWh"] / 1000
            fig = px.bar(
                week,
                x="weekday_name",
                y="MWh",
                title="Répartition annuelle du besoin énergétique dans la semaine",
                labels={"weekday_name": "Jour", "MWh": "Besoin utile annuel (MWh)"},
            )
            st.plotly_chart(fig, width="stretch")
            st.dataframe(week, width="stretch", hide_index=True)

        else:
            daily = daily_summary(profile_df)
            daily["date"] = pd.to_datetime(daily["date"])
            daily["MWh"] = daily["E_total_kWh"] / 1000
            fig1 = px.bar(
                daily,
                x="date",
                y="MWh",
                title="Besoin énergétique journalier",
                labels={"date": "Date", "MWh": "Besoin utile (MWh/j)"},
            )
            st.plotly_chart(fig1, width="stretch")

            sample = profile_df[["datetime", "E_total_kWh"]].copy()
            sample["P_moy_horaire_kW"] = sample["E_total_kWh"]
            fig2 = px.line(
                sample,
                x="datetime",
                y="P_moy_horaire_kW",
                title="Profil de puissance horaire moyenne",
                labels={"datetime": "Date", "P_moy_horaire_kW": "Puissance moyenne horaire (kW)"},
            )
            st.plotly_chart(fig2, width="stretch")

        st.subheader("Export Excel")
        xlsx_bytes = build_excel_bytes(profile_df, bilan_mensuel, profile_type, config, input_table=input_table)
        st.download_button(
            label="Télécharger le profil 8760 h Excel",
            data=xlsx_bytes,
            file_name=f"profil_8760h_{profile_name.lower().replace(' ', '_')}_{int(year)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

        with st.expander("Aperçu du fichier compatible HelioDyn"):
            st.dataframe(
                profile_df[["hour_index", "month", "day", "hour", "E besoin HT kWh", "E besoin BT kWh"]].head(24),
                width="stretch",
                hide_index=True,
            )

    except Exception as exc:
        st.error("HelioProfil n'a pas pu générer le profil.")
        st.exception(exc)
