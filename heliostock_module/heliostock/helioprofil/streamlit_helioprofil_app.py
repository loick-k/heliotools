from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .profile_generator import (
    CP_WHLK,
    DEFAULT_L_60C_PER_EHPAD_RESIDENT_DAY,
    DEFAULT_L_60C_PER_VEHICLE,
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
    "EHPAD cuisine ECS + lingerie": APP_DIR / "profiles" / "ehpad_cuisine_lingerie.csv",
}
PROFILE_THEMES_COMING_SOON = [
    "Logement",
    "Hébergement collectif",
    "Équipement sportif",
    "Restauration collective",
    "Industrie avec besoin process",
]
PROFILE_NOTES = {
    "Station de lavage poids lourds": (
        "Ratio SOCOL retenu : 860 L équivalent 60 °C par véhicule lavé à l'eau chaude. "
        "Cette valeur est documentée à partir du site Prolavage Poids Lourds à Angers et correspond "
        "à environ 45 kWh utiles par véhicule avec une eau froide de référence à 15 °C."
    ),
    "EHPAD cuisine ECS + lingerie": (
        "Profil horaire approché depuis la courbe du guide ADEME/COSTIC pour un EHPAD avec cuisine "
        "alimentée en ECS et lingerie. Ratio SOCOL affiché : 15 L équivalent 60 °C par résident et par jour. "
        "Si des relevés gaz sont utilisés, HelioProfil distingue le besoin ECS utile, un bouclage sanitaire "
        "estimé depuis le talon estival et un chauffage résiduel non exporté dans le profil HelioDyn."
    ),
}
PROFILE_BAR_COLOR = "#22B2A6"
PROFILE_BAR_LINE = "#486DAC"
PROFILE_GRID_COLOR = "#D9E1EF"
PROFILE_LABEL_BG = "#F8FAFC"
PROFILE_LABEL_BORDER = "#22B2A6"
PROFILE_FONT_FAMILY = "PF Beau Sans Pro, Inter, Segoe UI, Arial, sans-serif"


def _profile_bar_layout(fig: go.Figure, *, title: str, x_title: str, y_title: str, height: int = 440) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        height=height,
        margin={"l": 56, "r": 24, "t": 72, "b": 78},
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        font={"family": PROFILE_FONT_FAMILY, "size": 13, "color": "#111827"},
    )
    fig.update_xaxes(
        title=x_title,
        tickmode="linear",
        showline=True,
        linecolor="#64748B",
        gridcolor=PROFILE_GRID_COLOR,
        gridwidth=0.7,
        griddash="dash",
    )
    fig.update_yaxes(
        title=y_title,
        rangemode="tozero",
        showline=True,
        linecolor="#64748B",
        gridcolor=PROFILE_GRID_COLOR,
        gridwidth=0.7,
        griddash="dash",
    )
    return fig


def _add_profile_value_labels(fig: go.Figure, rows: pd.DataFrame, *, x_col: str, y_col: str, text_col: str | None = None) -> None:
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
            font={"family": PROFILE_FONT_FAMILY, "size": 11, "color": "#111827"},
            bgcolor=PROFILE_LABEL_BG,
            bordercolor=PROFILE_LABEL_BORDER,
            borderwidth=0.5,
            borderpad=2,
        )


def _daily_profile_chart(hourly_norm: pd.DataFrame, *, profile_name: str) -> go.Figure:
    rows = hourly_norm.copy()
    rows["hour_label"] = rows["hour"].astype(int).astype(str)
    fig = go.Figure(
        data=[
            go.Bar(
                x=rows["hour_label"],
                y=rows["part_journaliere_pct"],
                marker={"color": PROFILE_BAR_COLOR, "line": {"color": PROFILE_BAR_LINE, "width": 1}},
                hovertemplate="Heure %{x} h<br>Coefficient horaire %{y:.2f}<extra></extra>",
            )
        ]
    )
    _add_profile_value_labels(fig, rows, x_col="hour_label", y_col="part_journaliere_pct")
    fig = _profile_bar_layout(
        fig,
        title=f"Profil journalier : {profile_name}",
        x_title="Heures de la journée",
        y_title="Coefficient horaire",
        height=460,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=[str(i) for i in range(24)])
    return fig


