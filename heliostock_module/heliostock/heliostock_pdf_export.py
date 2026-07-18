from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from .scenario_outputs import ScenarioResult


SCENARIOS = [
    ("A - Géothermie seule", "Geothermie seule"),
    ("B - Géothermie avec recharge solaire", "Geothermie + solaire meme sondes"),
    ("C - Recharge solaire et sondes réduites", "Geothermie + solaire sondes reduites"),
]


def _fmt_number(value: Any, digits: int = 0, suffix: str = "") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n.d."
    if pd.isna(numeric):
        return "n.d."
    formatted = f"{numeric:,.{digits}f}".replace(",", " ")
    return f"{formatted} {suffix}".strip()


def _fmt_mwh_from_kwh(value: Any, digits: int = 0) -> str:
    try:
        return _fmt_number(float(value) / 1000.0, digits, "MWh")
    except (TypeError, ValueError):
        return "n.d."


def _row_float(row: pd.Series | None, column: str, default: float | None = None) -> float | None:
    if row is None or column not in row:
        return default
    value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
    if pd.isna(value):
        return default
    return float(value)


def _trajectory_row(df: pd.DataFrame, scenario_name: str, *, final: bool = True) -> pd.Series | None:
    if df.empty or "Scenario" not in df:
        return None
    rows = df[df["Scenario"].astype(str) == scenario_name]
    if rows.empty:
        return None
    if "Annee" in rows:
        rows = rows.sort_values("Annee")
    return rows.iloc[-1 if final else 0]


def _economic_row(df: pd.DataFrame, scenario_name: str) -> pd.Series | None:
    if df.empty or "Scenario" not in df:
        return None
    rows = df[df["Scenario"].astype(str) == scenario_name]
    return None if rows.empty else rows.iloc[0]


def _draw_header(canvas, *, title: str, subtitle: str, width: float, height: float) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(34, height - 38, title)
    canvas.setFont("Helvetica", 9)
    canvas.setFillColorRGB(0.47, 0.49, 0.55)
    canvas.drawString(34, height - 56, subtitle)
    canvas.setStrokeColorRGB(0.88, 0.9, 0.94)
    canvas.line(34, height - 68, width - 34, height - 68)


def _draw_footer(canvas, *, page_number: int, width: float) -> None:
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.55, 0.57, 0.64)
    canvas.drawRightString(width - 34, 24, f"Page {page_number}")


def _draw_section_title(canvas, title: str, *, x: float, y: float) -> float:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(x, y, title)
    return y - 18


def _draw_kpi_grid(canvas, metrics: list[tuple[str, str]], *, x: float, y: float, width: float, cols: int = 4) -> float:
    if not metrics:
        return y
    gap = 8
    card_w = (width - gap * (cols - 1)) / cols
    card_h = 46
    for idx, (label, value) in enumerate(metrics):
        col = idx % cols
        row = idx // cols
        cx = x + col * (card_w + gap)
        cy = y - row * (card_h + 8)
        canvas.setFillColorRGB(0.97, 0.98, 1.0)
        canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
        canvas.roundRect(cx, cy - card_h, card_w, card_h, 6, fill=1, stroke=1)
        canvas.setFillColorRGB(0.45, 0.47, 0.53)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(cx + 8, cy - 13, str(label)[:33])
        canvas.setFillColorRGB(0.18, 0.19, 0.25)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(cx + 8, cy - 34, str(value)[:25])
    rows = (len(metrics) + cols - 1) // cols
    return y - rows * (card_h + 8)


