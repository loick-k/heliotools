from __future__ import annotations

from io import BytesIO
import math
from typing import Any

import pandas as pd
from reportlab.lib.utils import ImageReader

from .architectural_patrimony_service import CATEGORY_CONFIG
from .architectural_static_map import StaticMapError, render_static_map
from .common.pdf import draw_report_footer, draw_report_header, safe_pdf_text as _safe_text
from .gas_reference import gas_reference_context_label
from .scenario_outputs import ScenarioResult


SCENARIOS = [
    ("A - Géothermie seule", "Geothermie seule"),
    ("B - Géothermie avec recharge solaire", "Geothermie + solaire meme sondes"),
    ("C - Recharge solaire et sondes réduites", "Geothermie + solaire sondes reduites"),
]

SCENARIO_COLORS = {
    "A - Géothermie seule": (0.00, 0.38, 0.72),
    "B - Géothermie avec recharge solaire": (0.40, 0.72, 0.96),
    "C - Recharge solaire et linéaire réduit": (0.95, 0.18, 0.18),
    "C - Recharge solaire et sondes réduites": (0.95, 0.18, 0.18),
}

ENERGY_COLORS = {
    "Solaire thermique": (0.98, 0.80, 0.08),
    "Injection solaire BTES": (0.98, 0.45, 0.08),
    "Géothermie PAC": (0.09, 0.64, 0.29),
    "Appoint gaz": (0.56, 0.61, 0.67),
}


def _fmt_number(value: Any, digits: int = 0, suffix: str = "") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n.d."
    if pd.isna(numeric):
        return "n.d."
    formatted = f"{numeric:,.{digits}f}".replace(",", " ")
    return f"{formatted} {suffix}".strip()


