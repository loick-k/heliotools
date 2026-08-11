from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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

SIMSOL_BLUE = "#7fb2f0"
SIMSOL_BLUE_LINE = "#2f5597"
SIMSOL_GREEN_GRID = "#16a34a"
SIMSOL_YELLOW = "#fff200"


def _simsol_bar_layout(fig: go.Figure, *, title: str, x_title: str, y_title: str, height: int = 440) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        height=height,
        margin={"l": 56, "r": 24, "t": 72, "b": 78},
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        font={"family": "Arial", "size": 13, "color": "#111827"},
    )
    fig.update_xaxes(
        title=x_title,
        tickmode="linear",
        showline=True,
        linecolor="#111827",
        gridcolor=SIMSOL_GREEN_GRID,
        gridwidth=0.7,
        griddash="dash",
    )
    fig.update_yaxes(
        title=y_title,
        rangemode="tozero",
        showline=True,
        linecolor="#111827",
        gridcolor=SIMSOL_GREEN_GRID,
        gridwidth=0.7,
        griddash="dash",
    )
    return fig


def _add_yellow_value_labels(fig: go.Figure, rows: pd.DataFrame, *, x_col: str, y_col: str, text_col: str | None = None) -> None:
    ymax = max(float(rows[y_col].max() or 0.0), 1.0)
    for _, row in rows.iterrows():
        value = float(row[y_col])
        if value <= 0:
            continue
        label_value = row[text_col] if text_col else value
        fig.add_annotation(
            x=row[x_col],
            y=max(value * 0.52, ymax * 0.035),
            text=f"{float(label_value):.2g}",
            showarrow=False,
            textangle=-90 if len(str(row[x_col])) <= 2 else 0,
            font={"size": 11, "color": "#111827"},
            bgcolor=SIMSOL_YELLOW,
            bordercolor="#d4b106",
            borderwidth=0.5,
            borderpad=2,
        )


def _daily_profile_simsol_chart(hourly_norm: pd.DataFrame, *, profile_name: str) -> go.Figure:
    rows = hourly_norm.copy()
    rows["hour_label"] = rows["hour"].astype(int).astype(str)
    fig = go.Figure(
        data=[
            go.Bar(
                x=rows["hour_label"],
                y=rows["part_journaliere_pct"],
                marker={"color": SIMSOL_BLUE, "line": {"color": SIMSOL_BLUE_LINE, "width": 1}},
                hovertemplate="Heure %{x} h<br>Coefficient horaire %{y:.2f}<extra></extra>",
            )
        ]
    )
    _add_yellow_value_labels(fig, rows, x_col="hour_label", y_col="part_journaliere_pct")
    fig = _simsol_bar_layout(
        fig,
        title=f"Profil journalier : {profile_name}",
        x_title="Heures de la journée",
        y_title="Coefficient horaire",
        height=460,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=[str(i) for i in range(24)])
    return fig


def _monthly_profile_simsol_chart(monthly_df: pd.DataFrame) -> go.Figure:
    rows = monthly_df.copy()
    rows["MWh"] = rows["E_total_generee_kWh"] / 1000.0
    mean_mwh = max(float(rows["MWh"].mean()), 1e-9)
    rows["coef_multiplicateur"] = rows["MWh"] / mean_mwh
    fig = go.Figure(
        data=[
            go.Bar(
                x=rows["mois"],
                y=rows["coef_multiplicateur"],
                marker={"color": SIMSOL_BLUE, "line": {"color": SIMSOL_BLUE_LINE, "width": 1}},
                hovertemplate="%{x}<br>Coefficient %{y:.2f}<br>%{customdata:.1f} MWh<extra></extra>",
                customdata=rows["MWh"],
            )
        ]
    )
    _add_yellow_value_labels(fig, rows, x_col="mois", y_col="coef_multiplicateur")
    fig = _simsol_bar_layout(
        fig,
        title="Profil annuel : répartition mensuelle",
        x_title="Mois de l'année",
        y_title="Coefficient multiplicateur",
        height=460,
    )
    fig.update_xaxes(type="category", tickangle=-90)
    return fig


def _weekly_profile_table(profile_df: pd.DataFrame) -> pd.DataFrame:
    daily = daily_summary(profile_df).copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["semaine"] = daily["date"].dt.isocalendar().week.astype(int)
    rows = []
    for week, chunk in daily.groupby("semaine", sort=True):
        if int(week) > 52:
            continue
        month_number = int(chunk["month"].mode().iloc[0])
        dominant_type = str(chunk["jour_type"].mode().iloc[0])
        rows.append(
            {
                "Semaine": int(week),
                "Profil": dominant_type,
                "Mois": MONTHS_FR[month_number - 1],
            }
        )
    return pd.DataFrame(rows)


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
            chart_col, table_col = st.columns([2.6, 0.9], gap="large")
            with chart_col:
                fig = _daily_profile_simsol_chart(hourly_norm, profile_name=profile_name)
                st.plotly_chart(fig, width="stretch")
            with table_col:
                st.markdown("#### Coefficients horaires")
                table = hourly_norm.copy()
                table["Heure"] = table["hour"].astype(int).map(lambda value: f"{value} h")
                table["Répartition"] = table["part_journaliere_pct"].round(2)
                st.dataframe(table[["Heure", "Répartition"]], width="stretch", hide_index=True, height=420)
            st.caption("Profil type normalisé en répartition horaire. Les coefficients décrivent la forme d'une journée type avant recalage sur les besoins mensuels.")

        elif selected_section == "Répartition mensuelle":
            bm = bilan_mensuel.copy()
            bm["MWh"] = bm["E_total_generee_kWh"] / 1000
            mean_mwh = max(float(bm["MWh"].mean()), 1e-9)
            bm["coef_multiplicateur"] = bm["MWh"] / mean_mwh
            chart_col, table_col = st.columns([2.2, 0.9], gap="large")
            with chart_col:
                fig = _monthly_profile_simsol_chart(bm)
                st.plotly_chart(fig, width="stretch")
            with table_col:
                st.markdown("#### Coefficients mensuels")
                table = bm.copy()
                table["Coef. multiplicateur"] = table["coef_multiplicateur"].round(2)
                table["Besoin"] = table["MWh"].round(1).map(lambda value: f"{value:.1f} MWh")
                st.dataframe(table[["mois", "Coef. multiplicateur", "Besoin"]], width="stretch", hide_index=True, height=420)
            with st.expander("Détail mensuel de recalage", expanded=False):
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
            chart_col, table_col = st.columns([1.2, 1], gap="large")
            with chart_col:
                fig = px.bar(
                    week,
                    x="weekday_name",
                    y="MWh",
                    title="Répartition annuelle dans la semaine",
                    labels={"weekday_name": "Jour", "MWh": "Besoin utile annuel (MWh)"},
                    color_discrete_sequence=[SIMSOL_BLUE],
                )
                fig.update_layout(height=430, showlegend=False, plot_bgcolor="white")
                fig.update_yaxes(gridcolor=SIMSOL_GREEN_GRID, griddash="dash")
                st.plotly_chart(fig, width="stretch")
            with table_col:
                st.markdown("#### Profil hebdomadaire : année type")
                weekly_table = _weekly_profile_table(profile_df)
                st.dataframe(weekly_table, width="stretch", hide_index=True, height=430)

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
