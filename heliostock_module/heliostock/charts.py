from __future__ import annotations

import altair as alt
import pandas as pd

def _temperature_chart(results_df: pd.DataFrame):
    temp_df = results_df[
        [
            "Jour annee",
            "solar_ht_buffer_temp_end_c",
            "collector_temp_ht_c",
            "T_source_PAC_C",
            "T_paroi_forage_C",
        ]
    ].rename(
        columns={
            "solar_ht_buffer_temp_end_c": "T ballon solaire (C)",
            "collector_temp_ht_c": "T capteur charge ballon (C)",
            "T_source_PAC_C": "Température source PAC (C)",
            "T_paroi_forage_C": "Température paroi forage (C)",
        }
    )
    temp_long = temp_df.melt(
        id_vars=["Jour annee"],
        value_vars=[
            "T ballon solaire (C)",
            "T capteur charge ballon (C)",
            "Température source PAC (C)",
            "Température paroi forage (C)",
        ],
        var_name="Grandeur",
        value_name="Temperature (C)",
    )
    return (
        alt.Chart(temp_long)
        .mark_line(strokeWidth=1.4)
        .encode(
            x=alt.X("Jour annee:Q", title="Jour de l'annee"),
            y=alt.Y("Temperature (C):Q", title="Temperature (C)"),
            color="Grandeur:N",
            tooltip=[
                alt.Tooltip("Jour annee:Q", format=".1f"),
                "Grandeur:N",
                alt.Tooltip("Temperature (C):Q", format=".1f"),
            ],
        )
        .properties(height=390)
    )


def _multiyear_btes_temperature_chart(summary_df: pd.DataFrame):
    temp_long = summary_df[
        [
            "Mois index",
            "Mois",
            "T source PAC fin (C)",
            "T source PAC min (C)",
            "T source PAC max (C)",
            "T paroi forage fin (C)",
        ]
    ].melt(
        id_vars=["Mois index", "Mois"],
        value_vars=[
            "T source PAC fin (C)",
            "T source PAC min (C)",
            "T source PAC max (C)",
            "T paroi forage fin (C)",
        ],
        var_name="Grandeur",
        value_name="Temperature (C)",
    )
    return (
        alt.Chart(temp_long)
        .mark_line(point=False, strokeWidth=1.8)
        .encode(
            x=alt.X("Mois index:Q", title="Mois de simulation"),
            y=alt.Y("Temperature (C):Q", title="Température (C)"),
            color=alt.Color("Grandeur:N", title="Grandeur"),
            tooltip=[
                "Mois:N",
                "Grandeur:N",
                alt.Tooltip("Temperature (C):Q", format=".1f"),
            ],
        )
        .properties(height=390)
    )


def _multiyear_btes_temperature_comparison_chart(comparison_df: pd.DataFrame):
    return (
        alt.Chart(comparison_df)
        .mark_line(point=False, strokeWidth=2.0)
        .encode(
            x=alt.X("Mois index:Q", title="Mois de simulation"),
            y=alt.Y("T source PAC fin (C):Q", title="Température source PAC fin de mois (C)"),
            color=alt.Color("Scenario:N", title="Scenario"),
            tooltip=[
                "Scenario:N",
                "Mois:N",
                alt.Tooltip("T source PAC fin (C):Q", format=".1f"),
                alt.Tooltip("T source PAC min (C):Q", format=".1f"),
                alt.Tooltip("T source PAC max (C):Q", format=".1f"),
                alt.Tooltip("Heures sous Tmin source:Q", format=".0f"),
            ],
        )
        .properties(height=390)
    )