def _fmt_payback_years(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "Non atteint"
    if pd.isna(numeric) or not math.isfinite(numeric):
        return "Non atteint"
    return _fmt_number(numeric, 1, "ans")


def _fmt_mwh_from_kwh(value: Any, digits: int = 0) -> str:
    try:
        return _fmt_number(float(value) / 1000.0, digits, "MWh")
    except (TypeError, ValueError):
        return "n.d."


def _solar_buffer_at_max_hours(scenario: ScenarioResult) -> int:
    hourly_df = scenario.hourly_df
    if not isinstance(hourly_df, pd.DataFrame) or hourly_df.empty:
        return 0
    if "solar_ht_buffer_at_max" in hourly_df:
        return int(pd.to_numeric(hourly_df["solar_ht_buffer_at_max"], errors="coerce").fillna(0.0).sum())
    if "solar_ht_buffer_temp_end_c" not in hourly_df:
        return 0
    max_temp_c = scenario.config.collector.daily_buffer_max_temp_c
    temperatures = pd.to_numeric(hourly_df["solar_ht_buffer_temp_end_c"], errors="coerce")
    return int((temperatures >= max_temp_c - 1e-6).sum())


def _solar_buffer_at_max_episodes(scenario: ScenarioResult) -> int:
    hourly_df = scenario.hourly_df
    if not isinstance(hourly_df, pd.DataFrame) or hourly_df.empty:
        return 0
    if "solar_ht_buffer_at_max" in hourly_df:
        at_max = pd.to_numeric(hourly_df["solar_ht_buffer_at_max"], errors="coerce").fillna(0.0).astype(bool)
    elif "solar_ht_buffer_temp_end_c" in hourly_df:
        max_temp_c = scenario.config.collector.daily_buffer_max_temp_c
        temperatures = pd.to_numeric(hourly_df["solar_ht_buffer_temp_end_c"], errors="coerce")
        at_max = temperatures >= max_temp_c - 1e-6
    else:
        return 0
    previous = at_max.shift(1, fill_value=False)
    return int((at_max & ~previous).sum())


def _sum_hourly_column_kwh(scenario: ScenarioResult, column: str) -> float:
    hourly_df = scenario.hourly_df
    if not isinstance(hourly_df, pd.DataFrame) or hourly_df.empty or column not in hourly_df:
        return 0.0
    return float(pd.to_numeric(hourly_df[column], errors="coerce").fillna(0.0).sum())


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def _solar_buffer_loss_kwh(scenario: ScenarioResult) -> float:
    direct = getattr(scenario, "solar_buffer_loss_kwh", None)
    try:
        if direct is not None and float(direct) > 0.0:
            return float(direct)
    except (TypeError, ValueError):
        pass
    return _sum_hourly_column_kwh(scenario, "solar_ht_buffer_loss_kwh")


def _storage_value_for_pdf(scenario: ScenarioResult, *, has_geothermal: bool) -> str:
    volume_l = scenario.config.collector.area_m2 * scenario.config.collector.daily_buffer_l_per_m2
    if has_geothermal:
        return _fmt_number(volume_l / 1000.0, 0, "m3")
    return _fmt_number(volume_l, 0, "L")


def _monthly_with_solar_losses(scenario: ScenarioResult) -> pd.DataFrame:
    month_df = scenario.hourly_by_month_df.copy()
    if "month" not in month_df.columns and "Mois" in month_df.columns:
        month_lookup = {
            "jan": 1,
            "janvier": 1,
            "feb": 2,
            "fév": 2,
            "fev": 2,
            "février": 2,
            "fevrier": 2,
            "mar": 3,
            "mars": 3,
            "apr": 4,
            "avr": 4,
            "avril": 4,
            "may": 5,
            "mai": 5,
            "jun": 6,
            "juin": 6,
            "jul": 7,
            "juil": 7,
            "juillet": 7,
            "aug": 8,
            "aoû": 8,
            "aou": 8,
            "août": 8,
            "aout": 8,
            "sep": 9,
            "sept": 9,
            "septembre": 9,
            "oct": 10,
            "octobre": 10,
            "nov": 11,
            "novembre": 11,
            "dec": 12,
            "déc": 12,
            "décembre": 12,
            "decembre": 12,
        }
        month_df["month"] = (
            month_df["Mois"]
            .astype(str)
            .str.strip()
            .str.lower()
            .map(month_lookup)
        )
    if month_df.empty:
        hourly_df = scenario.hourly_df
        if not isinstance(hourly_df, pd.DataFrame) or hourly_df.empty or "month" not in hourly_df.columns:
            return month_df
        month_df = (
            pd.DataFrame({"month": list(range(1, 13))})
            .assign(Mois=lambda df: df["month"].map({i: name for i, name in enumerate(
                ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            )}))
        )
    if "Pertes ballon solaire (MWh)" not in month_df.columns and "Pertes ballon HT (kWh)" in month_df.columns:
        month_df["Pertes ballon solaire (MWh)"] = (
            pd.to_numeric(month_df["Pertes ballon HT (kWh)"], errors="coerce").fillna(0.0) / 1000.0
        )
    if "Pertes ballon solaire (MWh)" not in month_df.columns:
        hourly_df = scenario.hourly_df
        loss_col = _first_existing_column(
            hourly_df if isinstance(hourly_df, pd.DataFrame) else pd.DataFrame(),
            ("solar_ht_buffer_loss_kwh", "Q_losses_tank_kWh"),
        )
        if isinstance(hourly_df, pd.DataFrame) and not hourly_df.empty and loss_col and "month" in hourly_df.columns:
            losses = (
                hourly_df.assign(
                    month=pd.to_numeric(hourly_df["month"], errors="coerce"),
                    _loss_kwh=pd.to_numeric(hourly_df[loss_col], errors="coerce").fillna(0.0),
                )
                .dropna(subset=["month"])
                .groupby("month", as_index=False)["_loss_kwh"]
                .sum()
            )
            losses["month"] = losses["month"].astype(int)
            losses["Pertes ballon solaire (MWh)"] = losses["_loss_kwh"] / 1000.0
            month_df = month_df.merge(losses[["month", "Pertes ballon solaire (MWh)"]], on="month", how="left")
            month_df["Pertes ballon solaire (MWh)"] = pd.to_numeric(
                month_df["Pertes ballon solaire (MWh)"], errors="coerce"
            ).fillna(0.0)
    return month_df


def _solar_only_duration_dataframe(scenario: ScenarioResult) -> pd.DataFrame:
    hourly_df = scenario.hourly_df
    if not isinstance(hourly_df, pd.DataFrame) or hourly_df.empty:
        return pd.DataFrame()
    backup_col = _first_existing_column(hourly_df, ("unmet_ht_kwh", "backup_ht_kwh"))
    required = {"demand_ht_kwh", "solar_ht_from_buffer_kwh"}
    if backup_col is None or not required.issubset(hourly_df.columns):
        return pd.DataFrame()
    data = pd.DataFrame(
        {
            "Besoin HT": pd.to_numeric(hourly_df["demand_ht_kwh"], errors="coerce").fillna(0.0),
            "Solaire thermique": pd.to_numeric(hourly_df["solar_ht_from_buffer_kwh"], errors="coerce").fillna(0.0),
            "Appoint gaz": pd.to_numeric(hourly_df[backup_col], errors="coerce").fillna(0.0),
        }
    ).sort_values("Besoin HT", ascending=False)
    data = data.reset_index(drop=True)
    data["Heure classee"] = data.index + 1
    return data


def _architectural_conclusion_lines(architectural_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(architectural_context, dict) or not architectural_context:
        return ["Analyse des contraintes architecturales non disponible dans ce calcul."]
    result = architectural_context.get("result")
    if not isinstance(result, dict):
        return ["Analyse des contraintes architecturales non réalisée ou non sauvegardée avec ce calcul."]
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    total = sum(int(counts.get(category, 0) or 0) for category in CATEGORY_CONFIG)
    if total <= 0:
        return ["Aucune servitude AC1, AC2 ou AC4 n'a été détectée au droit du point dans les données interrogées."]
    parts = [
        f"{category} : {int(counts.get(category, 0) or 0)}"
        for category in CATEGORY_CONFIG
        if int(counts.get(category, 0) or 0) > 0
    ]
    return [
        "Des contraintes architecturales potentielles ont été détectées au droit du point.",
        "Synthèse des objets détectés : " + ", ".join(parts) + ".",
    ]


def _draw_architectural_conclusion(
    canvas,
    architectural_context: dict[str, Any] | None,
    *,
    x: float,
    y: float,
    width: float,
) -> float:
    y = _draw_section_title(canvas, "Analyse des contraintes architecturales", x=x, y=y)
    for line in _architectural_conclusion_lines(architectural_context):
        y = _draw_note(canvas, line, x=x, y=y, width=width)
    return y


def _draw_architectural_map(
    canvas,
    architectural_context: dict[str, Any] | None,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    if not isinstance(architectural_context, dict):
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title="Carte du site")
        return
    latitude = architectural_context.get("latitude")
    longitude = architectural_context.get("longitude")
    if latitude is None or longitude is None:
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title="Carte du site")
        return
    try:
        image = render_static_map(
            latitude=float(latitude),
            longitude=float(longitude),
            result=architectural_context.get("result") if isinstance(architectural_context.get("result"), dict) else None,
            address=str(architectural_context.get("selected_address") or ""),
            zoom=16,
            width=1100,
            height=620,
        )
        image_buffer = BytesIO()
        image.save(image_buffer, format="PNG")
        image_buffer.seek(0)
        canvas.drawImage(
            ImageReader(image_buffer),
            x,
            y,
            width=width,
            height=height,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
    except (StaticMapError, ValueError, OSError) as exc:
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title="Carte du site")
        _draw_note(canvas, f"La carte n'a pas pu être générée : {exc}", x=x + 12, y=y + height / 2, width=width - 24)


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


def _capex_summary_row(scenario: ScenarioResult, generator_name: str) -> pd.Series | None:
    capex_df = scenario.heat_costs.get("capex_summary") if isinstance(scenario.heat_costs, dict) else None
    if not isinstance(capex_df, pd.DataFrame) or capex_df.empty or "Generateur" not in capex_df:
        return None
    rows = capex_df[capex_df["Generateur"].astype(str) == generator_name]
    return None if rows.empty else rows.iloc[0]


def _draw_header(canvas, *, title: str, subtitle: str, width: float, height: float) -> None:
    draw_report_header(canvas, title=title, subtitle=subtitle, width=width, height=height)


def _draw_footer(canvas, *, page_number: int, width: float) -> None:
    draw_report_footer(canvas, page_number=page_number, width=width)


def _product_title(scenario: ScenarioResult) -> str:
    if bool(getattr(scenario.config, "btes_injection_enabled", False)):
        return "HelioDyn / HelioStock"
    return "HelioDyn"


def _has_geothermal_results(scenario: ScenarioResult) -> bool:
    return bool(getattr(scenario.config, "geothermal_enabled", True)) and float(getattr(scenario, "total_bt_kwh", 0.0) or 0.0) > 1e-6


def _draw_section_title(canvas, title: str, *, x: float, y: float) -> float:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(x, y, _safe_text(title))
    return y - 18


def _draw_note(canvas, text: str, *, x: float, y: float, width: float) -> float:
    canvas.setFillColorRGB(0.48, 0.50, 0.58)
    canvas.setFont("Helvetica", 7)
    line = ""
    for word in _safe_text(text).split():
        candidate = f"{line} {word}".strip()
        if line and canvas.stringWidth(candidate, "Helvetica", 7) > width:
            canvas.drawString(x, y, line)
            y -= 10
            line = word
        else:
            line = candidate
    if line:
        canvas.drawString(x, y, line)
        y -= 10
    return y


def _gmi_conclusion_lines(gmi_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(gmi_context, dict):
        return ["Analyse de zone GMI non disponible dans ce calcul."]
    result = gmi_context.get("result")
    if not isinstance(result, dict):
        return ["Analyse de zone GMI non réalisée ou non sauvegardée avec ce calcul."]

    zone = str(result.get("zone") or result.get("status") or "").strip().lower()
    zone_label = str(result.get("zone_label") or result.get("label") or zone or "non déterminée")
    address = str(gmi_context.get("selected_address_label") or gmi_context.get("address_query") or "").strip()
    exchanger = str(gmi_context.get("exchanger_label") or "").strip()
    depth = gmi_context.get("depth_max_m")

    if zone == "vert":
        conclusion = "Conclusion GMI : zone verte selon la couche cartographique interrogée."
    elif zone == "orange":
        conclusion = "Conclusion GMI : zone orange, une vérification réglementaire et hydrogéologique renforcée est à prévoir."
    elif zone == "rouge":
        conclusion = "Conclusion GMI : zone rouge, le projet doit être interprété comme défavorable au titre du zonage cartographique GMI."
    elif zone in {"aucune_donnee", "no_data"}:
        conclusion = "Conclusion GMI : aucune donnée cartographique exploitable au point interrogé."
    else:
        conclusion = f"Conclusion GMI : statut {zone_label}."

    details = []
    if address:
        details.append(address)
    if exchanger:
        details.append(exchanger)
    if depth not in (None, ""):
        details.append(f"profondeur {depth} m")
    if details:
        conclusion = f"{conclusion} Point étudié : {' - '.join(str(item) for item in details)}."

    lines = [conclusion]
    feature_count = result.get("feature_count")
    layer_title = str(result.get("layer_title") or "").strip()
    if layer_title:
        lines.append(f"Couche cartographique utilisée : {layer_title}.")
    if feature_count not in (None, ""):
        lines.append(f"Nombre d'entités cartographiques intersectées : {feature_count}.")
    return lines


def _draw_gmi_conclusion(canvas, gmi_context: dict[str, Any] | None, *, x: float, y: float, width: float) -> float:
    y = _draw_section_title(canvas, "Conclusion analyse zone GMI", x=x, y=y)
    for line in _gmi_conclusion_lines(gmi_context):
        y = _draw_note(canvas, line, x=x, y=y, width=width)
    return y


def _numeric_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty or any(column not in df.columns for column in columns):
        return pd.DataFrame()
    out = df[columns].copy()
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.dropna()


def _nice_bounds(values: list[float]) -> tuple[float, float]:
    clean = [float(v) for v in values if pd.notna(v) and math.isfinite(float(v))]
    if not clean:
        return 0.0, 1.0
    lo = min(clean)
    hi = max(clean)
    if math.isclose(lo, hi):
        margin = max(1.0, abs(lo) * 0.1)
        return lo - margin, hi + margin
    margin = (hi - lo) * 0.08
    return lo - margin, hi + margin


def _draw_no_data(canvas, *, x: float, y: float, width: float, height: float, title: str) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x, y + height - 10, _safe_text(title))
    canvas.setFillColorRGB(0.96, 0.97, 0.99)
    canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
    canvas.roundRect(x, y, width, height - 24, 5, fill=1, stroke=1)
    canvas.setFillColorRGB(0.50, 0.52, 0.58)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(
        x + width / 2,
        y + (height - 24) / 2,
        _safe_text("Données non disponibles dans ce résultat exporté."),
    )


def _draw_line_chart(
    canvas,
    series: list[tuple[str, pd.DataFrame, str, str, tuple[float, float, float]]],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    x_label: str,
    y_label: str,
    max_points: int = 260,
) -> None:
    usable_series: list[tuple[str, pd.DataFrame, str, str, tuple[float, float, float]]] = []
    all_x: list[float] = []
    all_y: list[float] = []
    for label, df, x_col, y_col, color in series:
        data = _numeric_frame(df, [x_col, y_col])
        if data.empty:
            continue
        if len(data) > max_points:
            step = max(1, math.ceil(len(data) / max_points))
            data = data.iloc[::step].copy()
        usable_series.append((label, data, x_col, y_col, color))
        all_x.extend(data[x_col].astype(float).tolist())
        all_y.extend(data[y_col].astype(float).tolist())

    if not usable_series:
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title=title)
        return

    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x, y + height - 10, _safe_text(title))

    plot_x = x + 42
    plot_y = y + 34
    plot_w = width - 132
    plot_h = height - 66
    x_min, x_max = _nice_bounds(all_x)
    y_min, y_max = _nice_bounds(all_y)
    if x_min < 0 < x_max and min(all_x) >= 0:
        x_min = 0.0

    canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
    canvas.setLineWidth(0.6)
    for i in range(6):
        gx = plot_x + plot_w * i / 5
        gy = plot_y + plot_h * i / 5
        canvas.line(plot_x, gy, plot_x + plot_w, gy)
        canvas.line(gx, plot_y, gx, plot_y + plot_h)

    canvas.setStrokeColorRGB(0.58, 0.62, 0.70)
    canvas.line(plot_x, plot_y, plot_x, plot_y + plot_h)
    canvas.line(plot_x, plot_y, plot_x + plot_w, plot_y)

    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColorRGB(0.42, 0.45, 0.53)
    for i in range(6):
        xv = x_min + (x_max - x_min) * i / 5
        yv = y_min + (y_max - y_min) * i / 5
        canvas.drawCentredString(plot_x + plot_w * i / 5, plot_y - 10, _fmt_number(xv, 0))
        canvas.drawRightString(plot_x - 5, plot_y + plot_h * i / 5 - 2, _fmt_number(yv, 1))

    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(plot_x + plot_w / 2, y + 5, _safe_text(x_label))
    canvas.saveState()
    canvas.translate(x + 8, plot_y + plot_h / 2)
    canvas.rotate(90)
    canvas.drawCentredString(0, 0, _safe_text(y_label))
    canvas.restoreState()

    def project(px: float, py: float) -> tuple[float, float]:
        return (
            plot_x + (px - x_min) / max(1e-9, x_max - x_min) * plot_w,
            plot_y + (py - y_min) / max(1e-9, y_max - y_min) * plot_h,
        )

    legend_y = plot_y + plot_h - 6
    for label, data, x_col, y_col, color in usable_series:
        points = list(zip(data[x_col].astype(float), data[y_col].astype(float)))
        canvas.setStrokeColorRGB(*color)
        canvas.setLineWidth(1.2)
        px0, py0 = project(points[0][0], points[0][1])
        if len(points) == 1:
            canvas.setFillColorRGB(*color)
            canvas.circle(px0, py0, 2.2, fill=1, stroke=0)
        else:
            for px, py in points[1:]:
                px1, py1 = project(px, py)
                canvas.line(px0, py0, px1, py1)
                px0, py0 = px1, py1
        canvas.setFillColorRGB(*color)
        canvas.rect(plot_x + plot_w + 14, legend_y - 4, 8, 3, fill=1, stroke=0)
        canvas.setFillColorRGB(0.35, 0.37, 0.45)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(plot_x + plot_w + 26, legend_y - 5, _safe_text(label)[:28])
        legend_y -= 12


