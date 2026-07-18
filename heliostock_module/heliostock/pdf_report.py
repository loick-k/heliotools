from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"

TEXT_COLOR = (0.18, 0.19, 0.25)
MUTED_COLOR = (0.47, 0.49, 0.55)
GRID_COLOR = (0.88, 0.90, 0.94)
CARD_FILL = (0.97, 0.98, 1.0)
CARD_STROKE = (0.86, 0.89, 0.94)
ATLANSUN_BLUE = (0.27, 0.42, 0.69)
ATLANSUN_YELLOW = (0.98, 0.72, 0.08)
CHART_COLORS = [
    (0.27, 0.42, 0.69),
    (0.98, 0.72, 0.08),
    (0.00, 0.70, 0.62),
    (0.95, 0.31, 0.32),
    (0.46, 0.66, 0.86),
    (0.56, 0.61, 0.67),
]


def _safe_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("€", "EUR")
        .replace("²", "2")
        .replace("³", "3")
        .replace("×", "x")
        .replace("–", "-")
        .replace("—", "-")
    )


def _fmt_number(value: Any, digits: int = 0, suffix: str = "") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n.d."
    if pd.isna(numeric):
        return "n.d."
    formatted = f"{numeric:,.{digits}f}".replace(",", " ")
    return f"{formatted} {suffix}".strip()


def _numeric(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(numeric) else numeric


def _short_label(value: object, max_chars: int = 26) -> str:
    try:
        if pd.notna(value) and float(value).is_integer():
            label = str(int(float(value)))
            return label if len(label) <= max_chars else f"{label[: max_chars - 1]}..."
    except (TypeError, ValueError):
        pass
    label = str(value or "Non renseigné")
    return label if len(label) <= max_chars else f"{label[: max_chars - 1]}..."


def draw_report_header(canvas, *, title: str, subtitle: str = "", width: float, height: float) -> None:
    if ATLANSUN_LOGO.exists():
        try:
            canvas.drawImage(
                str(ATLANSUN_LOGO),
                width - 154,
                height - 52,
                width=120,
                height=35,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(34, height - 38, _safe_text(title))
    if subtitle:
        canvas.setFont("Helvetica", 9)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.drawString(34, height - 56, _safe_text(subtitle)[:120])
    canvas.setStrokeColorRGB(*GRID_COLOR)
    canvas.line(34, height - 68, width - 34, height - 68)


def draw_report_footer(
    canvas,
    *,
    page_number: int,
    width: float,
    footer_text: str = "HelioTools - document généré automatiquement",
) -> None:
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(*MUTED_COLOR)
    canvas.drawString(34, 24, _safe_text(footer_text))
    canvas.drawRightString(width - 34, 24, f"Page {page_number}")


def draw_wrapped_text(
    canvas,
    text: str,
    *,
    x: float,
    y: float,
    width: float | None = None,
    max_chars: int | None = None,
    leading: float = 11,
    font: str = "Helvetica",
    size: int = 8,
) -> float:
    canvas.setFont(font, size)
    line = ""
    for word in _safe_text(text).split():
        candidate = f"{line} {word}".strip()
        too_wide = bool(width and line and canvas.stringWidth(candidate, font, size) > width)
        too_long = bool(max_chars and len(candidate) > max_chars and line)
        if too_wide or too_long:
            canvas.drawString(x, y, line)
            y -= leading
            line = word
        else:
            line = candidate
    if line:
        canvas.drawString(x, y, line)
        y -= leading
    return y


def draw_kpi_cards(canvas, metrics: list[tuple[str, str]], *, x: float, y: float, width: float, cols: int = 4) -> float:
    if not metrics:
        return y
    cols = min(cols, max(1, len(metrics)))
    gap = 10
    card_w = (width - gap * (cols - 1)) / cols
    card_h = 54
    for idx, (label, value) in enumerate(metrics):
        col = idx % cols
        row = idx // cols
        cx = x + col * (card_w + gap)
        cy = y - row * (card_h + 10)
        canvas.setFillColorRGB(*CARD_FILL)
        canvas.setStrokeColorRGB(*CARD_STROKE)
        canvas.roundRect(cx, cy - card_h, card_w, card_h, 7, fill=1, stroke=1)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(cx + 10, cy - 16, _safe_text(label)[:34])
        canvas.setFillColorRGB(*TEXT_COLOR)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(cx + 10, cy - 40, _safe_text(value)[:27])
    rows = math.ceil(len(metrics) / cols)
    return y - rows * (card_h + 10)


def draw_bar_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    label_col: str,
    value_col: str,
    color: tuple[float, float, float],
    max_items: int = 10,
) -> None:
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, _safe_text(title))
    if data.empty or label_col not in data or value_col not in data:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart = data[[label_col, value_col]].copy().head(max_items)
    chart[value_col] = chart[value_col].map(_numeric)
    max_value = max(chart[value_col].max(), 1.0)
    canvas.setStrokeColorRGB(*GRID_COLOR)
    for step in range(5):
        gy = y + (height * step / 4)
        canvas.line(x + 28, gy, x + width, gy)
    bar_area_w = width - 36
    bar_w = min(22, max(8, bar_area_w / max(len(chart), 1) * 0.56))
    slot = bar_area_w / max(len(chart), 1)
    canvas.setFont("Helvetica", 7)
    for idx, row in chart.iterrows():
        value = _numeric(row[value_col])
        bx = x + 32 + idx * slot + (slot - bar_w) / 2
        bh = height * value / max_value
        canvas.setFillColorRGB(*color)
        canvas.rect(bx, y, bar_w, bh, fill=1, stroke=0)
        canvas.setFillColorRGB(0.38, 0.4, 0.48)
        canvas.drawCentredString(bx + bar_w / 2, y - 9, _short_label(row[label_col], 10))
        canvas.drawCentredString(bx + bar_w / 2, y + bh + 3, _fmt_number(value))