def _monthly_profile_chart(monthly_df: pd.DataFrame) -> go.Figure:
    rows = monthly_df.copy()
    rows["MWh"] = rows["E_total_generee_kWh"] / 1000.0
    mean_mwh = max(float(rows["MWh"].mean()), 1e-9)
    rows["coef_multiplicateur"] = rows["MWh"] / mean_mwh
    fig = go.Figure(
        data=[
            go.Bar(
                x=rows["mois"],
                y=rows["coef_multiplicateur"],
                marker={"color": PROFILE_BAR_COLOR, "line": {"color": PROFILE_BAR_LINE, "width": 1}},
                hovertemplate="%{x}<br>Coefficient %{y:.2f}<br>%{customdata:.1f} MWh<extra></extra>",
                customdata=rows["MWh"],
            )
        ]
    )
    _add_profile_value_labels(fig, rows, x_col="mois", y_col="coef_multiplicateur")
    fig = _profile_bar_layout(
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
            "véhicules": [0.0] * 12,
        }
    )


def _ehpad_default_input_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mois_num": range(1, 13),
            "mois": MONTHS_FR,
            "gaz_mesure": [0.0] * 12,
            "volume_l_j": [0.0] * 12,
        }
    )


def _month_days() -> list[int]:
    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _volume_l_day_to_kwh_month(volume_l_day: float, days: int, *, cold_water_c: float = 15.0) -> float:
    delta_t = max(0.0, 60.0 - float(cold_water_c))
    return max(0.0, float(volume_l_day)) * float(days) * CP_WHLK * delta_t / 1000.0


def _ehpad_targets_from_ratio(résidents: float, ratio_l_résident_day: float) -> tuple[list[float], pd.DataFrame]:
    daily_l = max(0.0, float(résidents)) * max(0.0, float(ratio_l_résident_day))
    useful = [_volume_l_day_to_kwh_month(daily_l, days) for days in _month_days()]
    return _ehpad_detail_from_parts(useful, [0.0] * 12, [0.0] * 12)


def _ehpad_targets_from_daily_volumes(volumes_l_day: list[float]) -> tuple[list[float], pd.DataFrame]:
    useful = [
        _volume_l_day_to_kwh_month(volume, days)
        for volume, days in zip(volumes_l_day, _month_days())
    ]
    return _ehpad_detail_from_parts(useful, [0.0] * 12, [0.0] * 12)


def _gas_values_to_useful_kwh(values: list[float], *, gas_unit: str, gas_conversion_kwh_per_m3: float, gas_efficiency: float) -> pd.Series:
    gas = pd.Series(values, index=range(1, 13), dtype=float).fillna(0.0)
    if gas_unit == "MWh":
        gas = gas * 1000.0
    elif gas_unit == "m3 gaz":
        gas = gas * gas_conversion_kwh_per_m3
    return gas * max(0.0, float(gas_efficiency))


def _ehpad_targets_from_gas_talon(
    gas_values: list[float],
    *,
    gas_unit: str,
    gas_conversion_kwh_per_m3: float,
    gas_efficiency: float,
    résidents: float,
    ratio_l_résident_day: float,
) -> tuple[list[float], pd.DataFrame]:
    useful, _detail = _ehpad_targets_from_ratio(résidents, ratio_l_résident_day)
    days = _month_days()
    useful_from_gas = _gas_values_to_useful_kwh(
        gas_values,
        gas_unit=gas_unit,
        gas_conversion_kwh_per_m3=gas_conversion_kwh_per_m3,
        gas_efficiency=gas_efficiency,
    )
    summer_months = [6, 7, 8, 9]
    gas_daily_talon = min((float(useful_from_gas.loc[m]) / days[m - 1] for m in summer_months), default=0.0)
    useful_daily_talon = min((float(useful[m - 1]) / days[m - 1] for m in summer_months), default=0.0)
    loop_daily = max(0.0, gas_daily_talon - useful_daily_talon)
    loop = [loop_daily * d for d in days]
    target = [u + b for u, b in zip(useful, loop)]
    heating = [max(0.0, float(useful_from_gas.loc[m]) - target[m - 1]) for m in range(1, 13)]
    return _ehpad_detail_from_parts(useful, loop, heating)