def _draw_grouped_bar_chart(
    canvas,
    df: pd.DataFrame,
    *,
    categories_col: str,
    series_cols: list[tuple[str, str, tuple[float, float, float]]],
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    y_label: str,
) -> None:
    required = [categories_col] + [column for _, column, _ in series_cols]
    if df.empty or any(column not in df.columns for column in required):
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title=title)
        return
    data = df[required].copy()
    for _, column, _ in series_cols:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0).clip(lower=0.0)
    data = data.head(12)
    if data.empty:
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title=title)
        return

    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x, y + height - 10, _safe_text(title))

    plot_x = x + 42
    plot_y = y + 34
    plot_w = width - 132
    plot_h = height - 66
    totals = data[[column for _, column, _ in series_cols]].sum(axis=1)
    y_max = max(1.0, float(totals.max()) * 1.12)

    canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
    canvas.setLineWidth(0.6)
    for i in range(6):
        gy = plot_y + plot_h * i / 5
        canvas.line(plot_x, gy, plot_x + plot_w, gy)
        canvas.setFillColorRGB(0.42, 0.45, 0.53)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawRightString(plot_x - 5, gy - 2, _fmt_number(y_max * i / 5, 0))

    bar_gap = 3
    bar_w = max(3.0, (plot_w - bar_gap * (len(data) - 1)) / max(1, len(data)))
    for idx, (_, row) in enumerate(data.iterrows()):
        bx = plot_x + idx * (bar_w + bar_gap)
        bottom = plot_y
        for _, column, color in series_cols:
            value = float(row[column])
            bh = value / y_max * plot_h if y_max > 0 else 0.0
            canvas.setFillColorRGB(*color)
            canvas.rect(bx, bottom, bar_w, bh, fill=1, stroke=0)
            bottom += bh
        canvas.setFillColorRGB(0.42, 0.45, 0.53)
        canvas.setFont("Helvetica", 5.5)
        canvas.drawCentredString(bx + bar_w / 2, plot_y - 9, _safe_text(row[categories_col])[:5])

    canvas.setStrokeColorRGB(0.58, 0.62, 0.70)
    canvas.line(plot_x, plot_y, plot_x, plot_y + plot_h)
    canvas.line(plot_x, plot_y, plot_x + plot_w, plot_y)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColorRGB(0.42, 0.45, 0.53)
    canvas.saveState()
    canvas.translate(x + 8, plot_y + plot_h / 2)
    canvas.rotate(90)
    canvas.drawCentredString(0, 0, _safe_text(y_label))
    canvas.restoreState()

    legend_y = plot_y + plot_h - 6
    for label, _, color in series_cols:
        canvas.setFillColorRGB(*color)
        canvas.rect(plot_x + plot_w + 14, legend_y - 4, 8, 5, fill=1, stroke=0)
        canvas.setFillColorRGB(0.35, 0.37, 0.45)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(plot_x + plot_w + 26, legend_y - 5, _safe_text(label)[:34])
        legend_y -= 12


