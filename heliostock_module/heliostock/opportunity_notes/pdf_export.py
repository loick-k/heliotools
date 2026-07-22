from __future__ import annotations

from datetime import datetime
from typing import Any

from ..common.pdf import PdfReport, _fmt_number
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


def _percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n.d."
    return f"{100.0 * float(value):.{digits}f} %"


def _monthly_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    return [
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
    rows = list(build_yearly_cashflow_projection(inputs, results))
    return [
        {
            "Année": row["Année"],
            "Flux moyen": row["Flux cumulé moyen (€)"],
            "Flux inflation": row["Flux cumulé inflation annuelle (€)"],
        }
        for row in rows
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


def _ecs_pie_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    if float(results.annual_loop_losses_mwh or 0.0) <= 0:
        return []
    return [
        {"Poste": "Besoin utile ECS", "MWh": results.annual_useful_energy_mwh},
        {"Poste": "Bouclage sanitaire", "MWh": results.annual_loop_losses_mwh},
    ]


def _ecs_heating_pie_rows(results: OpportunityResults) -> list[dict[str, Any]]:
    if float(results.annual_loop_losses_mwh or 0.0) <= 0 or float(results.annual_heating_after_boiler_mwh or 0.0) <= 0:
        return []
    return [
        {"Poste": "Besoin utile ECS", "MWh": results.annual_useful_energy_mwh},
        {"Poste": "Bouclage sanitaire", "MWh": results.annual_loop_losses_mwh},
        {"Poste": "Chauffage estimé", "MWh": results.annual_heating_after_boiler_mwh},
    ]


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

    y = report.start_page()
    y = report.section_title("Synthèse du projet", x=margin, y=y)
    y = report.kpi_grid(
        [
            ("Volume ECS annuel", f"{_fmt_number(opportunity_results.annual_volume_l_60c / 1000.0, 1)} m3/an"),
            ("Besoin utile ECS", f"{_fmt_number(opportunity_results.annual_useful_energy_mwh, 1)} MWh/an"),
            ("Bouclage sanitaire", f"{_fmt_number(opportunity_results.annual_loop_losses_mwh, 1)} MWh/an"),
            ("Chauffage estimé", f"{_fmt_number(opportunity_results.annual_heating_after_boiler_mwh, 1)} MWh/an"),
            ("Besoin ECS + bouclage", f"{_fmt_number(opportunity_results.annual_total_ecs_energy_mwh, 1)} MWh/an"),
            ("Surface capteurs", f"{_fmt_number(opportunity_results.collectors.surface_m2, 1)} m2"),
            ("Stockage proposé", f"{_fmt_number(opportunity_results.storage.total_volume_l, 0)} L"),
            ("Coût chaleur solaire", _eur_mwh(economic_results.solar_heat_cost_eur_mwh, 1)),
        ],
        x=margin,
        y=y,
        width=content_width,
    )

    y -= 16
    y = report.section_title("Hypothèses principales", x=margin, y=y)
    report.table(
        [
            {"Paramètre": "Typologie", "Valeur": site_inputs.typology},
            {"Paramètre": "Nature du bâtiment", "Valeur": site_inputs.building_state},
            {"Paramètre": "Source de besoin ECS", "Valeur": site_inputs.data_source},
            {"Paramètre": "Méthode bouclage", "Valeur": loop_inputs.method},
            {"Paramètre": "Capteur solaire", "Valeur": sizing_inputs.collector_name},
            {
                "Paramètre": "Productivité solaire",
                "Valeur": f"{_fmt_number(sizing_inputs.productivity_kwh_m2_year, 0)} kWh/m2.an",
            },
            {"Paramètre": "Ratio V/S cible", "Valeur": f"{_fmt_number(sizing_inputs.target_storage_ratio_l_m2, 0)} L/m2"},
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
        row_height=14,
    )
    report.draw_footer()

    report.start_page(title="Note d'opportunité - besoins et prédimensionnement")
    y = report.section_title("Répartition annuelle des besoins", x=margin, y=report.page_height - 92)
    ecs_pie_rows = _ecs_pie_rows(opportunity_results)
    ecs_heating_pie_rows = _ecs_heating_pie_rows(opportunity_results)
    if ecs_pie_rows:
        report.pie_chart(
            ecs_pie_rows,
            x=52,
            y=y - 165,
            radius=62,
            title="ECS utile / bouclage",
            label_col="Poste",
            value_col="MWh",
        )
    if ecs_heating_pie_rows:
        report.pie_chart(
            ecs_heating_pie_rows,
            x=70 + half_w,
            y=y - 165,
            radius=62,
            title="ECS utile / bouclage / chauffage",
            label_col="Poste",
            value_col="MWh",
        )
    y = report.section_title("Graphiques mensuels et bilan annuel", x=margin, y=250)
    report.line_chart(
        _monthly_chart_rows(opportunity_results),
        x=margin,
        y=62,
        width=half_w,
        height=155,
        x_col="Mois",
        y_cols=[("Besoin utile ECS", "Besoin utile ECS"), ("ECS + bouclage", "ECS + bouclage")],
        title="Besoin mensuel ECS",
        y_label="MWh/mois",
    )
    report.bar_chart(
        [
            {"Poste": "ECS utile", "MWh": opportunity_results.annual_useful_energy_mwh},
            {"Poste": "Bouclage", "MWh": opportunity_results.annual_loop_losses_mwh},
            {"Poste": "Chauffage", "MWh": opportunity_results.annual_heating_after_boiler_mwh},
            {"Poste": "Solaire", "MWh": opportunity_results.estimated_solar_production_mwh_year},
        ],
        x=50 + half_w,
        y=62,
        width=half_w,
        height=155,
        label_col="Poste",
        value_col="MWh",
        title="Bilan annuel simplifié",
        y_label="MWh/an",
    )
    report.draw_footer()

    y = report.start_page(title="Note d'opportunité - tableau mensuel")
    y = report.section_title("Tableau mensuel", x=margin, y=y)
    report.table(
        _monthly_rows(opportunity_results),
        x=margin,
        y=y,
        width=content_width,
        columns=["Mois", "Volume moyen (L/j)", "Besoin utile (MWh)", "Bouclage (MWh)", "Chauffage (MWh)", "Total ECS (MWh)"],
        max_rows=12,
        col_weights=[0.8, 1.4, 1.2, 1.1, 1.1, 1.2],
        font_size=8,
        row_height=17,
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
            ("P1 auxiliaires", _eur_mwh(economic_results.heat_cost_p1_eur_mwh, 1)),
            ("P2 maintenance", _eur_mwh(economic_results.heat_cost_p2_eur_mwh, 1)),
        ],
        x=margin,
        y=y,
        width=content_width,
    )
    y -= 8
    report.section_title("Flux et coûts", x=margin, y=y)
    report.line_chart(
        _cashflow_chart_rows(economic_inputs, economic_results),
        x=margin,
        y=88,
        width=half_w,
        height=170,
        x_col="Année",
        y_cols=[("Flux moyen", "Flux moyen"), ("Flux inflation", "Flux avec inflation")],
        title="Flux cumulé",
        y_label="EUR",
    )
    report.table(
        _cost_table_rows(economic_results),
        x=50 + half_w,
        y=258,
        width=half_w,
        columns=["Famille", "Poste", "Coût total", "Aide", "Net", "Coût chaleur"],
        max_rows=8,
        col_weights=[1.45, 1.65, 1.0, 0.9, 0.9, 1.15],
        font_size=6.8,
        row_height=13,
    )

    return report.finish()
