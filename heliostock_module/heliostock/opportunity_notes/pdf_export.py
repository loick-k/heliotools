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
    sample = rows[0] if rows else {}
    mean_key = next((key for key in sample if str(key).startswith("Flux cumulé moyen")), "Flux cumulé moyen (€)")
    inflation_key = next(
        (key for key in sample if str(key).startswith("Flux cumulé inflation")),
        "Flux cumulé inflation annuelle (€)",
    )
    return [
        {
            "Année": row["Année"],
            "Flux moyen": row[mean_key],
            "Flux inflation": row[inflation_key],
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
    return [
        {"Poste": "Besoin utile ECS", "MWh": results.annual_useful_energy_mwh},
        {"Poste": "Bouclage sanitaire", "MWh": results.annual_loop_losses_mwh},
    ]


def _ecs_heating_pie_rows(results: OpportunityResults) -> list[dict[str, Any]]:
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

    y = report.start_page()
    y = report.section_title("Synthèse du projet", x=34, y=y)
    report.kpi_grid(
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
        x=34,
        y=y,
        width=report.page_width - 68,
    )

    y -= 10
    y = report.section_title("Hypothèses principales", x=34, y=y)
    report.table(
        [
            {"Paramètre": "Typologie", "Valeur": site_inputs.typology},
            {"Paramètre": "Nature du bâtiment", "Valeur": site_inputs.building_state},
            {"Paramètre": "Source de besoin ECS", "Valeur": site_inputs.data_source},
            {"Paramètre": "Méthode bouclage", "Valeur": loop_inputs.method},
            {"Paramètre": "Capteur solaire", "Valeur": sizing_inputs.collector_name},
            {"Paramètre": "Productivité solaire", "Valeur": f"{_fmt_number(sizing_inputs.productivity_kwh_m2_year, 0)} kWh/m2.an"},
            {"Paramètre": "Ratio V/S cible", "Valeur": f"{_fmt_number(sizing_inputs.target_storage_ratio_l_m2, 0)} L/m2"},
            {"Paramètre": "Coût énergie référence", "Valeur": _eur_mwh(economic_inputs.reference_energy_cost_eur_mwh, 1)},
            {"Paramètre": "Durée d'analyse", "Valeur": f"{economic_inputs.years} ans"},
        ],
        x=34,
        y=y,
        width=report.page_width - 68,
        columns=["Paramètre", "Valeur"],
        max_rows=12,
    )
    report.draw_footer()

    report.start_page(title="Note d'opportunité - besoins et prédimensionnement")
    half_w = (report.page_width - 84) / 2
    report.section_title("Répartition annuelle des besoins", x=34, y=report.page_height - 92)
    report.pie_chart(
        _ecs_pie_rows(opportunity_results),
        x=52,
        y=report.page_height - 298,
        radius=68,
        title="ECS utile / bouclage",
        label_col="Poste",
        value_col="MWh",
    )
    report.pie_chart(
        _ecs_heating_pie_rows(opportunity_results),
        x=70 + half_w,
        y=report.page_height - 298,
        radius=68,
        title="ECS utile / bouclage / chauffage",
        label_col="Poste",
        value_col="MWh",
    )
    report.line_chart(
        _monthly_chart_rows(opportunity_results),
        x=34,
        y=165,
        width=half_w,
        height=165,
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
        y=165,
        width=half_w,
        height=165,
        label_col="Poste",
        value_col="MWh",
        title="Bilan annuel simplifié",
        y_label="MWh/an",
    )
    y = report.section_title("Tableau mensuel", x=34, y=145)
    report.table(
        _monthly_rows(opportunity_results),
        x=34,
        y=y,
        width=report.page_width - 68,
        columns=["Mois", "Volume moyen (L/j)", "Besoin utile (MWh)", "Bouclage (MWh)", "Chauffage (MWh)", "Total ECS (MWh)"],
        max_rows=12,
    )
    report.draw_footer()

    y = report.start_page(title="Note d'opportunité - économie")
    y = report.section_title("Indicateurs économiques", x=34, y=y)
    report.kpi_grid(
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
        x=34,
        y=y,
        width=report.page_width - 68,
    )
    report.line_chart(
        _cashflow_chart_rows(economic_inputs, economic_results),
        x=34,
        y=170,
        width=(report.page_width - 84) / 2,
        height=190,
        x_col="Année",
        y_cols=[("Flux moyen", "Flux moyen"), ("Flux inflation", "Flux avec inflation")],
        title="Flux cumulé",
        y_label="EUR",
    )
    report.table(
        _cost_table_rows(economic_results),
        x=50 + (report.page_width - 84) / 2,
        y=348,
        width=(report.page_width - 84) / 2,
        columns=["Famille", "Poste", "Coût total", "Aide", "Net", "Coût chaleur"],
        max_rows=8,
    )

    return report.finish()
