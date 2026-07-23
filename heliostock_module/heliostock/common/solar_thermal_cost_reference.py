from __future__ import annotations

import math
from typing import Any


SOLAR_THERMAL_COST_REFERENCE_DATE = "13/01/2026"
SOLAR_THERMAL_COST_REFERENCE_N = 89
SOLAR_THERMAL_COST_REFERENCE_MEAN_EUR_M2 = 1471.0
SOLAR_THERMAL_COST_REFERENCE_SIGMA_EUR_M2 = 524.0
SOLAR_THERMAL_COST_REFERENCE_MEDIAN_EUR_M2 = 1404.0
SOLAR_THERMAL_COST_REFERENCE_MIN_EUR_M2 = 546.0
SOLAR_THERMAL_COST_REFERENCE_MAX_EUR_M2 = 3513.0
SOLAR_THERMAL_COST_REFERENCE_Q1_EUR_M2 = 1119.0
SOLAR_THERMAL_COST_REFERENCE_Q3_EUR_M2 = 1717.0

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
    bin_centers = [500 + 150 * index for index in range(21)]
    histogram_density = [_normal_density(center, mean, sigma) for center in bin_centers]
    curve_x = [450 + 25 * index for index in range(129)]
    curve_y = [_normal_density(x, mean, sigma) for x in curve_x]

    fig = go_module.Figure()
    fig.add_trace(
        go_module.Bar(
            x=bin_centers,
            y=histogram_density,
            width=120,
            name="Histogramme indicatif des coûts",
            marker_color="#b7d7b5",
            marker_line_color="#386641",
            marker_line_width=1,
            opacity=0.78,
            hovertemplate="Coût : %{x:.0f} €HT/m²<br>Densité indicative : %{y:.5f}<extra></extra>",
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
        (mean - sigma, "μ - σ<br>947 €HT/m²", "#7bc96f", "dash"),
        (mean, "μ<br>1 471 €HT/m²", "#087a1e", "dash"),
        (mean + sigma, "μ + σ<br>1 995 €HT/m²", "#7bc96f", "dash"),
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
            font={"color": "#166534", "size": 12},
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

    stats_text = (
        f"<b>Statistiques (N = {SOLAR_THERMAL_COST_REFERENCE_N})</b><br>"
        f"Moyenne : {mean:.0f} €HT/m²<br>"
        f"Écart-type : {sigma:.0f} €HT/m²<br>"
        f"Médiane : {SOLAR_THERMAL_COST_REFERENCE_MEDIAN_EUR_M2:.0f} €HT/m²<br>"
        f"Min : {SOLAR_THERMAL_COST_REFERENCE_MIN_EUR_M2:.0f} €HT/m²<br>"
        f"Max : {SOLAR_THERMAL_COST_REFERENCE_MAX_EUR_M2:.0f} €HT/m²<br>"
        f"Q1 : {SOLAR_THERMAL_COST_REFERENCE_Q1_EUR_M2:.0f} €HT/m²<br>"
        f"Q3 : {SOLAR_THERMAL_COST_REFERENCE_Q3_EUR_M2:.0f} €HT/m²"
    )
    fig.add_annotation(
        x=0.78,
        y=0.73,
        xref="paper",
        yref="paper",
        text=stats_text,
        align="left",
        showarrow=False,
        bgcolor="rgba(255, 255, 255, 0.92)",
        bordercolor="#cbd5e1",
        borderwidth=1,
        font={"color": "#1f2937", "size": 12},
    )

    fig.update_layout(
        title=f"Coûts des travaux de nouvelles installations solaires thermiques en €HT/m² - {SOLAR_THERMAL_COST_REFERENCE_DATE}",
        height=430,
        margin={"l": 20, "r": 20, "t": 70, "b": 55},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
    )
    fig.update_xaxes(
        title="Coût travaux (€HT/m² capteurs)",
        range=[380, 3650],
        dtick=500,
        ticksuffix=" €HT/m²",
        showgrid=True,
        gridcolor="#e5e7eb",
    )
    fig.update_yaxes(title="Densité", showgrid=True, gridcolor="#e5e7eb")
    return fig
