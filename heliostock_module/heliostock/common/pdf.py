from __future__ import annotations

from ..pdf_report import (
    ATLANSUN_LOGO,
    PdfReport,
    _fmt_number,
    draw_report_footer,
    draw_report_header,
)
from .formatting import format_number


def safe_pdf_text(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


__all__ = [
    "ATLANSUN_LOGO",
    "PdfReport",
    "_fmt_number",
    "draw_report_footer",
    "draw_report_header",
    "format_number",
    "safe_pdf_text",
]
