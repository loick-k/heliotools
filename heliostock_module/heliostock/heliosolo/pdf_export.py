from __future__ import annotations

from datetime import date
from typing import Any

from heliostock.pdf_report import PdfReport


def _fmt(value: Any, decimals: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "-")
    return f"{number:,.{decimals}f}".replace(",", " ").replace(".", ",")


def _rows_from_pairs(pairs: list[tuple[str, str]], group: str) -> list[dict[str, str]]:
    return [{"Groupe": group, "Paramètre": label, "Valeur": value} for label, value in pairs]


def build_heliosolo_overview_pdf(payload: dict[str, Any]) -> bytes:
    """Construit un rapport PDF HelioSOLO avec le moteur partagé HelioTools.

    Le PDF ne relance pas le calcul : il reçoit le même paquet de résultats que
    celui affiché dans Streamlit afin d'éviter une divergence entre écran et export.
    """

    project_name = str(payload.get("project_name") or "Projet HelioSOLO").strip()
    subtitle = str(payload.get("subtitle") or f"Rapport généré le {date.today():%d/%m/%Y}")
    report = PdfReport(title=f"HelioSOLO - {project_name}", subtitle=subtitle, landscape=True)

    margin = 34
    content_width = report.page_width - 2 * margin

    y = report.start_page()
    y = report.section_title("Synthèse du calcul", x=margin, y=y)
    y = report.kpi_grid(payload.get("metrics", []), x=margin, y=y, width=content_width, cols=4)

    controls = payload.get("controls", [])
    if controls:
        y = report.section_title("Contrôles de cohérence", x=margin, y=y)
        for _level, message in controls[:5]:
            y = report.note(f"- {message}", x=margin, y=y, width=content_width, size=7.5)
        y -= 6

    assumptions: list[dict[str, str]] = []
    assumptions.extend(_rows_from_pairs(payload.get("station_rows", []), "Météo"))
    assumptions.extend(_rows_from_pairs(payload.get("besoins_rows", []), "Besoins ECS"))
    assumptions.extend(_rows_from_pairs(payload.get("capteur_rows", []), "Capteurs"))
    assumptions.extend(_rows_from_pairs(payload.get("stock_rows", []), "Stockage"))
    if payload.get("bouclage_rows"):
        assumptions.extend(_rows_from_pairs(payload.get("bouclage_rows", []), "Bouclage"))
    assumptions.extend(_rows_from_pairs(payload.get("circuit_rows", []), "Hydraulique"))

    y = report.section_title("Hypothèses principales", x=margin, y=y)
    report.table(
        assumptions,
        x=margin,
        y=y,
        width=content_width,
        columns=["Groupe", "Paramètre", "Valeur"],
        col_weights=[1.0, 1.55, 2.2],
        max_rows=24,
        font_size=6.8,
        row_height=10,
    )
    report.draw_footer()

    y = report.start_page(title=f"HelioSOLO - {project_name}", subtitle="Analyse mensuelle")
    monthly_rows = payload.get("monthly_rows", [])
    left_w = content_width * 0.52
    right_x = margin + left_w + 24
    right_w = content_width - left_w - 24
    chart_y = y - 245
    report.bar_chart(
        monthly_rows,
        x=margin,
        y=chart_y,
        width=left_w,
        height=215,
        label_col="Mois",
        value_col="Production solaire valeur",
        title="Production solaire mensuelle",
        y_label="MWh/mois",
        x_label="Mois",
        color=(0.98, 0.75, 0.14),
    )
    report.table(
        monthly_rows,
        x=right_x,
        y=y - 8,
        width=right_w,
        columns=["Mois", "Besoin total (MWh)", "Production solaire (MWh)", "Couverture"],
        col_weights=[1.0, 1.25, 1.35, 1.0],
        max_rows=12,
        font_size=6.6,
        row_height=13,
    )

    y = chart_y - 42
    y = report.section_title("Lecture physique du modèle", x=margin, y=y)
    for note in payload.get("audit_notes", [])[:8]:
        y = report.note(f"- {note}", x=margin, y=y, width=content_width, size=7.4)

    return report.finish()
