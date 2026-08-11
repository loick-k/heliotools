from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pandas as pd
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Image,
)

from ..pdf_report import draw_report_footer, draw_report_header
from ..ui_surface_orientation import GEOPORTAIL_ORTHO_WMTS
from .engine import ADEME_REFERENCE_URL, ADEME_REFERENCE_VIGILANCES, CalculationInputs, CalculationResults

try:  # pragma: no cover - optional rendering dependency
    from PIL import Image as PILImage
    from PIL import ImageDraw
except ModuleNotFoundError:  # pragma: no cover
    PILImage = None
    ImageDraw = None


TEAL = colors.HexColor("#0B6F70")
DARK = colors.HexColor("#17324D")
ORANGE = colors.HexColor("#E58A2A")
SOLAR_YELLOW = colors.HexColor("#FCBF24")
LIGHT = colors.HexColor("#EEF5F4")
GREY = colors.HexColor("#667085")
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
ADEME_LOGO = ASSETS_DIR / "Logo_ADEME.png"
CHATEAUBRIANT_RCU_PHOTO = ASSETS_DIR / "heliorc_chateaubriant_rcu.jpg"
CHATEAUBRIANT_RCU_CAPTION = "Installation solaire thermique du RCU de Chateaubriant (44)"
SOLAR_NETWORK_SCHEMA = ASSETS_DIR / "heliorc_schema_reseau_solaire.png"
SOLAR_NETWORK_SCHEMA_CAPTION = "Principe d'intégration d'une centrale solaire thermique sur réseau de chaleur"


def _money(value: float) -> str:
    return f"{value:,.0f} € HT".replace(",", " ")


