from __future__ import annotations

import altair as alt
import pandas as pd


def month_order(months: list[str]) -> dict[str, int]:
    return {m: idx + 1 for idx, m in enumerate(months)}


def month_axis(months: list[str]) -> alt.Axis:
    labels = ",".join(f"'{m}'" for m in months)
    return alt.Axis(
        values=list(range(1, 13)),
        labelExpr=f"[{labels}][datum.value-1]",
        title="Mois",
    )


def month_x_encoding(months: list[str]) -> alt.X:
    return alt.X(
        "month_order:Q",
        scale=alt.Scale(domain=[0.5, 12.5]),
        axis=month_axis(months),
    )


def build_besoins_production_chart(detail_df: pd.DataFrame, months: list[str]) -> alt.Chart:
    order = month_order(months)
    month_x = month_x_encoding(months)
    chart_monthly = detail_df[detail_df["month"].isin(months)][
        ["month", "besoin_prod_kwh_j", "pertes_boucle_kwh_j", "prod_solaire_kwh_j"]
    ].copy()
    chart_monthly = chart_monthly.rename(
        columns={
            "month": "Mois",
            "besoin_prod_kwh_j": "Besoins ECS",
            "pertes_boucle_kwh_j": "Besoins bouclage",
            "prod_solaire_kwh_j": "Production solaire",
        }
    )
    chart_monthly["month_order"] = chart_monthly["Mois"].map(order)
    chart_long = chart_monthly.melt(
        id_vars=["Mois", "month_order", "Production solaire"],
        value_vars=["Besoins ECS", "Besoins bouclage"],
        var_name="Poste",
        value_name="kWh/j",
    )
    chart_long["OrdrePoste"] = chart_long["Poste"].map({"Besoins ECS": 0, "Besoins bouclage": 1})
    bars = alt.Chart(chart_long).mark_bar(size=26).encode(
        x=month_x,
        y=alt.Y("kWh/j:Q", title="kWh/jour"),
        color=alt.Color(
            "Poste:N",
            scale=alt.Scale(domain=["Besoins ECS", "Besoins bouclage"], range=["#4C78A8", "#F58518"]),
            legend=alt.Legend(title=None),
        ),
        order=alt.Order("OrdrePoste:Q", sort="ascending"),
        tooltip=["Mois:N", "Poste:N", alt.Tooltip("kWh/j:Q", format=".2f")],
    )
    line = alt.Chart(chart_monthly).mark_line(strokeWidth=3, color="#FFC107").encode(
        x=month_x,
        y=alt.Y("Production solaire:Q"),
        tooltip=["Mois:N", alt.Tooltip("Production solaire:Q", format=".2f")],
    )
    points = alt.Chart(chart_monthly).mark_point(size=70, color="#111111").encode(
        x=month_x,
        y=alt.Y("Production solaire:Q"),
        tooltip=["Mois:N", alt.Tooltip("Production solaire:Q", format=".2f")],
    )
    return (bars + line + points).resolve_scale(y="shared")


def build_couverture_chart(detail_df: pd.DataFrame, months: list[str]) -> alt.Chart:
    order = month_order(months)
    month_x = month_x_encoding(months)
    chart_couv = detail_df[detail_df["month"].isin(months)][["month", "couvsol_m"]].copy()
    chart_couv["couvsol_pct"] = pd.to_numeric(chart_couv["couvsol_m"], errors="coerce").fillna(0.0) * 100.0
    chart_couv["month_order"] = chart_couv["month"].map(order)
    rule = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(strokeDash=[6, 4], color="#555555").encode(y="y:Q")
    line = alt.Chart(chart_couv).mark_line(strokeWidth=3, color="#2E86DE").encode(
        x=month_x,
        y=alt.Y("couvsol_pct:Q", title="Couverture (%)", scale=alt.Scale(domain=[0, 100])),
        tooltip=["month:N", alt.Tooltip("couvsol_pct:Q", format=".1f", title="Couverture (%)")],
    )
    points = alt.Chart(chart_couv).mark_point(size=60, color="#111111").encode(
        x=month_x,
        y=alt.Y("couvsol_pct:Q", scale=alt.Scale(domain=[0, 100])),
        tooltip=["month:N", alt.Tooltip("couvsol_pct:Q", format=".1f", title="Couverture (%)")],
    )
    return rule + line + points