def _draw_simple_bar_chart(
    canvas,
    df: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    y_label: str,
    color: tuple[float, float, float],
    max_items: int = 8,
    y_max_override: float | None = None,
) -> None:
    data = df[[label_col, value_col]].copy() if not df.empty and {label_col, value_col}.issubset(df.columns) else pd.DataFrame()
    if data.empty:
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title=title)
        return
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce").fillna(0.0)
    data = data.dropna().head(max_items)
    for label, raw_name in SCENARIOS:
        data.loc[data[label_col].astype(str) == raw_name, label_col] = label

    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x, y + height - 10, _safe_text(title))
    plot_x = x + 48
    plot_y = y + 34
    plot_w = width - 68
    plot_h = height - 66
    if y_max_override is None:
        y_max = max(1.0, float(data[value_col].max()) * 1.12)
    else:
        y_max = max(1.0, float(y_max_override))
    bar_w = min(46.0, plot_w / max(1, len(data)) * 0.55)
    spacing = plot_w / max(1, len(data))

    canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
    for i in range(6):
        gy = plot_y + plot_h * i / 5
        canvas.line(plot_x, gy, plot_x + plot_w, gy)
        canvas.setFillColorRGB(0.42, 0.45, 0.53)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawRightString(plot_x - 5, gy - 2, _fmt_number(y_max * i / 5, 0))
    for idx, (_, row) in enumerate(data.iterrows()):
        cx = plot_x + idx * spacing + spacing / 2
        bh = min(float(row[value_col]), y_max) / y_max * plot_h
        canvas.setFillColorRGB(*color)
        canvas.rect(cx - bar_w / 2, plot_y, bar_w, bh, fill=1, stroke=0)
        canvas.setFillColorRGB(0.35, 0.37, 0.45)
        canvas.setFont("Helvetica", 6)
        canvas.drawCentredString(cx, plot_y - 9, _safe_text(row[label_col])[:20])
    canvas.setFont("Helvetica", 7)
    canvas.saveState()
    canvas.translate(x + 10, plot_y + plot_h / 2)
    canvas.rotate(90)
    canvas.drawCentredString(0, 0, _safe_text(y_label))
    canvas.restoreState()


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
        canvas.drawString(cx + 8, cy - 13, _safe_text(label)[:33])
        canvas.setFillColorRGB(0.18, 0.19, 0.25)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(cx + 8, cy - 34, _safe_text(value)[:25])
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
        canvas.drawString(cx, y, _safe_text(label))
        cx += col_w
    y -= 12
    canvas.setFont("Helvetica", 7)
    for _, row in scenario.economic_comparison_df.head(8).iterrows():
        cx = x
        for source, _, col_w in cols:
            value = row.get(source, "")
            text = str(value)[:32] if source == "Scenario" else _fmt_number(value, 0)
            canvas.drawString(cx, y, _safe_text(text))
            cx += col_w
        y -= 11
    return y


