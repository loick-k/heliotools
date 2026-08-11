from __future__ import annotations

import math

import altair as alt
import pandas as pd
import streamlit as st

from .charts import _heat_cost_vector_chart
from .ui_formatting import display_dataframe, round_display_df


SOLAR_ONLY_SCENARIO_LABELS = {
    "Reference 100 % gaz": "Référence 100 % gaz",
    "Geothermie + solaire meme sondes": "Solaire thermique + appoint gaz",
}

SOLAR_ONLY_SCENARIOS = tuple(SOLAR_ONLY_SCENARIO_LABELS)

GEOTHERMAL_ECONOMIC_COLUMNS = [
    "Lineaire sondes (ml)",
    "Saved borefield length (ml)",
    "Electricite PAC (MWh/an)",
    "Electricite PAC cumulee (MWh)",
    "COP annee finale",
    "Couverture PAC BT annee finale (%)",
    "T source min annee finale (C)",
    "Heures limite source annee finale",
    "Conformite GMI annee finale",
    "Heures hors GMI annee finale",
]


def _is_solar_ht_only(demand_scope: str) -> bool:
    return str(demand_scope or "").lower() == "ht_only"


def _filter_solar_only_scenarios(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Scenario" not in df.columns:
        return df
    filtered = df[df["Scenario"].astype(str).isin(SOLAR_ONLY_SCENARIOS)].copy()
    filtered["Scenario"] = filtered["Scenario"].astype(str).replace(SOLAR_ONLY_SCENARIO_LABELS)
    return filtered


def _solar_only_comparison_table(economic_comparison_df: pd.DataFrame) -> pd.DataFrame:
    filtered = _filter_solar_only_scenarios(economic_comparison_df)
    if filtered.empty:
        return filtered
    return filtered.drop(columns=[col for col in GEOTHERMAL_ECONOMIC_COLUMNS if col in filtered.columns])


def _solar_only_comparison_chart_df(economic_comparison_chart_df: pd.DataFrame) -> pd.DataFrame:
    filtered = _filter_solar_only_scenarios(economic_comparison_chart_df)
    if filtered.empty or "Indicateur" not in filtered.columns:
        return filtered
    geothermal_indicators = {"Lineaire sondes (ml)", "Electricite PAC (MWh/an)"}
    return filtered[~filtered["Indicateur"].astype(str).isin(geothermal_indicators)].copy()


def _solar_only_heat_costs(heat_costs: dict[str, float | pd.DataFrame]) -> dict[str, float | pd.DataFrame]:
    filtered = dict(heat_costs)
    keep_generators = {"Solaire thermique", "Appoint gaz", "Mix ENR", "Reference 100% gaz"}
    for key in ("capex_summary", "p1_p2_p4"):
        value = filtered.get(key)
        if isinstance(value, pd.DataFrame) and "Generateur" in value.columns:
            filtered[key] = value[value["Generateur"].astype(str).isin(keep_generators)].copy()
    cost_bars = filtered.get("cost_bars")
    if isinstance(cost_bars, pd.DataFrame) and "Vecteur" in cost_bars.columns:
        filtered["cost_bars"] = cost_bars[cost_bars["Vecteur"].astype(str).isin(keep_generators)].copy()
    return filtered


def _scenario_comparison_chart(chart_df: pd.DataFrame, *, title: str) -> alt.Chart:
    return (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("Scenario:N", title=None, sort=None, axis=alt.Axis(labelAngle=-35, labelLimit=80)),
            y=alt.Y("Valeur:Q", title=None),
            color=alt.Color("Scenario:N", legend=None),
            tooltip=["Scenario:N", alt.Tooltip("Valeur:Q", format=".0f")],
        )
        .properties(height=250, title=title)
    )


def _recharge_value_table(recharge_value: dict[str, float | bool | str]) -> pd.DataFrame:
    payback_recharge = float(recharge_value["recharge_payback_years"])
    payback = (
        payback_recharge
        if bool(recharge_value["applicable"])
        and str(recharge_value["status"]) == "ok"
        and math.isfinite(payback_recharge)
        else math.nan
    )
    return pd.DataFrame(
        [
            ("Part solaire affectée à la recharge", float(recharge_value["solar_recharge_part"]) * 100.0, "%"),
            ("CAPEX solaire affecté recharge", float(recharge_value["capex_solar_recharge_eur"]), "EUR"),
            ("Économie CAPEX sondes brute", float(recharge_value["saved_borefield_capex_eur"]), "EUR"),
            ("Économie CAPEX sondes nette", float(recharge_value["saved_borefield_net_capex_eur"]), "EUR"),
            ("Économie électricité PAC", float(recharge_value["electricity_savings_eur_an"]), "EUR/an"),
            ("Coût annuel solaire recharge", float(recharge_value["annual_solar_recharge_cost_eur_an"]), "EUR/an"),
            ("Bilan net recharge", float(recharge_value["net_recharge_balance_eur_an"]), "EUR/an"),
            ("TRB recharge", payback, "ans"),
        ],
        columns=["Grandeur", "Valeur", "Unité"],
    )


