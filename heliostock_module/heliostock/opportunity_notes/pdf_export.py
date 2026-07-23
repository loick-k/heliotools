from __future__ import annotations

from datetime import datetime
from typing import Any

from ..common.pdf import PdfReport, _fmt_number
from ..pdf_report import CARD_FILL, CARD_STROKE, MUTED_COLOR, TEXT_COLOR
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
            "Mois": index + 1,
            "Besoin utile ECS": row.useful_energy_mwh,
            "ECS + bouclage": row.total_ecs_energy_mwh,
        }
        for index, row in enumerate(results.monthly_needs)
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


def _cost_table_rows(results: CescEconomicResults) -> list[dict[str, Any]]:
    return [
        {
            "Famille": line.category,
            "Poste": line.label,
            "Coût total": _eur(line.total_cost_eur, 0) if line.total_cost_eur is not None else "-",
            "Aide": _eur(line.ademe_aid_eur, 0) if line.ademe_aid_eur is not None else "-",
            "Net": _eur(line.net_cost_eur, 0) if line.net_cost_eur is not None else "-",
            "Coût chaleur": _eur_mwh(line.cost_eur_mwh_year, 1) if line.cost_eur_mwh_year is not None else "-",
        }
        for line in results.cost_lines
    ]


def _heat_cost_rows(results: CescEconomicResults) -> list[dict[str, Any]]:
    return [
        {"Poste": "P1 auxiliaires", "EUR/MWh": results.heat_cost_p1_eur_mwh or 0.0},
        {"Poste": "P2 maintenance", "EUR/MWh": results.heat_cost_p2_eur_mwh or 0.0},
        {"Poste": "P4 investissement", "EUR/MWh": results.heat_cost_p4_eur_mwh or 0.0},
        {"Poste": "Référence", "EUR/MWh": results.average_reference_energy_cost_eur_mwh or 0.0},
    ]


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
    rows = [
        {"Poste": "Besoin utile ECS", "MWh/an": results.annual_useful_energy_mwh},
        {"Poste": "Besoin ECS total", "MWh/an": results.annual_total_ecs_energy_mwh},
        {"Poste": "Production solaire", "MWh/an": results.estimated_solar_production_mwh_year},
    ]
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


def build_opportunity_note_pdf(
    *,
    site_inputs: SiteInputs,
    needs_inputs: NeedsInputs,
    sizing_inputs: SizingInputs,
    loop_inputs: LoopInputs,
    economic_inputs: CescEconomicInputs,
    opportunity_results: OpportunityResults,
    economic_results: CescEconomicResults,
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
    status_title, status_body = _opportunity_status(opportunity_results, economic_results)
    coverage = _coverage_ratio(opportunity_results)

    y = report.start_page()
    y = report.section_title("Conclusion rapide", x=margin, y=y)
    y = _draw_callout(report, status_title, status_body, x=margin, y=y, width=content_width)

    y = report.section_title("Synthèse du projet", x=margin, y=y)
    y = report.kpi_grid(
        [
            ("Besoin ECS total", f"{_fmt_number(opportunity_results.annual_total_ecs_energy_mwh, 1)} MWh/an"),
            ("Volume moyen à 60 °C", f"{_fmt_number(opportunity_results.average_daily_volume_l_60c, 0)} L/j"),
            ("Surface capteurs", f"{_fmt_number(opportunity_results.collectors.surface_m2, 1)} m²"),
            ("Taux couverture ECS", _percent(coverage, 0)),
            ("Production solaire", f"{_fmt_number(opportunity_results.estimated_solar_production_mwh_year, 1)} MWh/an"),
            ("Stockage proposé", f"{_fmt_number(opportunity_results.storage.total_volume_l, 0)} L"),
            ("Coût chaleur solaire", _eur_mwh(economic_results.solar_heat_cost_eur_mwh, 1)),
            ("Temps retour brut", f"{_fmt_number(economic_results.raw_payback_years, 1)} ans"),
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
    report.line_chart(
        _monthly_chart_rows(opportunity_results),
        x=left_x,
        y=120,
        width=half_w,
        height=170,
        x_col="Mois",
        y_cols=[("Besoin utile ECS", "Besoin utile ECS"), ("ECS + bouclage", "ECS + bouclage")],
        title="Besoin ECS mensuel",
        y_label="MWh/mois",
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
    _draw_dimensioning_box(
        report,
        x=margin,
        y=112,
        width=content_width,
        results=opportunity_results,
        sizing_inputs=sizing_inputs,
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
            ("Coût chaleur solaire", _eur_mwh(economic_results.solar_heat_cost_eur_mwh, 1)),
            ("Référence moyenne", _eur_mwh(economic_results.average_reference_energy_cost_eur_mwh, 1)),
        ],
        x=margin,
        y=y,
        width=content_width,
    )
    y -= 4
    report.section_title("Flux et coûts de chaleur", x=margin, y=y)
    report.line_chart(
        _cashflow_chart_rows(economic_inputs, economic_results),
        x=margin,
        y=84,
        width=half_w,
        height=175,
        x_col="Année",
        y_cols=[("Flux moyen", "Flux moyen"), ("Flux inflation", "Flux avec inflation")],
        title="Flux cumulé sur la période",
        y_label="EUR",
    )
    report.bar_chart(
        _heat_cost_rows(economic_results),
        x=right_x,
        y=84,
        width=half_w,
        height=175,
        label_col="Poste",
        value_col="EUR/MWh",
        title="Décomposition du coût chaleur",
        y_label="EUR/MWh utile",
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
    )
    report.note(
        "P1 correspond aux auxiliaires électriques, P2 au suivi-maintenance, et P4 à l'investissement net aidé ramené à la chaleur utile solaire.",
        x=margin,
        y=300,
        width=content_width,
        size=8,
    )

    return report.finish()