def _monthly_comparison_series(scenario: ScenarioResult) -> list[tuple[str, pd.DataFrame, str, str, tuple[float, float, float]]]:
    frames = [
        ("A - Géothermie seule", scenario.no_solar_multiyear_btes_df),
        ("B - Géothermie avec recharge solaire", scenario.multiyear_btes_df),
        ("C - Recharge solaire et linéaire réduit", scenario.reduced_multiyear_btes_df),
    ]
    return [
        (label, df, "Mois index", "T source PAC fin (C)", SCENARIO_COLORS[label])
        for label, df in frames
        if isinstance(df, pd.DataFrame) and not df.empty
    ]


def _annual_temperature_series(scenario: ScenarioResult) -> list[tuple[str, pd.DataFrame, str, str, tuple[float, float, float]]]:
    if scenario.economic_trajectory_df.empty or {"Scenario", "Annee", "T_source_PAC_min (C)"}.difference(
        scenario.economic_trajectory_df.columns
    ):
        return []
    out = []
    labels = {
        "Geothermie seule": "A - Géothermie seule",
        "Geothermie + solaire meme sondes": "B - Géothermie avec recharge solaire",
        "Geothermie + solaire sondes reduites": "C - Recharge solaire et linéaire réduit",
    }
    for raw_name, label in labels.items():
        rows = scenario.economic_trajectory_df[scenario.economic_trajectory_df["Scenario"].astype(str) == raw_name].copy()
        if rows.empty:
            continue
        data = pd.DataFrame(
            {
                "Annee": pd.to_numeric(rows["Annee"], errors="coerce"),
                "T source PAC min (C)": pd.to_numeric(rows["T_source_PAC_min (C)"], errors="coerce"),
            }
        )
        out.append((label, data, "Annee", "T source PAC min (C)", SCENARIO_COLORS[label]))
    return out


def _draw_multiyear_charts_page(canvas, scenario: ScenarioResult, *, width: float, height: float, subtitle: str) -> None:
    _draw_header(canvas, title=f"{_product_title(scenario)} - graphiques multiannuels", subtitle=subtitle, width=width, height=height)
    chart_w = (width - 82) / 2
    chart_h = 310
    _draw_line_chart(
        canvas,
        _monthly_comparison_series(scenario),
        x=34,
        y=height - 92 - chart_h,
        width=chart_w,
        height=chart_h,
        title="Fluctuations mensuelles - scénarios A, B et C",
        x_label="Mois de simulation",
        y_label="Température source PAC fin de mois (°C)",
        max_points=320,
    )
    _draw_line_chart(
        canvas,
        _annual_temperature_series(scenario),
        x=48 + chart_w,
        y=height - 92 - chart_h,
        width=chart_w,
        height=chart_h,
        title="Dérive annuelle - scénarios A, B et C",
        x_label="Année de simulation",
        y_label="Température source PAC minimale annuelle (°C)",
    )
    _draw_note(
        canvas,
        "Les courbes multiannuelles reprennent les mêmes grandeurs que l'onglet Multiannuel BTES : scénario A sans solaire, scénario B avec recharge solaire et linéaire initial, scénario C avec recharge solaire et linéaire réduit quand il a été simulé.",
        x=34,
        y=80,
        width=width - 68,
    )


def _draw_display_year_charts_page(canvas, scenario: ScenarioResult, *, width: float, height: float, subtitle: str) -> None:
    _draw_header(canvas, title=f"{_product_title(scenario)} - graphiques année affichée", subtitle=subtitle, width=width, height=height)
    has_geothermal = _has_geothermal_results(scenario)
    chart_w = (width - 82) / 2
    chart_h = 310
    hourly_series = [
        (
            "T ballon solaire",
            scenario.hourly_df,
            "Jour annee",
            "solar_ht_buffer_temp_end_c",
            (0.00, 0.45, 0.85),
        ),
    ]
    if has_geothermal:
        hourly_series.extend(
            [
                (
                    "T source PAC fin d'heure",
                    scenario.hourly_df,
                    "Jour annee",
                    "T_source_PAC_fin_heure_C",
                    (0.09, 0.64, 0.29),
                ),
                (
                    "T paroi forage",
                    scenario.hourly_df,
                    "Jour annee",
                    "T_paroi_forage_C",
                    (0.98, 0.45, 0.08),
                ),
                (
                    "T évaporateur PAC",
                    scenario.hourly_df,
                    "Jour annee",
                    "T_evaporateur_PAC_C",
                    (0.92, 0.20, 0.14),
                ),
            ]
        )
    _draw_line_chart(
        canvas,
        hourly_series,
        x=34,
        y=height - 92 - chart_h,
        width=chart_w,
        height=chart_h,
        title=(
            f"Températures horaires - scénario B, année {scenario.simulation_year_displayed}"
            if has_geothermal
            else f"Températures solaires horaires - année {scenario.simulation_year_displayed}"
        ),
        x_label="Jour de l'année",
        y_label="Température (°C)",
        max_points=365,
    )
    _draw_grouped_bar_chart(
        canvas,
        scenario.hourly_by_month_df,
        categories_col="Mois",
        series_cols=(
            [
                ("Solaire ECS", "Prechauffage HT solaire (MWh)", ENERGY_COLORS["Solaire thermique"]),
                ("PAC géothermie", "BT PAC (MWh)", ENERGY_COLORS["Géothermie PAC"]),
                ("Appoint HT", "Appoint HT (MWh)", ENERGY_COLORS["Appoint gaz"]),
                ("Appoint BT", "Appoint BT (MWh)", ENERGY_COLORS["Appoint gaz"]),
            ]
            if has_geothermal
            else [
                ("Solaire ECS", "Prechauffage HT solaire (MWh)", ENERGY_COLORS["Solaire thermique"]),
                ("Appoint gaz HT", "Appoint HT (MWh)", ENERGY_COLORS["Appoint gaz"]),
            ]
        ),
        x=48 + chart_w,
        y=height - 92 - chart_h,
        width=chart_w,
        height=chart_h,
        title=f"Besoins couverts par générateur - année {scenario.simulation_year_displayed}",
        y_label="MWh/mois",
    )
    note = "Les températures horaires sont échantillonnées pour garder un rapport lisible et léger."
    if has_geothermal:
        note += " L'injection BTES n'est pas empilée dans le bilan par générateur : elle recharge le sol et contribue indirectement à la PAC géothermique."
    _draw_note(canvas, note, x=34, y=80, width=width - 68)


