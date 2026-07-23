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
    bin_count = 15
    x_min = SOLAR_THERMAL_COST_REFERENCE_MIN_EUR_M2 - 100.0
    x_max = SOLAR_THERMAL_COST_REFERENCE_MAX_EUR_M2 + 100.0
    bin_width = (x_max - x_min) / bin_count
    histogram_counts = [0 for _ in range(bin_count)]
    for cost in costs:
        index = min(bin_count - 1, max(0, int((cost - x_min) / bin_width)))
        histogram_counts[index] += 1
    curve_x = [
        x_min + index * ((x_max - x_min) / 499.0)
        for index in range(500)
    ]
    curve_y = [
        _normal_density(x, mean, sigma) * SOLAR_THERMAL_COST_REFERENCE_N * bin_width
        for x in curve_x
    ]
    y_max = max(max(histogram_counts), max(curve_y), 1.0)

    fig = go_module.Figure()
    fig.add_trace(
        go_module.Histogram(
            x=costs,
            xbins={"start": x_min, "end": x_max, "size": bin_width},
            name="Nombre de devis",
            marker_color="#b7d7b5",
            marker_line_color="#386641",
            marker_line_width=1,
            opacity=0.62,
            hovertemplate="Coût : %{x:.0f} €HT/m²<br>Nombre de devis : %{y}<extra></extra>",
        )
    )
    fig.add_trace(
        go_module.Scatter(
            x=curve_x,
            y=curve_y,
            mode="lines",
            name="Tendance statistique",
            line={"color": "#087a1e", "width": 3},
            hovertemplate="Coût : %{x:.0f} €HT/m²<br>Nombre estimé : %{y:.1f}<extra></extra>",
        )
    )

    for value, color, dash, line_width in [
        (mean - sigma, "#7bc96f", "dash", 1),
        (mean, "#087a1e", "dash", 2),
        (mean + sigma, "#7bc96f", "dash", 1),
    ]:
        fig.add_vline(x=value, line_color=color, line_dash=dash, line_width=line_width)
    fig.add_annotation(
        x=mean,
        y=y_max * 1.05,
        text=f"Moyenne : {mean:.0f} €HT/m²",
        showarrow=False,
        bgcolor="rgba(246, 252, 246, 0.96)",
        bordercolor="#087a1e",
        borderwidth=1,
        font={"color": "#166534", "size": 11},
    )

    if selected_cost_eur_m2 is not None and selected_cost_eur_m2 > 0:
        selected_cost = float(selected_cost_eur_m2)
        fig.add_vline(
            x=selected_cost,
            line_color="#e9473d",
            line_dash="dot",
            line_width=3,
        )
        fig.add_annotation(
            x=selected_cost,
            y=y_max * 0.88,
            text=f"Valeur saisie : {selected_cost:.0f} €HT/m²",
            showarrow=True,
            arrowhead=2,
            ax=36,
            ay=-30,
            bgcolor="rgba(255, 255, 255, 0.94)",
            bordercolor="#e9473d",
            borderwidth=1,
            font={"color": "#991b1b", "size": 11},
        )

    fig.update_layout(
        title=(
            "Référence coût travaux solaire thermique"
            f"<br><sup>Échantillon N = {SOLAR_THERMAL_COST_REFERENCE_N} - {SOLAR_THERMAL_COST_REFERENCE_DATE}</sup>"
        ),
        height=530,
        margin={"l": 24, "r": 20, "t": 82, "b": 88},
        legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "center", "x": 0.5},
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
    fig.update_yaxes(title="Nombre de devis", range=[0, y_max * 1.18], dtick=2, showgrid=True, gridcolor="#e5e7eb")
    return fig