def _scenario_metrics(scenario: ScenarioResult, scenario_name: str) -> list[tuple[str, str]]:
    final_row = _trajectory_row(scenario.economic_trajectory_df, scenario_name, final=True)
    first_row = _trajectory_row(scenario.economic_trajectory_df, scenario_name, final=False)
    econ_row = _economic_row(scenario.economic_comparison_df, scenario_name)
    hours_gmi = (_row_float(final_row, "Heures sous Tmin GMI", 0.0) or 0.0) + (
        _row_float(final_row, "Heures sur Tmax GMI", 0.0) or 0.0
    )
    return [
        ("Coût chaleur", _fmt_number(_row_float(econ_row, "Cout chaleur global (EUR/MWh)"), 0, "EUR/MWh")),
        ("Taux EnR global", _fmt_number(_row_float(final_row, "Taux EnR (%)"), 0, "%")),
        ("Linéaire sondes", _fmt_number(_row_float(econ_row, "Lineaire sondes (ml)"), 0, "ml")),
        ("COP machine PAC", _fmt_number(_row_float(final_row, "COP moyen"), 1)),
        ("SPF PAC avec auxiliaires", _fmt_number(_row_float(final_row, "SPF PAC complet"), 1)),
        ("Chaleur PAC BT", _fmt_number(_row_float(final_row, "Chaleur PAC BT (MWh)"), 0, "MWh")),
        ("Couverture PAC BT", _fmt_number(_row_float(final_row, "Couverture PAC BT (%)"), 0, "%")),
        ("Électricité PAC", _fmt_number(_row_float(final_row, "Electricite PAC (MWh)"), 0, "MWh/an")),
        ("Appoint gaz année 1", _fmt_number(_row_float(first_row, "Appoint gaz total (MWh)"), 0, "MWh")),
        ("Appoint gaz année finale", _fmt_number(_row_float(final_row, "Appoint gaz total (MWh)"), 0, "MWh")),
        ("T source min finale", _fmt_number(_row_float(final_row, "T_source_PAC_min (C)"), 1, "°C")),
        ("Heures hors GMI", _fmt_number(hours_gmi, 0, "h")),
        ("Heures limite source", _fmt_number(_row_float(final_row, "Heures limite source"), 0, "h")),
        ("q extraction max", _fmt_number(_row_float(final_row, "q_extraction_W_m_max"), 0, "W/m")),
        ("q injection max", _fmt_number(_row_float(final_row, "q_injection_W_m_max"), 0, "W/m")),
    ]


def _draw_economic_table(canvas, scenario: ScenarioResult, *, x: float, y: float, width: float) -> float:
    if scenario.economic_comparison_df.empty:
        return y
    cols = [
        ("Scenario", "Scénario", 180),
        ("Cout chaleur global (EUR/MWh)", "Coût chaleur", 90),
        ("CAPEX net (EUR)", "CAPEX net", 90),
        ("P1 cumule (EUR)", "P1 cumulé", 80),
        ("P2 cumule (EUR)", "P2 cumulé", 80),
        ("Appoint gaz cumule (MWh)", "Gaz cumulé", 80),
    ]
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    cx = x
    for _, label, col_w in cols:
        canvas.drawString(cx, y, label)
        cx += col_w
    y -= 12
    canvas.setFont("Helvetica", 7)
    for _, row in scenario.economic_comparison_df.head(8).iterrows():
        cx = x
        for source, _, col_w in cols:
            value = row.get(source, "")
            text = str(value)[:32] if source == "Scenario" else _fmt_number(value, 0)
            canvas.drawString(cx, y, text)
            cx += col_w
        y -= 11
    return y