def _draw_monthly_analysis_charts_page(canvas, scenario: ScenarioResult, *, width: float, height: float, subtitle: str) -> None:
    _draw_header(canvas, title=f"{_product_title(scenario)} - analyses mensuelles", subtitle=subtitle, width=width, height=height)
    has_geothermal = _has_geothermal_results(scenario)
    chart_w = (width - 92) / 2
    chart_h = 205
    left_x = 34
    right_x = 58 + chart_w
    top_y = height - 92 - chart_h
    bottom_y = 72
    month_df = _monthly_with_solar_losses(scenario)

    _draw_simple_bar_chart(
        canvas,
        month_df,
        label_col="Mois",
        value_col="Taux couverture solaire HT (%)",
        x=left_x,
        y=top_y,
        width=chart_w,
        height=chart_h,
        title=f"Couverture solaire HT - année {scenario.simulation_year_displayed}",
        y_label="%",
        color=ENERGY_COLORS["Solaire thermique"],
        max_items=12,
        y_max_override=100.0,
    )
    if has_geothermal:
        _draw_grouped_bar_chart(
            canvas,
            month_df,
            categories_col="Mois",
            series_cols=[
                ("PAC géothermie BT", "BT PAC (MWh)", (0.09, 0.64, 0.29)),
                ("Appoint gaz BT", "Appoint BT (MWh)", ENERGY_COLORS["Appoint gaz"]),
            ],
            x=right_x,
            y=top_y,
            width=chart_w,
            height=chart_h,
            title=f"Couverture PAC géothermie BT - scénario B, année {scenario.simulation_year_displayed}",
            y_label="MWh/mois",
        )
    _draw_grouped_bar_chart(
        canvas,
        month_df,
        categories_col="Mois",
        series_cols=(
            [
                ("Production solaire ECS", "Prechauffage HT solaire (MWh)", ENERGY_COLORS["Solaire thermique"]),
                ("Injection BTES", "Injection BTES (MWh)", ENERGY_COLORS["Injection solaire BTES"]),
            ]
            if has_geothermal
            else [("Production solaire ECS", "Prechauffage HT solaire (MWh)", ENERGY_COLORS["Solaire thermique"])]
        ),
        x=left_x,
        y=bottom_y,
        width=chart_w,
        height=chart_h,
        title=(
            f"Production solaire ECS et injection BTES - scénario B, année {scenario.simulation_year_displayed}"
            if has_geothermal
            else f"Production solaire ECS - année {scenario.simulation_year_displayed}"
        ),
        y_label="MWh/mois",
    )
    _draw_grouped_bar_chart(
        canvas,
        month_df,
        categories_col="Mois",
        series_cols=[
            ("Production solaire ECS", "Prechauffage HT solaire (MWh)", ENERGY_COLORS["Solaire thermique"]),
            ("Appoint gaz HT", "Appoint HT (MWh)", ENERGY_COLORS["Appoint gaz"]),
        ],
        x=right_x,
        y=bottom_y,
        width=chart_w,
        height=chart_h,
        title=f"Couverture besoin HT - scénario B, année {scenario.simulation_year_displayed}",
        y_label="MWh/mois",
    )


def _draw_economic_chart(canvas, scenario: ScenarioResult, *, x: float, y: float, width: float, height: float) -> None:
    _draw_simple_bar_chart(
        canvas,
        scenario.economic_comparison_df,
        label_col="Scenario",
        value_col="Cout chaleur global (EUR/MWh)",
        x=x,
        y=y,
        width=width,
        height=height,
        title="Coût de chaleur multiannuel par scénario",
        y_label="EUR/MWh",
        color=(0.09, 0.48, 0.74),
    )


def _economic_row_from_candidates(df: pd.DataFrame, names: list[str]) -> pd.Series | None:
    for name in names:
        row = _economic_row(df, name)
        if row is not None:
            return row
    if df.empty:
        return None
    if "Scenario" in df:
        non_reference = df[~df["Scenario"].astype(str).str.contains("reference", case=False, na=False)]
        if not non_reference.empty:
            return non_reference.iloc[0]
    return df.iloc[0]


def _economic_components_eur_mwh(row: pd.Series | None, delivered_mwh: float) -> dict[str, float]:
    if row is None or delivered_mwh <= 0:
        return {"P1": 0.0, "P2": 0.0, "P4": 0.0}
    return {
        "P1": float(_row_float(row, "P1 annuel (EUR/an)", 0.0) or 0.0) / delivered_mwh,
        "P2": float(_row_float(row, "P2 annuel (EUR/an)", 0.0) or 0.0) / delivered_mwh,
        "P4": float(_row_float(row, "P4 annuel (EUR/an)", 0.0) or 0.0) / delivered_mwh,
    }


def _draw_solar_gas_heat_cost_chart(canvas, scenario: ScenarioResult, *, x: float, y: float, width: float, height: float) -> None:
    df = scenario.economic_comparison_df
    delivered_mwh = max(1e-9, float(scenario.total_ht_kwh or 0.0) / 1000.0)
    solar_row = _economic_row_from_candidates(
        df,
        ["Geothermie + solaire meme sondes", "Solaire thermique + appoint gaz", "Mix ENR"],
    )
    reference_row = _economic_row_from_candidates(df[df["Scenario"].astype(str).str.contains("Reference", case=False, na=False)] if not df.empty and "Scenario" in df else pd.DataFrame(), ["Reference 100 % gaz", "Reference 100% gaz"])
    solar_parts = _economic_components_eur_mwh(solar_row, delivered_mwh)
    reference_parts = _economic_components_eur_mwh(reference_row, delivered_mwh)
    if reference_row is not None:
        ref_cost = _row_float(reference_row, "Cout chaleur global (EUR/MWh)")
        if ref_cost is not None and sum(reference_parts.values()) <= 0:
            reference_parts["P1"] = float(ref_cost)
    if solar_row is not None:
        solar_cost = _row_float(solar_row, "Cout chaleur global (EUR/MWh)")
        if solar_cost is not None and sum(solar_parts.values()) <= 0:
            solar_parts["P4"] = float(solar_cost)

    labels = ["Solaire + gaz", "Référence gaz"]
    stacks = [solar_parts, reference_parts]
    colors = {
        "P1": (0.02, 0.42, 0.78),
        "P2": (0.46, 0.74, 0.94),
        "P4": (0.98, 0.80, 0.08),
    }
    totals = [sum(parts.values()) for parts in stacks]
    if max(totals or [0.0]) <= 0:
        _draw_no_data(canvas, x=x, y=y, width=width, height=height, title="Coût de chaleur solaire thermique / gaz")
        return

    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x, y + height - 10, _safe_text("Coût de chaleur : solaire thermique + gaz vs référence gaz"))
    plot_x = x + 52
    plot_y = y + 34
    plot_w = width - 130
    plot_h = height - 72
    y_max = max(totals) * 1.18
    canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
    for i in range(6):
        gy = plot_y + plot_h * i / 5
        canvas.line(plot_x, gy, plot_x + plot_w, gy)
        canvas.setFillColorRGB(0.42, 0.45, 0.53)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawRightString(plot_x - 5, gy - 2, _fmt_number(y_max * i / 5, 0))
    bar_w = min(72.0, plot_w / 4)
    for idx, parts in enumerate(stacks):
        bx = plot_x + plot_w * (idx + 1) / 3 - bar_w / 2
        bottom = plot_y
        for poste in ("P1", "P2", "P4"):
            value = max(0.0, float(parts.get(poste, 0.0)))
            bh = value / y_max * plot_h
            canvas.setFillColorRGB(*colors[poste])
            canvas.rect(bx, bottom, bar_w, bh, fill=1, stroke=0)
            bottom += bh
        canvas.setFillColorRGB(0.35, 0.37, 0.45)
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(bx + bar_w / 2, plot_y - 10, _safe_text(labels[idx]))
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawCentredString(bx + bar_w / 2, bottom + 4, _fmt_number(totals[idx], 1, "EUR/MWh"))
    canvas.setFont("Helvetica", 7)
    canvas.saveState()
    canvas.translate(x + 10, plot_y + plot_h / 2)
    canvas.rotate(90)
    canvas.drawCentredString(0, 0, _safe_text("EUR/MWh utile"))
    canvas.restoreState()
    legend_y = plot_y + plot_h - 4
    labels_postes = {"P1": "P1 énergie", "P2": "P2 maintenance", "P4": "P4 investissement"}
    for poste in ("P1", "P2", "P4"):
        canvas.setFillColorRGB(*colors[poste])
        canvas.rect(plot_x + plot_w + 14, legend_y - 4, 8, 6, fill=1, stroke=0)
        canvas.setFillColorRGB(0.35, 0.37, 0.45)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(plot_x + plot_w + 26, legend_y - 5, _safe_text(labels_postes[poste]))
        legend_y -= 12