def _multiyear_btes_flux_chart(summary_df: pd.DataFrame):
    flux_long = summary_df[
        [
            "Mois index",
            "Mois",
            "Injection BTES (MWh)",
            "Extraction PAC (MWh)",
            "Q net sol (MWh)",
        ]
    ].melt(
        id_vars=["Mois index", "Mois"],
        value_vars=[
            "Injection BTES (MWh)",
            "Extraction PAC (MWh)",
            "Q net sol (MWh)",
        ],
        var_name="Poste",
        value_name="MWh/mois",
    )
    flux_long.loc[flux_long["Poste"] == "Extraction PAC (MWh)", "MWh/mois"] *= -1.0
    return (
        alt.Chart(flux_long)
        .mark_bar()
        .encode(
            x=alt.X("Mois index:Q", title="Mois de simulation"),
            y=alt.Y("MWh/mois:Q", title="MWh/mois"),
            color=alt.Color("Poste:N", title="Poste"),
            tooltip=["Mois:N", "Poste:N", alt.Tooltip("MWh/mois:Q", format=".1f")],
        )
        .properties(height=320)
    )


def _efficiency_chart(results_df: pd.DataFrame):
    eff_df = results_df[["Jour annee", "collector_eff_ht", "collector_eff_storage"]].rename(
        columns={
            "collector_eff_ht": "Rendement capteur charge ballon",
            "collector_eff_storage": "Rendement capteur injection BTES",
        }
    )
    eff_long = eff_df.melt(
        id_vars=["Jour annee"],
        value_vars=["Rendement capteur charge ballon", "Rendement capteur injection BTES"],
        var_name="Grandeur",
        value_name="Rendement",
    )
    return (
        alt.Chart(eff_long)
        .mark_line(strokeWidth=1.2)
        .encode(
            x=alt.X("Jour annee:Q", title="Jour de l'annee"),
            y=alt.Y("Rendement:Q", title="Rendement"),
            color="Grandeur:N",
            tooltip=[
                alt.Tooltip("Jour annee:Q", format=".1f"),
                "Grandeur:N",
                alt.Tooltip("Rendement:Q", format=".3f"),
            ],
        )
        .properties(height=300)
    )


def _duration_chart(duration_df: pd.DataFrame, *, sort_by: str):
    return (
        alt.Chart(duration_df)
        .mark_line(interpolate="step-after", strokeWidth=2)
        .encode(
            x=alt.X("Heure triee:Q", title=f"Heures triees par {sort_by} decroissant"),
            y=alt.Y("Puissance (kW):Q", title="Puissance (kW)"),
            color="Courbe:N",
            tooltip=[
                "Heure triee:Q",
                "Courbe:N",
                alt.Tooltip("Puissance (kW):Q", format=".1f"),
                "Mois:Q",
                "Jour:Q",
                "Heure EPW:Q",
                alt.Tooltip("Tair (C):Q", format=".1f"),
            ],
        )
        .properties(height=430)
    )


def _stacked_coverage_duration_chart(df: pd.DataFrame, *, title: str):
    return (
        alt.Chart(df)
        .mark_area(interpolate="step-after")
        .encode(
            x=alt.X("Heure triee:Q", title="Heures triees par besoin decroissant"),
            y=alt.Y("Puissance (kW):Q", title="Puissance appelee/couverte (kW)", stack="zero"),
            color=alt.Color(
                "Poste:N",
                title="Poste",
                scale=alt.Scale(
                    domain=["Solaire thermique", "Géothermie PAC", "Appoint HT", "Appoint BT"],
                    range=["#facc15", "#16a34a", "#9ca3af", "#6b7280"],
                ),
            ),
            order=alt.Order("Ordre:Q", sort="ascending"),
            tooltip=[
                "Heure triee:Q",
                "Poste:N",
                alt.Tooltip("Puissance (kW):Q", format=".1f"),
                "Mois:Q",
                "Jour:Q",
                "Heure EPW:Q",
                alt.Tooltip("Tair (C):Q", format=".1f"),
            ],
        )
        .properties(height=360, title=title)
    )


