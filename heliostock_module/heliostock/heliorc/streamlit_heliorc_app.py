from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data import load_locations
from .engine import (
    AID_FORFAITS,
    CALCULATION_MODES,
    DEFAULT_MONTHLY_NEEDS_MWH,
    MONTHS_FR,
    REGIMES,
    CalculationInputs,
    calculate_opportunity,
    estimate_monthly_needs,
)
from .report import build_opportunity_note

APP_DIR = Path(__file__).resolve().parent


def _render_styles() -> None:
    st.markdown(
        """
        <style>
          .block-container {padding-top: 1.35rem; padding-bottom: 3rem;}
          [data-testid="stMetric"] {
            background: #f7faf9;
            border: 1px solid #dce8e6;
            border-radius: 0.65rem;
            padding: 0.8rem 0.9rem;
          }
          .heliorc-banner {
            border-left: 6px solid #0b6f70;
            padding: 0.85rem 1.05rem;
            background: linear-gradient(90deg, #edf7f5, #ffffff);
            border-radius: 0.45rem;
            margin-bottom: 1rem;
          }
          .heliorc-banner h1 {margin: 0; color: #17324d; font-size: 2.05rem;}
          .heliorc-banner p {margin: 0.25rem 0 0 0; color: #475467;}
          .small-muted {color: #667085; font-size: 0.88rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _initial_monthly_dataframe(values: list[float] | None = None) -> pd.DataFrame:
    data = values if values is not None else DEFAULT_MONTHLY_NEEDS_MWH
    return pd.DataFrame({"Mois": MONTHS_FR, "Besoins RCU (MWh)": data})


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "project_name": "Étude d'opportunité solaire thermique",
        "client": "",
        "airtable_id": "",
        "analyst": "",
        "project_date": date.today(),
        "notes": "",
        "location_label": "1 - Bourg-en-Bresse",
        "zone": "Nord",
        "regime_label": "Moyen (75°C/55°C)",
        "mean_temp": 65.0,
        "calculation_mode": "excel_v5_3",
        "base_load_percent": 90,
        "needs_mode": "Besoins mensuels connus",
        "annual_heating": 10000.0,
        "annual_ecs": 2000.0,
        "network_efficiency_percent": 85,
        "manual_needs_df": _initial_monthly_dataframe(),
        "network_operates_summer": True,
        "summer_excess_enr": False,
        "land_identified": True,
        "other_aid": 0.0,
        "electricity_price": 245.1,
        "project_lifetime": 30,
        "override_discount_rate": False,
        "discount_rate_percent": 6.0,
        "last_results": None,
        "last_monthly": None,
        "last_inputs": None,
        "last_project": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value



def render_heliorc_app() -> None:
    """Render HelioRC inside the HelioTools portal."""

    _render_styles()
    _init_state()
    locations = load_locations()
    location_labels = locations["label"].tolist()

    with st.sidebar:
        st.subheader("Projet")
        imported = st.file_uploader(
            "Importer un projet HelioRC (JSON)",
            type=["json"],
            help="Recharge les métadonnées, hypothèses et besoins mensuels exportés par l'application.",
        )
        if imported is not None:
            payload_bytes = imported.getvalue()
            payload_hash = hashlib.sha256(payload_bytes).hexdigest()
            if payload_hash != st.session_state.get("_last_import_hash"):
                try:
                    payload = json.loads(payload_bytes.decode("utf-8"))
                    project_data = payload.get("project", {})
                    input_data = payload.get("inputs", {})
                    for key in ["project_name", "client", "airtable_id", "analyst", "notes"]:
                        if key in project_data:
                            st.session_state[key] = project_data[key]
                    if project_data.get("date"):
                        st.session_state["project_date"] = date.fromisoformat(project_data["date"])
                    mapping = {
                        "location_label": "location_label",
                        "zone": "zone",
                        "regime_label": "regime_label",
                        "mean_network_temperature_c": "mean_temp",
                        "calculation_mode": "calculation_mode",
                        "other_aid_eur": "other_aid",
                        "electricity_price_eur_mwh": "electricity_price",
                        "project_lifetime_years": "project_lifetime",
                        "network_operates_summer": "network_operates_summer",
                        "summer_excess_enr": "summer_excess_enr",
                        "land_identified": "land_identified",
                    }
                    for source_key, state_key in mapping.items():
                        if source_key in input_data:
                            st.session_state[state_key] = input_data[source_key]
                    if "base_load_fraction" in input_data:
                        st.session_state["base_load_percent"] = round(
                            float(input_data["base_load_fraction"]) * 100
                        )
                    monthly_values = input_data.get("monthly_needs_mwh")
                    if isinstance(monthly_values, list) and len(monthly_values) == 12:
                        st.session_state["manual_needs_df"] = _initial_monthly_dataframe(
                            [float(value) for value in monthly_values]
                        )
                        st.session_state.pop("manual_needs_editor", None)
                    rate = input_data.get("discount_rate_override")
                    st.session_state["override_discount_rate"] = rate is not None
                    if rate is not None:
                        st.session_state["discount_rate_percent"] = float(rate) * 100
                    st.session_state["_last_import_hash"] = payload_hash
                    st.success("Projet importé.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Import impossible : {exc}")

        st.text_input("Nom du projet", key="project_name")
        st.text_input("Maître d'ouvrage / territoire", key="client")
        st.text_input("Référence / ID Airtable", key="airtable_id")
        st.text_input("Analyste", key="analyst")
        st.date_input("Date de la note", key="project_date")
        st.text_area("Commentaire de synthèse", key="notes", height=110)

    st.markdown(
        """
        <div class="heliorc-banner">
          <h1>HelioRC</h1>
          <p>Note d'opportunité pour l'intégration du solaire thermique sur un réseau de chaleur urbain.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "Reprise du moteur NO STH RCU v5.3 : prédimensionnement au talon estival, productivité paramétrique, stockage journalier, CAPEX, aide indicative et LCOH."
    )

    input_tabs = st.tabs(["1. Contexte", "2. Besoins du RCU", "3. Hypothèses techniques et économiques"])

    with input_tabs[0]:
        col_a, col_b = st.columns([1.15, 0.85])
        with col_a:
            st.selectbox("Localisation", location_labels, key="location_label")
            st.checkbox(
                "Le réseau fonctionne en été",
                key="network_operates_summer",
                help="Condition indispensable du cadre d'application du modèle.",
            )
            st.checkbox(
                "Présence d'une EnR&R excédentaire en été",
                key="summer_excess_enr",
                help="Une autre production excédentaire en été peut réduire ou annuler le talon disponible pour le solaire.",
            )
            st.checkbox("Un foncier potentiel est identifié", key="land_identified")
        with col_b:
            selected_location = locations.loc[
                locations["label"] == st.session_state.location_label
            ].iloc[0]
            st.map(
                pd.DataFrame(
                    {
                        "lat": [float(selected_location["latitude"])],
                        "lon": [float(selected_location["longitude"])],
                    }
                ),
                zoom=8,
                width="stretch",
            )
            st.markdown(
                f"<div class='small-muted'>Point de référence météorologique : <b>{selected_location['city']}</b> ({selected_location['department']}).</div>",
                unsafe_allow_html=True,
            )

    with input_tabs[1]:
        st.radio(
            "Mode de saisie",
            ["Besoins mensuels connus", "Estimation depuis les besoins annuels"],
            horizontal=True,
            key="needs_mode",
        )
        if st.session_state.needs_mode == "Besoins mensuels connus":
            st.markdown(
                "Saisir les besoins mensuels **au niveau du réseau**, pertes comprises, comme dans l'onglet principal du classeur."
            )
            edited = st.data_editor(
                st.session_state.manual_needs_df,
                key="manual_needs_editor",
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                column_config={
                    "Mois": st.column_config.TextColumn("Mois"),
                    "Besoins RCU (MWh)": st.column_config.NumberColumn(
                        "Besoins RCU (MWh)", min_value=0.0, step=1.0, format="%.1f"
                    ),
                },
            )
            st.session_state.manual_needs_df = edited
            needs_preview = edited.copy()
        else:
            col_1, col_2, col_3 = st.columns(3)
            with col_1:
                st.number_input(
                    "Besoins annuels de chauffage des abonnés (MWh/an)",
                    min_value=0.0,
                    step=100.0,
                    key="annual_heating",
                )
            with col_2:
                st.number_input(
                    "Besoins annuels d'ECS des abonnés (MWh/an)",
                    min_value=0.0,
                    step=50.0,
                    key="annual_ecs",
                )
            with col_3:
                st.slider(
                    "Rendement moyen du réseau",
                    min_value=50,
                    max_value=100,
                    step=1,
                    key="network_efficiency_percent",
                    format="%d %%",
                )
            try:
                estimated = estimate_monthly_needs(
                    location_label=st.session_state.location_label,
                    annual_heating_mwh=float(st.session_state.annual_heating),
                    annual_ecs_mwh=float(st.session_state.annual_ecs),
                    network_efficiency=float(st.session_state.network_efficiency_percent) / 100,
                    calculation_mode=st.session_state.calculation_mode,
                )
                needs_preview = estimated
                st.dataframe(
                    estimated.style.format(
                        {
                            "Température extérieure moyenne (°C)": "{:.1f}",
                            "Chauffage (MWh)": "{:.1f}",
                            "ECS (MWh)": "{:.1f}",
                            "Pertes réseau (MWh)": "{:.1f}",
                            "Besoins RCU (MWh)": "{:.1f}",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )
            except ValueError as exc:
                needs_preview = pd.DataFrame()
                st.error(str(exc))

    with input_tabs[2]:
        tech_col, eco_col = st.columns(2)
        with tech_col:
            selected_regime = st.selectbox(
                "Régime moyen du réseau",
                list(REGIMES),
                key="regime_label",
            )
            suggested_temp = REGIMES[selected_regime]
            if st.session_state.get("_last_regime") != selected_regime:
                st.session_state.mean_temp = suggested_temp
                st.session_state._last_regime = selected_regime
            st.number_input(
                "Température moyenne estivale départ-retour (°C)",
                min_value=35.0,
                max_value=100.0,
                step=1.0,
                key="mean_temp",
            )
            st.slider(
                "Talon de dimensionnement",
                min_value=50,
                max_value=100,
                step=1,
                key="base_load_percent",
                format="%d %%",
            )
            st.selectbox(
                "Référentiel de calcul",
                list(CALCULATION_MODES),
                key="calculation_mode",
                format_func=lambda code: CALCULATION_MODES[code],
                help=(
                    "Le mode strict reproduit les formules du classeur. Le mode présentation corrige "
                    "la conversion du rendement en pertes et applique la recommandation 200 m/MW."
                ),
            )
        with eco_col:
            st.selectbox("Zone géographique de l'aide", list(AID_FORFAITS), key="zone")
            st.number_input(
                "Autres aides (régionales, CEE, etc.) (€ HT)",
                min_value=0.0,
                step=10000.0,
                key="other_aid",
            )
            st.number_input(
                "Prix de l'électricité (€ HT/MWh)",
                min_value=0.0,
                step=1.0,
                key="electricity_price",
            )
            st.number_input(
                "Durée de vie économique (années)",
                min_value=1,
                max_value=50,
                step=1,
                key="project_lifetime",
            )
            st.checkbox("Forcer le taux d'actualisation", key="override_discount_rate")
            if st.session_state.override_discount_rate:
                st.number_input(
                    "Taux d'actualisation (%)",
                    min_value=0.0,
                    max_value=20.0,
                    step=0.1,
                    key="discount_rate_percent",
                )
            else:
                st.caption("Taux automatique du classeur : 5 % sous 500 m², 6 % au-delà.")

    st.divider()
    calculate_clicked = st.button(
        "Lancer le calcul HelioRC",
        type="primary",
        width="stretch",
    )

    if calculate_clicked:
        progress = st.progress(0, text="Contrôle des données...")
        try:
            progress.progress(25, text="Construction du profil mensuel...")
            if st.session_state.needs_mode == "Besoins mensuels connus":
                monthly_needs = (
                    st.session_state.manual_needs_df["Besoins RCU (MWh)"]
                    .astype(float)
                    .tolist()
                )
            else:
                estimated = estimate_monthly_needs(
                    location_label=st.session_state.location_label,
                    annual_heating_mwh=float(st.session_state.annual_heating),
                    annual_ecs_mwh=float(st.session_state.annual_ecs),
                    network_efficiency=float(st.session_state.network_efficiency_percent) / 100,
                    calculation_mode=st.session_state.calculation_mode,
                )
                monthly_needs = estimated["Besoins RCU (MWh)"].astype(float).tolist()

            inputs = CalculationInputs(
                location_label=st.session_state.location_label,
                zone=st.session_state.zone,
                regime_label=st.session_state.regime_label,
                mean_network_temperature_c=float(st.session_state.mean_temp),
                base_load_fraction=float(st.session_state.base_load_percent) / 100,
                monthly_needs_mwh=monthly_needs,
                other_aid_eur=float(st.session_state.other_aid),
                electricity_price_eur_mwh=float(st.session_state.electricity_price),
                project_lifetime_years=int(st.session_state.project_lifetime),
                discount_rate_override=(
                    float(st.session_state.discount_rate_percent) / 100
                    if st.session_state.override_discount_rate
                    else None
                ),
                calculation_mode=st.session_state.calculation_mode,
                network_operates_summer=bool(st.session_state.network_operates_summer),
                summer_excess_enr=bool(st.session_state.summer_excess_enr),
                land_identified=bool(st.session_state.land_identified),
            )
            progress.progress(60, text="Prédimensionnement technique...")
            results, monthly = calculate_opportunity(inputs)
            progress.progress(85, text="Analyse économique et interprétation...")
            project = {
                "project_name": st.session_state.project_name,
                "client": st.session_state.client,
                "airtable_id": st.session_state.airtable_id,
                "analyst": st.session_state.analyst,
                "date": st.session_state.project_date.isoformat(),
                "notes": st.session_state.notes,
                "needs_mode": st.session_state.needs_mode,
            }
            st.session_state.last_results = results
            st.session_state.last_monthly = monthly
            st.session_state.last_inputs = inputs
            st.session_state.last_project = project
            progress.progress(100, text="Calcul terminé.")
            progress.empty()
            st.success("Calcul terminé. Les résultats ci-dessous correspondent au dernier lancement.")
        except Exception as exc:  # noqa: BLE001
            progress.empty()
            st.error(f"Calcul impossible : {exc}")

    results = st.session_state.last_results
    monthly = st.session_state.last_monthly
    inputs = st.session_state.last_inputs
    project = st.session_state.last_project

    if results is None or monthly is None or inputs is None or project is None:
        st.info("Renseignez les hypothèses puis lancez le calcul pour afficher la note d'opportunité.")
        st.stop()

    st.markdown("## Résultats du dernier calcul")
    status_lower = results.opportunity_status.lower()
    if "favorable" in status_lower:
        st.success(f"**{results.opportunity_status}** - {results.scope_status}")
    elif "intermédiaire" in status_lower:
        st.warning(f"**{results.opportunity_status}** - {results.scope_status}")
    else:
        st.error(f"**{results.opportunity_status}** - {results.scope_status}")

    result_tabs = st.tabs(["Synthèse", "Profil mensuel", "Détail des calculs", "Exports", "Méthode et limites"])

    with result_tabs[0]:
        st.markdown("### Analyse technique")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Surface de capteurs", f"{results.collector_area_m2:,.0f} m²".replace(",", " "))
        m2.metric("Production solaire", f"{results.annual_solar_production_mwh:,.0f} MWh/an".replace(",", " "))
        m3.metric("Fraction solaire", f"{results.solar_fraction:.1%}")
        m4.metric("Productivité", f"{results.productivity_kwh_m2_year:,.0f} kWh/m².an".replace(",", " "))
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Stockage journalier", f"{results.storage_volume_m3:,.0f} m³".replace(",", " "))
        m6.metric("Emprise foncière", f"{results.land_area_ha:.2f} ha")
        m7.metric("Distance conseillée", f"{results.recommended_connection_distance_m:,.0f} m".replace(",", " "))
        m8.metric("Panneaux de 15 m²", f"{results.panel_count_15m2}")

        st.markdown("### Première analyse économique")
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("CAPEX indicatif", f"{results.capex_eur / 1_000_000:.2f} M€ HT")
        e2.metric("Aide ADEME indicative", f"{results.ademe_aid_eur / 1_000_000:.2f} M€")
        e3.metric("Reste à charge", f"{results.remaining_cost_eur / 1_000_000:.2f} M€ HT")
        e4.metric("LCOH aidé", f"{results.lcoh_aided_eur_mwh:.1f} € HT/MWh")

        with st.expander("Vigilances identifiées", expanded=True):
            for warning in results.warnings:
                st.write(f"- {warning}")

    with result_tabs[1]:
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=monthly["Mois"],
                y=monthly["Besoins RCU (MWh)"],
                mode="lines",
                name="Besoins RCU",
                line={"color": "#98A2B3", "width": 2},
                fill="tozeroy",
                fillcolor="rgba(152,162,179,0.28)",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=monthly["Mois"],
                y=monthly["Production solaire (MWh)"],
                mode="lines+markers",
                name="Production solaire",
                line={"color": "#E58A2A", "width": 3},
                marker={"size": 7},
            )
        )
        figure.update_layout(
            title="Profil de solarisation du réseau",
            xaxis_title="Mois",
            yaxis_title="Énergie (MWh/mois)",
            hovermode="x unified",
            legend={"orientation": "h", "y": 1.12, "x": 0},
            margin={"l": 30, "r": 20, "t": 80, "b": 35},
            height=480,
        )
        st.plotly_chart(figure, width="stretch")

        display_monthly = monthly[
            [
                "Mois",
                "Besoins RCU (MWh)",
                "Production solaire (MWh)",
                "Taux de couverture mensuel",
            ]
        ].copy()
        st.dataframe(
            display_monthly.style.format(
                {
                    "Besoins RCU (MWh)": "{:.1f}",
                    "Production solaire (MWh)": "{:.1f}",
                    "Taux de couverture mensuel": "{:.1%}",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    with result_tabs[2]:
        technical_rows = {
            "Besoin annuel du RCU (MWh/an)": results.annual_need_mwh,
            "Part des besoins estivaux mai-septembre": results.summer_need_share,
            "Talon mensuel minimal (MWh)": results.minimum_monthly_need_mwh,
            "Gisement horizontal (kWh/m².an)": results.annual_horizontal_irradiation_kwh_m2,
            "Production solaire (MWh/an)": results.annual_solar_production_mwh,
            "Productivité (kWh/m².an)": results.productivity_kwh_m2_year,
            "Surface de capteurs (m²)": results.collector_area_m2,
            "Stockage (m³)": results.storage_volume_m3,
            "Emprise (ha)": results.land_area_ha,
            "Distance de raccordement (m)": results.recommended_connection_distance_m,
            "Coût surfacique (€ HT/m²)": results.unit_capex_eur_m2,
            "CAPEX (€ HT)": results.capex_eur,
            "Aide ADEME (€)": results.ademe_aid_eur,
            "Autres aides (€)": results.other_aid_eur,
            "Taux d'aide total": results.aid_rate,
            "Reste à charge (€ HT)": results.remaining_cost_eur,
            "P1' (€ HT/MWh)": results.p1_eur_mwh,
            "P2/P3 (€ HT/MWh)": results.opex_eur_mwh,
            "P4 (€ HT/MWh)": results.capital_recovery_eur_mwh,
            "LCOH aidé (€ HT/MWh)": results.lcoh_aided_eur_mwh,
            "Taux d'actualisation": results.discount_rate,
        }
        details_df = pd.DataFrame(
            [{"Indicateur": key, "Valeur": value} for key, value in technical_rows.items()]
        )
        st.dataframe(details_df, hide_index=True, width="stretch")
        st.markdown("#### Table mensuelle complète")
        st.dataframe(monthly, hide_index=True, width="stretch")

    with result_tabs[3]:
        export_payload = {
            "format": "HelioRC-project-v1",
            "project": project,
            "inputs": asdict(inputs),
            "results": results.to_dict(),
        }
        json_bytes = json.dumps(export_payload, ensure_ascii=False, indent=2).encode("utf-8")
        csv_bytes = monthly.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
        try:
            pdf_bytes = build_opportunity_note(
                project=project,
                inputs=inputs,
                results=results,
                monthly=monthly,
            )
        except Exception as exc:  # noqa: BLE001
            pdf_bytes = None
            st.error(f"La note PDF n'a pas pu être générée : {exc}")

        export_col_1, export_col_2, export_col_3 = st.columns(3)
        with export_col_1:
            if pdf_bytes is not None:
                st.download_button(
                    "Télécharger la note PDF",
                    data=pdf_bytes,
                    file_name="HelioRC_note_opportunite.pdf",
                    mime="application/pdf",
                    width="stretch",
                )
        with export_col_2:
            st.download_button(
                "Télécharger le projet JSON",
                data=json_bytes,
                file_name="HelioRC_projet.json",
                mime="application/json",
                width="stretch",
            )
        with export_col_3:
            st.download_button(
                "Télécharger le détail CSV",
                data=csv_bytes,
                file_name="HelioRC_resultats_mensuels.csv",
                mime="text/csv",
                width="stretch",
            )
        st.caption(
            "Le JSON peut être réimporté dans l'application. Le PDF est une note de premier niveau et doit rester accompagné des limites du modèle."
        )

    with result_tabs[4]:
        st.markdown(
            r"""
    ### Logique reprise du classeur v5.3

    1. Le profil de production mensuel est obtenu à partir de l'irradiation sur le plan optimal, corrigée par les 12 coefficients saisonniers du classeur, puis normalisée sur son maximum.
    2. La production mensuelle vaut : **taux de talon × minimum mensuel des besoins × profil solaire normalisé**.
    3. La productivité annuelle est calculée par l'équation paramétrique :

    $$P = (0{,}4818G - 503{,}1B_e + 1{,}1244B_eG - 199{,}6)\,[1 + 0{,}014(55-T_m)]$$

    avec $G$ le gisement horizontal annuel, $B_e$ la part des besoins de mai à septembre et $T_m$ la température moyenne du réseau.

    4. La surface est déduite de la production annuelle et de la productivité. Le stockage vaut environ **0,2 m³/m²**, l'emprise **2,5 m² de terrain par m² de capteur**.
    5. Le CAPEX surfacique suit la courbe par morceaux du classeur. L'aide est forfaitaire sous 1 500 m² puis devient indicative. Le LCOH additionne P1', P2/P3 et le facteur de récupération du capital P4.

    ### Cadre d'utilisation

    - Centrale avec stockage journalier et capteurs plans vitrés haute performance.
    - Champ supérieur à 100 m² et fraction solaire indicative de 10 à 30 %.
    - Outil de priorisation et de discussion en amont d'une étude de faisabilité.
    - Hors cadre : stockage intersaisonnier, tracker, capteurs sous vide, recharge géothermique, raccordement complexe ou foncier atypique.
    - L'objectif est un ordre de grandeur technique ; l'économie reste particulièrement sensible aux hypothèses de CAPEX, d'aides, de financement et de raccordement.

    ### Deux référentiels disponibles

    - **Excel v5.3 - reproduction stricte** : conserve la formule de pertes constante du classeur et sa formule de distance.
    - **Méthode présentation** : transforme correctement le rendement en pertes par `besoin / rendement` et applique l'ordre de grandeur de 200 m/MW.
    """
        )
        st.info(
            "Étape suivante recommandée lorsque l'opportunité est confirmée : étude de faisabilité avec modélisation dynamique et analyse du réseau, du foncier, de l'hydraulique et du montage économique."
        )