def _draw_solar_only_duration_page(canvas, scenario: ScenarioResult, *, width: float, height: float, subtitle: str) -> None:
    _draw_header(canvas, title=f"{_product_title(scenario)} - monotone solaire", subtitle=subtitle, width=width, height=height)
    duration_df = _solar_only_duration_dataframe(scenario)
    _draw_line_chart(
        canvas,
        [
            ("Besoin HT", duration_df, "Heure classee", "Besoin HT", (0.18, 0.19, 0.25)),
            ("Solaire thermique", duration_df, "Heure classee", "Solaire thermique", ENERGY_COLORS["Solaire thermique"]),
            ("Appoint gaz", duration_df, "Heure classee", "Appoint gaz", ENERGY_COLORS["Appoint gaz"]),
        ],
        x=34,
        y=height - 92 - 330,
        width=width - 68,
        height=330,
        title=f"Monotone horaire du besoin HT - année {scenario.simulation_year_displayed}",
        x_label="Heures classées par besoin décroissant",
        y_label="Puissance moyenne horaire (kW)",
        max_points=500,
    )
    _draw_note(
        canvas,
        "La monotone classe les heures de l'année affichée par besoin haute température décroissant. "
        "Elle permet de visualiser la part couverte par le solaire thermique et la part restant à l'appoint gaz.",
        x=34,
        y=82,
        width=width - 68,
    )


def _draw_solar_only_economic_page(canvas, scenario: ScenarioResult, *, width: float, height: float, subtitle: str) -> None:
    _draw_header(canvas, title=f"{_product_title(scenario)} - économie solaire thermique", subtitle=subtitle, width=width, height=height)
    y = height - 92
    econ_row = _economic_row_from_candidates(
        scenario.economic_comparison_df,
        ["Geothermie + solaire meme sondes", "Solaire thermique + appoint gaz", "Mix ENR"],
    )
    reference_row = _economic_row_from_candidates(
        scenario.economic_comparison_df[
            scenario.economic_comparison_df["Scenario"].astype(str).str.contains("Reference", case=False, na=False)
        ]
        if not scenario.economic_comparison_df.empty and "Scenario" in scenario.economic_comparison_df
        else pd.DataFrame(),
        ["Reference 100 % gaz", "Reference 100% gaz"],
    )
    solar_capex_row = _capex_summary_row(scenario, "Solaire thermique")
    y = _draw_section_title(canvas, "Synthèse économique", x=34, y=y)
    y = _draw_kpi_grid(
        canvas,
        [
            ("Coût solaire + gaz", _fmt_number(_row_float(econ_row, "Cout chaleur global (EUR/MWh)"), 1, "EUR/MWh")),
            ("Référence gaz", _fmt_number(_row_float(reference_row, "Cout chaleur global (EUR/MWh)"), 1, "EUR/MWh")),
            ("Investissement total", _fmt_number(_row_float(solar_capex_row, "CAPEX brut (EUR)"), 0, "EUR")),
            ("Aide ADEME", _fmt_number(_row_float(solar_capex_row, "Aide ADEME (EUR)"), 0, "EUR")),
            ("CAPEX net solaire", _fmt_number(_row_float(econ_row, "CAPEX net (EUR)"), 0, "EUR")),
            ("Temps retour brut", _fmt_payback_years(_row_float(econ_row, "Temps retour brut (ans)"))),
            ("Contexte référence", gas_reference_context_label(str(scenario.heat_costs.get("gas_reference_context", "")))),
        ],
        x=34,
        y=y,
        width=width - 68,
    )
    _draw_solar_gas_heat_cost_chart(canvas, scenario, x=34, y=72, width=width - 68, height=260)