def _number(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", " ")


def _header_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    width, height = A4
    draw_report_header(
        canvas,
        title="HelioRC - note d'opportunité",
        subtitle="Solaire thermique sur réseau de chaleur urbain",
        width=width,
        height=height,
    )
    if ADEME_LOGO.exists():
        try:
            canvas.drawImage(
                str(ADEME_LOGO),
                width - 260,
                height - 58,
                width=92,
                height=42,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass
    draw_report_footer(canvas, page_number=doc.page, width=width, footer_text="HelioTools - HelioRC")
    canvas.restoreState()


def _chart(
    monthly: pd.DataFrame,
    *,
    needs_col: str = "Besoins RCU (MWh)",
    title: str = "Couverture mensuelle des besoins RCU",
) -> Drawing:
    drawing = Drawing(500, 220)
    x0 = 45
    y0 = 35
    height = 145
    width = 410
    needs = monthly[needs_col].astype(float).tolist()
    solar = monthly["Production solaire (MWh)"].astype(float).tolist()
    solar_covered = [min(max(solar_value, 0.0), max(need, 0.0)) for need, solar_value in zip(needs, solar)]
    backup = [max(need - solar_value, 0.0) for need, solar_value in zip(needs, solar_covered)]
    y_max = max(needs) * 1.12 if max(needs) > 0 else 1.0

    drawing.add(String(x0, 205, title, fontName="Helvetica-Bold", fontSize=10))
    drawing.add(String(x0, 187, "MWh/mois", fontName="Helvetica", fontSize=7, fillColor=GREY))
    drawing.add(Line(x0, y0, x0 + width, y0, strokeColor=colors.black, strokeWidth=0.8))
    drawing.add(Line(x0, y0, x0, y0 + height, strokeColor=colors.black, strokeWidth=0.8))

    for index in range(5):
        value = y_max * index / 4
        y = y0 + height * index / 4
        drawing.add(Line(x0, y, x0 + width, y, strokeColor=colors.HexColor("#D9E1EF"), strokeWidth=0.4))
        drawing.add(String(x0 - 24, y - 2, f"{value:.0f}", fontName="Helvetica", fontSize=7, fillColor=GREY))

    bar_gap = 5
    bar_width = (width - bar_gap * 13) / 12
    month_labels = [str(month)[:3] for month in monthly["Mois"].tolist()]
    for index, (solar_value, backup_value, label) in enumerate(zip(solar_covered, backup, month_labels)):
        x = x0 + bar_gap + index * (bar_width + bar_gap)
        solar_height = height * solar_value / y_max
        backup_height = height * backup_value / y_max
        drawing.add(
            Rect(
                x,
                y0,
                bar_width,
                solar_height,
                fillColor=SOLAR_YELLOW,
                strokeColor=colors.HexColor("#334155"),
                strokeWidth=0.25,
            )
        )
        drawing.add(
            Rect(
                x,
                y0 + solar_height,
                bar_width,
                backup_height,
                fillColor=colors.HexColor("#98A2B3"),
                strokeColor=colors.HexColor("#334155"),
                strokeWidth=0.25,
            )
        )
        drawing.add(String(x - 1, y0 - 13, label, fontName="Helvetica", fontSize=6.5, fillColor=GREY))

    legend = Legend()
    legend.x = 305
    legend.y = 205
    legend.dx = 8
    legend.dy = 8
    legend.fontName = "Helvetica"
    legend.fontSize = 8
    legend.colorNamePairs = [
        (SOLAR_YELLOW, "Couverture solaire thermique"),
        (colors.HexColor("#98A2B3"), "Appoint / réseau existant"),
    ]
    drawing.add(legend)
    return drawing


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _foncier_conclusion(
    *,
    results: CalculationResults,
    sizing_context: dict[str, Any] | None,
    surface_orientation: dict[str, Any] | None,
) -> list[list[str]]:
    metrics = surface_orientation.get("metrics", {}) if isinstance(surface_orientation, dict) else {}
    surface_m2 = _as_float(metrics.get("surface_m2")) if isinstance(metrics, dict) else None
    max_collector_m2 = _as_float(metrics.get("max_collector_surface_m2")) if isinstance(metrics, dict) else None
    available_ground_m2 = surface_m2
    if available_ground_m2 is None and isinstance(sizing_context, dict):
        available_ground_m2 = _as_float(sizing_context.get("available_ground_area_m2"))
    required_ground_m2 = max(0.0, results.land_area_ha * 10_000.0)

    rows: list[list[str]] = []
    if available_ground_m2 is not None and available_ground_m2 > 0:
        rows.append(["Surface au sol mesurée", f"{available_ground_m2:.0f} m²"])
        if max_collector_m2 is not None and max_collector_m2 > 0:
            rows.append(["Surface capteurs maximale estimée", f"{max_collector_m2:.0f} m²"])
        rows.append(["Emprise foncière requise par le calcul", f"{required_ground_m2:.0f} m²"])
        if available_ground_m2 >= required_ground_m2:
            conclusion = "La surface mesurée semble compatible avec l'emprise foncière estimée à ce stade."
        else:
            conclusion = (
                "La surface mesurée est inférieure à l'emprise foncière estimée. Le dimensionnement devra être "
                "réduit ou le foncier disponible devra être confirmé."
            )
    else:
        conclusion = "Aucune surface disponible n'a été mesurée dans l'onglet Orientation / surface."
    rows.append(["Conclusion foncier", conclusion])
    return rows


def _architectural_conclusion(architectural_constraints: dict[str, Any] | None) -> list[list[str]]:
    if not isinstance(architectural_constraints, dict):
        return [["Conclusion contraintes architecturales", "L'analyse des servitudes patrimoniales n'a pas été renseignée."]]
    result = architectural_constraints.get("result")
    if not isinstance(result, dict):
        return [["Conclusion contraintes architecturales", "L'analyse des servitudes patrimoniales n'a pas été lancée."]]
    counts = result.get("counts")
    if not isinstance(counts, dict):
        return [["Conclusion contraintes architecturales", "Le résultat patrimonial enregistré n'est pas exploitable."]]
    total = sum(int(value or 0) for value in counts.values())
    if total <= 0:
        conclusion = "Aucune servitude AC1, AC2 ou AC4 n'a été détectée au droit du point dans les données interrogées."
    else:
        details = ", ".join(f"{key} : {int(value or 0)}" for key, value in counts.items())
        conclusion = f"{total} élément(s) patrimonial(aux) détecté(s) dans les données interrogées ({details})."
    return [["Conclusion contraintes architecturales", conclusion]]


def _simple_key_value_table(rows: list[list[str]], styles: dict[str, Any]) -> Table:
    table_rows = [[Paragraph(str(label), styles["BodyText"]), Paragraph(str(value), styles["BodyText"])] for label, value in rows]
    table = Table(table_rows, colWidths=[5.4 * cm, 11.1 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E1E0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _filtered_project_warnings(warnings: list[str]) -> list[str]:
    hidden_fragments = (
        "Mode strict",
        "200 m/MW",
    )
    filtered: list[str] = []
    for warning in warnings:
        text = str(warning)
        if any(fragment in text for fragment in hidden_fragments):
            continue
        filtered.append(text)
    return filtered


def _surface_drawings(surface_orientation: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(surface_orientation, dict):
        return []
    drawings = surface_orientation.get("drawings")
    if isinstance(drawings, list):
        return [feature for feature in drawings if isinstance(feature, dict)]
    nested = surface_orientation.get("surface_orientation")
    if isinstance(nested, dict) and isinstance(nested.get("drawings"), list):
        return [feature for feature in nested["drawings"] if isinstance(feature, dict)]
    return []


def _feature_lon_lat_coordinates(feature: dict[str, Any]) -> list[list[float]]:
    geometry = feature.get("geometry") or {}
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        if coordinates and isinstance(coordinates[0], list) and coordinates[0] and isinstance(coordinates[0][0], list):
            coordinates = coordinates[0]
    elif geometry_type != "LineString":
        return []
    parsed: list[list[float]] = []
    for coordinate in coordinates:
        if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2:
            try:
                parsed.append([float(coordinate[0]), float(coordinate[1])])
            except (TypeError, ValueError):
                continue
    return parsed


def _surface_polygon_and_line(drawings: list[dict[str, Any]]) -> tuple[list[list[float]], list[list[float]]]:
    polygons = [
        _feature_lon_lat_coordinates(feature)
        for feature in drawings
        if (feature.get("geometry") or {}).get("type") == "Polygon"
    ]
    lines = [
        _feature_lon_lat_coordinates(feature)
        for feature in drawings
        if (feature.get("geometry") or {}).get("type") == "LineString"
    ]
    return (polygons[-1] if polygons else []), (lines[-1] if lines else [])


def _lon_lat_to_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    sin_lat = math.sin(math.radians(lat))
    world_size = 256 * (2**zoom)
    x = (lon + 180.0) / 360.0 * world_size
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * world_size
    return x, y


def _choose_surface_zoom(coords: list[list[float]], width_px: int, height_px: int) -> int:
    if len(coords) < 2:
        return 18
    margin_x = 100
    margin_y = 70
    for zoom in range(19, 11, -1):
        pixels = [_lon_lat_to_pixel(lon, lat, zoom) for lon, lat in coords]
        x_values = [point[0] for point in pixels]
        y_values = [point[1] for point in pixels]
        if max(x_values) - min(x_values) <= width_px - 2 * margin_x and max(y_values) - min(y_values) <= height_px - 2 * margin_y:
            return zoom
    return 12


def _fetch_tile(z: int, x: int, y: int) -> Any | None:
    if PILImage is None:
        return None
    url = GEOPORTAIL_ORTHO_WMTS.format(z=z, x=x, y=y)
    request = Request(url, headers={"User-Agent": "HelioTools PDF export"})
    try:
        with urlopen(request, timeout=6) as response:
            tile_bytes = response.read()
    except (OSError, URLError, TimeoutError, ValueError):
        return None
    try:
        return PILImage.open(BytesIO(tile_bytes)).convert("RGB")
    except Exception:
        return None


def _render_surface_snapshot_png(
    *,
    surface_orientation: dict[str, Any] | None,
    project: dict[str, Any],
    width_px: int = 980,
    height_px: int = 460,
) -> bytes | None:
    if PILImage is None or ImageDraw is None:
        return None
    polygon, line = _surface_polygon_and_line(_surface_drawings(surface_orientation))
    focus_coords = polygon or line
    if len(focus_coords) < 2:
        return None

    zoom = _choose_surface_zoom(focus_coords, width_px, height_px)
    bbox_pixels = [_lon_lat_to_pixel(lon, lat, zoom) for lon, lat in focus_coords]
    x_min = min(point[0] for point in bbox_pixels)
    x_max = max(point[0] for point in bbox_pixels)
    y_min = min(point[1] for point in bbox_pixels)
    y_max = max(point[1] for point in bbox_pixels)
    center_x = (x_min + x_max) / 2.0
    center_y = (y_min + y_max) / 2.0
    crop_left = center_x - width_px / 2.0
    crop_top = center_y - height_px / 2.0
    first_tile_x = math.floor(crop_left / 256)
    first_tile_y = math.floor(crop_top / 256)
    last_tile_x = math.floor((crop_left + width_px) / 256)
    last_tile_y = math.floor((crop_top + height_px) / 256)

    mosaic = PILImage.new("RGB", (width_px, height_px), "#E5E7EB")
    fetched_tiles = 0
    for tile_x in range(first_tile_x, last_tile_x + 1):
        for tile_y in range(first_tile_y, last_tile_y + 1):
            tile = _fetch_tile(zoom, tile_x, tile_y)
            if tile is None:
                continue
            fetched_tiles += 1
            paste_x = int(tile_x * 256 - crop_left)
            paste_y = int(tile_y * 256 - crop_top)
            mosaic.paste(tile, (paste_x, paste_y))
    if fetched_tiles == 0:
        return None

    overlay = PILImage.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def to_image_xy(coord: list[float]) -> tuple[float, float]:
        x, y = _lon_lat_to_pixel(float(coord[0]), float(coord[1]), zoom)
        return x - crop_left, y - crop_top

    if len(polygon) >= 3:
        points = [to_image_xy(coord) for coord in polygon]
        draw.polygon(points, fill=(34, 178, 166, 70), outline=(34, 178, 166, 255))
        if hasattr(draw, "line"):
            closed = points + [points[0]]
            draw.line(closed, fill=(34, 178, 166, 255), width=4)
    if len(line) >= 2:
        draw.line([to_image_xy(coord) for coord in line], fill=(252, 191, 36, 255), width=7)

    project_lat = _as_float(project.get("latitude") or project.get("project_latitude"))
    project_lon = _as_float(project.get("longitude") or project.get("project_longitude"))
    if project_lat is not None and project_lon is not None:
        marker_x, marker_y = to_image_xy([project_lon, project_lat])
        radius = 9
        draw.ellipse(
            (marker_x - radius, marker_y - radius, marker_x + radius, marker_y + radius),
            fill=(231, 71, 61, 240),
            outline=(255, 255, 255, 255),
            width=3,
        )

    rendered = PILImage.alpha_composite(mosaic.convert("RGBA"), overlay).convert("RGB")
    output = BytesIO()
    rendered.save(output, format="PNG")
    return output.getvalue()


def _surface_snapshot_flowables(
    *,
    surface_orientation: dict[str, Any] | None,
    project: dict[str, Any],
    styles: dict[str, Any],
) -> list[Any]:
    if not _surface_drawings(surface_orientation):
        return []
    image_bytes = _render_surface_snapshot_png(surface_orientation=surface_orientation, project=project)
    if image_bytes is None:
        return [
            Paragraph(
                "Vue du terrain sélectionné : non disponible dans l'export. Les mesures chiffrées restent reportées ci-dessus.",
                styles["SmallHelio"],
            )
        ]
    image = Image(BytesIO(image_bytes), width=16.5 * cm, height=7.75 * cm)
    return [
        Paragraph("Vue du terrain sélectionné", styles["SectionHelio"]),
        image,
        Paragraph("Fond cartographique : Géoportail orthophotos / IGN. Emprise dessinée en bleu-vert, orientation en jaune.", styles["SmallHelio"]),
    ]


def _intro_visual_cell(
    *,
    image_path: Path,
    caption: str,
    styles: dict[str, Any],
    max_width: float,
    max_height: float,
) -> list[Any]:
    return [
        Image(str(image_path), width=max_width, height=max_height, kind="proportional"),
        Paragraph(caption, styles["PhotoCaptionHelio"]),
    ]


def build_opportunity_note(
    *,
    project: dict[str, Any],
    inputs: CalculationInputs,
    results: CalculationResults,
    monthly: pd.DataFrame,
    sizing_context: dict[str, Any] | None = None,
    surface_orientation: dict[str, Any] | None = None,
    architectural_constraints: dict[str, Any] | None = None,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2.35 * cm,
        bottomMargin=1.45 * cm,
        title=f"HelioRC - {project.get('project_name', 'Projet')}",
        author=str(project.get("analyst", "")),
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleHelio",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=DARK,
            alignment=TA_LEFT,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHelio",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=TEAL,
            spaceBefore=8,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallHelio",
            parent=styles["BodyText"],
            fontSize=8.5,
            leading=11,
            textColor=GREY,
        )
    )
    styles.add(
        ParagraphStyle(
            name="PhotoCaptionHelio",
            parent=styles["SmallHelio"],
            alignment=TA_CENTER,
            spaceBefore=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CenterKpi",
            parent=styles["BodyText"],
            alignment=TA_CENTER,
            fontSize=10,
            leading=13,
        )
    )

    story: list[Any] = []
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Note d'opportunité", styles["TitleHelio"]))
    story.append(
        Paragraph(
            "Intégration d'une centrale solaire thermique sur réseau de chaleur urbain",
            styles["Heading3"],
        )
    )
    story.append(Paragraph(f"Documentation de référence ADEME : {ADEME_REFERENCE_URL}", styles["SmallHelio"]))
    intro_visuals: list[list[Any] | str] = []
    if SOLAR_NETWORK_SCHEMA.exists():
        intro_visuals.append(
            _intro_visual_cell(
                image_path=SOLAR_NETWORK_SCHEMA,
                caption=SOLAR_NETWORK_SCHEMA_CAPTION,
                styles=styles,
                max_width=7.7 * cm,
                max_height=4.65 * cm,
            )
        )
    else:
        intro_visuals.append("")
    if CHATEAUBRIANT_RCU_PHOTO.exists():
        intro_visuals.append(
            _intro_visual_cell(
                image_path=CHATEAUBRIANT_RCU_PHOTO,
                caption=CHATEAUBRIANT_RCU_CAPTION,
                styles=styles,
                max_width=7.7 * cm,
                max_height=4.65 * cm,
            )
        )
    else:
        intro_visuals.append("")
    if any(intro_visuals):
        visual_table = Table([intro_visuals], colWidths=[8.05 * cm, 8.05 * cm])
        visual_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (0, 0), "LEFT"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(Spacer(1, 0.15 * cm))
        story.append(visual_table)
    story.append(Spacer(1, 0.2 * cm))

    project_rows = [
        ["Projet", str(project.get("project_name", "Non renseigné"))],
        ["Maître d'ouvrage / territoire", str(project.get("client", "Non renseigné"))],
        ["Référence / ID Airtable", str(project.get("airtable_id", "Non renseigné"))],
        ["Localisation", inputs.location_label],
        ["Analyste", str(project.get("analyst", "Non renseigné"))],
        ["Date", str(project.get("date", ""))],
    ]
    table = Table(project_rows, colWidths=[5.4 * cm, 11.1 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("TEXTCOLOR", (0, 0), (0, -1), DARK),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E1E0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.35 * cm))

    display_annual_need = results.annual_need_mwh
    display_solar_fraction = results.solar_fraction
    calculation_solar_fraction = results.solar_fraction
    connection_mode = ""
    if isinstance(sizing_context, dict):
        connection_mode = str(sizing_context.get("solar_connection_mode") or "")
        if isinstance(sizing_context.get("annual_total_need_mwh"), (float, int)):
            display_annual_need = float(sizing_context["annual_total_need_mwh"])
        if isinstance(sizing_context.get("global_solar_fraction"), (float, int)):
            display_solar_fraction = float(sizing_context["global_solar_fraction"])
        if isinstance(sizing_context.get("calculation_solar_fraction"), (float, int)):
            calculation_solar_fraction = float(sizing_context["calculation_solar_fraction"])

    story.append(Paragraph("1. Hypothèses principales", styles["SectionHelio"]))
    assumptions = [
        ["Régime moyen", f"{inputs.regime_label} - {inputs.mean_network_temperature_c:.0f} °C"],
        ["Dimensionnement au talon", f"{inputs.base_load_fraction:.0%}"],
        ["Besoins annuels du RCU", f"{_number(display_annual_need)} MWh/an"],
        ["Part des besoins mai-septembre", f"{results.summer_need_share:.1%}"],
        ["Gisement horizontal", f"{_number(results.annual_horizontal_irradiation_kwh_m2)} kWh/m².an"],
        ["Zone d'aide ADEME", f"{inputs.zone}"],
    ]
    if connection_mode.startswith("Installation décentralisée"):
        assumptions.append(["Mode d'implantation", "Décentralisé sur branche du réseau"])
        assumptions.append(["Fraction solaire branche", f"{calculation_solar_fraction:.1%}"])
    assumptions_table = Table(assumptions, colWidths=[7.5 * cm, 9.0 * cm])
    assumptions_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E1E0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(assumptions_table)

    story.append(Paragraph("2. Résultats techniques", styles["SectionHelio"]))
    technical = [
        ["Surface de capteurs", f"{_number(results.collector_area_m2)} m²", "Production solaire", f"{_number(results.annual_solar_production_mwh)} MWh/an"],
        ["Productivité", f"{_number(results.productivity_kwh_m2_year)} kWh/m².an", "Fraction solaire RCU global", f"{display_solar_fraction:.1%}"],
        ["Stockage journalier", f"{_number(results.storage_volume_m3)} m³", "Emprise foncière", f"{results.land_area_ha:.2f} ha"],
        [
            Paragraph("Distance maximum<br/>de raccordement conseillée", styles["BodyText"]),
            f"{_number(results.recommended_connection_distance_m)} m",
            "Panneaux de 15 m²",
            f"{results.panel_count_15m2}",
        ],
    ]
    technical_table = Table(technical, colWidths=[4.2 * cm, 4.0 * cm, 4.2 * cm, 4.1 * cm])
    technical_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("BACKGROUND", (2, 0), (2, -1), LIGHT),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.7),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E1E0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(technical_table)
    story.append(Spacer(1, 0.15 * cm))
    project_conclusions_table = _simple_key_value_table(
        _foncier_conclusion(
            results=results,
            sizing_context=sizing_context,
            surface_orientation=surface_orientation,
        )
        + _architectural_conclusion(architectural_constraints),
        styles,
    )
    story.append(KeepTogether([project_conclusions_table]))
    story.append(Spacer(1, 0.15 * cm))
    story.extend(
        _surface_snapshot_flowables(
            surface_orientation=surface_orientation,
            project=project,
            styles=styles,
        )
    )
    story.append(Spacer(1, 0.15 * cm))
    story.append(_chart(monthly))
    if "Besoins branche sélectionnée (MWh)" in monthly.columns:
        story.append(Spacer(1, 0.12 * cm))
        story.append(
            _chart(
                monthly,
                needs_col="Besoins branche sélectionnée (MWh)",
                title="Production solaire thermique sur besoins de la branche",
            )
        )

    economics = [
        ["CAPEX indicatif", _money(results.capex_eur)],
        ["Coût surfacique", f"{_number(results.unit_capex_eur_m2)} € HT/m²"],
        ["Aide ADEME indicative", _money(results.ademe_aid_eur)],
        ["Autres aides", _money(results.other_aid_eur)],
        ["Reste à charge", _money(results.remaining_cost_eur)],
        ["Taux d'aide total", f"{results.aid_rate:.1%}"],
        ["Coût de chaleur aidé (LCOH)", f"{results.lcoh_aided_eur_mwh:.1f} € HT/MWh"],
        ["Décomposition P1' / P2-P3 / P4", f"{results.p1_eur_mwh:.1f} / {results.opex_eur_mwh:.1f} / {results.capital_recovery_eur_mwh:.1f} € HT/MWh"],
    ]
    economics_table = Table(economics, colWidths=[8.2 * cm, 8.3 * cm])
    economics_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, -2), (1, -2), "Helvetica-Bold"),
                ("TEXTCOLOR", (1, -2), (1, -2), TEAL),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E1E0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(
        KeepTogether(
            [
                Paragraph("3. Première analyse économique", styles["SectionHelio"]),
                economics_table,
            ]
        )
    )

    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph("4. Profil mensuel", styles["SectionHelio"]))
    monthly_rows = [["Mois", "Besoins RCU", "Production solaire", "Couverture"]]
    for _, row in monthly.iterrows():
        monthly_rows.append(
            [
                str(row["Mois"]),
                f"{float(row['Besoins RCU (MWh)']):.1f} MWh",
                f"{float(row['Production solaire (MWh)']):.1f} MWh",
                f"{float(row['Taux de couverture mensuel']):.1%}",
            ]
        )
    monthly_table = Table(monthly_rows, colWidths=[4.0 * cm, 4.2 * cm, 4.7 * cm, 3.6 * cm], repeatRows=1)
    monthly_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(KeepTogether([monthly_table]))

    story.append(Paragraph("5. Vigilances et suites à donner", styles["SectionHelio"]))
    warning_flowables = []
    project_warnings = _filtered_project_warnings(results.warnings)
    if project_warnings:
        warning_flowables.append(Paragraph("Vigilances propres au projet", styles["Heading3"]))
    for warning in project_warnings:
        warning_flowables.append(Paragraph(f"- {warning}", styles["BodyText"]))
        warning_flowables.append(Spacer(1, 0.08 * cm))
    warning_flowables.append(Paragraph("Garde-fous issus de la documentation ADEME", styles["Heading3"]))
    for warning in ADEME_REFERENCE_VIGILANCES:
        warning_flowables.append(Paragraph(f"- {warning}", styles["BodyText"]))
        warning_flowables.append(Spacer(1, 0.08 * cm))
    warning_flowables.extend(
        [
            Spacer(1, 0.15 * cm),
            Paragraph(
                "La présente note fournit des ordres de grandeur de prédimensionnement. Elle ne remplace pas une étude de faisabilité menée par un bureau d'études compétent, notamment pour la modélisation dynamique, l'hydraulique, le foncier, le raccordement, le phasage et l'instruction des aides.",
                styles["SmallHelio"],
            ),
        ]
    )
    story.append(KeepTogether(warning_flowables))

    story.append(Spacer(1, 0.35 * cm))
    story.append(
        Paragraph(
            "Méthode de prédimensionnement issue de la documentation ADEME. Plage de référence principale : capteurs plans vitrés haute performance, stockage journalier, surface de capteurs > 100 m² et fraction solaire entre 10 et 30 %. En dehors de ces valeurs, la précision attendue diminue et le résultat doit être confirmé par une étude de faisabilité.",
            styles["SmallHelio"],
        )
    )

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()