def draw_line_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    x_col: str,
    y_col: str,
    y_axis_label: str = "",
) -> None:
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, _safe_text(title))
    if data.empty or x_col not in data or y_col not in data:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart = data[[x_col, y_col]].dropna().copy()
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart[x_col] = chart[x_col].map(_numeric)
    chart[y_col] = chart[y_col].map(_numeric)
    min_x, max_x = chart[x_col].min(), chart[x_col].max()
    max_y = max(chart[y_col].max(), 1.0)
    canvas.setStrokeColorRGB(*GRID_COLOR)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    for step in range(5):
        gy = y + (height * step / 4)
        canvas.line(x + 28, gy, x + width, gy)
        canvas.drawRightString(x + 24, gy - 3, _fmt_number(max_y * step / 4))
    points = []
    for _, row in chart.iterrows():
        px = x + 32 if max_x == min_x else x + 32 + (width - 36) * (row[x_col] - min_x) / (max_x - min_x)
        py = y + height * row[y_col] / max_y
        points.append((px, py))
    canvas.setStrokeColorRGB(*ATLANSUN_BLUE)
    canvas.setLineWidth(1.5)
    for start, end in zip(points, points[1:]):
        canvas.line(start[0], start[1], end[0], end[1])
    canvas.setFillColorRGB(*ATLANSUN_BLUE)
    for px, py in points:
        canvas.circle(px, py, 2.2, fill=1, stroke=0)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    if y_axis_label:
        canvas.drawString(x + 28, y + height + 3, _safe_text(y_axis_label))
    canvas.drawString(x + 28, y - 10, _fmt_number(min_x))
    canvas.drawRightString(x + width, y - 10, _fmt_number(max_x))