def build_heliostock_overview_pdf(
    scenario: ScenarioResult,
    *,
    calculation_id: str = "",
    calculated_at: str = "",
    gmi_context: dict[str, Any] | None = None,
    architectural_context: dict[str, Any] | None = None,
) -> bytes:
    """Build a compact PDF export from the already-computed HelioDyn result."""

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas as pdf_canvas

    buffer = BytesIO()
    page_width, page_height = landscape(A4)
    canvas = pdf_canvas.Canvas(buffer, pagesize=(page_width, page_height), pageCompression=0)
    subtitle = (
        f"Calcul {calculation_id} - {calculated_at} - année affichée {scenario.simulation_year_displayed} "
        f"sur {scenario.simulation_years_total} ans"
    )

    product_title = _product_title(scenario)
    has_geothermal = _has_geothermal_results(scenario)

    _draw_header(canvas, title=f"{product_title} - synthèse du calcul", subtitle=subtitle, width=page_width, height=page_height)
    y = page_height - 92
    input_metrics = [
        ("Surface solaire", _fmt_number(scenario.config.collector.area_m2, 0, "m²")),
        ("Volume stockage solaire", _storage_value_for_pdf(scenario, has_geothermal=has_geothermal)),
    ]
    if has_geothermal:
        input_metrics.extend(
            [
                ("Puissance PAC géothermie", _fmt_number(scenario.config.heat_pump.max_thermal_power_kw, 0, "kW")),
                ("Linéaire sondes", _fmt_number(scenario.full_borefield_length_m, 0, "ml")),
            ]
        )
    y = _draw_section_title(canvas, "Données d'entrée principales", x=34, y=y)
    y = _draw_kpi_grid(
        canvas,
        input_metrics,
        x=34,
        y=y,
        width=page_width - 68,
    )
    y -= 6
    y = _draw_section_title(canvas, "Besoins et production solaire", x=34, y=y)
    solar_metrics = [
        ("Besoin total", _fmt_mwh_from_kwh(scenario.total_ht_kwh + scenario.total_bt_kwh)),
    ]
    if has_geothermal:
        solar_metrics.append(("Besoin haute température", _fmt_mwh_from_kwh(scenario.total_ht_kwh)))
        solar_metrics.extend(
            [
                ("Besoin basse température", _fmt_mwh_from_kwh(scenario.total_bt_kwh)),
                ("Production solaire totale", _fmt_mwh_from_kwh(scenario.total_preheat_ht_kwh + scenario.total_to_btes_kwh)),
                ("Production solaire ECS", _fmt_mwh_from_kwh(scenario.total_preheat_ht_kwh)),
                ("Production solaire injectée BTES", _fmt_mwh_from_kwh(scenario.total_to_btes_kwh)),
            ]
        )
    else:
        solar_metrics.extend(
            [
                ("Production solaire thermique", _fmt_mwh_from_kwh(scenario.total_preheat_ht_kwh)),
                ("Pertes ballon solaire", _fmt_mwh_from_kwh(_solar_buffer_loss_kwh(scenario))),
                ("Appoint gaz HT", _fmt_mwh_from_kwh(scenario.total_backup_ht_kwh)),
            ]
        )
    solar_metrics.extend(
        [
            ("Heures palier haut ballon", _fmt_number(_solar_buffer_at_max_hours(scenario), 0, "h")),
            ("Épisodes de surchauffe", _fmt_number(_solar_buffer_at_max_episodes(scenario), 0)),
            ("Couverture solaire HT", _fmt_number(scenario.annual_ht_solar_coverage * 100.0, 0, "%")),
            ("Productivité solaire valorisée", _fmt_number(scenario.solar_productivity_valued_kwh_m2_year, 0, "kWh/m².an")),
        ]
    )
    y = _draw_kpi_grid(
        canvas,
        solar_metrics,
        x=34,
        y=y,
        width=page_width - 68,
    )
    y -= 6
    if has_geothermal:
        _draw_gmi_conclusion(canvas, gmi_context, x=34, y=y, width=page_width - 68)
    page_number = 1
    _draw_footer(canvas, page_number=page_number, width=page_width)
    canvas.showPage()
    page_number += 1

    if has_geothermal:
        _draw_header(canvas, title=f"{product_title} - scénarios techniques", subtitle=subtitle, width=page_width, height=page_height)
        y = page_height - 92
        for label, scenario_name in SCENARIOS:
            y = _draw_section_title(canvas, label, x=34, y=y)
            y = _draw_kpi_grid(canvas, _scenario_metrics(scenario, scenario_name), x=34, y=y, width=page_width - 68)
            y -= 4
            if y < 120:
                _draw_footer(canvas, page_number=page_number, width=page_width)
                canvas.showPage()
                page_number += 1
                _draw_header(canvas, title=f"{product_title} - scénarios techniques", subtitle=subtitle, width=page_width, height=page_height)
                y = page_height - 92
        _draw_footer(canvas, page_number=page_number, width=page_width)
        canvas.showPage()
        page_number += 1

    if not has_geothermal:
        _draw_header(canvas, title=f"{product_title} - localisation et contraintes", subtitle=subtitle, width=page_width, height=page_height)
        y = page_height - 92
        y = _draw_architectural_conclusion(canvas, architectural_context, x=34, y=y, width=page_width - 68)
        _draw_architectural_map(
            canvas,
            architectural_context,
            x=34,
            y=76,
            width=page_width - 68,
            height=max(180, min(320, y - 96)),
        )
        _draw_footer(canvas, page_number=page_number, width=page_width)
        canvas.showPage()
        page_number += 1

    if has_geothermal:
        _draw_multiyear_charts_page(canvas, scenario, width=page_width, height=page_height, subtitle=subtitle)
        _draw_footer(canvas, page_number=page_number, width=page_width)
        canvas.showPage()
        page_number += 1

    _draw_display_year_charts_page(canvas, scenario, width=page_width, height=page_height, subtitle=subtitle)
    _draw_footer(canvas, page_number=page_number, width=page_width)
    canvas.showPage()
    page_number += 1

    _draw_monthly_analysis_charts_page(canvas, scenario, width=page_width, height=page_height, subtitle=subtitle)
    _draw_footer(canvas, page_number=page_number, width=page_width)
    canvas.showPage()
    page_number += 1

    if not has_geothermal:
        _draw_solar_only_duration_page(canvas, scenario, width=page_width, height=page_height, subtitle=subtitle)
        _draw_footer(canvas, page_number=page_number, width=page_width)
        canvas.showPage()
        page_number += 1

    if has_geothermal:
        _draw_header(canvas, title=f"{product_title} - économie multiannuelle", subtitle=subtitle, width=page_width, height=page_height)
        y = page_height - 92
        chart_w = (page_width - 82) / 2
        _draw_economic_chart(canvas, scenario, x=34, y=page_height - 92 - 220, width=chart_w, height=220)
        y = _draw_section_title(canvas, "Comparaison économique des scénarios", x=48 + chart_w, y=y)
        y = _draw_economic_table(canvas, scenario, x=48 + chart_w, y=y, width=chart_w)
        y -= 10
        savings = scenario.savings or {}
        y = _draw_section_title(canvas, "Statut économie de sondes", x=48 + chart_w, y=y)
        _draw_kpi_grid(
            canvas,
            [
                ("Calcul physique C", "réalisé" if bool(savings.get("simulated", False)) else "non lancé"),
                ("Réduction validée", "oui" if bool(savings.get("found", False)) else "non"),
                ("Linéaire testé", _fmt_number(savings.get("candidate_length_m"), 0, "ml")),
                ("Gain retenu", _fmt_number(savings.get("saved_length_m", 0.0), 0, "ml")),
            ],
            x=48 + chart_w,
            y=y,
            width=chart_w,
            cols=2,
        )
        _draw_footer(canvas, page_number=page_number, width=page_width)
    else:
        _draw_solar_only_economic_page(canvas, scenario, width=page_width, height=page_height, subtitle=subtitle)
        _draw_footer(canvas, page_number=page_number, width=page_width)
    canvas.save()
    return buffer.getvalue()
