from __future__ import annotations

from pathlib import Path
from typing import Any

from .formatting import format_number


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"


def safe_pdf_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def draw_report_header(canvas, *, title: str, subtitle: str = "", width: float, height: float) -> None:
    """Common Atlansun header for lightweight ReportLab exports."""
    if ATLANSUN_LOGO.exists():
        try:
            canvas.drawImage(
                str(ATLANSUN_LOGO),
                width - 124,
                height - 54,
                width=90,
                height=26,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(34, height - 38, safe_pdf_text(title))
    if subtitle:
        canvas.setFont("Helvetica", 9)
        canvas.setFillColorRGB(0.47, 0.49, 0.55)
        canvas.drawString(34, height - 56, safe_pdf_text(subtitle))
    canvas.setStrokeColorRGB(0.88, 0.90, 0.94)
    canvas.line(34, height - 68, width - 34, height - 68)


def draw_report_footer(
    canvas,
    *,
    page_number: int,
    width: float,
    footer_text: str = "HelioTools - export de predimensionnement",
) -> None:
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.55, 0.57, 0.64)
    canvas.drawString(34, 24, safe_pdf_text(footer_text))
    canvas.drawRightString(width - 34, 24, f"Page {page_number}")


# Compatibility bridge: the existing rich PDF engine is progressively migrated
# behind this common namespace so apps can share it without changing outputs.
from ..pdf_report import PdfReport  # noqa: E402
from ..pdf_report import _fmt_number as legacy_format_number  # noqa: E402

_fmt_number = legacy_format_number

__all__ = [
    "ATLANSUN_LOGO",
    "PdfReport",
    "_fmt_number",
    "draw_report_footer",
    "draw_report_header",
    "format_number",
    "safe_pdf_text",
]