def draw_pie_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    radius: float,
    title: str,
    label_col: str,
    value_col: str,
    colors: list[tuple[float, float, float]],
    max_items: int = 7,
) -> None:
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + radius * 2 + 16, _safe_text(title))
    if data.empty or label_col not in data or value_col not in data:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + radius, "Aucune donnée.")
        return
    chart = data[[label_col, value_col]].copy().head(max_items)
    chart[value_col] = chart[value_col].map(_numeric)
    total = chart[value_col].sum()
    if total <= 0:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + radius, "Aucune donnée.")
        return
    start = 90
    for idx, row in chart.iterrows():
        extent = 360 * _numeric(row[value_col]) / total
        canvas.setFillColorRGB(*colors[idx % len(colors)])
        canvas.wedge(x, y, x + radius * 2, y + radius * 2, start, extent, fill=1, stroke=0)
        start += extent
    legend_x = x + radius * 2 + 18
    legend_y = y + radius * 2 - 4
    canvas.setFont("Helvetica", 8)
    for idx, row in chart.iterrows():
        pct = 100 * _numeric(row[value_col]) / total
        ly = legend_y - idx * 13
        canvas.setFillColorRGB(*colors[idx % len(colors)])
        canvas.rect(legend_x, ly - 7, 7, 7, fill=1, stroke=0)
        canvas.setFillColorRGB(0.32, 0.34, 0.42)
        canvas.drawString(legend_x + 10, ly - 7, f"{_short_label(row[label_col], 22)} - {pct:.0f} %")


def draw_log_scatter_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    x_col: str = "Superficie (m²)",
    y_col: str = "Production annuelle (MWh)",
) -> None:
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, _safe_text(title))
    if data.empty or x_col not in data or y_col not in data:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart = data.dropna(subset=[x_col, y_col]).copy()
    chart = chart[(chart[x_col].map(_numeric) > 0) & (chart[y_col].map(_numeric) > 0)].copy()
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée avec surface et production strictement positives.")
        return
    min_x = max(chart[x_col].map(_numeric).min(), 1.0)
    max_x = max(chart[x_col].map(_numeric).max(), min_x)
    min_y = max(chart[y_col].map(_numeric).min(), 1.0)
    max_y = max(chart[y_col].map(_numeric).max(), min_y)
    log_min = math.floor(math.log10(min_x))
    log_max = math.ceil(math.log10(max_x))
    log_y_min = math.floor(math.log10(min_y))
    log_y_max = math.ceil(math.log10(max_y))
    log_span = max(log_max - log_min, 1e-9)
    log_y_span = max(log_y_max - log_y_min, 1e-9)
    canvas.setStrokeColorRGB(*GRID_COLOR)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    for tick in [10**power for power in range(log_y_min, log_y_max + 1)]:
        gy = y + height * (math.log10(tick) - log_y_min) / log_y_span
        canvas.line(x + 28, gy, x + width, gy)
        canvas.drawRightString(x + 24, gy - 3, _fmt_number(tick))
    for tick in [10**power for power in range(log_min, log_max + 1)]:
        gx = x + 28 + (width - 36) * (math.log10(tick) - log_min) / log_span
        canvas.line(gx, y, gx, y + height)
        canvas.drawCentredString(gx, y - 11, _fmt_number(tick))
    canvas.setFillColorRGB(0.0, 0.7, 0.62)
    for _, row in chart.head(120).iterrows():
        px = x + 28 + (width - 36) * (math.log10(max(_numeric(row[x_col]), min_x)) - log_min) / log_span
        py = y + height * (math.log10(max(_numeric(row[y_col]), min_y)) - log_y_min) / log_y_span
        canvas.circle(px, py, 2.4, fill=1, stroke=0)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(x + width / 2, y - 24, "Surface de capteurs installée (m², axe logarithmique)")
    canvas.drawString(x + 28, y + height + 3, "Production annuelle (MWh/an, axe logarithmique)")
    canvas.setFillColorRGB(0.5, 0.52, 0.58)
    canvas.drawString(x + 28, y - 36, "Axes log : comparaison lisible des petites, moyennes et grandes installations.")


