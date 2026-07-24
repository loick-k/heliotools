from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..pdf_report import draw_report_footer, draw_report_header
from .engine import CALCULATION_MODES, CalculationInputs, CalculationResults


TEAL = colors.HexColor("#0B6F70")
DARK = colors.HexColor("#17324D")
ORANGE = colors.HexColor("#E58A2A")
LIGHT = colors.HexColor("#EEF5F4")
GREY = colors.HexColor("#667085")


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
    draw_report_footer(canvas, page_number=doc.page, width=width, footer_text="HelioTools - HelioRC")
    canvas.restoreState()


def _chart(monthly: pd.DataFrame) -> Drawing:
    drawing = Drawing(500, 220)
    plot = LinePlot()
    plot.x = 45
    plot.y = 35
    plot.height = 145
    plot.width = 410
    needs = monthly["Besoins RCU (MWh)"].astype(float).tolist()
    solar = monthly["Production solaire (MWh)"].astype(float).tolist()
    plot.data = [
        [(index + 1, value) for index, value in enumerate(needs)],
        [(index + 1, value) for index, value in enumerate(solar)],
    ]
    plot.lines[0].strokeColor = GREY
    plot.lines[0].strokeWidth = 2
    plot.lines[1].strokeColor = ORANGE
    plot.lines[1].strokeWidth = 2.5
    plot.xValueAxis.valueMin = 1
    plot.xValueAxis.valueMax = 12
    plot.xValueAxis.valueSteps = list(range(1, 13))
    plot.xValueAxis.labelTextFormat = lambda value: str(int(value))
    plot.yValueAxis.valueMin = 0
    plot.yValueAxis.valueMax = max(needs) * 1.10 if max(needs) > 0 else 1
    plot.yValueAxis.labelTextFormat = lambda value: f"{value:.0f}"
    drawing.add(plot)

    legend = Legend()
    legend.x = 65
    legend.y = 205
    legend.dx = 8
    legend.dy = 8
    legend.fontName = "Helvetica"
    legend.fontSize = 8
    legend.colorNamePairs = [
        (GREY, "Besoins RCU"),
        (ORANGE, "Production solaire"),
    ]
    drawing.add(legend)
    return drawing


def build_opportunity_note(
    *,
    project: dict[str, Any],
    inputs: CalculationInputs,
    results: CalculationResults,
    monthly: pd.DataFrame,
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

    status_color = TEAL if "favorable" in results.opportunity_status.lower() else ORANGE
    status_table = Table(
        [
            [Paragraph("Conclusion de premier niveau", styles["CenterKpi"]), Paragraph(results.opportunity_status, styles["CenterKpi"])],
            [Paragraph("Domaine du modèle", styles["CenterKpi"]), Paragraph(results.scope_status, styles["CenterKpi"])],
        ],
        colWidths=[7.0 * cm, 9.5 * cm],
    )
    status_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 1.1, status_color),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D5DD")),
                ("TEXTCOLOR", (1, 0), (1, 0), status_color),
                ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(status_table)

    story.append(Paragraph("1. Hypothèses principales", styles["SectionHelio"]))
    assumptions = [
        ["Mode de calcul", CALCULATION_MODES[inputs.calculation_mode]],
        ["Régime moyen", f"{inputs.regime_label} - {inputs.mean_network_temperature_c:.0f} °C"],
        ["Dimensionnement au talon", f"{inputs.base_load_fraction:.0%}"],
        ["Besoins annuels du RCU", f"{_number(results.annual_need_mwh)} MWh/an"],
        ["Part des besoins mai-septembre", f"{results.summer_need_share:.1%}"],
        ["Gisement horizontal", f"{_number(results.annual_horizontal_irradiation_kwh_m2)} kWh/m².an"],
        ["Zone d'aide", f"{inputs.zone}"],
    ]
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
        ["Productivité", f"{_number(results.productivity_kwh_m2_year)} kWh/m².an", "Fraction solaire", f"{results.solar_fraction:.1%}"],
        ["Stockage journalier", f"{_number(results.storage_volume_m3)} m³", "Emprise foncière", f"{results.land_area_ha:.2f} ha"],
        ["Distance conseillée", f"{_number(results.recommended_connection_distance_m)} m", "Panneaux de 15 m²", f"{results.panel_count_15m2}"],
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
    story.append(_chart(monthly))

    story.append(Paragraph("3. Première analyse économique", styles["SectionHelio"]))
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
    story.append(economics_table)

    story.append(PageBreak())
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
    story.append(monthly_table)

    story.append(Paragraph("5. Vigilances et suites à donner", styles["SectionHelio"]))
    warning_flowables = []
    for warning in results.warnings:
        warning_flowables.append(Paragraph(f"• {warning}", styles["BodyText"]))
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

    notes = str(project.get("notes", "")).strip()
    if notes:
        story.append(Paragraph("6. Commentaires du chargé d'étude", styles["SectionHelio"]))
        story.append(Paragraph(notes.replace("\n", "<br/>"), styles["BodyText"]))

    story.append(Spacer(1, 0.35 * cm))
    story.append(
        Paragraph(
            "Méthode reprise du classeur NO_STH_RCU v5.3 et de sa présentation ADEME. Cadre principal : capteurs plans vitrés haute performance, stockage journalier, champ supérieur à 100 m² et fraction solaire indicative de 10 à 30 %.",
            styles["SmallHelio"],
        )
    )

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()