def _ehpad_detail_from_parts(useful: list[float], loop: list[float], heating: list[float]) -> tuple[list[float], pd.DataFrame]:
    target = [float(u) + float(b) for u, b in zip(useful, loop)]
    detail = pd.DataFrame(
        {
            "mois": MONTHS_FR,
            "Besoin ECS utile (kWh)": useful,
            "Bouclage sanitaire estimé (kWh)": loop,
            "Chauffage residuel estimé (kWh)": heating,
            "Cible exportée HelioDyn (kWh)": target,
        }
    )
    return target, detail


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
            "véhicules": [0.0] * 12,
        }
    )


def _input_mode_from_label(label: str) -> str:
    return {
        "Relevés mensuels gaz": "gaz_mensuel",
        "Véhicules mensuels": "véhicules_mensuels",
        "Véhicules annuels / véhicules par jour": "véhicules_annuels",
        "Hybride": "hybride",
        "Ratio SOCOL résidents": "ehpad_ratio_socol",
        "Profil L/jour moyen": "ehpad_l_jour",
        "Releves gaz avec talon": "ehpad_gaz_talon",
    }[label]


def _input_columns_for_mode(input_mode: str) -> list[str]:
    columns = ["mois_num", "mois"]
    if input_mode in {"gaz_mensuel", "hybride"}:
        columns.append("gaz_mesure")
    if input_mode in {"véhicules_mensuels", "hybride"}:
        columns.append("véhicules")
    if input_mode == "ehpad_gaz_talon":
        columns.append("gaz_mesure")
    if input_mode == "ehpad_l_jour":
        columns.append("volume_l_j")
    return columns


def _merge_visible_input_table(previous: pd.DataFrame, edited_visible: pd.DataFrame) -> pd.DataFrame:
    merged = previous.copy()
    for column in edited_visible.columns:
        if column in merged.columns:
            merged[column] = edited_visible[column].values
    return merged


def _render_helioprofil_notice() -> None:
    st.subheader("Notice HelioProfil")
    st.markdown(
        """
HelioProfil genere un profil de puissance horaire 8760 h a partir d'un profil type, d'une saisonnalite
mensuelle et d'un recalage annuel ou mensuel. Le fichier exporte est destine a alimenter HelioDyn avec
un besoin horaire haute temperature.

L'annee calendrier de reference sert uniquement a positionner les jours de semaine, week-ends, jours
feries et periodes de fermeture. Elle ne constitue pas une hypothese meteo.
"""
    )

    st.markdown("### Sources et ratios")
    for profile_name, note in PROFILE_NOTES.items():
        st.markdown(f"**{profile_name}**")
        st.write(note)

    st.markdown("### Profils prevus")
    st.write(
        "Les thematiques Logement, Hebergement collectif, Equipement sportif, Restauration collective "
        "et Industrie avec besoin process sont affichees comme pistes futures, mais ne sont pas encore "
        "activables dans cette version."
    )

    st.markdown("### Limites")
    st.write(
        "Les profils fournis sont des profils de pre-dimensionnement. Ils ne remplacent pas un comptage "
        "horaire reel lorsque celui-ci existe. Les coefficients horaires decrivent la forme de la demande ; "
        "le niveau energetique final depend du recalage saisi par l'utilisateur."
    )


