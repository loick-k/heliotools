from __future__ import annotations

import math

import altair as alt
import pandas as pd
import streamlit as st

from .charts import _heat_cost_vector_chart
from .ui_formatting import display_dataframe, round_display_df


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
            ("Part solaire affectÃ©e Ã  la recharge", float(recharge_value["solar_recharge_part"]) * 100.0, "%"),
            ("CAPEX solaire affectÃ© recharge", float(recharge_value["capex_solar_recharge_eur"]), "EUR"),
            ("Ã‰conomie CAPEX sondes brute", float(recharge_value["saved_borefield_capex_eur"]), "EUR"),
            ("Ã‰conomie CAPEX sondes nette", float(recharge_value["saved_borefield_net_capex_eur"]), "EUR"),
            ("Ã‰conomie Ã©lectricitÃ© PAC", float(recharge_value["electricity_savings_eur_an"]), "EUR/an"),
            ("CoÃ»t annuel solaire recharge", float(recharge_value["annual_solar_recharge_cost_eur_an"]), "EUR/an"),
            ("Bilan net recharge", float(recharge_value["net_recharge_balance_eur_an"]), "EUR/an"),
            ("TRB recharge", payback, "ans"),
        ],
        columns=["Grandeur", "Valeur", "UnitÃ©"],
    )


def _generator_economic_table(heat_costs: dict[str, float | pd.DataFrame]) -> pd.DataFrame:
    capex_df = heat_costs["capex_summary"]
    p1_p2_p4_df = heat_costs["p1_p2_p4"]
    assert isinstance(capex_df, pd.DataFrame)
    assert isinstance(p1_p2_p4_df, pd.DataFrame)

    p1_p2_table = p1_p2_p4_df.pivot(index="Generateur", columns="Poste", values="EUR/MWh").reset_index()
    p1_p2_table["CoÃ»t chaleur (EUR/MWh)"] = p1_p2_table[["P1", "P2", "P4"]].sum(axis=1)
    generator_table = p1_p2_table.merge(capex_df, on="Generateur", how="left")
    generator_table["Generateur"] = generator_table["Generateur"].replace(
        {
            "Appoint gaz": "Appoint gaz",
            "Geothermie PAC": "GÃ©othermie",
            "Solaire thermique": "Solaire thermique",
            "Mix ENR": "Mix ENR",
            "Reference 100% gaz": "RÃ©fÃ©rence 100 % gaz",
        }
    )
    generator_order = ["Appoint gaz", "GÃ©othermie", "Solaire thermique", "Mix ENR", "RÃ©fÃ©rence 100 % gaz"]
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
) -> None:
    st.markdown("### Comparaison Ã©conomique des 4 scÃ©narios")
    st.caption(
        "Lecture type Dim A / Dim B / Dim C : rÃ©fÃ©rence gaz, gÃ©othermie seule, gÃ©othermie + solaire Ã  linÃ©aire "
        "constant, puis gÃ©othermie + solaire avec linÃ©aire rÃ©duit. La recharge solaire est analysÃ©e comme un "
        "service rendu au champ de sondes, sans Ã©conomie P2 proportionnelle aux ml Ã©conomisÃ©s. Les coÃ»ts variables "
        "sont calculÃ©s sur une trajectoire physique multiannuelle nominale."
    )
    st.dataframe(display_dataframe(economic_comparison_df), width="stretch", hide_index=True)

    chart_cols = st.columns(4)
    chart_titles = {
        "Cout chaleur global (EUR/MWh)": "CoÃ»t chaleur",
        "Taux EnR global (%)": "Taux EnR",
        "Lineaire sondes (ml)": "LinÃ©aire sondes",
        "Electricite PAC (MWh/an)": "Ã‰lectricitÃ© PAC",
    }
    for col, indicator in zip(chart_cols, chart_titles):
        chart_df = economic_comparison_chart_df[economic_comparison_chart_df["Indicateur"] == indicator]
        col.altair_chart(_scenario_comparison_chart(chart_df, title=chart_titles[indicator]), width="stretch")

    st.markdown("### SynthÃ¨se P1 Ã©lectrique - gÃ©othermie avec recharge solaire")
    st.caption("Ces indicateurs correspondent au scÃ©nario principal avec recharge solaire et linÃ©aire initial.")
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("ElectricitÃ© compresseur PAC", f"{total_compressor / 1000.0:.1f} MWh/an")
    e2.metric("Forfait pompes + auxiliaires PAC", f"{total_auxiliaries / 1000.0:.1f} MWh/an")
    e3.metric("Veille/rÃ©gulation", f"{total_standby / 1000.0:.1f} MWh/an")
    e4.metric("ElectricitÃ© totale PAC", f"{total_elec / 1000.0:.1f} MWh/an")
    e5, e6, e7 = st.columns(3)
    e5.metric("COP machine", f"{mean_cop:.1f}")
    e6.metric("SPF PAC complet", f"{spf_pac_total:.1f}")
    e7.metric("SPF systÃ¨me simplifiÃ©", f"{spf_system:.1f}")

    st.markdown("### Valeur Ã©conomique de la recharge solaire")
    if not bool(recharge_value["applicable"]):
        st.info("Recharge solaire non applicable : aucune Ã©nergie solaire injectÃ©e au BTES.")
    elif str(recharge_value["status"]) == "desactive":
        st.info("Optimisation par recharge solaire non lancÃ©e.")
    elif str(recharge_value["status"]) == "non determine":
        st.warning("Gain de linÃ©aire non dÃ©terminÃ© : le solveur n'a pas trouvÃ© de rÃ©duction Ã©quivalente robuste.")

    st.caption(
        "`CoÃ»t annuel solaire recharge` = annuitÃ© de la part de CAPEX solaire affectÃ©e Ã  la recharge "
        "+ P2 solaire recharge + P4 solaire recharge. `Bilan net recharge` = gains annuels de recharge "
        "(Ã©conomie CAPEX sondes nette annualisÃ©e + Ã©conomie Ã©lectricitÃ© PAC) - coÃ»t annuel solaire recharge. "
        "L'Ã©conomie nette tient compte de la baisse d'aide ADEME quand le CAPEX sondes diminue."
    )
    st.dataframe(display_dataframe(_recharge_value_table(recharge_value)), width="stretch", hide_index=True)
    st.caption("Aucune Ã©conomie de P2 n'est appliquÃ©e au linÃ©aire de sondes Ã©conomisÃ©.")

    st.markdown("### DÃ©tail Ã©conomique par gÃ©nÃ©rateur")
    st.dataframe(display_dataframe(_generator_economic_table(heat_costs)), width="stretch", hide_index=True)
    st.altair_chart(_heat_cost_vector_chart(heat_costs["cost_bars"]), width="stretch")

    st.markdown("### Trajectoire annuelle utilisÃ©e pour l'Ã©conomie")
    st.caption(
        "Si l'horizon Ã©conomique dÃ©passe les annÃ©es simulÃ©es, la derniÃ¨re annÃ©e simulÃ©e est rÃ©pÃ©tÃ©e comme annÃ©e stabilisÃ©e."
    )
    st.dataframe(display_dataframe(economic_trajectory_df), width="stretch", hide_index=True)