def _stacked_coverage_duration_chart(df: pd.DataFrame, *, title: str):
    return (
        alt.Chart(df)
        .mark_area(interpolate="step-after")
        .encode(
            x=alt.X("Heure triee:Q", title="Heures triees par besoin decroissant"),
            y=alt.Y("Puissance (kW):Q", title="Puissance appelee/couverte (kW)", stack="zero"),
            color=alt.Color(
                "Poste:N",
                title="Poste",
                scale=alt.Scale(
                    domain=[
                        "Solaire thermique",
                        "Geothermie PAC",
                        "Geothermie PAC",
                        "Appoint HT",
                        "Appoint BT",
                        "Appoint gaz",
                    ],
                    range=["#facc15", "#16a34a", "#16a34a", "#9ca3af", "#6b7280", "#6b7280"],
                ),
            ),
            order=alt.Order("Ordre:Q", sort="ascending"),
            tooltip=[
                "Heure triee:Q",
                "Poste:N",
                alt.Tooltip("Puissance (kW):Q", format=".1f"),
                "Mois:Q",
                "Jour:Q",
                "Heure EPW:Q",
                alt.Tooltip("Tair (C):Q", format=".1f"),
            ],
        )
        .properties(height=360, title=title)
    )


def _bar_chart(df: pd.DataFrame, *, y_title: str = "MWh/mois", height: int = 340):
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("Mois:N", title="Mois", sort=None),
            y=alt.Y("Valeur:Q", title=y_title),
            color=alt.Color("Poste:N", title="Poste"),
            tooltip=["Mois:N", "Poste:N", alt.Tooltip("Valeur:Q", format=".1f")],
        )
        .properties(height=height)
    )


def _line_chart(df: pd.DataFrame, *, y_title: str, height: int = 300, y_domain: list[float] | None = None):
    y_scale = alt.Scale(domain=y_domain) if y_domain is not None else alt.Undefined
    return (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("Mois:N", title="Mois", sort=None),
            y=alt.Y("Valeur:Q", title=y_title, scale=y_scale),
            tooltip=["Mois:N", alt.Tooltip("Valeur:Q", format=".1f")],
        )
        .properties(height=height)
    )


def _economic_cost_breakdown_chart(cost_breakdown_df: pd.DataFrame, *, reference_cost_eur_mwh: float):
    bars = (
        alt.Chart(cost_breakdown_df)
        .mark_bar()
        .encode(
            x=alt.X("Poste:N", title="Poste", sort=None),
            y=alt.Y("Valeur:Q", title="€/MWh solaire valorisé"),
            color=alt.Color("Poste:N", title="Poste"),
            tooltip=["Poste:N", alt.Tooltip("Valeur:Q", format=".1f")],
        )
    )
    reference_df = pd.DataFrame(
        [{"Poste": "Référence", "Valeur": max(0.0, float(reference_cost_eur_mwh))}]
    )
    line = (
        alt.Chart(reference_df)
        .mark_rule(color="#dc2626", strokeDash=[6, 4], strokeWidth=2)
        .encode(
            y="Valeur:Q",
            tooltip=[alt.Tooltip("Valeur:Q", title="Coût référence moyen", format=".1f")],
        )
    )
    return (bars + line).properties(height=330)


def _heat_cost_vector_chart(cost_bars_df: pd.DataFrame):
    return (
        alt.Chart(cost_bars_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "Vecteur:N",
                title="Generateur",
                sort=["Solaire thermique", "Geothermie PAC", "Appoint gaz", "Mix ENR", "Reference 100% gaz"],
            ),
            y=alt.Y("Valeur:Q", title="EUR/MWh"),
            color=alt.Color("Poste:N", title="Poste"),
            tooltip=[
                "Vecteur:N",
                "Poste:N",
                alt.Tooltip("Valeur:Q", title="EUR/MWh", format=".1f"),
            ],
        )
        .properties(height=360)
    )