def _generator_economic_table(heat_costs: dict[str, float | pd.DataFrame]) -> pd.DataFrame:
    capex_df = heat_costs["capex_summary"]
    p1_p2_p4_df = heat_costs["p1_p2_p4"]
    assert isinstance(capex_df, pd.DataFrame)
    assert isinstance(p1_p2_p4_df, pd.DataFrame)

    p1_p2_table = p1_p2_p4_df.pivot(index="Generateur", columns="Poste", values="EUR/MWh").reset_index()
    p1_p2_table["Coût chaleur (EUR/MWh)"] = p1_p2_table[["P1", "P2", "P4"]].sum(axis=1)
    generator_table = p1_p2_table.merge(capex_df, on="Generateur", how="left")
    generator_table["Generateur"] = generator_table["Generateur"].replace(
        {
            "Appoint gaz": "Appoint gaz",
            "Geothermie PAC": "Géothermie",
            "Solaire thermique": "Solaire thermique",
            "Mix ENR": "Mix ENR",
            "Reference 100% gaz": "Référence 100 % gaz",
        }
    )
    generator_order = ["Appoint gaz", "Géothermie", "Solaire thermique", "Mix ENR", "Référence 100 % gaz"]
    generator_table["Ordre"] = generator_table["Generateur"].apply(
        lambda value: generator_order.index(value) if value in generator_order else 99
    )
    return generator_table.sort_values("Ordre").drop(columns=["Ordre"])


def render_economics_tab(
    *,
    economic_comparison_df: pd.DataFrame,
    economic_comparison_chart_df: pd.DataFrame,
    economic_trajectory_df: pd.DataFrame,
    recharge_value: dict[str, float | bool | str],
    heat_costs: dict[str, float | pd.DataFrame],
    total_compressor: float,
    total_auxiliaries: float,
    total_standby: float,
    total_elec: float,
    mean_cop: float,
    spf_pac_total: float,
    spf_system: float,
    demand_scope: str = "ht_bt",
) -> None:
    solar_only = _is_solar_ht_only(demand_scope)
    comparison_df = _solar_only_comparison_table(economic_comparison_df) if solar_only else economic_comparison_df
    comparison_chart_df = (
        _solar_only_comparison_chart_df(economic_comparison_chart_df) if solar_only else economic_comparison_chart_df
    )
    trajectory_df = _filter_solar_only_scenarios(economic_trajectory_df) if solar_only else economic_trajectory_df
    heat_costs_to_display = _solar_only_heat_costs(heat_costs) if solar_only else heat_costs

    if solar_only:
        st.markdown("### Analyse économique solaire thermique seul")
        st.caption(
            "Lecture : comparaison entre une référence 100 % appoint gaz et le scénario solaire thermique haute "
            "température avec appoint gaz en complément. Les coûts sont calculés sans PAC géothermique, sans champ "
            "de sondes et sans recharge BTES."
        )
    else:
        st.markdown("### Comparaison économique des 4 scénarios")
        st.caption(
            "Lecture type Dim A / Dim B / Dim C : référence gaz, géothermie seule, géothermie + solaire à linéaire "
            "constant, puis géothermie + solaire avec linéaire réduit. La recharge solaire est analysée comme un "
            "service rendu au champ de sondes, sans économie P2 proportionnelle aux ml économisés. Les coûts variables "
            "sont calculés sur une trajectoire physique multiannuelle nominale."
        )
    st.dataframe(display_dataframe(comparison_df), width="stretch", hide_index=True)

    chart_titles = {
        "Cout chaleur global (EUR/MWh)": "Coût chaleur",
        "Taux EnR global (%)": "Taux EnR",
        "Lineaire sondes (ml)": "Linéaire sondes",
        "Electricite PAC (MWh/an)": "Électricité PAC",
    }
    active_chart_titles = [
        (indicator, title)
        for indicator, title in chart_titles.items()
        if not solar_only or indicator not in {"Lineaire sondes (ml)", "Electricite PAC (MWh/an)"}
    ]
    chart_cols = st.columns(len(active_chart_titles))
    for col, (indicator, title) in zip(chart_cols, active_chart_titles):
        chart_df = comparison_chart_df[comparison_chart_df["Indicateur"] == indicator]
        if not chart_df.empty:
            col.altair_chart(_scenario_comparison_chart(chart_df, title=title), width="stretch")

    if not solar_only:
        st.markdown("### Valeur économique de la recharge solaire")
        if not bool(recharge_value["applicable"]):
            st.info("Recharge solaire non applicable : aucune énergie solaire injectée au BTES.")
        elif str(recharge_value["status"]) == "desactive":
            st.info("Optimisation par recharge solaire non lancée.")
        elif str(recharge_value["status"]) == "non determine":
            st.warning("Gain de linéaire non déterminé : le solveur n'a pas trouvé de réduction équivalente robuste.")

        st.caption(
            "`Coût annuel solaire recharge` = annuité de la part de CAPEX solaire affectée à la recharge "
            "+ P2 solaire recharge + P4 solaire recharge. `Bilan net recharge` = gains annuels de recharge "
            "(économie CAPEX sondes nette annualisée + économie électricité PAC) - coût annuel solaire recharge. "
            "L'économie nette tient compte de la baisse d'aide ADEME quand le CAPEX sondes diminue."
        )
        st.dataframe(display_dataframe(_recharge_value_table(recharge_value)), width="stretch", hide_index=True)
        st.caption("Aucune économie de P2 n'est appliquée au linéaire de sondes économisé.")

    st.markdown("### Détail économique par générateur")
    st.dataframe(display_dataframe(_generator_economic_table(heat_costs_to_display)), width="stretch", hide_index=True)
    st.altair_chart(_heat_cost_vector_chart(heat_costs_to_display["cost_bars"]), width="stretch")

    if solar_only:
        st.markdown("### Trajectoire annuelle solaire thermique + appoint gaz")
    else:
        st.markdown("### Trajectoire annuelle utilisée pour l'économie")
    st.caption(
        "Si l'horizon économique dépasse les années simulées, la dernière année simulée est répétée comme année stabilisée."
    )
    st.dataframe(display_dataframe(trajectory_df), width="stretch", hide_index=True)

