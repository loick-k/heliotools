from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


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
