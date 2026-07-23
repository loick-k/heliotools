"""Application HelioEco intégrée au portail HelioTools.

HelioEco expose le modèle économique CESC existant sans dupliquer le moteur
de calcul : les formules restent portées par `opportunity_notes.cesc_economic_model`.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:  # pragma: no cover - dépendance optionnelle côté interface
    go = None

from ..opportunity_notes.cesc_economic_model import (
    CescEconomicInputs,
    CescEconomicResults,
    DEFAULT_AUXILIARY_ELECTRICITY_COST_EUR_MWH,
    DEFAULT_AUXILIARY_ELECTRICITY_RATIO,
    TYPOLOGY_LABELS,
    build_yearly_cashflow_projection,
    compute_cesc_economic_model,
    get_ademe_aid_eur_per_mwh_year,
)


APP_KEY = "helioeco"
APP_LABEL = "HelioEco"


def _number(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def _eur(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n.d."
    return f"{_number(value, digits)} €"


def _eur_mwh(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{_number(value, digits)} €/MWh"


def _percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{_number(100.0 * value, digits)} %"


def build_heat_cost_breakdown_rows(results: CescEconomicResults) -> list[dict[str, float | str]]:
    """Décomposition P1/P2/P4 du coût de chaleur solaire."""

    return [
        {
            "Poste": "P1' - Auxiliaires électriques",
            "Famille": "P1'",
            "Coût chaleur (€/MWh)": results.heat_cost_p1_eur_mwh or 0.0,
        },
        {
            "Poste": "P2 - Suivi et maintenance",
            "Famille": "P2",
            "Coût chaleur (€/MWh)": results.heat_cost_p2_eur_mwh or 0.0,
        },
        {
            "Poste": "P4 - Investissement net aidé",
            "Famille": "P4",
            "Coût chaleur (€/MWh)": results.heat_cost_p4_eur_mwh or 0.0,
        },
    ]


def _first_positive_year(rows: list[dict[str, float | int]], cumulative_key: str) -> int | None:
    for row in rows:
        if float(row.get(cumulative_key, 0.0) or 0.0) >= 0.0:
            return int(row.get("Année", 0) or 0)
    return None


def _first_available_key(row: dict[str, float | int], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return key
    available = ", ".join(str(key) for key in row)
    raise KeyError(f"Aucune colonne disponible parmi {candidates}. Colonnes reçues : {available}")


def _render_heat_cost_breakdown_plotly(results: CescEconomicResults):
    if go is None:
        return None

    rows = build_heat_cost_breakdown_rows(results)
    total_cost = float(results.solar_heat_cost_eur_mwh or 0.0)
    reference_cost = float(results.average_reference_energy_cost_eur_mwh or 0.0)
    x_max = max(total_cost, reference_cost, 1.0) * 1.25

    fig = go.Figure()
    colors = {"P1'": "#64748b", "P2": "#94a3b8", "P4": "#f59e0b"}
    for row in rows:
        value = float(row["Coût chaleur (€/MWh)"])
        fig.add_trace(
            go.Bar(
                y=["Coût chaleur solaire"],
                x=[value],
                name=str(row["Poste"]),
                orientation="h",
                marker_color=colors.get(str(row["Famille"]), "#0f766e"),
                text=[f"{value:.1f} €/MWh"],
                textposition="inside",
                hovertemplate="%{fullData.name}<br>%{x:.1f} €/MWh<extra></extra>",
            )
        )

    fig.add_vline(
        x=reference_cost,
        line_dash="dash",
        annotation_text=f"Référence énergie moyenne : {reference_cost:.1f} €/MWh",
        annotation_position="top right",
    )
    fig.update_layout(
        barmode="stack",
        height=320,
        margin={"l": 10, "r": 20, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis_title="Coût de la chaleur solaire utile (€/MWh)",
        yaxis_title=None,
        hovermode="closest",
    )
    fig.update_xaxes(range=[0, x_max], ticksuffix=" €/MWh")
    fig.update_yaxes(showticklabels=False)
    return fig


def _render_cashflow_plotly(cashflow_rows: list[dict[str, float | int]]):
    if go is None or not cashflow_rows:
        return None

    sample = cashflow_rows[0]
    year_key = _first_available_key(sample, ("Année", "Annee"))
    annual_key = _first_available_key(
        sample,
        (
            "Économie annuelle inflation (€)",
            "Economie annuelle inflation (€)",
            "Flux annuel inflation annuelle (€)",
            "Économie annuelle moyenne (€)",
            "Economie annuelle moyenne (€)",
        ),
    )
    cumulative_key = _first_available_key(
        sample,
        (
            "Flux cumulé inflation annuelle (€)",
            "Flux cumule inflation annuelle (€)",
            "Flux cumulé moyen (€)",
            "Flux cumule moyen (€)",
        ),
    )

    years = [int(row[year_key]) for row in cashflow_rows]
    cumulative = [float(row[cumulative_key]) for row in cashflow_rows]
    annual = [float(row[annual_key]) for row in cashflow_rows]
    breakeven_year = _first_positive_year(cashflow_rows, cumulative_key)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=cumulative,
            mode="lines+markers",
            name="Flux cumulé",
            customdata=annual,
            hovertemplate=(
                "Année %{x}<br>"
                "Flux annuel : %{customdata:,.0f} €<br>"
                "Flux cumulé : %{y:,.0f} €"
                "<extra></extra>"
            ),
        )
    )
    fig.add_hline(y=0, line_dash="dash", annotation_text="Seuil de retour à zéro", annotation_position="top left")
    if breakeven_year is not None:
        fig.add_vline(
            x=breakeven_year,
            line_dash="dot",
            annotation_text=f"Retour année {breakeven_year}",
            annotation_position="top",
        )
    fig.update_layout(
        height=390,
        margin={"l": 10, "r": 20, "t": 35, "b": 40},
        xaxis_title="Année",
        yaxis_title="Flux cumulé (€)",
        hovermode="x unified",
    )
    fig.update_xaxes(dtick=max(1, round(max(years) / 10)))
    fig.update_yaxes(ticksuffix=" €")
    return fig


def render_helioeco_app() -> None:
    """Rendu Streamlit de l'application HelioEco."""

    st.title("HelioEco")
    st.caption(
        "Modèle économique solaire thermique issu de l'onglet Excel « Simulateur eco CESC ». "
        "Cette première intégration garde HelioEco autonome tout en réutilisant le moteur économique commun à HelioNOP."
    )

    st.markdown("### Hypothèses principales")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        typologie = st.selectbox("Typologie", options=list(TYPOLOGY_LABELS), key="helioeco_typologie")
        surface_m2 = st.number_input("Surface capteurs (m²)", min_value=0.0, value=33.8, step=1.0)
        productivity = st.number_input("Productivité estimée (kWh/m².an)", min_value=0.0, value=562.0, step=10.0)
    with col_b:
        reference_energy_cost = st.number_input("Coût énergie de référence (€/MWh)", min_value=0.0, value=75.0, step=5.0)
        inflation = st.number_input("Inflation énergie de référence (%/an)", value=3.0, step=0.5) / 100.0
        years = st.number_input("Durée d'analyse (ans)", min_value=1, value=20, step=1)
    with col_c:
        works_cost = st.number_input("Coût travaux installation (€HT/m²)", min_value=0.0, value=1563.0, step=50.0)
        eta_appoint = st.number_input("Rendement appoint global", min_value=0.01, max_value=1.5, value=0.82, step=0.01)
        st.metric("Forfait ADEME appliqué", _eur(get_ademe_aid_eur_per_mwh_year(typologie), 0) + "/MWh.an")

    with st.expander("Hypothèses avancées", expanded=False):
        adv_a, adv_b, adv_c = st.columns(3)
        auxiliary_ratio = adv_a.number_input(
            "Consommation électrique des auxiliaires (% de la production solaire)",
            value=DEFAULT_AUXILIARY_ELECTRICITY_RATIO * 100.0,
            step=0.5,
        ) / 100.0
        electricity_cost = adv_a.number_input(
            "Prix de l'électricité des auxiliaires (€/MWh)",
            value=DEFAULT_AUXILIARY_ELECTRICITY_COST_EUR_MWH,
            step=10.0,
        )
        adv_a.caption(
            f"P1' auxiliaires = {auxiliary_ratio * 100.0:.1f} % × {electricity_cost:.0f} €/MWh = "
            f"{auxiliary_ratio * electricity_cost:.1f} €/MWh solaire utile."
        )
        maintenance_cost = adv_b.number_input("Maintenance (€/m².an)", value=22.0, step=1.0)
        fae_cost = adv_b.number_input("FAE (€HT)", value=4929.0, step=100.0)
        fae_aid_rate = adv_c.number_input("Taux aide FAE (%)", value=70.0, step=5.0) / 100.0
        ademe_cap = adv_c.number_input("Plafond aide travaux (% coût)", value=65.0, step=5.0) / 100.0

    inputs = CescEconomicInputs(
        typologie=str(typologie),
        surface_m2=float(surface_m2),
        productivity_kwh_m2_year=float(productivity),
        reference_energy_cost_eur_mwh=float(reference_energy_cost),
        reference_energy_inflation_rate=float(inflation),
        years=int(years),
        works_cost_eur_m2=float(works_cost),
        eta_appoint=float(eta_appoint),
        auxiliary_electricity_ratio=float(auxiliary_ratio),
        electricity_cost_eur_mwh=float(electricity_cost),
        maintenance_cost_eur_m2_year=float(maintenance_cost),
        fae_cost_eur=float(fae_cost),
        fae_aid_rate=float(fae_aid_rate),
        ademe_aid_max_rate_on_works=float(ademe_cap),
    )

    try:
        results = compute_cesc_economic_model(inputs)
    except ValueError as exc:
        st.error(str(exc))
        return

    st.markdown("### Synthèse")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Production solaire", f"{_number(results.annual_production_mwh, 1)} MWh/an")
    k2.metric("Investissement", _eur(results.investment_cost_eur, 0))
    k3.metric("Aides", _eur(results.aid_total_eur, 0), _percent(results.aid_rate))
    k4.metric("Reste à charge", _eur(results.net_investment_eur, 0))

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Économies annuelles", _eur(results.annual_savings_eur, 0))
    k6.metric(
        "Temps de retour brut",
        f"{_number(results.raw_payback_years, 1)} ans" if results.raw_payback_years is not None else "Non atteint",
    )
    k7.metric("Coût chaleur solaire", _eur_mwh(results.solar_heat_cost_eur_mwh, 1))
    k8.metric(f"Économies sur {inputs.years} ans", _eur(results.savings_over_period_eur, 0))

    st.markdown("### Décomposition du coût de chaleur")
    breakdown_rows = build_heat_cost_breakdown_rows(results)
    chart_col, table_col = st.columns([2.2, 1])
    with chart_col:
        fig_breakdown = _render_heat_cost_breakdown_plotly(results)
        if fig_breakdown is None:
            st.warning("Plotly n'est pas installé.")
        else:
            st.plotly_chart(fig_breakdown, width="stretch")
    with table_col:
        st.metric("Total P1' + P2 + P4", _eur_mwh(results.solar_heat_cost_eur_mwh, 1))
        st.metric("Référence énergie moyenne", _eur_mwh(results.average_reference_energy_cost_eur_mwh, 1))
        st.dataframe(pd.DataFrame(breakdown_rows), hide_index=True, width="stretch")

    st.markdown("### Projection économique")
    cashflow_rows = list(build_yearly_cashflow_projection(inputs, results))
    cashflow_col, info_col = st.columns([2.2, 1])
    with cashflow_col:
        fig_cashflow = _render_cashflow_plotly(cashflow_rows)
        if fig_cashflow is None:
            st.warning("Plotly n'est pas installé.")
        else:
            st.plotly_chart(fig_cashflow, width="stretch")
    with info_col:
        breakeven_year = _first_positive_year(cashflow_rows, "Flux cumulé inflation annuelle (€)")
        st.metric("Année de retour", f"Année {breakeven_year}" if breakeven_year is not None else "Non atteint")
        st.metric("Flux cumulé final", _eur(float(cashflow_rows[-1]["Flux cumulé inflation annuelle (€)"]), 0))

    with st.expander("Détail des coûts", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Poste": line.category,
                        "Libellé": line.label,
                        "Coût total (€)": line.total_cost_eur,
                        "Aide ADEME (€)": line.ademe_aid_eur,
                        "Reste à charge (€)": line.net_cost_eur,
                        "€/MWh.an": line.cost_eur_mwh_year,
                    }
                    for line in results.cost_lines
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    with st.expander("Export JSON", expanded=False):
        payload = {
            "app": APP_LABEL,
            "inputs": inputs.__dict__,
            "results": results.as_dict(),
            "breakdown_p1_p2_p4": breakdown_rows,
            "cashflow": cashflow_rows,
        }
        json_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        st.code(json_payload, language="json")
        st.download_button(
            "Télécharger le résultat JSON",
            data=json_payload.encode("utf-8"),
            file_name="helioeco_modele_cesc.json",
            mime="application/json",
            width="stretch",
        )
