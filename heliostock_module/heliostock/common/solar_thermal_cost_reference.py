from __future__ import annotations

import math
import statistics
from typing import Any


SOLAR_THERMAL_COST_REFERENCE_DATE = "13/01/2026"
SOLAR_THERMAL_COSTS_EUR_M2 = (
    2373.0,
    1512.0,
    1262.0,
    1010.0,
    1666.0,
    2100.0,
    1725.0,
    1481.0,
    1343.0,
    1175.0,
    1746.0,
    1357.0,
    1702.0,
    1559.0,
    1975.0,
    1982.0,
    1487.0,
    1119.492337,
    1372.217391,
    3513.0,
    1374.0,
    1606.0,
    1234.0,
    1000.0,
    1069.0,
    2492.0,
    3324.0,
    1699.0,
    1654.0,
    1341.0,
    1511.0,
    1609.0,
    1269.0,
    1951.0,
    1275.0,
    2485.0,
    1582.0,
    1782.0,
    1773.0,
    1721.0,
    1192.0,
    1179.0,
    546.0,
    964.0,
    1267.0,
    1142.0,
    900.0,
    886.0,
    1678.0,
    979.0,
    989.0,
    750.0,
    912.0,
    1531.0,
    1320.0,
    1404.0,
    2478.0,
    2198.0,
    1440.0,
    1245.0,
    1665.0,
    1322.0,
    2504.0,
    2480.0,
    1539.0,
    1124.0,
    1808.0,
    2121.0,
    1259.0,
    735.0,
    1021.0,
    1472.0,
    1581.0,
    1980.0,
    1895.0,
    1266.0,
    1683.0,
    1206.0,
    1791.0,
    1535.0,
    1516.0,
    1717.0,
    1245.0,
    2467.0,
    1636.0,
    1647.0,
    1475.0,
    2004.0,
    1129.0,
)


def _percentile(values: tuple[float, ...], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


SOLAR_THERMAL_COST_REFERENCE_N = len(SOLAR_THERMAL_COSTS_EUR_M2)
SOLAR_THERMAL_COST_REFERENCE_MEAN_EUR_M2 = statistics.fmean(SOLAR_THERMAL_COSTS_EUR_M2)
SOLAR_THERMAL_COST_REFERENCE_SIGMA_EUR_M2 = statistics.pstdev(SOLAR_THERMAL_COSTS_EUR_M2)
SOLAR_THERMAL_COST_REFERENCE_MEDIAN_EUR_M2 = statistics.median(SOLAR_THERMAL_COSTS_EUR_M2)
SOLAR_THERMAL_COST_REFERENCE_MIN_EUR_M2 = min(SOLAR_THERMAL_COSTS_EUR_M2)
SOLAR_THERMAL_COST_REFERENCE_MAX_EUR_M2 = max(SOLAR_THERMAL_COSTS_EUR_M2)
SOLAR_THERMAL_COST_REFERENCE_Q1_EUR_M2 = _percentile(SOLAR_THERMAL_COSTS_EUR_M2, 25.0)
SOLAR_THERMAL_COST_REFERENCE_Q3_EUR_M2 = _percentile(SOLAR_THERMAL_COSTS_EUR_M2, 75.0)

SOLAR_THERMAL_COST_REFERENCE_NOTE = (
    "Repère indicatif pour des installations solaires thermiques neuves : moyenne 1 471 €HT/m², "
    "écart-type 524 €HT/m², médiane 1 404 €HT/m², échantillon N = 89 au 13/01/2026."
)


def _normal_density(x: float, mean: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    return math.exp(-0.5 * ((x - mean) / sigma) ** 2) / (sigma * math.sqrt(2.0 * math.pi))


def build_solar_thermal_cost_reference_plotly(go_module: Any, *, selected_cost_eur_m2: float | None = None):
    """Build a Plotly reference chart for solar thermal installation costs."""

    if go_module is None:
        return None

    mean = SOLAR_THERMAL_COST_REFERENCE_MEAN_EUR_M2
    sigma = SOLAR_THERMAL_COST_REFERENCE_SIGMA_EUR_M2
    costs = list(SOLAR_THERMAL_COSTS_EUR_M2)
    curve_x = [
        SOLAR_THERMAL_COST_REFERENCE_MIN_EUR_M2 - 100.0
        + index
        * (
            (SOLAR_THERMAL_COST_REFERENCE_MAX_EUR_M2 - SOLAR_THERMAL_COST_REFERENCE_MIN_EUR_M2 + 200.0)
            / 499.0
        )
        for index in range(500)
    ]
    curve_y = [_normal_density(x, mean, sigma) for x in curve_x]

    fig = go_module.Figure()
    fig.add_trace(
        go_module.Histogram(
            x=costs,
            nbinsx=15,
            histnorm="probability density",
            name="Histogramme des coûts (€/m²)",
            marker_color="#b7d7b5",
            marker_line_color="#386641",
            marker_line_width=1,
            opacity=0.62,
            hovertemplate="Coût : %{x:.0f} €HT/m²<br>Densité : %{y:.5f}<extra></extra>",
        )
    )
    fig.add_trace(
        go_module.Scatter(
            x=curve_x,
            y=curve_y,
            mode="lines",
            name=f"Courbe de Gauss (N = {SOLAR_THERMAL_COST_REFERENCE_N})",
            line={"color": "#087a1e", "width": 3},
            hovertemplate="Coût : %{x:.0f} €HT/m²<br>Densité : %{y:.5f}<extra></extra>",
        )
    )

    markers = [
        (mean - sigma, f"μ - σ<br>{mean - sigma:.0f}", "#7bc96f", "dash"),
        (mean, f"μ<br>{mean:.0f}", "#087a1e", "dash"),
        (mean + sigma, f"μ + σ<br>{mean + sigma:.0f}", "#7bc96f", "dash"),
    ]
    for value, label, color, dash in markers:
        fig.add_vline(x=value, line_color=color, line_dash=dash, line_width=2)
        fig.add_annotation(
            x=value,
            y=max(curve_y) * 1.16,
            text=label,
            showarrow=False,
            bgcolor="rgba(246, 252, 246, 0.96)",
            bordercolor=color,
            borderwidth=1,
            font={"color": "#166534", "size": 10},
        )

    if selected_cost_eur_m2 is not None and selected_cost_eur_m2 > 0:
        fig.add_vline(
            x=float(selected_cost_eur_m2),
            line_color="#e9473d",
            line_dash="dot",
            line_width=3,
            annotation_text=f"Valeur saisie : {float(selected_cost_eur_m2):.0f} €HT/m²",
            annotation_position="bottom right",
        )

    fig.update_layout(
        title=f"Coûts des travaux de nouvelles installations solaires thermiques - {SOLAR_THERMAL_COST_REFERENCE_DATE}",
        height=530,
        margin={"l": 24, "r": 20, "t": 76, "b": 64},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
        bargap=0.08,
    )
    fig.update_xaxes(
        title="Coût travaux (€HT/m² capteurs)",
        range=[380, 3650],
        dtick=500,
        showgrid=True,
        gridcolor="#e5e7eb",
    )
    fig.update_yaxes(title="Densité", showgrid=True, gridcolor="#e5e7eb")
    return fig
