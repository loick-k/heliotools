"""Application HelioEco intÃ©grÃ©e au portail HelioTools.

HelioEco expose le modÃ¨le Ã©conomique CESC existant sans dupliquer le moteur
de calcul : les formules restent portÃ©es par `opportunity_notes.cesc_economic_model`.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:  # pragma: no cover - dÃ©pendance optionnelle cÃ´tÃ© interface
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
from ..common.solar_thermal_cost_reference import (
    SOLAR_THERMAL_COST_REFERENCE_NOTE,
    build_solar_thermal_cost_reference_plotly,
)
from ..gas_reference import (
    GAS_REFERENCE_CONTEXT_HELP,
    GAS_REFERENCE_CONTEXT_LABELS,
    GAS_REFERENCE_EXISTING_BOILER,
    GAS_REFERENCE_RENEWAL,
    gas_reference_context_label,
    includes_gas_boiler_fixed_costs,
    normalize_gas_reference_context,
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
    return f"{_number(value, digits)} â‚¬"


def _eur_mwh(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{_number(value, digits)} â‚¬/MWh"


def _percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{_number(100.0 * value, digits)} %"


def build_heat_cost_breakdown_rows(results: CescEconomicResults) -> list[dict[str, float | str]]:
    """DÃ©composition P1/P2/P4 du coÃ»t de chaleur solaire."""

    return [
        {
            "Poste": "P1' - Auxiliaires Ã©lectriques",
            "Famille": "P1'",
            "CoÃ»t chaleur (â‚¬/MWh)": results.heat_cost_p1_eur_mwh or 0.0,
        },
        {
            "Poste": "P2 - Suivi et maintenance",
            "Famille": "P2",
            "CoÃ»t chaleur (â‚¬/MWh)": results.heat_cost_p2_eur_mwh or 0.0,
        },
        {
            "Poste": "P4 - Investissement net aidÃ©",
            "Famille": "P4",
            "CoÃ»t chaleur (â‚¬/MWh)": results.heat_cost_p4_eur_mwh or 0.0,
        },
    ]


def _first_positive_year(rows: list[dict[str, float | int]], cumulative_key: str) -> int | None:
    for row in rows:
        if float(row.get(cumulative_key, 0.0) or 0.0) >= 0.0:
            return int(row.get("AnnÃ©e", 0) or 0)
    return None


def _first_available_key(row: dict[str, float | int], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return key
    available = ", ".join(str(key) for key in row)
    raise KeyError(f"Aucune colonne disponible parmi {candidates}. Colonnes reÃ§ues : {available}")


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
        value = float(row["CoÃ»t chaleur (â‚¬/MWh)"])
        fig.add_trace(
            go.Bar(
                y=["CoÃ»t chaleur solaire"],
                x=[value],
                name=str(row["Poste"]),
                orientation="h",
                marker_color=colors.get(str(row["Famille"]), "#0f766e"),
                text=[f"{value:.1f} â‚¬/MWh"],
                textposition="inside",
                hovertemplate="%{fullData.name}<br>%{x:.1f} â‚¬/MWh<extra></extra>",
            )
        )

    fig.add_vline(
        x=reference_cost,
        line_dash="dash",
        annotation_text=f"RÃ©fÃ©rence Ã©nergie moyenne : {reference_cost:.1f} â‚¬/MWh",
        annotation_position="top right",
    )
    fig.update_layout(
        barmode="stack",
        height=320,
        margin={"l": 10, "r": 20, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis_title="CoÃ»t de la chaleur solaire utile (â‚¬/MWh)",
        yaxis_title=None,
        hovermode="closest",
    )
    fig.update_xaxes(range=[0, x_max], ticksuffix=" â‚¬/MWh")
    fig.update_yaxes(showticklabels=False)
    return fig


def _render_cashflow_plotly(cashflow_rows: list[dict[str, float | int]]):
    if go is None or not cashflow_rows:
        return None

    sample = cashflow_rows[0]
    year_key = _first_available_key(sample, ("AnnÃ©e", "Annee"))
    annual_key = _first_available_key(
        sample,
        (
            "Ã‰conomie annuelle inflation (â‚¬)",
            "Economie annuelle inflation (â‚¬)",
            "Flux annuel inflation annuelle (â‚¬)",
            "Ã‰conomie annuelle moyenne (â‚¬)",
            "Economie annuelle moyenne (â‚¬)",
        ),
    )
    cumulative_key = _first_available_key(
        sample,
        (
            "Flux cumulÃ© inflation annuelle (â‚¬)",
            "Flux cumule inflation annuelle (â‚¬)",
            "Flux cumulÃ© moyen (â‚¬)",
            "Flux cumule moyen (â‚¬)",
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
            name="Flux cumulÃ©",
            customdata=annual,
            hovertemplate=(
                "AnnÃ©e %{x}<br>"
                "Flux annuel : %{customdata:,.0f} â‚¬<br>"
                "Flux cumulÃ© : %{y:,.0f} â‚¬"
                "<extra></extra>"
            ),
        )
    )
    fig.add_hline(y=0, line_dash="dash", annotation_text="Seuil de retour Ã  zÃ©ro", annotation_position="top left")
    if breakeven_year is not None:
        fig.add_vline(
            x=breakeven_year,
            line_dash="dot",
            annotation_text=f"Retour annÃ©e {breakeven_year}",
            annotation_position="top",
        )
    fig.update_layout(
        height=390,
        margin={"l": 10, "r": 20, "t": 35, "b": 40},
        xaxis_title="AnnÃ©e",
        yaxis_title="Flux cumulÃ© (â‚¬)",
        hovermode="x unified",
    )
    fig.update_xaxes(dtick=max(1, round(max(years) / 10)))
    fig.update_yaxes(ticksuffix=" â‚¬")
    return fig


def render_helioeco_app() -> None:
    """Rendu Streamlit de l'application HelioEco."""

    st.title("HelioEco")
    st.caption(
        "ModÃ¨le Ã©conomique solaire thermique issu de l'onglet Excel Â« Simulateur eco CESC Â». "
        "Cette premiÃ¨re intÃ©gration garde HelioEco autonome tout en rÃ©utilisant le moteur Ã©conomique commun Ã  HelioNOP."
    )

    st.markdown("### HypothÃ¨ses principales")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        typologie = st.selectbox("Typologie", options=list(TYPOLOGY_LABELS), key="helioeco_typologie")
        surface_m2 = st.number_input("Surface capteurs (mÂ²)", min_value=0.0, value=33.8, step=1.0)
        productivity = st.number_input("ProductivitÃ© estimÃ©e (kWh/mÂ².an)", min_value=0.0, value=562.0, step=10.0)
    with col_b:
        reference_energy_cost = st.number_input("CoÃ»t Ã©nergie de rÃ©fÃ©rence (â‚¬HT/MWh)", min_value=0.0, value=75.0, step=5.0)
        inflation = st.number_input("Inflation Ã©nergie de rÃ©fÃ©rence (%/an)", value=3.0, step=0.5) / 100.0
        years = st.number_input("DurÃ©e d'analyse (ans)", min_value=1, value=20, step=1)
        gas_context_options = list(GAS_REFERENCE_CONTEXT_LABELS)
        gas_reference_context = st.radio(
            "Contexte reference gaz",
            options=gas_context_options,
            format_func=gas_reference_context_label,
            index=gas_context_options.index(
                normalize_gas_reference_context(
                    st.session_state.get("helioeco_gas_reference_context", GAS_REFERENCE_EXISTING_BOILER)
                )
            ),
            horizontal=True,
            key="helioeco_gas_reference_context",
            help=GAS_REFERENCE_CONTEXT_HELP,
        )
    with col_c:
        works_cost = st.number_input("CoÃ»t travaux installation (â‚¬HT/mÂ²)", min_value=0.0, value=1563.0, step=50.0)
        eta_appoint = st.number_input("Rendement appoint global", min_value=0.01, max_value=1.5, value=0.82, step=0.01)
        st.metric("Forfait ADEME appliquÃ©", _eur(get_ademe_aid_eur_per_mwh_year(typologie), 0) + "/MWh.an")

    fig_cost_reference = build_solar_thermal_cost_reference_plotly(go, selected_cost_eur_m2=float(works_cost))
    if fig_cost_reference is not None:
        st.plotly_chart(fig_cost_reference, width="stretch")
        st.caption(SOLAR_THERMAL_COST_REFERENCE_NOTE)

    with st.expander("HypothÃ¨ses avancÃ©es", expanded=False):
        adv_a, adv_b, adv_c = st.columns(3)
        auxiliary_ratio = adv_a.number_input(
            "Consommation Ã©lectrique des auxiliaires (% de la production solaire)",
            value=DEFAULT_AUXILIARY_ELECTRICITY_RATIO * 100.0,
            step=0.5,
        ) / 100.0
        electricity_cost = adv_a.number_input(
            "Prix de l'Ã©lectricitÃ© des auxiliaires (â‚¬/MWh)",
            value=DEFAULT_AUXILIARY_ELECTRICITY_COST_EUR_MWH,
            step=10.0,
        )
        adv_a.caption(
            f"P1' auxiliaires = {auxiliary_ratio * 100.0:.1f} % Ã— {electricity_cost:.0f} â‚¬/MWh = "
            f"{auxiliary_ratio * electricity_cost:.1f} â‚¬/MWh solaire utile."
        )
        maintenance_cost = adv_b.number_input("Maintenance (â‚¬/mÂ².an)", value=22.0, step=1.0)
        fae_cost = adv_b.number_input("FAE (â‚¬HT)", value=4929.0, step=100.0)
        fae_aid_rate = adv_c.number_input("Taux aide FAE (%)", value=70.0, step=5.0) / 100.0
        ademe_cap = adv_c.number_input("Plafond aide travaux (% coÃ»t)", value=65.0, step=5.0) / 100.0

        reference_boiler_power_kw = adv_c.number_input(
            "Puissance chaudiere gaz de reference (kW)",
            min_value=0.0,
            value=max(0.0, float(surface_m2) * float(productivity) / 1200.0),
            step=10.0,
            disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
        )
        reference_boiler_p2_eur_kw_year = adv_c.number_input(
            "P2 chaudiere gaz reference (EUR/kW.an)",
            min_value=0.0,
            value=10.0,
            step=1.0,
            disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
        )
        reference_boiler_capex_eur_kw = adv_c.number_input(
            "P4 chaudiere gaz reference (EUR/kW)",
            min_value=0.0,
            value=200.0,
            step=10.0,
            disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
        )

    inputs = CescEconomicInputs(
        typologie=str(typologie),
        surface_m2=float(surface_m2),
        productivity_kwh_m2_year=float(productivity),
        reference_energy_cost_eur_mwh=float(reference_energy_cost),
        reference_energy_inflation_rate=float(inflation),
        years=int(years),
        works_cost_eur_m2=float(works_cost),
        eta_appoint=float(eta_appoint),
        gas_reference_context=gas_reference_context,
        reference_boiler_power_kw=float(reference_boiler_power_kw),
        reference_boiler_p2_eur_kw_year=float(reference_boiler_p2_eur_kw_year),
        reference_boiler_capex_eur_kw=float(reference_boiler_capex_eur_kw),
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

    gas_reference_is_renewal = includes_gas_boiler_fixed_costs(gas_reference_context)

    st.markdown("### SynthÃ¨se")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Production solaire", f"{_number(results.annual_production_mwh, 1)} MWh/an")
    k2.metric("Investissement solaire thermique", _eur(results.solar_thermal_investment_eur, 0))
    k3.metric("Aides", _eur(results.aid_total_eur, 0), _percent(results.aid_rate))
    k4.metric("Reste Ã  charge", _eur(results.net_investment_eur, 0))

    k5, k6, k7, k8 = st.columns(4)
    if gas_reference_is_renewal:
        k5.metric("Investissement solaire + gaz", _eur(results.solar_plus_gas_investment_eur, 0))
        k6.metric("Investissement référence gaz", _eur(results.reference_gas_investment_eur, 0))
        k7.metric(f"Coût cumulé solaire + gaz sur {inputs.years} ans", _eur(results.solar_plus_gas_cumulative_cost_eur, 0))
        k8.metric(f"Coût cumulé référence gaz sur {inputs.years} ans", _eur(results.reference_gas_cumulative_cost_eur, 0))
        st.caption(
            "En contexte chaudière gaz à renouveler, le temps de retour brut est masqué : "
            "la lecture pertinente est une comparaison d'investissements et de coûts cumulés."
        )
    else:
        k5.metric("Économies annuelles", _eur(results.annual_savings_eur, 0))
        k6.metric(
            "Temps de retour brut",
            f"{_number(results.raw_payback_years, 1)} ans" if results.raw_payback_years is not None else "Non atteint",
        )
        k7.metric("Coût chaleur solaire", _eur_mwh(results.solar_heat_cost_eur_mwh, 1))
        k8.metric(f"Économies sur {inputs.years} ans", _eur(results.savings_over_period_eur, 0))

    st.markdown("### DÃ©composition du coÃ»t de chaleur")
    breakdown_rows = build_heat_cost_breakdown_rows(results)
    chart_col, table_col = st.columns([2.2, 1])
    with chart_col:
        fig_breakdown = _render_heat_cost_breakdown_plotly(results)
        if fig_breakdown is None:
            st.warning("Plotly n'est pas installÃ©.")
        else:
            st.plotly_chart(fig_breakdown, width="stretch")
    with table_col:
        st.metric("Total P1' + P2 + P4", _eur_mwh(results.solar_heat_cost_eur_mwh, 1))
        st.metric("RÃ©fÃ©rence Ã©nergie moyenne", _eur_mwh(results.average_reference_energy_cost_eur_mwh, 1))
        st.dataframe(pd.DataFrame(breakdown_rows), hide_index=True, width="stretch")

    st.markdown("### Projection Ã©conomique")
    cashflow_rows = list(build_yearly_cashflow_projection(inputs, results))
    cashflow_col, info_col = st.columns([2.2, 1])
    with cashflow_col:
        fig_cashflow = _render_cashflow_plotly(cashflow_rows)
        if fig_cashflow is None:
            st.warning("Plotly n'est pas installÃ©.")
        else:
            st.plotly_chart(fig_cashflow, width="stretch")
    with info_col:
        breakeven_year = _first_positive_year(cashflow_rows, "Flux cumulÃ© inflation annuelle (â‚¬)")
        st.metric("AnnÃ©e de retour", f"AnnÃ©e {breakeven_year}" if breakeven_year is not None else "Non atteint")
        st.metric("Flux cumulÃ© final", _eur(float(cashflow_rows[-1]["Flux cumulÃ© inflation annuelle (â‚¬)"]), 0))

    with st.expander("DÃ©tail des coÃ»ts", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Poste": line.category,
                        "LibellÃ©": line.label,
                        "CoÃ»t total (â‚¬)": line.total_cost_eur,
                        "Aide ADEME (â‚¬)": line.ademe_aid_eur,
                        "Reste Ã  charge (â‚¬)": line.net_cost_eur,
                        "â‚¬/MWh.an": line.cost_eur_mwh_year,
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
            "TÃ©lÃ©charger le rÃ©sultat JSON",
            data=json_payload.encode("utf-8"),
            file_name="helioeco_modele_cesc.json",
            mime="application/json",
            width="stretch",
        )
