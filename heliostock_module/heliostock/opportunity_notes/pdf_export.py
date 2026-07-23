from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader

from ..architectural_patrimony_service import CATEGORY_CONFIG
from ..architectural_static_map import (
    GEOPORTAIL_ORTHO_TILE_URL,
    StaticMapError,
    _create_background,
    _draw_geometry,
    _draw_project_marker,
    render_static_map,
)
from ..common.pdf import PdfReport, _fmt_number
from ..pdf_report import CARD_FILL, CARD_STROKE, CHART_COLORS, GRID_COLOR, MUTED_COLOR, PDF_FONT_BOLD, PDF_FONT_REGULAR, TEXT_COLOR
from .cesc_economic_model import CescEconomicInputs, CescEconomicResults, build_yearly_cashflow_projection
from .opportunity_model import LoopInputs, NeedsInputs, OpportunityResults, SizingInputs, SiteInputs


def _eur(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n.d."
    return f"{_fmt_number(value, digits)} EUR"


def _eur_mwh(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{_fmt_number(value, digits)} EUR/MWh"


def _percent(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n.d."
    return f"{100.0 * float(value):.{digits}f} %"


def _coverage_ratio(results: OpportunityResults) -> float | None:
    if results.annual_total_ecs_energy_mwh <= 0:
        return None
    return min(1.0, results.estimated_solar_production_mwh_year / results.annual_total_ecs_energy_mwh)


def _opportunity_status(results: OpportunityResults, economic_results: CescEconomicResults) -> tuple[str, str]:
    coverage = _coverage_ratio(results) or 0.0
    if coverage >= 0.45 and (economic_results.raw_payback_years or 999.0) <= 15:
        return (
            "Opportunité favorable",
            "Le prédimensionnement présente une couverture solaire et une économie simple cohérentes pour une poursuite d'étude.",
        )
    if coverage >= 0.25:
        return (
            "Opportunité à confirmer",
            "Le projet semble techniquement possible, mais les hypothèses de besoin, d'aides et d'intégration doivent être consolidées.",
        )
    return (
        "Opportunité fragile",
        "La couverture solaire estimée est faible au regard du besoin. Le dimensionnement ou les hypothèses d'usage sont à revoir.",
    )


def _monthly_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    rows = [
        {
            "Mois": row.month,
            "Volume moyen (L/j)": _fmt_number(row.average_l_day_60c, 0),
            "Besoin utile (MWh)": _fmt_number(row.useful_energy_mwh, 1),
            "Bouclage (MWh)": _fmt_number(row.loop_losses_mwh, 1),
            "Chauffage (MWh)": _fmt_number(row.heating_after_boiler_mwh, 1),
            "Total ECS (MWh)": _fmt_number(row.total_ecs_energy_mwh, 1),
        }
        for row in results.monthly_needs
    ]
    rows.append(
        {
            "Mois": "Total",
            "Volume moyen (L/j)": _fmt_number(results.average_daily_volume_l_60c, 0),
            "Besoin utile (MWh)": _fmt_number(results.annual_useful_energy_mwh, 1),
            "Bouclage (MWh)": _fmt_number(results.annual_loop_losses_mwh, 1),
            "Chauffage (MWh)": _fmt_number(results.annual_heating_after_boiler_mwh, 1),
            "Total ECS (MWh)": _fmt_number(results.annual_total_ecs_energy_mwh, 1),
        }
    )
    return rows


def _monthly_chart_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    return [
        {
            "Mois": row.month[:3],
            "Besoin utile ECS": row.useful_energy_mwh,
            "Besoin ECS": row.total_ecs_energy_mwh,
        }
        for row in results.monthly_needs
    ]


def _cashflow_chart_rows(inputs: CescEconomicInputs, results: CescEconomicResults) -> list[dict[str, Any]]:
    return [
        {
            "Année": row["Année"],
            "Flux moyen": row["Flux cumulé moyen (€)"],
            "Flux inflation": row["Flux cumulé inflation annuelle (€)"],
        }
        for row in build_yearly_cashflow_projection(inputs, results)
    ]


def _cashflow_zero_year(rows: list[dict[str, Any]], value_key: str) -> int | None:
    for row in rows:
        try:
            if float(row.get(value_key, 0.0)) >= 0:
                return int(float(row.get("Année", 0)))
        except (TypeError, ValueError):
            continue
    return None


def _draw_cashflow_chart(
    report: PdfReport,
    rows: list[dict[str, Any]],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas = report.canvas
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont(PDF_FONT_BOLD, 10)
    canvas.drawString(x, y + height + 14, "Flux cumulé sur la période")

    if not rows:
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.setFont(PDF_FONT_REGULAR, 8)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return

    years = [float(row.get("Année", 0.0)) for row in rows]
    mean_values = [float(row.get("Flux moyen", 0.0)) for row in rows]
    inflation_values = [float(row.get("Flux inflation", 0.0)) for row in rows]
    all_values = mean_values + inflation_values + [0.0]
    min_x, max_x = min(years), max(years)
    min_y, max_y = min(all_values), max(all_values)
    if max_x <= min_x:
        max_x = min_x + 1
    if max_y <= min_y:
        max_y = min_y + 1

    plot_x = x + 44
    plot_y = y + 18
    plot_w = width - 96
    plot_h = height - 46

    def px(value: float) -> float:
        return plot_x + (value - min_x) / (max_x - min_x) * plot_w

    def py(value: float) -> float:
        return plot_y + (value - min_y) / (max_y - min_y) * plot_h

    canvas.setStrokeColorRGB(*GRID_COLOR)
    canvas.setLineWidth(0.6)
    for step in range(5):
        gy = plot_y + step * plot_h / 4
        value = min_y + (max_y - min_y) * step / 4
        canvas.line(plot_x, gy, plot_x + plot_w, gy)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.setFont(PDF_FONT_REGULAR, 6.5)
        canvas.drawRightString(plot_x - 5, gy - 2, _fmt_number(value, 0))

    zero_y = py(0.0)
    canvas.setStrokeColorRGB(0.08, 0.08, 0.08)
    canvas.setDash(4, 4)
    canvas.setLineWidth(1.0)
    canvas.line(plot_x, zero_y, plot_x + plot_w, zero_y)
    canvas.setDash()
    canvas.setFillColorRGB(*MUTED_COLOR)
    canvas.setFont(PDF_FONT_REGULAR, 7)
    canvas.drawRightString(plot_x + plot_w, zero_y + 4, "Équilibre 0 €")

    for values, color in [(mean_values, CHART_COLORS[0]), (inflation_values, CHART_COLORS[1])]:
        points = [(px(year), py(value)) for year, value in zip(years, values)]
        canvas.setStrokeColorRGB(*color)
        canvas.setLineWidth(1.4)
        for start, end in zip(points, points[1:]):
            canvas.line(start[0], start[1], end[0], end[1])
        canvas.setFillColorRGB(*color)
        for point_x, point_y in points:
            canvas.circle(point_x, point_y, 2.0, fill=1, stroke=0)

    for key, label, x_shift in [
        ("Flux moyen", "Retour moyen", -18),
        ("Flux inflation", "Retour inflation", 14),
    ]:
        year = _cashflow_zero_year(rows, key)
        if year is None:
            continue
        line_x = px(float(year))
        canvas.setStrokeColorRGB(0.08, 0.08, 0.08)
        canvas.setDash(2, 2)
        canvas.line(line_x, plot_y, line_x, plot_y + plot_h)
        canvas.setDash()
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.setFont(PDF_FONT_REGULAR, 7)
        canvas.drawString(line_x + x_shift, plot_y + plot_h + 4, f"{label} : {year} ans")

    canvas.setFillColorRGB(*MUTED_COLOR)
    canvas.setFont(PDF_FONT_REGULAR, 7)
    canvas.drawString(plot_x, y + height - 5, "EUR")
    canvas.drawCentredString(plot_x + plot_w / 2, y - 4, "Année")
    for step in range(5):
        tx = plot_x + step * plot_w / 4
        value = min_x + (max_x - min_x) * step / 4
        canvas.drawCentredString(tx, plot_y - 10, _fmt_number(value, 0))

    legend_x = plot_x + plot_w - 126
    legend_y = y + height + 11
    for index, (label, color) in enumerate([("Flux moyen", CHART_COLORS[0]), ("Flux avec inflation", CHART_COLORS[1])]):
        ly = legend_y - index * 11
        canvas.setFillColorRGB(*color)
        canvas.rect(legend_x, ly - 5, 7, 5, fill=1, stroke=0)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.drawString(legend_x + 10, ly - 5, label)


def _cost_table_rows(results: CescEconomicResults) -> list[dict[str, Any]]:
    rows = [
        {
            "Famille": line.category,
            "Poste": line.label,
            "Coût total": _eur(line.total_cost_eur, 0) if line.total_cost_eur is not None else "-",
            "Aide": _eur(line.ademe_aid_eur, 0) if line.ademe_aid_eur is not None else "-",
            "Net": _eur(line.net_cost_eur, 0) if line.net_cost_eur is not None else "-",
            "Coût chaleur": _eur_mwh(
                line.cost_eur_mwh_year if line.cost_eur_mwh_year is not None else results.solar_heat_cost_eur_mwh,
                1,
            )
            if line.label.lower() == "total"
            else (_eur_mwh(line.cost_eur_mwh_year, 1) if line.cost_eur_mwh_year is not None else "-"),
        }
        for line in results.cost_lines
    ]
    return rows


def _heat_cost_rows(results: CescEconomicResults) -> list[dict[str, Any]]:
    return [
        {"Poste": "P1 auxiliaires", "EUR/MWh": results.heat_cost_p1_eur_mwh or 0.0},
        {"Poste": "P2 maintenance", "EUR/MWh": results.heat_cost_p2_eur_mwh or 0.0},
        {"Poste": "P4 investissement", "EUR/MWh": results.heat_cost_p4_eur_mwh or 0.0},
        {"Poste": "Référence", "EUR/MWh": results.average_reference_energy_cost_eur_mwh or 0.0},
    ]


def _total_heat_cost_label(results: CescEconomicResults) -> str:
    total = (
        float(results.heat_cost_p1_eur_mwh or 0.0)
        + float(results.heat_cost_p2_eur_mwh or 0.0)
        + float(results.heat_cost_p4_eur_mwh or 0.0)
    )
    return _eur_mwh(total, 1)


def _draw_heat_cost_comparison_chart(
    report: PdfReport,
    results: CescEconomicResults,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    canvas = report.canvas
    p1 = float(results.heat_cost_p1_eur_mwh or 0.0)
    p2 = float(results.heat_cost_p2_eur_mwh or 0.0)
    p4 = float(results.heat_cost_p4_eur_mwh or 0.0)
    solar_total = p1 + p2 + p4
    reference = float(results.average_reference_energy_cost_eur_mwh or 0.0)
    max_value = max(solar_total, reference, 1.0) * 1.15

    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont(PDF_FONT_BOLD, 10)
    canvas.drawString(x, y + height + 14, "Coût de chaleur : référence vs solaire thermique")

    plot_x = x + 42
    plot_y = y + 30
    plot_w = width - 74
    plot_h = height - 58
    canvas.setStrokeColorRGB(*GRID_COLOR)
    canvas.setFillColorRGB(*MUTED_COLOR)
    canvas.setFont(PDF_FONT_REGULAR, 6.5)
    for step in range(5):
        gy = plot_y + step * plot_h / 4
        value = max_value * step / 4
        canvas.line(plot_x, gy, plot_x + plot_w, gy)
        canvas.drawRightString(plot_x - 4, gy - 2, f"{_fmt_number(value, 0)}")
    canvas.drawString(plot_x, y + height - 5, "€/MWh utile")

    bar_w = min(46, plot_w * 0.22)
    solar_x = plot_x + plot_w * 0.24 - bar_w / 2
    ref_x = plot_x + plot_w * 0.72 - bar_w / 2

    current_y = plot_y
    segments = [
        ("P1' auxiliaires", p1, CHART_COLORS[0]),
        ("P2 maintenance", p2, CHART_COLORS[1]),
        ("P4 investissement", p4, CHART_COLORS[3]),
    ]
    for _label, value, color in segments:
        segment_h = plot_h * value / max_value
        canvas.setFillColorRGB(*color)
        canvas.rect(solar_x, current_y, bar_w, segment_h, fill=1, stroke=0)
        current_y += segment_h

    ref_h = plot_h * reference / max_value
    canvas.setFillColorRGB(0.82, 0.86, 0.92)
    canvas.rect(ref_x, plot_y, bar_w, ref_h, fill=1, stroke=0)

    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont(PDF_FONT_REGULAR, 7)
    canvas.drawCentredString(solar_x + bar_w / 2, current_y + 4, f"{_fmt_number(solar_total, 1)}")
    canvas.drawCentredString(ref_x + bar_w / 2, plot_y + ref_h + 4, f"{_fmt_number(reference, 1)}")
    canvas.drawCentredString(solar_x + bar_w / 2, plot_y - 10, "Solaire")
    canvas.drawCentredString(ref_x + bar_w / 2, plot_y - 10, "Référence")

    legend_x = plot_x
    legend_y = y + 10
    for idx, (label, _value, color) in enumerate(segments):
        lx = legend_x + idx * 92
        ly = legend_y
        canvas.setFillColorRGB(*color)
        canvas.rect(lx, ly - 5, 7, 7, fill=1, stroke=0)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.drawString(lx + 10, ly - 5, label[:20])


def _architectural_count_rows(architectural_constraints: dict[str, Any] | None) -> list[dict[str, Any]]:
    result = architectural_constraints.get("result") if isinstance(architectural_constraints, dict) else None
    if not isinstance(result, dict):
        return []
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    return [
        {
            "Catégorie": category,
            "Protection": str(config.get("title", category)),
            "Objets détectés": int(counts.get(category, 0) or 0),
        }
        for category, config in CATEGORY_CONFIG.items()
    ]


def _draw_architectural_map(
    report: PdfReport,
    architectural_constraints: dict[str, Any] | None,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    if not isinstance(architectural_constraints, dict):
        report.note(
            "Aucune analyse de contraintes architecturales n'est enregistrée dans ce projet.",
            x=x,
            y=y + height - 10,
            width=width,
            size=8,
        )
        return
    latitude = architectural_constraints.get("latitude")
    longitude = architectural_constraints.get("longitude")
    result = architectural_constraints.get("result")
    address = str(architectural_constraints.get("selected_address") or "")
    if latitude is None or longitude is None:
        report.note(
            "Aucune coordonnée projet n'est disponible pour générer la carte des contraintes architecturales.",
            x=x,
            y=y + height - 10,
            width=width,
            size=8,
        )
        return
    try:
        image = render_static_map(
            latitude=float(latitude),
            longitude=float(longitude),
            result=result if isinstance(result, dict) else None,
            address=address,
            zoom=16,
            width=1100,
            height=620,
        )
        image_buffer = BytesIO()
        image.save(image_buffer, format="PNG")
        image_buffer.seek(0)
        report.canvas.drawImage(
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
        report.note(
            f"La carte n'a pas pu être générée dans le PDF : {exc}",
            x=x,
            y=y + height - 10,
            width=width,
            size=8,
        )


def _ecs_pie_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    if float(results.annual_loop_losses_mwh or 0.0) <= 0:
        return []
    return [
        {"Poste": "Besoin utile ECS", "MWh": results.annual_useful_energy_mwh},
        {"Poste": "Bouclage sanitaire", "MWh": results.annual_loop_losses_mwh},
    ]


def _ecs_heating_pie_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    values = [
        ("Besoin utile ECS", results.annual_useful_energy_mwh),
        ("Bouclage sanitaire", results.annual_loop_losses_mwh),
        ("Chauffage estimé", results.annual_heating_after_boiler_mwh),
    ]
    positive = [{"Poste": label, "MWh": value} for label, value in values if float(value or 0.0) > 0]
    if len(positive) <= 1 or float(results.annual_heating_after_boiler_mwh or 0.0) <= 0:
        return []
    return positive


def _annual_balance_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    useful = float(results.annual_useful_energy_mwh or 0.0)
    total = float(results.annual_total_ecs_energy_mwh or 0.0)
    rows = []
    if abs(total - useful) > 0.05:
        rows.append({"Poste": "Besoin utile ECS", "MWh/an": useful})
        rows.append({"Poste": "Besoin ECS total", "MWh/an": total})
    else:
        rows.append({"Poste": "Besoin ECS total", "MWh/an": total})
    rows.append({"Poste": "Production solaire", "MWh/an": results.estimated_solar_production_mwh_year})
    if results.annual_loop_losses_mwh > 0:
        rows.insert(1, {"Poste": "Bouclage sanitaire", "MWh/an": results.annual_loop_losses_mwh})
    if results.annual_heating_after_boiler_mwh > 0:
        rows.insert(2, {"Poste": "Chauffage estimé", "MWh/an": results.annual_heating_after_boiler_mwh})
    return rows


def _draw_callout(report: PdfReport, title: str, body: str, *, x: float, y: float, width: float) -> float:
    canvas = report.canvas
    height = 66
    canvas.setFillColorRGB(1.0, 0.98, 0.90)
    canvas.setStrokeColorRGB(0.98, 0.75, 0.30)
    canvas.roundRect(x, y - height, width, height, 8, fill=1, stroke=1)
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x + 12, y - 18, title)
    canvas.setFillColorRGB(*MUTED_COLOR)
    return report.note(body, x=x + 12, y=y - 34, width=width - 24, size=8) - 8


def _draw_dimensioning_box(
    report: PdfReport,
    *,
    x: float,
    y: float,
    width: float,
    results: OpportunityResults,
    sizing_inputs: SizingInputs,
) -> float:
    canvas = report.canvas
    height = 78
    canvas.setFillColorRGB(*CARD_FILL)
    canvas.setStrokeColorRGB(*CARD_STROKE)
    canvas.roundRect(x, y - height, width, height, 8, fill=1, stroke=1)
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(x + 12, y - 18, "Prédimensionnement proposé")
    lines = [
        f"{results.collectors.collector_count} capteurs {sizing_inputs.collector_name}",
        f"Surface capteurs : {_fmt_number(results.collectors.surface_m2, 1)} m²",
        f"Stockage : {results.storage.label}",
        f"Ratio V/S obtenu : {_fmt_number(results.collectors.storage_ratio_l_m2, 0)} L/m²",
        f"Production solaire estimée : {_fmt_number(results.estimated_solar_production_mwh_year, 1)} MWh/an",
        f"Taux de couverture ECS : {_percent(_coverage_ratio(results), 0)}",
    ]
    canvas.setFillColorRGB(*MUTED_COLOR)
    canvas.setFont("Helvetica", 7.6)
    line_y = y - 38
    for index, line in enumerate(lines):
        col_x = x + 12 if index < 3 else x + width / 2
        row_y = line_y - (index % 3) * 13
        canvas.drawString(col_x, row_y, line)
    return y - height - 10


def _surface_orientation_metrics(surface_orientation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(surface_orientation, dict):
        return {}
    metrics = surface_orientation.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _surface_orientation_drawings(surface_orientation: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(surface_orientation, dict):
        return []
    drawings = surface_orientation.get("drawings")
    return [feature for feature in drawings if isinstance(feature, dict)] if isinstance(drawings, list) else []


def _geometry_lon_lat_coordinates(value: Any) -> list[list[float]]:
    coords: list[list[float]] = []
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        coords.append([float(value[0]), float(value[1])])
    elif isinstance(value, (list, tuple)):
        for item in value:
            coords.extend(_geometry_lon_lat_coordinates(item))
    return coords


def _surface_orientation_center(
    drawings: list[dict[str, Any]],
    fallback_latitude: float,
    fallback_longitude: float,
) -> tuple[float, float]:
    coords: list[list[float]] = []
    for feature in drawings:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if isinstance(geometry, dict):
            coords.extend(_geometry_lon_lat_coordinates(geometry.get("coordinates")))
    if not coords:
        return fallback_latitude, fallback_longitude
    longitude = sum(coord[0] for coord in coords) / len(coords)
    latitude = sum(coord[1] for coord in coords) / len(coords)
    return latitude, longitude


def _draw_surface_orientation_map(
    report: PdfReport,
    surface_orientation: dict[str, Any] | None,
    *,
    fallback_latitude: float,
    fallback_longitude: float,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    drawings = _surface_orientation_drawings(surface_orientation)
    if not drawings:
        report.note(
            "Aucune emprise de toiture ou zone au sol n'est enregistrée dans ce projet.",
            x=x,
            y=y + height - 10,
            width=width,
            size=8,
        )
        return

    latitude, longitude = _surface_orientation_center(drawings, fallback_latitude, fallback_longitude)
    try:
        base, left, top, _tiles_loaded = _create_background(
            longitude=longitude,
            latitude=latitude,
            zoom=19,
            width=1100,
            height=620,
            tile_url=GEOPORTAIL_ORTHO_TILE_URL,
            tile_label="Géoportail orthophotos",
        )
        overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
        for feature in drawings:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not isinstance(geometry, dict):
                continue
            color = (34, 178, 166, 210) if geometry.get("type") == "Polygon" else (233, 71, 61, 240)
            _draw_geometry(overlay=overlay, geometry=geometry, color=color, zoom=19, left=left, top=top)
        _draw_project_marker(overlay=overlay, latitude=fallback_latitude, longitude=fallback_longitude, zoom=19, left=left, top=top)
        rendered = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(rendered, "RGBA")
        draw.rounded_rectangle([12, 12, 420, 64], radius=8, fill=(255, 255, 255, 225), outline=(90, 90, 90, 120))
        draw.text((26, 24), "Emprise et orientation mesurées dans HelioNOP", fill=(30, 30, 30, 255))
        image_buffer = BytesIO()
        rendered.save(image_buffer, format="PNG")
        image_buffer.seek(0)
        report.canvas.drawImage(
            ImageReader(image_buffer),
            x,
            y,
            width=width,
            height=height,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
    except Exception as exc:
        report.note(
            f"La carte orientation/surface n'a pas pu être générée dans le PDF : {exc}",
            x=x,
            y=y + height - 10,
            width=width,
            size=8,
        )


def build_opportunity_note_pdf(
    *,
    site_inputs: SiteInputs,
    needs_inputs: NeedsInputs,
    sizing_inputs: SizingInputs,
    loop_inputs: LoopInputs,
    economic_inputs: CescEconomicInputs,
    opportunity_results: OpportunityResults,
    economic_results: CescEconomicResults,
    architectural_constraints: dict[str, Any] | None = None,
    surface_orientation: dict[str, Any] | None = None,
) -> bytes:
    """Construit le PDF de note d'opportunité à partir des résultats affichés."""

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    report = PdfReport(
        title="Note d'opportunité solaire thermique",
        subtitle=f"{site_inputs.project_name or 'Projet'} - généré le {generated_at}",
        landscape=True,
    )

    margin = 34
    content_width = report.page_width - 2 * margin
    half_w = (report.page_width - 84) / 2
    coverage = _coverage_ratio(opportunity_results)

    y = report.start_page()
    y = report.section_title("Synthèse technique du projet", x=margin, y=y)
    y = report.kpi_grid(
        [
            ("Besoin ECS total", f"{_fmt_number(opportunity_results.annual_total_ecs_energy_mwh, 1)} MWh/an"),
            ("Volume moyen à 60 °C", f"{_fmt_number(opportunity_results.average_daily_volume_l_60c, 0)} L/j"),
            ("Surface capteurs", f"{_fmt_number(opportunity_results.collectors.surface_m2, 1)} m²"),
            ("Taux couverture ECS", _percent(coverage, 0)),
            ("Production solaire", f"{_fmt_number(opportunity_results.estimated_solar_production_mwh_year, 1)} MWh/an"),
            ("Stockage proposé", f"{_fmt_number(opportunity_results.storage.total_volume_l, 0)} L"),
            ("Ratio V/S obtenu", f"{_fmt_number(opportunity_results.collectors.storage_ratio_l_m2, 0)} L/m²"),
            ("Coût chaleur solaire", _eur_mwh(economic_results.solar_heat_cost_eur_mwh, 1)),
        ],
        x=margin,
        y=y,
        width=content_width,
    )

    y -= 8
    y = report.section_title("Hypothèses principales", x=margin, y=y)
    report.table(
        [
            {"Paramètre": "Typologie", "Valeur": site_inputs.typology},
            {"Paramètre": "Commune / adresse", "Valeur": f"{site_inputs.city} - {site_inputs.address}".strip(" -")},
            {"Paramètre": "Nature du bâtiment", "Valeur": site_inputs.building_state},
            {"Paramètre": "Source de besoin ECS", "Valeur": site_inputs.data_source},
            {"Paramètre": "Température ECS cible", "Valeur": f"{_fmt_number(needs_inputs.ecs_temperature_c, 0)} °C"},
            {"Paramètre": "Méthode bouclage", "Valeur": loop_inputs.method},
            {"Paramètre": "Capteur solaire", "Valeur": sizing_inputs.collector_name},
            {"Paramètre": "Productivité solaire", "Valeur": f"{_fmt_number(sizing_inputs.productivity_kwh_m2_year, 0)} kWh/m².an"},
            {"Paramètre": "Ratio V/S cible", "Valeur": f"{_fmt_number(sizing_inputs.target_storage_ratio_l_m2, 0)} L/m²"},
            {"Paramètre": "Coût énergie référence", "Valeur": _eur_mwh(economic_inputs.reference_energy_cost_eur_mwh, 1)},
            {"Paramètre": "Durée d'analyse", "Valeur": f"{economic_inputs.years} ans"},
        ],
        x=margin,
        y=y,
        width=content_width,
        columns=["Paramètre", "Valeur"],
        max_rows=12,
        col_weights=[1.0, 2.0],
        font_size=8,
        row_height=13,
        show_header_rule=False,
    )
    report.draw_footer()

    y = report.start_page(title="Note d'opportunité - surface et orientation")
    y = report.section_title("Surface disponible et orientation solaire", x=margin, y=y)
    orientation_metrics = _surface_orientation_metrics(surface_orientation)
    surface_m2 = orientation_metrics.get("surface_m2")
    max_collector_surface_m2 = orientation_metrics.get("max_collector_surface_m2")
    orientation_label = str(orientation_metrics.get("orientation_label") or "non déterminée")
    orientation_from_south = orientation_metrics.get("orientation_from_south_deg")
    orientation_source = str(orientation_metrics.get("orientation_source") or "non déterminée")
    y = report.kpi_grid(
        [
            (
                "Surface au sol/toiture",
                f"{_fmt_number(float(surface_m2), 1)} m²" if isinstance(surface_m2, (float, int)) else "n.d.",
            ),
            ("Orientation solaire", orientation_label),
            (
                "Écart au sud",
                f"{_fmt_number(float(orientation_from_south), 0)}°"
                if isinstance(orientation_from_south, (float, int))
                else "n.d.",
            ),
            (
                "Surface capteurs max.",
                f"{_fmt_number(float(max_collector_surface_m2), 1)} m²"
                if isinstance(max_collector_surface_m2, (float, int))
                else "n.d.",
            ),
        ],
        x=margin,
        y=y,
        width=content_width,
    )
    y = report.note(
        f"Convention : 0° = plein sud, valeur négative = vers l'est, valeur positive = vers l'ouest. "
        f"Orientation retenue depuis : {orientation_source}. La surface capteurs maximale applique l'hypothèse "
        "2 m² de zone disponible par m² de capteur installé.",
        x=margin,
        y=y,
        width=content_width,
        size=8,
    )
    _draw_surface_orientation_map(
        report,
        surface_orientation,
        fallback_latitude=float(site_inputs.latitude),
        fallback_longitude=float(site_inputs.longitude),
        x=margin,
        y=54,
        width=content_width,
        height=300,
    )
    report.draw_footer()

    report.start_page(title="Note d'opportunité - besoins et prédimensionnement")
    y = report.page_height - 92
    left_x = margin
    right_x = 50 + half_w
    y = report.section_title("Répartition annuelle des besoins", x=margin, y=y)
    ecs_pie_rows = _ecs_pie_rows(opportunity_results)
    ecs_heating_pie_rows = _ecs_heating_pie_rows(opportunity_results)
    if ecs_pie_rows:
        report.pie_chart(
            ecs_pie_rows,
            x=left_x,
            y=y - 150,
            radius=58,
            title="ECS utile / bouclage sanitaire",
            label_col="Poste",
            value_col="MWh",
        )
    else:
        report.note(
            "Aucun bouclage sanitaire n'est pris en compte : le besoin ECS total est égal au besoin utile.",
            x=left_x,
            y=y - 16,
            width=half_w,
            size=8,
        )
    if ecs_heating_pie_rows:
        report.pie_chart(
            ecs_heating_pie_rows,
            x=right_x,
            y=y - 150,
            radius=58,
            title="ECS et chauffage estimé",
            label_col="Poste",
            value_col="MWh",
        )
    else:
        report.note(
            "Aucun poste chauffage distinct n'est intégré à cette note : le second camembert est volontairement masqué.",
            x=right_x,
            y=y - 16,
            width=half_w,
            size=8,
        )

    y = 330
    report.bar_chart(
        _monthly_chart_rows(opportunity_results),
        x=left_x,
        y=120,
        width=half_w,
        height=170,
        label_col="Mois",
        value_col="Besoin ECS",
        title="Besoin ECS mensuel",
        y_label="MWh/mois",
        x_label="Mois",
        color=CHART_COLORS[0],
    )
    report.bar_chart(
        _annual_balance_rows(opportunity_results),
        x=right_x,
        y=120,
        width=half_w,
        height=170,
        label_col="Poste",
        value_col="MWh/an",
        title="Bilan annuel besoin / production",
        y_label="MWh/an",
    )
    report.draw_footer()

    y = report.start_page(title="Note d'opportunité - détail mensuel")
    y = report.section_title("Tableau mensuel des besoins", x=margin, y=y)
    y = report.table(
        _monthly_rows(opportunity_results),
        x=margin,
        y=y,
        width=content_width,
        columns=["Mois", "Volume moyen (L/j)", "Besoin utile (MWh)", "Bouclage (MWh)", "Chauffage (MWh)", "Total ECS (MWh)"],
        max_rows=13,
        col_weights=[0.8, 1.4, 1.2, 1.1, 1.1, 1.2],
        font_size=8,
        row_height=15,
        show_header_rule=False,
    )
    report.note(
        "Le volume moyen est exprimé en litres par jour équivalents à 60 °C. Il sert de référence au prédimensionnement solaire.",
        x=margin,
        y=y - 4,
        width=content_width,
        size=8,
    )
    report.draw_footer()

    y = report.start_page(title="Note d'opportunité - économie")
    y = report.section_title("Indicateurs économiques", x=margin, y=y)
    y = report.kpi_grid(
        [
            ("Investissement", _eur(economic_results.investment_cost_eur, 0)),
            ("Aides", f"{_eur(economic_results.aid_total_eur, 0)} ({_percent(economic_results.aid_rate, 0)})"),
            ("Reste à charge", _eur(economic_results.net_investment_eur, 0)),
            ("Économies annuelles", _eur(economic_results.annual_savings_eur, 0)),
            ("Temps retour brut", f"{_fmt_number(economic_results.raw_payback_years, 1)} ans"),
            ("Économies période", _eur(economic_results.savings_over_period_eur, 0)),
            ("Coût chaleur P1'+P2+P4", _total_heat_cost_label(economic_results)),
            ("Référence moyenne", _eur_mwh(economic_results.average_reference_energy_cost_eur_mwh, 1)),
        ],
        x=margin,
        y=y,
        width=content_width,
    )
    y -= 4
    report.section_title("Flux et coûts de chaleur", x=margin, y=y)
    chart_gap = 34
    chart_w = (content_width - chart_gap) / 2
    heat_chart_x = margin + chart_w + chart_gap
    _draw_cashflow_chart(
        report,
        _cashflow_chart_rows(economic_inputs, economic_results),
        x=margin,
        y=84,
        width=chart_w,
        height=175,
    )
    _draw_heat_cost_comparison_chart(
        report,
        economic_results,
        x=heat_chart_x,
        y=84,
        width=chart_w,
        height=175,
    )
    report.draw_footer()

    y = report.start_page(title="Note d'opportunité - détail économique")
    y = report.section_title("Détail des postes économiques", x=margin, y=y)
    report.table(
        _cost_table_rows(economic_results),
        x=margin,
        y=y,
        width=content_width,
        columns=["Famille", "Poste", "Coût total", "Aide", "Net", "Coût chaleur"],
        max_rows=6,
        col_weights=[1.45, 1.65, 1.0, 0.9, 0.9, 1.15],
        font_size=8,
        row_height=16,
        show_header_rule=False,
    )
    report.note(
        "P1 correspond aux auxiliaires électriques, P2 au suivi-maintenance, et P4 à l'investissement net aidé ramené à la chaleur utile solaire.",
        x=margin,
        y=300,
        width=content_width,
        size=8,
    )

    y = report.start_page(title="Note d'opportunité - contraintes architecturales")
    y = report.section_title("Analyse des contraintes architecturales", x=margin, y=y)
    if isinstance(architectural_constraints, dict):
        project_type = str(architectural_constraints.get("project_type") or "-")
        result = architectural_constraints.get("result")
        has_protection = bool(result.get("has_protection")) if isinstance(result, dict) else None
        status = "Protections détectées" if has_protection else "Aucune protection détectée"
        if has_protection is None:
            status = "Analyse non réalisée"
        y = report.kpi_grid(
            [
                ("Configuration", project_type),
                ("Statut", status),
                ("Latitude", _fmt_number(float(architectural_constraints.get("latitude") or 0.0), 6)),
                ("Longitude", _fmt_number(float(architectural_constraints.get("longitude") or 0.0), 6)),
            ],
            x=margin,
            y=y,
            width=content_width,
        )
    else:
        y = report.note(
            "Aucune analyse de contraintes architecturales n'est enregistrée dans ce projet.",
            x=margin,
            y=y,
            width=content_width,
            size=8,
        )
    table_y = y - 4
    rows = _architectural_count_rows(architectural_constraints)
    if rows:
        report.table(
            rows,
            x=margin,
            y=table_y,
            width=content_width,
            columns=["Catégorie", "Protection", "Objets détectés"],
            max_rows=4,
            col_weights=[0.8, 2.5, 0.9],
            font_size=8,
            row_height=14,
            show_header_rule=False,
        )
    if isinstance(architectural_constraints, dict):
        result = architectural_constraints.get("result")
        has_protection = bool(result.get("has_protection")) if isinstance(result, dict) else None
        if has_protection is False:
            report.note(
                "Conclusion : aucune servitude AC1, AC2 ou AC4 n'a été détectée au droit du point dans les données interrogées.",
                x=margin,
                y=table_y - 74,
                width=content_width,
                size=9,
            )
    _draw_architectural_map(
        report,
        architectural_constraints,
        x=margin,
        y=58,
        width=content_width,
        height=250,
    )

    return report.finish()