def coordinate_points_for_pdf(df: pd.DataFrame) -> list[dict[str, object]]:
    if df.empty or "Latitude" not in df or "Longitude" not in df:
        return []
    points: list[dict[str, object]] = []
    for row in df.to_dict("records"):
        try:
            if pd.isna(row.get("Latitude")) or pd.isna(row.get("Longitude")):
                continue
        except (TypeError, ValueError):
            continue
        lat = _numeric(row.get("Latitude"))
        lon = _numeric(row.get("Longitude"))
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        points.append(
            {
                "lat": lat,
                "lon": lon,
                "Secteur": row.get("Secteur") or "Non renseigné",
                "Application": row.get("Application") or "Installation",
                "Ville": row.get("Ville") or "",
            }
        )
    return points


def _lon_to_tile_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * (2**zoom)


def _lat_to_tile_y(lat: float, zoom: int) -> float:
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    return (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * (2**zoom)


def select_static_map_zoom(points: list[dict[str, object]], *, width_px: int, height_px: int, padding_px: int) -> int:
    if len(points) <= 1:
        return 12
    lats = [float(point["lat"]) for point in points]
    lons = [float(point["lon"]) for point in points]
    for zoom in range(15, 4, -1):
        xs = [_lon_to_tile_x(lon, zoom) * 256 for lon in lons]
        ys = [_lat_to_tile_y(lat, zoom) * 256 for lat in lats]
        if (max(xs) - min(xs) <= width_px - 2 * padding_px) and (
            max(ys) - min(ys) <= height_px - 2 * padding_px
        ):
            return zoom
    return 5


def build_static_osm_map_png(
    points: list[dict[str, object]],
    *,
    colors: list[str],
    width_px: int = 1000,
    height_px: int = 520,
) -> bytes | None:
    if not points:
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    padding_px = 70
    zoom = select_static_map_zoom(points, width_px=width_px, height_px=height_px, padding_px=padding_px)
    center_lat = sum(float(point["lat"]) for point in points) / len(points)
    center_lon = sum(float(point["lon"]) for point in points) / len(points)
    center_x = _lon_to_tile_x(center_lon, zoom) * 256
    center_y = _lat_to_tile_y(center_lat, zoom) * 256
    top_left_x = center_x - width_px / 2
    top_left_y = center_y - height_px / 2
    tile_x_min = math.floor(top_left_x / 256)
    tile_y_min = math.floor(top_left_y / 256)
    tile_x_max = math.floor((top_left_x + width_px) / 256)
    tile_y_max = math.floor((top_left_y + height_px) / 256)
    tile_count = 2**zoom

    image = Image.new("RGB", (width_px, height_px), "#f2f4f7")
    headers = {"User-Agent": "HelioTools/1.0 PDF export"}
    for tile_x in range(tile_x_min, tile_x_max + 1):
        for tile_y in range(tile_y_min, tile_y_max + 1):
            if tile_y < 0 or tile_y >= tile_count:
                continue
            wrapped_x = tile_x % tile_count
            url = f"https://tile.openstreetmap.org/{zoom}/{wrapped_x}/{tile_y}.png"
            try:
                response = requests.get(url, headers=headers, timeout=5)
                response.raise_for_status()
                tile = Image.open(BytesIO(response.content)).convert("RGB")
            except Exception:
                continue
            paste_x = int(tile_x * 256 - top_left_x)
            paste_y = int(tile_y * 256 - top_left_y)
            image.paste(tile, (paste_x, paste_y))

    draw = ImageDraw.Draw(image)
    sectors = sorted({str(point.get("Secteur") or "Non renseigné") for point in points})
    sector_colors = {sector: colors[index % len(colors)] for index, sector in enumerate(sectors)}
    for point in points:
        px = _lon_to_tile_x(float(point["lon"]), zoom) * 256 - top_left_x
        py = _lat_to_tile_y(float(point["lat"]), zoom) * 256 - top_left_y
        color = sector_colors[str(point.get("Secteur") or "Non renseigné")]
        radius = 6
        draw.ellipse((px - radius - 1, py - radius - 1, px + radius + 1, py + radius + 1), fill="#ffffff")
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color, outline="#1f2937")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def draw_installation_map(
    canvas,
    df: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    colors: list[str],
    title: str = "Carte des installations filtrées",
) -> None:
    points = coordinate_points_for_pdf(df)
    canvas.setFillColorRGB(*TEXT_COLOR)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(x, y + height + 18, _safe_text(title))
    if not points:
        canvas.setFillColorRGB(*CARD_FILL)
        canvas.setStrokeColorRGB(*CARD_STROKE)
        canvas.roundRect(x, y, width, height, 5, fill=1, stroke=1)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(x + width / 2, y + height / 2, "Aucune coordonnée Latitude/Longitude disponible dans les données filtrées.")
        return

    png_bytes = build_static_osm_map_png(points, colors=colors)
    if not png_bytes:
        canvas.setFillColorRGB(*CARD_FILL)
        canvas.setStrokeColorRGB(*CARD_STROKE)
        canvas.roundRect(x, y, width, height, 5, fill=1, stroke=1)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(x + width / 2, y + height / 2, "Carte non disponible pendant la génération du PDF.")
        return

    from reportlab.lib.utils import ImageReader

    canvas.drawImage(ImageReader(BytesIO(png_bytes)), x, y, width=width, height=height, preserveAspectRatio=True, mask="auto")
    canvas.setFillColorRGB(*MUTED_COLOR)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(x, y - 12, f"Fond standard OpenStreetMap. Cadrage automatique sur {len(points)} installation(s) avec coordonnées.")