def _capex_generator_chart(capex_df: pd.DataFrame):
    chart_df = capex_df.melt(
        id_vars=["Generateur"],
        value_vars=["CAPEX brut (EUR)", "Aide ADEME (EUR)", "Autres aides (EUR)", "Gain sondes (EUR)", "CAPEX net (EUR)"],
        var_name="Poste",
        value_name="EUR",
    )
    return (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "Generateur:N",
                title="Generateur",
                sort=["Solaire thermique", "Geothermie PAC", "Appoint gaz", "Reference 100% gaz"],
            ),
            y=alt.Y("EUR:Q", title="EUR"),
            color=alt.Color("Poste:N", title="Poste"),
            column=alt.Column("Poste:N", title=None),
            tooltip=["Generateur:N", "Poste:N", alt.Tooltip("EUR:Q", format=",.0f")],
        )
        .properties(height=260)
    )


def _heat_cost_summary_chart(heat_cost_df: pd.DataFrame):
    return (
        alt.Chart(heat_cost_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "Generateur:N",
                title="Generateur",
                sort=["Solaire thermique", "Geothermie PAC", "Appoint gaz", "Mix ENR", "Reference 100% gaz"],
            ),
            y=alt.Y("Cout chaleur (EUR/MWh):Q", title="EUR/MWh"),
            color=alt.Color("Generateur:N", legend=None),
            tooltip=[
                "Generateur:N",
                alt.Tooltip("Energie (MWh/an):Q", format=",.1f"),
                alt.Tooltip("Cout chaleur (EUR/MWh):Q", format=".1f"),
            ],
        )
        .properties(height=320)
    )


def _parametric_surface_chart(parametric_df: pd.DataFrame):
    chart_df = parametric_df.melt(
        id_vars=["Surface solaire (m²)"],
        value_vars=[
            "Coût chaleur Mix ENR (EUR/MWh)",
            "Taux EnR global (%)",
            "Couverture solaire HT (%)",
        ],
        var_name="Indicateur",
        value_name="Valeur",
    )
    return (
        alt.Chart(chart_df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("Surface solaire (m²):Q", title="Surface solaire thermique (m²)"),
            y=alt.Y("Valeur:Q", title=None),
            color=alt.Color("Indicateur:N", legend=None),
            tooltip=[
                alt.Tooltip("Surface solaire (m²):Q", format=".0f"),
                "Indicateur:N",
                alt.Tooltip("Valeur:Q", format=".1f"),
            ],
        )
        .properties(height=210)
        .facet(row=alt.Row("Indicateur:N", title=None))
        .resolve_scale(y="independent")
    )


def _parametric_pac_chart(parametric_df: pd.DataFrame):
    chart_df = parametric_df.melt(
        id_vars=["P PAC (% Pmax BT)"],
        value_vars=[
            "Coût chaleur Mix ENR (EUR/MWh)",
            "Taux EnR global (%)",
            "Couverture PAC BT (%)",
            "Appoint total (MWh/an)",
        ],
        var_name="Indicateur",
        value_name="Valeur",
    )
    return (
        alt.Chart(chart_df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("P PAC (% Pmax BT):Q", title="Puissance PAC (% Pmax BT)"),
            y=alt.Y("Valeur:Q", title=None),
            color=alt.Color("Indicateur:N", legend=None),
            tooltip=[
                alt.Tooltip("P PAC (% Pmax BT):Q", format=".0f"),
                "Indicateur:N",
                alt.Tooltip("Valeur:Q", format=".1f"),
            ],
        )
        .properties(height=210)
        .facet(row=alt.Row("Indicateur:N", title=None))
        .resolve_scale(y="independent")
    )


def _cashflow_chart(cashflow_df: pd.DataFrame):
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#6b7280").encode(y="y:Q")
    curve = (
        alt.Chart(cashflow_df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("Annee:Q", title="Année"),
            y=alt.Y("Flux cumule (€):Q", title="Cashflow cumulé (€)"),
            tooltip=[
                "Annee:Q",
                alt.Tooltip("Flux annuel (€):Q", format=",.0f"),
                alt.Tooltip("Flux cumule (€):Q", format=",.0f"),
            ],
        )
    )
    return (zero + curve).properties(height=330)