def build_heliostock_overview_pdf(
    scenario: ScenarioResult,
    *,
    calculation_id: str = "",
    calculated_at: str = "",
) -> bytes:
    """Build a compact PDF export from the already-computed HelioStock result."""

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas as pdf_canvas

    buffer = BytesIO()
    page_width, page_height = landscape(A4)
    canvas = pdf_canvas.Canvas(buffer, pagesize=(page_width, page_height), pageCompression=0)
    subtitle = (
        f"Calcul {calculation_id} - {calculated_at} - année affichée {scenario.simulation_year_displayed} "
        f"sur {scenario.simulation_years_total} ans"
    )

    _draw_header(canvas, title="HelioStock - synthèse du calcul", subtitle=subtitle, width=page_width, height=page_height)
    y = page_height - 92
    storage_m3 = scenario.config.collector.area_m2 * scenario.config.collector.daily_buffer_l_per_m2 / 1000.0
    y = _draw_section_title(canvas, "Données d'entrée principales", x=34, y=y)
    y = _draw_kpi_grid(
        canvas,
        [
            ("Surface solaire", _fmt_number(scenario.config.collector.area_m2, 0, "m²")),
            ("Volume stockage solaire", _fmt_number(storage_m3, 0, "m³")),
            ("Puissance PAC géothermie", _fmt_number(scenario.config.heat_pump.nominal_power_kw, 0, "kW")),
            ("Linéaire sondes", _fmt_number(scenario.full_borefield_length_m, 0, "ml")),
        ],
        x=34,
        y=y,
        width=page_width - 68,
    )
    y -= 6
    y = _draw_section_title(canvas, "Besoins et production solaire", x=34, y=y)
    y = _draw_kpi_grid(
        canvas,
        [
            ("Besoin total", _fmt_mwh_from_kwh(scenario.total_ht_kwh + scenario.total_bt_kwh)),
            ("Besoin haute température", _fmt_mwh_from_kwh(scenario.total_ht_kwh)),
            ("Besoin basse température", _fmt_mwh_from_kwh(scenario.total_bt_kwh)),
            ("Production solaire totale", _fmt_mwh_from_kwh(scenario.total_preheat_ht_kwh + scenario.total_to_btes_kwh)),
            ("Production solaire ECS", _fmt_mwh_from_kwh(scenario.total_preheat_ht_kwh)),
            ("Production solaire injectée BTES", _fmt_mwh_from_kwh(scenario.total_to_btes_kwh)),
            ("Couverture solaire HT", _fmt_number(scenario.annual_ht_solar_coverage * 100.0, 0, "%")),
            ("Productivité solaire valorisée", _fmt_number(scenario.solar_productivity_valued_kwh_m2_year, 0, "kWh/m².an")),
        ],
        x=34,
        y=y,
        width=page_width - 68,
    )
    _draw_footer(canvas, page_number=1, width=page_width)
    canvas.showPage()

    _draw_header(canvas, title="HelioStock - scénarios techniques", subtitle=subtitle, width=page_width, height=page_height)
    y = page_height - 92
    for label, scenario_name in SCENARIOS:
        y = _draw_section_title(canvas, label, x=34, y=y)
        y = _draw_kpi_grid(canvas, _scenario_metrics(scenario, scenario_name), x=34, y=y, width=page_width - 68)
        y -= 4
        if y < 120:
            _draw_footer(canvas, page_number=2, width=page_width)
            canvas.showPage()
            _draw_header(canvas, title="HelioStock - scénarios techniques", subtitle=subtitle, width=page_width, height=page_height)
            y = page_height - 92
    _draw_footer(canvas, page_number=2, width=page_width)
    canvas.showPage()

    _draw_header(canvas, title="HelioStock - économie multiannuelle", subtitle=subtitle, width=page_width, height=page_height)
    y = page_height - 92
    y = _draw_section_title(canvas, "Comparaison économique des scénarios", x=34, y=y)
    y = _draw_economic_table(canvas, scenario, x=34, y=y, width=page_width - 68)
    y -= 16
    savings = scenario.savings or {}
    y = _draw_section_title(canvas, "Statut économie de sondes", x=34, y=y)
    _draw_kpi_grid(
        canvas,
        [
            ("Calcul physique C", "réalisé" if bool(savings.get("simulated", False)) else "non lancé"),
            ("Réduction validée", "oui" if bool(savings.get("found", False)) else "non"),
            ("Linéaire testé", _fmt_number(savings.get("candidate_length_m"), 0, "ml")),
            ("Gain retenu", _fmt_number(savings.get("saved_length_m", 0.0), 0, "ml")),
        ],
        x=34,
        y=y,
        width=page_width - 68,
    )
    _draw_footer(canvas, page_number=3, width=page_width)
    canvas.save()
    return buffer.getvalue()