class PdfReport:
    """Petit moteur PDF commun HelioTools.

    Chaque application reste responsable de ses données métier, mais délègue la
    mise en page commune : en-tête, pied de page, KPI cards, tableaux et graphiques.
    """

    def __init__(self, *, title: str, subtitle: str = "", landscape: bool = True) -> None:
        from reportlab.lib.pagesizes import A4, landscape as landscape_page
        from reportlab.pdfgen import canvas as pdf_canvas

        self.buffer = BytesIO()
        self.page_width, self.page_height = landscape_page(A4) if landscape else A4
        self.canvas = pdf_canvas.Canvas(
            self.buffer,
            pagesize=(self.page_width, self.page_height),
            pageCompression=0,
        )
        self.title = title
        self.subtitle = subtitle
        self.page_number = 0

    def start_page(self, *, title: str | None = None, subtitle: str | None = None) -> float:
        if self.page_number:
            self.canvas.showPage()
        self.page_number += 1
        title = title or self.title
        subtitle = self.subtitle if subtitle is None else subtitle
        self._draw_header(title=title, subtitle=subtitle)
        return self.page_height - 92

    def finish(self) -> bytes:
        self._draw_footer()
        self.canvas.save()
        return self.buffer.getvalue()

    def draw_footer(self) -> None:
        self._draw_footer()

    def section_title(self, title: str, *, x: float, y: float) -> float:
        self.canvas.setFillColorRGB(*TEXT_COLOR)
        self.canvas.setFont("Helvetica-Bold", 12)
        self.canvas.drawString(x, y, _safe_text(title))
        return y - 18

    def note(self, text: str, *, x: float, y: float, width: float, size: float = 7.5) -> float:
        self.canvas.setFillColorRGB(*MUTED_COLOR)
        self.canvas.setFont("Helvetica", size)
        line = ""
        for word in _safe_text(text).split():
            candidate = f"{line} {word}".strip()
            if line and self.canvas.stringWidth(candidate, "Helvetica", size) > width:
                self.canvas.drawString(x, y, line)
                y -= size + 3
                line = word
            else:
                line = candidate
        if line:
            self.canvas.drawString(x, y, line)
            y -= size + 3
        return y

    def kpi_grid(
        self,
        metrics: list[tuple[str, str]],
        *,
        x: float,
        y: float,
        width: float,
        cols: int = 4,
    ) -> float:
        if not metrics:
            return y
        gap = 8
        card_w = (width - gap * (cols - 1)) / cols
        card_h = 48
        for index, (label, value) in enumerate(metrics):
            row = index // cols
            col = index % cols
            cx = x + col * (card_w + gap)
            cy = y - row * (card_h + gap)
            self.canvas.setFillColorRGB(*CARD_FILL)
            self.canvas.setStrokeColorRGB(*CARD_STROKE)
            self.canvas.roundRect(cx, cy - card_h, card_w, card_h, 6, fill=1, stroke=1)
            self.canvas.setFillColorRGB(*MUTED_COLOR)
            self.canvas.setFont("Helvetica", 7)
            self.canvas.drawString(cx + 8, cy - 14, _safe_text(label)[:34])
            self.canvas.setFillColorRGB(*TEXT_COLOR)
            self.canvas.setFont("Helvetica-Bold", 12)
            self.canvas.drawString(cx + 8, cy - 35, _safe_text(value)[:27])
        rows = math.ceil(len(metrics) / cols)
        return y - rows * (card_h + gap) - 6

    def table(
        self,
        rows: list[dict[str, Any]],
        *,
        x: float,
        y: float,
        width: float,
        columns: list[str] | None = None,
        max_rows: int = 12,
    ) -> float:
        if not rows:
            self.canvas.setFillColorRGB(*MUTED_COLOR)
            self.canvas.setFont("Helvetica", 8)
            self.canvas.drawString(x, y, "Aucune donnée.")
            return y - 14
        columns = columns or list(rows[0].keys())
        col_w = width / max(1, len(columns))
        self.canvas.setFillColorRGB(*TEXT_COLOR)
        self.canvas.setFont("Helvetica-Bold", 7)
        for idx, column in enumerate(columns):
            self.canvas.drawString(x + idx * col_w, y, _safe_text(column)[:28])
        y -= 12
        self.canvas.setStrokeColorRGB(*GRID_COLOR)
        self.canvas.line(x, y + 5, x + width, y + 5)
        self.canvas.setFont("Helvetica", 7)
        for row in rows[:max_rows]:
            for idx, column in enumerate(columns):
                self.canvas.drawString(x + idx * col_w, y, _safe_text(row.get(column, ""))[:30])
            y -= 11
        if len(rows) > max_rows:
            self.canvas.setFillColorRGB(*MUTED_COLOR)
            self.canvas.drawString(x, y, f"... {len(rows) - max_rows} ligne(s) supplémentaire(s)")
            y -= 11
        return y - 4

    def bar_chart(
        self,
        rows: list[dict[str, Any]],
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        label_col: str,
        value_col: str,
        title: str,
        y_label: str = "",
    ) -> None:
        chart = [row for row in rows if _numeric(row.get(value_col)) > 0]
        self.canvas.setFillColorRGB(*TEXT_COLOR)
        self.canvas.setFont("Helvetica-Bold", 10)
        self.canvas.drawString(x, y + height + 14, _safe_text(title))
        if not chart:
            self.canvas.setFont("Helvetica", 8)
            self.canvas.drawString(x, y + height / 2, "Aucune donnée.")
            return
        max_value = max(_numeric(row.get(value_col)) for row in chart) or 1.0
        plot_x = x + 30
        plot_w = width - 38
        plot_h = height - 22
        bar_w = plot_w / max(1, len(chart)) * 0.62
        self.canvas.setStrokeColorRGB(*GRID_COLOR)
        for step in range(5):
            gy = y + step * plot_h / 4
            self.canvas.line(plot_x, gy, plot_x + plot_w, gy)
        self.canvas.setFont("Helvetica", 6.5)
        self.canvas.setFillColorRGB(*MUTED_COLOR)
        for idx, row in enumerate(chart):
            value = _numeric(row.get(value_col))
            bx = plot_x + idx * plot_w / len(chart) + (plot_w / len(chart) - bar_w) / 2
            bh = value / max_value * plot_h
            color = CHART_COLORS[idx % len(CHART_COLORS)]
            self.canvas.setFillColorRGB(*color)
            self.canvas.rect(bx, y, bar_w, bh, fill=1, stroke=0)
            self.canvas.setFillColorRGB(*MUTED_COLOR)
            self.canvas.drawCentredString(bx + bar_w / 2, y - 9, _safe_text(row.get(label_col, ""))[:7])
        if y_label:
            self.canvas.drawString(plot_x, y + height - 5, _safe_text(y_label))

    def line_chart(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        x_col: str,
        y_cols: list[tuple[str, str]],
        title: str,
        y_label: str = "",
    ) -> None:
        data = list(rows)
        self.canvas.setFillColorRGB(*TEXT_COLOR)
        self.canvas.setFont("Helvetica-Bold", 10)
        self.canvas.drawString(x, y + height + 14, _safe_text(title))
        series_values = [
            _numeric(row.get(col))
            for row in data
            for col, _ in y_cols
            if row.get(col) is not None
        ]
        if not data or not series_values:
            self.canvas.setFont("Helvetica", 8)
            self.canvas.drawString(x, y + height / 2, "Aucune donnée.")
            return
        x_values = [_numeric(row.get(x_col)) for row in data]
        min_x, max_x = min(x_values), max(x_values)
        min_y, max_y = min(series_values), max(series_values)
        if max_x <= min_x:
            max_x = min_x + 1
        if max_y <= min_y:
            max_y = min_y + 1
        plot_x = x + 34
        plot_y = y + 14
        plot_w = width - 74
        plot_h = height - 36
        self.canvas.setStrokeColorRGB(*GRID_COLOR)
        for step in range(5):
            gy = plot_y + step * plot_h / 4
            self.canvas.line(plot_x, gy, plot_x + plot_w, gy)
        self.canvas.setFont("Helvetica", 6.5)
        self.canvas.setFillColorRGB(*MUTED_COLOR)
        self.canvas.drawString(plot_x, y + height - 5, _safe_text(y_label))
        for col_idx, (col, label) in enumerate(y_cols):
            color = CHART_COLORS[col_idx % len(CHART_COLORS)]
            points: list[tuple[float, float]] = []
            for row in data:
                xv = _numeric(row.get(x_col))
                yv = _numeric(row.get(col))
                px = plot_x + (xv - min_x) / (max_x - min_x) * plot_w
                py = plot_y + (yv - min_y) / (max_y - min_y) * plot_h
                points.append((px, py))
            self.canvas.setStrokeColorRGB(*color)
            self.canvas.setLineWidth(1.2)
            for start, end in zip(points, points[1:]):
                self.canvas.line(start[0], start[1], end[0], end[1])
            self.canvas.setFillColorRGB(*color)
            self.canvas.rect(plot_x + plot_w + 10, y + height - 14 - col_idx * 12, 7, 4, fill=1, stroke=0)
            self.canvas.setFillColorRGB(*MUTED_COLOR)
            self.canvas.drawString(plot_x + plot_w + 20, y + height - 17 - col_idx * 12, _safe_text(label)[:25])

    def _draw_header(self, *, title: str, subtitle: str) -> None:
        canvas = self.canvas
        width = self.page_width
        height = self.page_height
        if ATLANSUN_LOGO.exists():
            try:
                canvas.drawImage(
                    str(ATLANSUN_LOGO),
                    width - 154,
                    height - 52,
                    width=120,
                    height=35,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception:
                pass
        canvas.setFillColorRGB(*TEXT_COLOR)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawString(34, height - 38, _safe_text(title))
        canvas.setFont("Helvetica", 9)
        canvas.setFillColorRGB(*MUTED_COLOR)
        canvas.drawString(34, height - 56, _safe_text(subtitle)[:120])
        canvas.setStrokeColorRGB(*GRID_COLOR)
        canvas.line(34, height - 68, width - 34, height - 68)

    def _draw_footer(self) -> None:
        self.canvas.setFont("Helvetica", 8)
        self.canvas.setFillColorRGB(*MUTED_COLOR)
        self.canvas.drawString(34, 24, "HelioTools - document généré automatiquement")
        self.canvas.drawRightString(self.page_width - 34, 24, f"Page {self.page_number}")
