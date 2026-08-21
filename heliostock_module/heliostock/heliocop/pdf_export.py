"""Export PDF HelioCOP via le moteur PDF mutualise HelioTools."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..pdf_report import PdfReport


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _get(data: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key, default)
    return current


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt_number(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n.d."
    formatted = f"{numeric:,.{digits}f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {suffix}".strip()


def _fmt_money(value: Any, digits: int = 0) -> str:
    return _fmt_number(value, digits, "EUR HT")


def _fmt_percent(value: Any, digits: int = 1) -> str:
    return _fmt_number(_num(value) * 100.0, digits, "%")


def _label(value: Any, default: str = "n.d.") -> str:
    text = "" if value is None else str(value).strip()
    return text or default


def _summary_subtitle(payload: Mapping[str, Any]) -> str:
    project = _as_mapping(payload.get("project"))
    parts = [
        _label(project.get("client"), ""),
        _label(project.get("city"), ""),
        "profil horaire" if payload.get("mode") == "profil_horaire" else "logement collectif",
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ]
    return " - ".join(part for part in parts if part)


def _project_rows(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    project = _as_mapping(payload.get("project"))
    return [
        {"Parametre": "Projet", "Valeur": _label(project.get("name"))},
        {"Parametre": "Maitre d'ouvrage", "Valeur": _label(project.get("client"))},
        {"Parametre": "Commune", "Valeur": _label(project.get("city"))},
        {"Parametre": "Typologie", "Valeur": _label(project.get("typology"))},
        {"Parametre": "Mode", "Valeur": "Profil horaire" if payload.get("mode") == "profil_horaire" else "Logement collectif"},
        {"Parametre": "Eau froide", "Valeur": _label(payload.get("cold_water_mode"))},
    ]


def _technical_rows(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    tank = _as_mapping(payload.get("selected_tank"))
    pac = _as_mapping(payload.get("selected_pac"))
    profile = _as_mapping(payload.get("profile"))
    simulation = _as_mapping(payload.get("profile_simulation"))
    rows = [
        {"Parametre": "Stockage cible eq. 60 C", "Valeur": _fmt_number(payload.get("target_storage_l_eq60"), 0, "L")},
        {"Parametre": "Stockage retenu", "Valeur": _label(tank.get("label") or _fmt_number(tank.get("total_volume_l"), 0, "L"))},
        {"Parametre": "Puissance ECS2", "Valeur": _fmt_number(payload.get("pecs_kw"), 1, "kW")},
        {"Parametre": "Puissance PAC minimale", "Valeur": _fmt_number(payload.get("pac_min_kw"), 1, "kW")},
        {"Parametre": "PAC retenue", "Valeur": _label(f"{pac.get('unit_count', '')} x {pac.get('model', '')} {pac.get('brand', '')}".strip())},
        {"Parametre": "Puissance PAC installee", "Valeur": _fmt_number(pac.get("installed_power_kw"), 1, "kW")},
        {"Parametre": "Source solaire", "Valeur": _label(payload.get("source_type"))},
        {"Parametre": "Surface source", "Valeur": _fmt_number(payload.get("source_surface_m2"), 1, "m2")},
    ]
    if profile:
        rows.extend(
            [
                {"Parametre": "Profil source", "Valeur": _label(profile.get("source_name"))},
                {"Parametre": "Energie annuelle profil", "Valeur": _fmt_number(profile.get("annual_energy_mwh"), 1, "MWh/an")},
                {"Parametre": "Pointe horaire profil", "Valeur": _fmt_number(profile.get("peak_hourly_kw"), 1, "kW")},
            ]
        )
    if simulation:
        rows.extend(
            [
                {"Parametre": "Couverture horaire simplifiee", "Valeur": _fmt_percent(simulation.get("coverage_fraction"), 1)},
                {"Parametre": "SOC minimal stockage", "Valeur": _fmt_percent(simulation.get("min_soc_fraction"), 1)},
                {"Parametre": "Heures pleine charge PAC", "Valeur": _fmt_number(simulation.get("equivalent_full_load_hours"), 0, "h/an")},
            ]
        )
    return rows


def _economics_rows(economics: Mapping[str, Any]) -> list[dict[str, str]]:
    if not economics:
        return []
    return [
        {"Poste": "P1 energie", "Valeur": _fmt_number(economics.get("p1_eur_mwh"), 1, "EUR/MWh")},
        {"Poste": "P2 maintenance", "Valeur": _fmt_number(economics.get("p2_eur_mwh"), 1, "EUR/MWh")},
        {"Poste": "P4 investissement", "Valeur": _fmt_number(economics.get("p4_eur_mwh"), 1, "EUR/MWh")},
        {"Poste": "Cout chaleur PAC solaire + gaz", "Valeur": _fmt_number(economics.get("heat_cost_eur_mwh"), 1, "EUR/MWh")},
        {"Poste": "Reference gaz", "Valeur": _fmt_number(economics.get("average_reference_heat_cost_eur_mwh"), 1, "EUR/MWh")},
        {"Poste": "Investissement brut PAC solaire", "Valeur": _fmt_money(economics.get("capex_mid_eur"))},
        {"Poste": "Aide indicative", "Valeur": _fmt_money(economics.get("estimated_aid_eur"))},
        {"Poste": "Investissement net", "Valeur": _fmt_money(economics.get("net_investment_eur"))},
        {"Poste": "Economies annuelles", "Valeur": _fmt_money(economics.get("annual_savings_eur"))},
        {"Poste": "Duree d'analyse", "Valeur": _fmt_number(economics.get("analysis_years"), 0, "ans")},
    ]


def _monthly_rows(source: Any) -> list[dict[str, Any]]:
    rows = source if isinstance(source, list) else []
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        raw = _as_mapping(row)
        month = raw.get("month")
        if not month:
            continue
        output.append(
            {
                "Mois index": index,
                "Mois": month,
                "Besoin utile": _num(raw.get("useful_need_mwh", raw.get("heat_mwh"))),
                "Chaleur PAC": _num(raw.get("pac_condenser_mwh", raw.get("heat_mwh"))),
                "Appoint gaz": _num(raw.get("gas_backup_heat_mwh")),
                "COP systeme": _num(raw.get("cop_system")),
            }
        )
    return output


def build_heliocop_overview_pdf(payload: Mapping[str, Any]) -> bytes:
    """Construit une synthese PDF HelioCOP a partir du payload de synthese.

    Le payload est volontairement celui deja sauvegarde avec le projet HelioCOP :
    l'export PDF ne recalcule rien et reste donc coherent avec les resultats
    affiches et enregistres.
    """

    project = _as_mapping(payload.get("project"))
    project_name = _label(project.get("name"), "Projet HelioCOP")
    economics = _as_mapping(payload.get("economics"))
    solopac = _as_mapping(payload.get("solopac_results"))
    profile = _as_mapping(payload.get("profile"))
    tank = _as_mapping(payload.get("selected_tank"))
    pac = _as_mapping(payload.get("selected_pac"))

    report = PdfReport(
        title=f"HelioCOP - {project_name}",
        subtitle=_summary_subtitle(payload),
        landscape=True,
    )
    width = report.page_width
    margin = 34
    content_w = width - 2 * margin

    y = report.start_page()
    annual_need = (
        economics.get("annual_ecs_need_mwh")
        or solopac.get("annual_useful_need_mwh")
        or profile.get("annual_energy_mwh")
    )
    kpis = [
        ("Besoin annuel", _fmt_number(annual_need, 1, "MWh/an")),
        ("Stockage retenu", _label(tank.get("label") or _fmt_number(tank.get("total_volume_l"), 0, "L"))),
        ("PAC installee", _fmt_number(pac.get("installed_power_kw"), 1, "kW")),
        ("Surface source", _fmt_number(payload.get("source_surface_m2"), 1, "m2")),
        ("COP systeme", _fmt_number(economics.get("system_cop_including_aux") or solopac.get("annual_cop_system"), 2)),
        ("Electricite PAC + aux.", _fmt_number(economics.get("pac_electricity_mwh") or solopac.get("annual_total_electricity_mwh"), 1, "MWh/an")),
        ("Appoint gaz", _fmt_number(economics.get("gas_backup_heat_mwh") or solopac.get("annual_gas_backup_heat_mwh"), 1, "MWh/an")),
        ("Cout chaleur", _fmt_number(economics.get("heat_cost_eur_mwh"), 1, "EUR/MWh")),
    ]
    y = report.kpi_grid(kpis, x=margin, y=y, width=content_w, cols=4)
    y -= 8

    left_w = content_w * 0.46
    right_x = margin + left_w + 28
    right_w = content_w - left_w - 28
    left_y = report.section_title("Contexte projet", x=margin, y=y)
    report.table(_project_rows(payload), x=margin, y=left_y, width=left_w, columns=["Parametre", "Valeur"], col_weights=[0.42, 0.58])
    right_y = report.section_title("Dimensionnement", x=right_x, y=y)
    report.table(
        _technical_rows(payload),
        x=right_x,
        y=right_y,
        width=right_w,
        columns=["Parametre", "Valeur"],
        max_rows=14,
        col_weights=[0.48, 0.52],
    )

    y = 190
    report.section_title("Economie P1 / P2 / P4", x=margin, y=y)
    report.table(
        _economics_rows(economics),
        x=margin,
        y=y - 18,
        width=left_w,
        columns=["Poste", "Valeur"],
        max_rows=12,
        col_weights=[0.5, 0.5],
    )
    if economics:
        heat_cost_rows = [
            {"Poste": "P1 energie", "EUR/MWh": _num(economics.get("p1_eur_mwh"))},
            {"Poste": "P2 maintenance", "EUR/MWh": _num(economics.get("p2_eur_mwh"))},
            {"Poste": "P4 investissement", "EUR/MWh": _num(economics.get("p4_eur_mwh"))},
            {"Poste": "Reference gaz", "EUR/MWh": _num(economics.get("average_reference_heat_cost_eur_mwh"))},
        ]
        report.bar_chart(
            heat_cost_rows,
            x=right_x,
            y=62,
            width=right_w,
            height=92,
            label_col="Poste",
            value_col="EUR/MWh",
            title="Cout de chaleur",
            y_label="EUR/MWh",
        )

    monthly_rows = _monthly_rows(solopac.get("monthly_rows") or economics.get("monthly_rows"))
    if monthly_rows:
        report.draw_footer()
        y = report.start_page(title=f"HelioCOP - detail mensuel", subtitle=_summary_subtitle(payload))
        report.section_title("Bilan mensuel", x=margin, y=y)
        table_rows = [
            {
                "Mois": row["Mois"],
                "Besoin utile": _fmt_number(row["Besoin utile"], 1, "MWh"),
                "Chaleur PAC": _fmt_number(row["Chaleur PAC"], 1, "MWh"),
                "Appoint gaz": _fmt_number(row["Appoint gaz"], 1, "MWh"),
                "COP systeme": _fmt_number(row["COP systeme"], 2),
            }
            for row in monthly_rows
        ]
        report.table(
            table_rows,
            x=margin,
            y=y - 18,
            width=content_w,
            columns=["Mois", "Besoin utile", "Chaleur PAC", "Appoint gaz", "COP systeme"],
            max_rows=12,
            col_weights=[0.18, 0.21, 0.21, 0.2, 0.2],
        )
        chart_y = 62
        report.bar_chart(
            monthly_rows,
            x=margin,
            y=chart_y,
            width=content_w * 0.48,
            height=155,
            label_col="Mois",
            value_col="Chaleur PAC",
            title="Chaleur PAC mensuelle",
            y_label="MWh/mois",
        )
        report.line_chart(
            monthly_rows,
            x=margin + content_w * 0.52,
            y=chart_y,
            width=content_w * 0.48,
            height=155,
            x_col="Mois index",
            y_cols=[("COP systeme", "COP systeme")],
            title="COP systeme mensuel",
            y_label="COP",
            x_label="Mois",
        )

    return report.finish()