def _render_helioprofil_generator() -> None:
    left, right = st.columns([1, 2], gap="large")

    with left:
        st.subheader("Paramètres")
        year = st.number_input(
            "Année calendrier de référence",
            min_value=2000,
            max_value=2100,
            value=2025,
            step=1,
            help=(
                "Sert uniquement à placer les jours de semaine, jours fériés et dates de fermeture "
                "dans le profil 8760 h. Ce n'est pas une hypothèse météo."
            ),
        )
        profile_name = st.selectbox("Profil type", list(PROFILE_LIBRARY.keys()), index=0)
        st.caption("Thématiques à venir, non disponibles dans cette version :")
        for unavailable_profile in PROFILE_THEMES_COMING_SOON:
            st.markdown(
                f"<span style='color:#9ca3af;'>• {unavailable_profile} — indisponible</span>",
                unsafe_allow_html=True,
            )
        demand_temperature_c = st.number_input(
            "Température de besoin (°C)",
            min_value=20.0,
            max_value=95.0,
            value=60.0,
            step=1.0,
        )
        is_ehpad_profile = profile_name == "EHPAD cuisine ECS + lingerie"
        if is_ehpad_profile:
            mode_label = st.radio(
                "Mode de recalage EHPAD",
                [
                    "Ratio SOCOL résidents",
                    "Profil L/jour moyen",
                    "Releves gaz avec talon",
                ],
                index=0,
            )
        else:
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

        gas_conversion = float(GeneratorConfig().gas_conversion_kwh_per_m3)
        gas_efficiency = 0.75
        gas_unit = "kWh"
        l_60c_per_vehicle = float(DEFAULT_L_60C_PER_VEHICLE)
        l_60c_per_ehpad_résident_day = float(DEFAULT_L_60C_PER_EHPAD_RESIDENT_DAY)
        ehpad_résidents = 80
        vehicles_per_day = 13.0

        uses_gas_readings = input_mode in {"gaz_mensuel", "hybride"}
        uses_ehpad_gas_talon = input_mode == "ehpad_gaz_talon"
        uses_monthly_vehicles = input_mode in {"véhicules_mensuels", "hybride"}
        uses_daily_vehicles = input_mode == "véhicules_annuels"
        uses_vehicle_ratio = (uses_monthly_vehicles or uses_daily_vehicles) and not is_ehpad_profile

        if is_ehpad_profile:
            st.markdown("**Recalage EHPAD**")
            ehpad_résidents = int(
                st.number_input(
                    "Nombre de résidents",
                    min_value=1,
                    max_value=5000,
                    value=80,
                    step=1,
                )
            )
            l_60c_per_ehpad_résident_day = st.number_input(
                "Ratio SOCOL (L équivalent 60 °C / résident / jour)",
                min_value=1.0,
                max_value=200.0,
                value=float(DEFAULT_L_60C_PER_EHPAD_RESIDENT_DAY),
                step=1.0,
                help="Ratio affiché pour le profil EHPAD cuisine ECS + lingerie. Il sert de base si aucune mesure directe n'est disponible.",
            )

        if uses_gas_readings or uses_ehpad_gas_talon:
            st.markdown("**Recalage par relevés gaz**")
            gas_efficiency = st.number_input(
                "Rendement gaz estimé",
                min_value=0.1,
                max_value=1.2,
                value=0.75,
                step=0.01,
                format="%.2f",
            )
            gas_unit = st.selectbox("Unité des relevés gaz", ["kWh", "MWh", "m3 gaz"], index=0)
            st.caption(f"Hypothèse gaz : 1 m³ gaz = {gas_conversion:.1f} kWh PCI.")

        if uses_vehicle_ratio:
            st.markdown("**Recalage par véhicules lavés**")
            l_60c_per_vehicle = st.number_input(
                "Ratio ECS SOCOL (L équivalent 60 °C / véhicule)",
                min_value=1.0,
                max_value=5000.0,
                value=float(DEFAULT_L_60C_PER_VEHICLE),
                step=10.0,
                help=(
                    "Volume ECS équivalent à 60 °C par véhicule. La valeur par défaut est calibrée "
                    "pour représenter environ 45 kWh utiles par véhicule avec une eau froide de référence à 15 °C."
                ),
            )
            st.caption(
                "Équivalent énergétique avec ce ratio : "
                f"{GeneratorConfig(l_60c_per_vehicle=float(l_60c_per_vehicle)).kwh_per_vehicle:.1f} kWh utile/véhicule."
            )

        if uses_daily_vehicles:
            vehicles_per_day = st.number_input(
                "Véhicules / jour ouvert",
                min_value=0.0,
                max_value=500.0,
                value=13.0,
                step=0.5,
            )

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
        if not is_ehpad_profile and st.button("Charger l'exemple Niort 2025", type="secondary"):
            st.session_state["helioprofil_input_table"] = _niort_demo_table()

        if "helioprofil_input_table" not in st.session_state:
            st.session_state["helioprofil_input_table"] = _default_input_table()

        base_input_table = st.session_state["helioprofil_input_table"]
        for required_column in ("gaz_mesure", "véhicules", "volume_l_j"):
            if required_column not in base_input_table.columns:
                base_input_table[required_column] = 0.0
        visible_columns = _input_columns_for_mode(input_mode)
        visible_input_table = base_input_table[visible_columns].copy()
        column_config = {
            "mois_num": st.column_config.NumberColumn("N°", disabled=True),
            "mois": st.column_config.TextColumn("Mois", disabled=True),
        }
        if "gaz_mesure" in visible_columns:
            column_config["gaz_mesure"] = st.column_config.NumberColumn(
                "Gaz mesuré",
                help="Selon l'unité choisie dans les paramètres.",
                format="%.2f",
            )
        if "véhicules" in visible_columns:
            column_config["véhicules"] = st.column_config.NumberColumn(
                "Véhicules",
                help="Nombre mensuel de véhicules.",
                format="%.2f",
            )

        if "volume_l_j" in visible_columns:
            column_config["volume_l_j"] = st.column_config.NumberColumn(
                "Volume ECS utile (L/jour moyen)",
                help="Volume journalier moyen d'ECS utile du mois.",
                format="%.1f",
            )

        if input_mode == "ehpad_ratio_socol":
            st.info(
                "Ce mode utilise uniquement le nombre de résidents et le ratio SOCOL. "
                "Aucune saisie mensuelle n'est nécessaire."
            )
            st.dataframe(
                visible_input_table,
                width="stretch",
                column_config=column_config,
                hide_index=True,
            )
            input_table = base_input_table
        elif input_mode == "véhicules_annuels":
            st.info(
                "Ce mode utilise le nombre de véhicules par jour ouvert et le calendrier de fermetures. "
                "Aucune saisie mensuelle n'est nécessaire."
            )
            st.dataframe(
                visible_input_table,
                width="stretch",
                column_config=column_config,
                hide_index=True,
            )
            input_table = base_input_table
        else:
            edited_visible_input_table = st.data_editor(
                visible_input_table,
                num_rows="fixed",
                width="stretch",
                column_config=column_config,
                hide_index=True,
            )
            input_table = _merge_visible_input_table(base_input_table, edited_visible_input_table)
        st.session_state["helioprofil_input_table"] = input_table

    generator_input_mode = "target_mensuel" if is_ehpad_profile else input_mode
    config = GeneratorConfig(
        year=int(year),
        profile_name=profile_name,
        demand_temperature_c=float(demand_temperature_c),
        gas_efficiency=float(gas_efficiency),
        gas_unit=gas_unit,
        gas_conversion_kwh_per_m3=gas_conversion,
        l_60c_per_vehicle=float(l_60c_per_vehicle),
        vehicles_per_day=float(vehicles_per_day),
        input_mode=generator_input_mode,
        close_weekends=bool(close_weekends),
        close_french_holidays=bool(close_holidays),
        compensate_closed_days=True,
        remove_feb_29=True,
        output_all_in_ht=True,
    )

    try:
        monthly_targets_kwh = None
        ehpad_detail_df = None
        monthly_gas = input_table["gaz_mesure"].tolist()
        monthly_vehicles = input_table["véhicules"].tolist()
        if is_ehpad_profile:
            monthly_gas = None
            monthly_vehicles = None
            if input_mode == "ehpad_ratio_socol":
                monthly_targets_kwh, ehpad_detail_df = _ehpad_targets_from_ratio(
                    ehpad_résidents,
                    l_60c_per_ehpad_résident_day,
                )
            elif input_mode == "ehpad_l_jour":
                monthly_targets_kwh, ehpad_detail_df = _ehpad_targets_from_daily_volumes(
                    input_table["volume_l_j"].tolist()
                )
            elif input_mode == "ehpad_gaz_talon":
                monthly_targets_kwh, ehpad_detail_df = _ehpad_targets_from_gas_talon(
                    input_table["gaz_mesure"].tolist(),
                    gas_unit=gas_unit,
                    gas_conversion_kwh_per_m3=gas_conversion,
                    gas_efficiency=gas_efficiency,
                    résidents=ehpad_résidents,
                    ratio_l_résident_day=l_60c_per_ehpad_résident_day,
                )
        elif input_mode == "gaz_mensuel":
            monthly_vehicles = None
        elif input_mode == "véhicules_mensuels":
            monthly_gas = None
        elif input_mode == "véhicules_annuels":
            monthly_gas = None
            monthly_vehicles = None

        profile_df, bilan_mensuel, profile_type = generate_profile(
            config=config,
            profile_csv=PROFILE_LIBRARY[profile_name],
            monthly_gas_values=monthly_gas,
            monthly_vehicle_values=monthly_vehicles,
            monthly_targets_kwh_values=monthly_targets_kwh,
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

        if ehpad_detail_df is not None:
            st.subheader("Décomposition EHPAD")
            useful_mwh = ehpad_detail_df["Besoin ECS utile (kWh)"].sum() / 1000.0
            loop_mwh = ehpad_detail_df["Bouclage sanitaire estimé (kWh)"].sum() / 1000.0
            heating_mwh = ehpad_detail_df["Chauffage residuel estimé (kWh)"].sum() / 1000.0
            target_mwh = ehpad_detail_df["Cible exportée HelioDyn (kWh)"].sum() / 1000.0
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Besoin ECS utile", f"{useful_mwh:.1f} MWh")
            d2.metric("Bouclage sanitaire estimé", f"{loop_mwh:.1f} MWh")
            d3.metric("Chauffage résiduel estimé", f"{heating_mwh:.1f} MWh")
            d4.metric("Cible exportée HelioDyn", f"{target_mwh:.1f} MWh")
            detail_display = ehpad_detail_df.copy()
            for col in detail_display.columns:
                if col != "mois":
                    detail_display[col] = (detail_display[col] / 1000.0).round(2)
            detail_display = detail_display.rename(
                columns={
                    "Besoin ECS utile (kWh)": "Besoin ECS utile (MWh)",
                    "Bouclage sanitaire estimé (kWh)": "Bouclage sanitaire estimé (MWh)",
                    "Chauffage residuel estimé (kWh)": "Chauffage résiduel estimé (MWh)",
                    "Cible exportée HelioDyn (kWh)": "Cible exportée HelioDyn (MWh)",
                }
            )
            st.dataframe(detail_display, width="stretch", hide_index=True)

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
                fig = _daily_profile_chart(hourly_norm, profile_name=profile_name)
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
                fig = _monthly_profile_chart(bm)
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
                    color_discrete_sequence=[PROFILE_BAR_COLOR],
                )
                fig.update_layout(
                    height=430,
                    showlegend=False,
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    font={"family": PROFILE_FONT_FAMILY, "size": 13, "color": "#111827"},
                )
                fig.update_xaxes(gridcolor=PROFILE_GRID_COLOR, griddash="dash")
                fig.update_yaxes(gridcolor=PROFILE_GRID_COLOR, griddash="dash")
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
                color_discrete_sequence=[PROFILE_BAR_COLOR],
            )
            fig1.update_layout(
                height=430,
                showlegend=False,
                plot_bgcolor="white",
                paper_bgcolor="white",
                font={"family": PROFILE_FONT_FAMILY, "size": 13, "color": "#111827"},
            )
            fig1.update_xaxes(gridcolor=PROFILE_GRID_COLOR, griddash="dash")
            fig1.update_yaxes(gridcolor=PROFILE_GRID_COLOR, griddash="dash")
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
            fig2.update_traces(line={"color": PROFILE_BAR_LINE, "width": 2})
            fig2.update_layout(
                height=430,
                showlegend=False,
                plot_bgcolor="white",
                paper_bgcolor="white",
                font={"family": PROFILE_FONT_FAMILY, "size": 13, "color": "#111827"},
            )
            fig2.update_xaxes(gridcolor=PROFILE_GRID_COLOR, griddash="dash")
            fig2.update_yaxes(gridcolor=PROFILE_GRID_COLOR, griddash="dash")
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


def render_helioprofil_app() -> None:
    """Render HelioProfil inside the HelioTools portal."""

    st.title("HelioProfil")
    st.caption(
        "Générateur de profils horaires 8760 h pour créer un fichier Excel de besoins process "
        "compatible avec HelioDyn."
    )

    creation_tab, notice_tab = st.tabs(["Création d'un profil de puissance horaire", "Notice"])
    with creation_tab:
        _render_helioprofil_generator()
    with notice_tab:
        _render_helioprofil_notice()