def build_tsortie_dataframe(
    detail_df: pd.DataFrame,
    months: list[str],
    cp_wh_l_k: float,
    tecs_moy_c: float,
    tmax_stock_c: float,
) -> pd.DataFrame:
    order = month_order(months)
    chart_tsol = detail_df[detail_df["month"].isin(months)][
        ["month", "prod_solaire_kwh_j", "tef_c", "tecs_c", "besoin_prod_kwh_j"]
    ].copy()
    chart_tsol["month_order"] = chart_tsol["month"].map(order)

    def calc_tsortie(row: pd.Series) -> float:
        tef = float(row.get("tef_c", 0.0))
        tecs = float(row.get("tecs_c", tef))
        besoin = float(row.get("besoin_prod_kwh_j", 0.0))
        delta = tecs - tef
        if delta <= 1e-9 or besoin <= 1e-9:
            return tef
        vecs_l_j_calc = 1000.0 * besoin / (cp_wh_l_k * delta)
        if vecs_l_j_calc <= 1e-9:
            return tef
        return tef + 1000.0 * float(row.get("prod_solaire_kwh_j", 0.0)) / (cp_wh_l_k * vecs_l_j_calc)

    chart_tsol["t_sortie_solaire_c"] = chart_tsol.apply(calc_tsortie, axis=1)
    chart_tsol["Temperature ECS"] = float(tecs_moy_c)
    chart_tsol["Tmax stockage"] = float(tmax_stock_c)
    return chart_tsol


def build_tsortie_chart(chart_tsol: pd.DataFrame, months: list[str]) -> alt.Chart:
    month_x = month_x_encoding(months)
    tsol_long = chart_tsol[
        ["month", "month_order", "t_sortie_solaire_c", "Temperature ECS", "Tmax stockage"]
    ].rename(columns={"t_sortie_solaire_c": "Temperature solaire equivalente"}).melt(
        id_vars=["month", "month_order"],
        var_name="Serie",
        value_name="degC",
    )
    return alt.Chart(tsol_long).mark_line(strokeWidth=3).encode(
        x=month_x,
        y=alt.Y("degC:Q", title="Temperature (degC)"),
        color=alt.Color(
            "Serie:N",
            scale=alt.Scale(
                domain=["Temperature solaire equivalente", "Temperature ECS", "Tmax stockage"],
                range=["#E74C3C", "#2E86DE", "#555555"],
            ),
        ),
        tooltip=["month:N", "Serie:N", alt.Tooltip("degC:Q", format=".1f")],
    )


def build_rayonnement_chart(detail_df: pd.DataFrame, months: list[str]) -> alt.Chart:
    order = month_order(months)
    required_cols = ["month", "global_dispo_kwh_m2_j", "global_capteur_kwh_m2_j"]
    missing_cols = [col for col in required_cols if col not in detail_df.columns]
    if missing_cols:
        return alt.Chart(pd.DataFrame({"month_order": [], "Mois": [], "Serie": [], "irradiance_kwh_m2_j": []})).mark_line()

    chart_rad = detail_df[detail_df["month"].isin(months)][required_cols].copy()
    chart_rad["month_order"] = chart_rad["month"].map(order)
    chart_rad = chart_rad.rename(
        columns={
            "month": "Mois",
            "global_dispo_kwh_m2_j": "RDisponible",
            "global_capteur_kwh_m2_j": "Global capteur",
        }
    )
    chart_rad_long = chart_rad.melt(
        id_vars=["Mois", "month_order"],
        var_name="Serie",
        value_name="irradiance_kwh_m2_j",
    )
    chart_rad_long["irradiance_kwh_m2_j"] = pd.to_numeric(
        chart_rad_long["irradiance_kwh_m2_j"], errors="coerce"
    )
    chart_rad_long = chart_rad_long.dropna(subset=["month_order", "irradiance_kwh_m2_j"])

    base = alt.Chart(chart_rad_long).encode(
        x=month_x_encoding(months),
        y=alt.Y("irradiance_kwh_m2_j:Q", title="kWh/m2.j"),
        color=alt.Color(
            "Serie:N",
            scale=alt.Scale(domain=["RDisponible", "Global capteur"], range=["#F2B705", "#2E86DE"]),
            legend=alt.Legend(title=None),
        ),
        tooltip=["Mois:N", "Serie:N", alt.Tooltip("irradiance_kwh_m2_j:Q", title="kWh/m2.j", format=".3f")],
    )
    lines = base.mark_line(strokeWidth=3)
    points = base.mark_point(size=65, filled=True, stroke="#1f2933", strokeWidth=1)
    return lines + points


