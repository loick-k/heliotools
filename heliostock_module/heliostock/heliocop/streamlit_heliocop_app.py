"""Interface Streamlit HelioCOP — prédimensionnement PAC solaire ECS."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
import uuid

import pandas as pd
import streamlit as st

from .model import (
    DEFAULT_AID_EUR_PER_MWH_ENR,
    DEFAULT_MAX_PAC_COUNT,
    DEFAULT_MAX_TANK_COUNT,
    DEFAULT_MONTHLY_COEFFICIENTS,
    DEFAULT_STORAGE_FRACTION,
    HOUSING_NEEDS_L_EQ40_DAY,
    HOUSING_STANDARD_EQUIVALENTS,
    MONTH_NAMES,
    SOURCE_SURFACE_RATIO_M2_PER_KW_PPAC,
    SOURCE_SURFACE_RATIO_RANGES_M2_PER_KW_PPAC,
    best_pac_option_by_brand,
    build_monthly_sizing_rows,
    compute_housing_reference,
    costic_pac_min_kw,
    costic_pecs_kw,
    ecs2_dimensioning_power_kw,
    nearest_tank_options,
    pac_options_for_minimum,
    source_surface_m2,
    source_surface_range_m2,
    weighted_annual_daily_storage_l_eq60,
)
from .economics_pac import (
    DEFAULT_ANALYSIS_YEARS,
    DEFAULT_ELECTRICITY_COST_EUR_MWH,
    DEFAULT_MAINTENANCE_ANNUAL_EUR,
    DEFAULT_MONTHLY_COP_60C,
    DEFAULT_REFERENCE_EFFICIENCY,
    DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH,
    DEFAULT_REFERENCE_INFLATION,
    DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR,
    DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW,
    compute_pac_heat_cost_model,
    compute_pac_heat_cost_from_solopac,
)
from .hourly_profile import (
    HourlyLoadProfile,
    evaluate_profile_configurations,
    load_hourly_profile,
    minimum_storage_for_each_pac,
    pareto_profile_options,
    simulate_hourly_profile,
)
from .solopac_results import SoloPacResults, load_solopac_results
from .solopac_reference import (
    available_pvt_references,
    collector_reference_for_pac_brand,
    load_pac_reference,
    round_collector_surface,
    solopac_indicators,
)
from ..common.project_context import project_context_to_payload
from ..common.project_identity import ProjectIdentity, ProjectIdentityOptions, render_project_identity_form
from ..common.project_store import JsonProjectStore, normalize_email, now_iso, project_library_metadata, safe_slug
from ..gas_reference import (
    GAS_REFERENCE_EXISTING_BOILER,
    GAS_REFERENCE_RENEWAL,
    GAS_REFERENCE_CONTEXT_LABELS,
    GAS_REFERENCE_CONTEXT_HELP,
    gas_reference_context_label,
    includes_gas_boiler_fixed_costs,
    normalize_gas_reference_context,
)
from ..epw_reader import read_epw_hourly_weather_from_zip
from ..opportunity_notes.opportunity_model import (
    DEFAULT_LOOP_AMBIENT_TEMPERATURES_C,
    LOOP_METHODS,
    SOLO_LOOP_LOSS_MODE_LABELS,
    SOLO_LOSS_INPUT_MODES,
    LoopInputs,
    NeedsInputs,
    SiteInputs,
    SizingInputs,
    build_monthly_needs,
)
from ..ui_inputs import DEFAULT_EPW_REGIONS, WEATHER_STATION_LABEL_ALIASES
from ..ui_surface_orientation import (
    current_surface_orientation_payload,
    render_surface_orientation_measurement,
    restore_surface_orientation_state,
)
from .project_state import build_heliocop_state_payload, restore_heliocop_state_payload

APP_KEY = "heliocop"
APP_LABEL = "HelioCOP"
PROJECT_STORE = JsonProjectStore(APP_KEY, app_label=APP_LABEL)
ECS2_REFERENCE_IMAGE = Path(__file__).resolve().parent / "assets" / "schema_ecs2_reference.png"
PROFILE_EXAMPLE_FILE = Path(__file__).resolve().parent / "assets" / "profil_8760h_Cholet2_pessimiste.xlsx"
SOLOPAC_RESULTS_EXAMPLE_FILE = Path(__file__).resolve().parent / "assets" / "Resultats_SOLOPAC_Cholet2.xlsx"
PROFILE_TYPOLOGY = "Station de lavage poids lourds"
COLD_WATER_MODES = ("Température eau froide fixée", "Méthode ESM2", "Méthode ESM2 + 3 °C")
PARK_TYPES = tuple(HOUSING_STANDARD_EQUIVALENTS)


def _current_owner_email() -> str:
    user = st.session_state.get("user")
    if isinstance(user, dict):
        email = normalize_email(str(user.get("email", "")))
        if email:
            return email
    return normalize_email(str(st.session_state.get("heliostock_admin_email", "")))


def _coerce_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            for parser in (
                lambda text: datetime.fromisoformat(text.replace("Z", "+00:00")).date(),
                lambda text: datetime.strptime(text, "%Y/%m/%d").date(),
                lambda text: datetime.strptime(text, "%d/%m/%Y").date(),
            ):
                try:
                    return parser(cleaned)
                except ValueError:
                    continue
    return date.today()


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _identity_from_state() -> ProjectIdentity:
    return ProjectIdentity(
        project_name=str(st.session_state.get("heliocop_project_name") or "Nouveau projet HelioCOP"),
        client_name=str(st.session_state.get("heliocop_client_name") or ""),
        airtable_id=str(st.session_state.get("heliocop_airtable_id") or ""),
        analyst=str(st.session_state.get("heliocop_analyst") or ""),
        project_date=_coerce_date(st.session_state.get("heliocop_project_date")),
        typology=str(st.session_state.get("heliocop_typology") or "Logement collectif"),
        region=str(st.session_state.get("heliocop_region") or ""),
        department=str(st.session_state.get("heliocop_department") or ""),
        city=str(st.session_state.get("heliocop_city") or ""),
        address=str(st.session_state.get("heliocop_project_address_label") or st.session_state.get("heliocop_address") or ""),
        latitude=_coerce_float(st.session_state.get("heliocop_project_latitude"), 47.2184),
        longitude=_coerce_float(st.session_state.get("heliocop_project_longitude"), -1.5536),
        weather_region=str(st.session_state.get("heliocop_weather_region") or "Bretagne"),
        weather_station=str(st.session_state.get("heliocop_weather_station") or "Rennes"),
        notes=str(st.session_state.get("heliocop_notes") or ""),
    )


def _build_project_payload() -> dict:
    identity = _identity_from_state()
    saved_at = now_iso()
    previous_project_id = str(st.session_state.get("heliocop_current_project_id") or "")
    library_id = str(st.session_state.get("heliocop_project_library_id") or previous_project_id or uuid.uuid4())
    metadata = project_library_metadata(
        project_name=identity.project_name or "Nouveau projet HelioCOP",
        project_reference=identity.airtable_id,
        saved_at=saved_at,
        library_id=library_id,
    )
    versioned_project_id = f"{metadata['version_id']}-{safe_slug(metadata['library_id'], fallback='heliocop')}"
    summary = st.session_state.get("heliocop_last_summary_payload")
    if not isinstance(summary, dict):
        summary = {}
    return {
        "schema_version": 1,
        "app_key": APP_KEY,
        "app_label": APP_LABEL,
        "project_id": versioned_project_id,
        "name": identity.project_name or "Nouveau projet HelioCOP",
        "created_at": str(st.session_state.get("heliocop_project_created_at") or saved_at),
        "saved_at": saved_at,
        **metadata,
        "project_context": project_context_to_payload(
            identity,
            app_key=APP_KEY,
            app_label=APP_LABEL,
            geographic_scope="Bretagne / Pays de la Loire",
            weather_source="Fichiers météo EPW locaux",
        ),
        "surface_orientation": current_surface_orientation_payload("heliocop"),
        "state": build_heliocop_state_payload(st.session_state),
        "summary": summary,
    }


def _project_file_label(project_file) -> str:
    payload = project_file.payload if hasattr(project_file, "payload") else project_file["payload"]
    path = project_file.path if hasattr(project_file, "path") else project_file["path"]
    name = str(payload.get("library_name") or payload.get("name") or payload.get("project_name") or path.stem)
    version = str(payload.get("version_label") or payload.get("updated_at") or payload.get("saved_at") or "")
    reference = str(payload.get("library_reference") or "")
    suffix = " - ".join(part for part in (reference, version[:16]) if part)
    return f"{name} | {suffix}" if suffix else name


def _restore_project_payload(payload: dict) -> None:
    project_id = str(payload.get("project_id") or payload.get("library_id") or "loaded")
    restore_heliocop_state_payload(payload.get("state", {}), st.session_state)
    restore_surface_orientation_state(payload, project_id=project_id, state_prefix="heliocop")
    st.session_state["heliocop_current_project_id"] = project_id
    st.session_state["heliocop_project_library_id"] = str(payload.get("library_id") or project_id)
    st.session_state["heliocop_project_created_at"] = str(payload.get("created_at") or payload.get("saved_at") or now_iso())
    summary = payload.get("summary")
    if isinstance(summary, dict):
        st.session_state["heliocop_last_summary_payload"] = summary


def _reset_project_state() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith(("heliocop_", "heliocop_v2_")):
            st.session_state.pop(key, None)
    st.session_state["heliocop_project_reset_notice"] = "Nouveau projet HelioCOP initialisé."


def _is_current_admin() -> bool:
    user = st.session_state.get("user")
    return isinstance(user, dict) and str(user.get("role", "user")).lower() == "admin"


def _normalise_project_emails(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [email for email in (normalize_email(str(value)) for value in values) if email]


def _load_accessible_project_payload(path: Path, current_email: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Format de projet HelioCOP invalide.")
    if str(payload.get("app_key") or "") != APP_KEY:
        raise ValueError("Ce projet n'est pas un projet HelioCOP.")
    owner_email = normalize_email(str(payload.get("owner_email", "")))
    shared_emails = _normalise_project_emails(payload.get("shared_with_emails"))
    if not (owner_email == current_email or current_email in shared_emails or _is_current_admin()):
        raise PermissionError("Ce projet HelioCOP n'est pas accessible à cet utilisateur.")
    return payload


def _accessible_project_files(owner_email: str) -> list[dict]:
    items: dict[Path, dict] = {}
    for project_file in PROJECT_STORE.list_projects(owner_email=owner_email):
        items[project_file.path] = {"path": project_file.path, "payload": project_file.payload}
    root = PROJECT_STORE.app_dir()
    if root.exists():
        for path in root.rglob("*.json"):
            if path in items:
                continue
            try:
                payload = _load_accessible_project_payload(path, owner_email)
            except Exception:
                continue
            items[path] = {"path": path, "payload": payload}
    return sorted(items.values(), key=lambda item: item["path"].stat().st_mtime, reverse=True)


def _render_project_store_controls() -> None:
    owner_email = _current_owner_email()
    if not owner_email:
        st.info("Connecte-toi pour enregistrer et recharger des projets HelioCOP.")
        return

    project_files = _accessible_project_files(owner_email)
    labels = [_project_file_label(project_file) for project_file in project_files]
    duplicates = {label for label in labels if labels.count(label) > 1}
    display_labels = [
        f"{label} [{index + 1}]" if label in duplicates else label
        for index, label in enumerate(labels)
    ]

    c_select, c_load, c_new, c_save, c_delete = st.columns([4, 1, 1, 1, 1])
    selected_index = None
    with c_select:
        selected_label = st.selectbox(
            "Projet enregistré",
            options=display_labels,
            index=0 if display_labels else None,
            placeholder="Aucun projet HelioCOP enregistré",
            key="heliocop_project_store_selected",
        )
        if selected_label in display_labels:
            selected_index = display_labels.index(selected_label)
    with c_load:
        st.write("")
        if st.button("Charger", width="stretch", disabled=selected_index is None, key="heliocop_project_load"):
            selected_project = project_files[int(selected_index)]
            payload = _load_accessible_project_payload(selected_project["path"], owner_email)
            _restore_project_payload(payload)
            st.session_state["heliocop_project_store_notice"] = "Projet HelioCOP chargé."
            st.rerun()
    with c_new:
        st.write("")
        if st.button("Nouveau", width="stretch", key="heliocop_project_new"):
            _reset_project_state()
            st.rerun()
    with c_save:
        st.write("")
        if st.button("Enregistrer", type="primary", width="stretch", key="heliocop_project_save"):
            payload = _build_project_payload()
            path = PROJECT_STORE.save_project(
                payload=payload,
                owner_email=owner_email,
                project_name=str(payload.get("name") or "Nouveau projet HelioCOP"),
                project_id=str(payload.get("project_id") or ""),
            )
            st.session_state["heliocop_current_project_id"] = str(payload.get("project_id") or path.stem)
            st.session_state["heliocop_project_library_id"] = str(payload.get("library_id") or "")
            st.session_state["heliocop_project_created_at"] = str(payload.get("created_at") or now_iso())
            st.session_state["heliocop_project_store_notice"] = "Projet HelioCOP enregistré."
            st.rerun()
    with c_delete:
        st.write("")
        selected_owner_email = ""
        if selected_index is not None:
            selected_owner_email = normalize_email(str(project_files[int(selected_index)]["payload"].get("owner_email", "")))
        can_delete = selected_index is not None and selected_owner_email == owner_email
        if st.button("Supprimer", width="stretch", disabled=not can_delete, key="heliocop_project_delete"):
            selected_project = project_files[int(selected_index)]
            PROJECT_STORE.delete_project(path=selected_project["path"], owner_email=owner_email)
            st.session_state["heliocop_project_store_notice"] = "Projet HelioCOP supprimé."
            st.rerun()

    notice = st.session_state.pop("heliocop_project_store_notice", "")
    reset_notice = st.session_state.pop("heliocop_project_reset_notice", "")
    if notice:
        st.success(str(notice))
    if reset_notice:
        st.info(str(reset_notice))


def _number(value: float, digits: int = 1) -> str:
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


def _percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{100.0 * value:.{digits}f} %".replace(".", ",")


def _render_heat_cost_bar(economics, gas_reference_context: str, *, key_prefix: str) -> None:
    """Barres empilées P1/P2/P4 des deux scénarios économiques."""
    try:
        import plotly.graph_objects as go
    except Exception:
        st.info("Plotly n'est pas disponible pour afficher le graphique du coût de chaleur.")
        return

    categories = ["Scénario PAC solaire + gaz", "Scénario référence gaz"]
    p1 = [economics.p1_eur_mwh, economics.reference_heat_p1_eur_mwh]
    p2 = [economics.p2_eur_mwh, economics.reference_heat_p2_eur_mwh]
    p4 = [economics.p4_eur_mwh, economics.reference_heat_p4_eur_mwh]
    fig = go.Figure()
    fig.add_bar(name="P1 - Énergie", x=categories, y=p1)
    fig.add_bar(name="P2 - Maintenance", x=categories, y=p2)
    fig.add_bar(name="P4 - Investissement", x=categories, y=p4)
    fig.update_layout(
        barmode="stack",
        title="Coût de chaleur des deux scénarios — P1 / P2 / P4",
        yaxis_title="€HT/MWh utile",
        xaxis_title="",
        legend_title_text="",
        margin=dict(l=40, r=20, t=55, b=35),
    )
    st.plotly_chart(fig, width="stretch", key=f"{key_prefix}_heat_cost")
    if not includes_gas_boiler_fixed_costs(gas_reference_context):
        st.caption("Référence gaz existante : la chaudière est déjà en place ; aucun nouvel investissement chaudière n'est ajouté dans les deux scénarios.")


def _render_investment_scenarios(economics, gas_reference_context: str, *, key_prefix: str) -> None:
    """Rend explicites les investissements initiaux des deux scénarios."""
    renewal = includes_gas_boiler_fixed_costs(gas_reference_context)
    st.markdown("#### Investissements initiaux — comparaison des deux scénarios")
    if renewal:
        st.info(
            "La chaudière gaz est à renouveler dans les deux scénarios. "
            "Le scénario de référence investit uniquement dans la chaudière gaz ; "
            "le scénario PAC solaire investit dans la PAC solaire **et** dans une chaudière gaz d'appoint/secours."
        )
    else:
        st.info(
            "La chaudière gaz est considérée existante et conservée. Son investissement initial est donc nul dans les deux scénarios ; "
            "seul le scénario PAC solaire porte un nouvel investissement."
        )

    left, right = st.columns(2)
    with left:
        st.markdown("**Scénario 1 — Référence gaz**")
        st.metric("PAC solaire", "0 € HT")
        st.metric("Chaudière gaz", f"{_number(economics.reference_scenario_gross_investment_eur, 0)} € HT")
        st.metric("Aide", "0 €")
        st.metric("Investissement net initial", f"{_number(economics.reference_scenario_net_investment_eur, 0)} € HT")
    with right:
        st.markdown("**Scénario 2 — PAC solaire + gaz**")
        st.metric("PAC solaire — CAPEX brut", f"{_number(economics.capex_mid_eur, 0)} € HT")
        st.metric("Chaudière gaz appoint/secours", f"{_number(economics.pac_scenario_boiler_investment_eur, 0)} € HT")
        st.metric("Aide PAC solaire", f"− {_number(economics.estimated_aid_eur, 0)} €")
        st.metric("Investissement net initial", f"{_number(economics.pac_scenario_net_investment_eur, 0)} € HT")

    delta = economics.incremental_net_investment_eur
    label = "Surinvestissement net du scénario PAC solaire" if delta >= 0 else "Économie d'investissement initiale du scénario PAC solaire"
    st.metric(label, f"{_number(abs(delta), 0)} € HT")

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Poste d'investissement": "PAC solaire / source / hydraulique",
                    "Scénario référence gaz (€HT)": 0.0,
                    "Scénario PAC solaire + gaz (€HT)": economics.capex_mid_eur,
                },
                {
                    "Poste d'investissement": "Chaudière gaz",
                    "Scénario référence gaz (€HT)": economics.reference_boiler_investment_eur,
                    "Scénario PAC solaire + gaz (€HT)": economics.pac_scenario_boiler_investment_eur,
                },
                {
                    "Poste d'investissement": "Total brut",
                    "Scénario référence gaz (€HT)": economics.reference_scenario_gross_investment_eur,
                    "Scénario PAC solaire + gaz (€HT)": economics.pac_scenario_gross_investment_eur,
                },
                {
                    "Poste d'investissement": "Aides déduites",
                    "Scénario référence gaz (€HT)": 0.0,
                    "Scénario PAC solaire + gaz (€HT)": -economics.estimated_aid_eur,
                },
                {
                    "Poste d'investissement": "Total net initial",
                    "Scénario référence gaz (€HT)": economics.reference_scenario_net_investment_eur,
                    "Scénario PAC solaire + gaz (€HT)": economics.pac_scenario_net_investment_eur,
                },
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    try:
        import plotly.graph_objects as go
    except Exception:
        return
    categories = ["Référence gaz", "PAC solaire + gaz"]
    fig = go.Figure()
    fig.add_bar(
        name="PAC solaire",
        x=categories,
        y=[0.0, economics.capex_mid_eur],
    )
    fig.add_bar(
        name="Chaudière gaz",
        x=categories,
        y=[economics.reference_boiler_investment_eur, economics.pac_scenario_boiler_investment_eur],
    )
    fig.update_layout(
        barmode="stack",
        title="Investissement brut par scénario",
        yaxis_title="€ HT",
        xaxis_title="",
        legend_title_text="",
        margin=dict(l=40, r=20, t=55, b=35),
    )
    st.plotly_chart(fig, width="stretch", key=f"{key_prefix}_investment")
    st.caption(
        "L'aide est déduite après le CAPEX brut de la PAC solaire. L'incertitude CAPEX s'applique au poste PAC solaire, "
        "pas au coût de la chaudière gaz."
    )


def _render_solopac_monthly_energy_chart(results: SoloPacResults) -> None:
    """Barres mensuelles EnR / électricité compresseur / appoint gaz + taux EnR."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except Exception:
        st.info("Plotly n'est pas disponible pour afficher les graphiques SOLOPAC.")
        return

    months = [r.month for r in results.monthly_rows]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(name="EnR captée par la PAC", x=months, y=[r.renewable_evaporator_mwh for r in results.monthly_rows], secondary_y=False)
    fig.add_bar(name="Part électrique compresseur", x=months, y=[r.compressor_electricity_mwh for r in results.monthly_rows], secondary_y=False)
    fig.add_bar(name="Appoint gaz", x=months, y=[r.gas_backup_heat_mwh for r in results.monthly_rows], secondary_y=False)
    fig.add_scatter(name="Taux EnR", x=months, y=[100.0 * r.renewable_rate for r in results.monthly_rows], mode="lines+markers", secondary_y=True)
    fig.update_layout(barmode="stack", title="Apports énergétiques mensuels issus de SOLOPAC", xaxis_title="", legend_title_text="", margin=dict(l=40, r=40, t=55, b=35))
    fig.update_yaxes(title_text="Énergie (MWh/mois)", secondary_y=False)
    fig.update_yaxes(title_text="Taux EnR (%)", range=[0, 100], secondary_y=True)
    st.plotly_chart(fig, width="stretch", key="solopac_monthly_energy")
    st.caption("La part électrique représente l'électricité du compresseur qui contribue à la chaleur au condenseur. Les auxiliaires électriques (circulateurs) ne sont pas empilés dans ce bilan thermique mais sont bien comptés dans le bilan économique.")


def _render_solopac_cop_chart(results: SoloPacResults) -> None:
    """Variation mensuelle du COP système fourni par SOLOPAC sous forme de colonnes."""
    try:
        import plotly.graph_objects as go
    except Exception:
        return
    months = [r.month for r in results.monthly_rows]
    fig = go.Figure()
    fig.add_bar(x=months, y=[r.cop_system for r in results.monthly_rows], name="COP SOLOPAC")
    fig.update_layout(title="Variation mensuelle du COP PAC solaire", xaxis_title="", yaxis_title="COP système", margin=dict(l=40, r=20, t=55, b=35), showlegend=False)
    st.plotly_chart(fig, width="stretch", key="solopac_monthly_cop")


def _solopac_monthly_dataframe(results: SoloPacResults) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Mois": r.month,
            "Besoin utile (MWh)": r.useful_need_mwh,
            "Chaleur PAC (MWh)": r.pac_condenser_mwh,
            "EnR évaporateur (MWh)": r.renewable_evaporator_mwh,
            "Élec. compresseur (MWh)": r.compressor_electricity_mwh,
            "Auxiliaires élec. (MWh)": r.auxiliary_electricity_mwh,
            "Appoint gaz (MWh utile)": r.gas_backup_heat_mwh,
            "COP": r.cop_system,
            "Taux EnR (%)": 100.0 * r.renewable_rate,
            "Couverture PAC (%)": 100.0 * r.pac_coverage_rate,
        }
        for r in results.monthly_rows
    ])


def _render_solopac_pac_reference(selected_pac) -> None:
    """Affiche les points de référence issus des XML SoloPAC 1.1."""
    xml_name = getattr(selected_pac, "xml_filename", None)
    if not xml_name:
        st.caption("Pas de fichier de performances SoloPAC 1.1 disponible pour cette PAC dans la bibliothèque actuelle.")
        return
    perf = load_pac_reference(xml_name)
    if perf is None:
        st.caption("Le fichier SoloPAC ne contient pas les deux points EN14511 nécessaires pour cette PAC.")
        return
    ref60 = perf.linear_reference_at_sink(60.0)
    with st.expander("Données de référence PAC — SoloPAC 1.1", expanded=False):
        st.caption(
            "SoloPAC construit sa matrice dynamique à partir de points EN14511 et des lois d'interpolation/extrapolation RE2020. "
            "HelioCOP ne reproduit pas encore cette matrice : B10/W60 ci-dessous est seulement une interpolation linéaire de repérage entre B10/W45 et B10/W65."
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("COP B10/W45", f"{perf.cop_10_45:.2f}")
        c2.metric("COP B10/W55", f"{perf.cop_10_55:.2f}" if perf.cop_10_55 > 0 else "—")
        c3.metric("COP B10/W65", f"{perf.cop_10_65:.2f}" if perf.cop_10_65 > 0 else "—")
        c4.metric(
            "Repère B10/W60",
            f"COP {ref60.cop_machine:.2f} / {ref60.thermal_power_kw * selected_pac.unit_count:.1f} kW" if ref60 is not None else "Non applicable",
        )
        st.write(
            f"Plage évaporateur déclarée : **{perf.tmin_evaporator_c:.0f} à {perf.tmax_evaporator_c:.0f} °C** — "
            f"Tmax condenseur : **{perf.tmax_condenser_c:.0f} °C**."
        )
        if perf.tmax_condenser_c > 0 and perf.tmax_condenser_c < 60.0:
            st.warning(
                "Cette PAC est déclarée avec une température maximale côté chauffage/condenseur inférieure à 60 °C. "
                "Elle reste disponible pour les applications process, mais son emploi sur un besoin réellement à 60 °C doit être validé "
                "avec le fabricant ou avec une architecture adaptée."
            )
        st.write(
            f"Auxiliaires hydrauliques déclarés : **{perf.aux_power_kw:.3f} kW par PAC** "
            f"({perf.evaporator_pump_kw:.3f} kW évaporateur + {perf.condenser_pump_kw:.3f} kW condenseur)."
        )


def _monthly_air_temperatures_from_station(region_name: str, station_label: str) -> dict[str, float]:
    station_label = WEATHER_STATION_LABEL_ALIASES.get(station_label, station_label)
    station = DEFAULT_EPW_REGIONS.get(region_name, {}).get(station_label)
    if station is None or not station.path.exists():
        return {month: 12.0 for month in MONTH_NAMES}
    _location, hourly = read_epw_hourly_weather_from_zip(
        station.path,
        tilt_deg=35.0,
        azimuth_deg_south=0.0,
        albedo=0.2,
    )
    rows = [
        {"Mois": MONTH_NAMES[item.month - 1], "Tair": float(item.tair_c)}
        for item in hourly
        if 1 <= item.month <= 12
    ]
    if not rows:
        return {month: 12.0 for month in MONTH_NAMES}
    means = pd.DataFrame(rows).groupby("Mois")["Tair"].mean().to_dict()
    return {month: float(means.get(month, 12.0)) for month in MONTH_NAMES}


def _esm2_cold_water_temperatures(monthly_air_c: dict[str, float], offset_c: float = 0.0) -> dict[str, float]:
    annual_mean = sum(monthly_air_c.get(month, 12.0) for month in MONTH_NAMES) / 12.0
    return {
        month: min(25.0, max(5.0, 0.6 * annual_mean + 0.4 * monthly_air_c.get(month, annual_mean) + offset_c))
        for month in MONTH_NAMES
    }


def _loop_inputs_ui(project_key: str) -> LoopInputs:
    st.subheader("Bouclage sanitaire")
    method = st.radio(
        "Méthode d'estimation",
        options=list(LOOP_METHODS),
        index=0,
        horizontal=True,
        key=f"{project_key}_loop_method",
    )

    kwargs: dict = {"method": method}
    if method == "Analyse factures gaz":
        st.caption(
            "Même logique que HelioNOP : le talon journalier minimal de juin à septembre est corrigé du rendement chaudière, "
            "puis le besoin ECS utile du mois porteur du talon est retranché."
        )
        efficiency = st.number_input(
            "Rendement chaudière",
            min_value=0.0,
            max_value=1.0,
            value=0.85,
            step=0.01,
            key=f"{project_key}_boiler_efficiency",
        )
        gas_rows = pd.DataFrame([{"Mois": m, "Conso gaz (kWh/mois)": 0.0} for m in MONTH_NAMES])
        gas_edit = st.data_editor(
            gas_rows,
            hide_index=True,
            width="stretch",
            disabled=["Mois"],
            key=f"{project_key}_gas_editor",
        )
        kwargs.update(
            boiler_efficiency=float(efficiency),
            gas_monthly_kwh={str(r["Mois"]): max(0.0, float(r["Conso gaz (kWh/mois)"])) for _, r in gas_edit.iterrows()},
        )

    elif method == "Hypothèses SOLO 2018":
        loss_label = st.selectbox(
            "Calcul des pertes de bouclage",
            options=list(SOLO_LOOP_LOSS_MODE_LABELS),
            index=5,
            key=f"{project_key}_solo_loss_mode",
        )
        kwargs["solo_loss_mode_label"] = loss_label

        if loss_label == "Saisie pertes (kWh/j)":
            input_mode = st.radio(
                "Mode de saisie",
                options=list(SOLO_LOSS_INPUT_MODES),
                horizontal=True,
                key=f"{project_key}_solo_loss_input_mode",
            )
            kwargs["solo_losses_input_mode"] = input_mode
            if input_mode == "Saisie annuelle":
                kwargs["solo_losses_annual_kwh"] = st.number_input(
                    "Pertes annuelles (kWh/an)", min_value=0.0, value=0.0, step=100.0, key=f"{project_key}_solo_loss_annual"
                )
            else:
                rows = pd.DataFrame([{"Mois": m, "Pertes (kWh/j)": 0.0} for m in MONTH_NAMES])
                edit = st.data_editor(rows, hide_index=True, width="stretch", disabled=["Mois"], key=f"{project_key}_solo_loss_monthly")
                kwargs["solo_losses_monthly_kwh_day"] = {
                    str(r["Mois"]): max(0.0, float(r["Pertes (kWh/j)"])) for _, r in edit.iterrows()
                }
        elif loss_label == "Débit et delta T connus":
            c1, c2 = st.columns(2)
            kwargs["solo_debit_bouclage_l_h"] = c1.number_input(
                "Débit de bouclage (L/h)", min_value=0.0, value=300.0, step=10.0, key=f"{project_key}_solo_debit"
            )
            kwargs["solo_delta_tmax_bouclage_k"] = c2.number_input(
                "Delta T max (K)", min_value=0.0, value=5.0, step=0.5, key=f"{project_key}_solo_dt"
            )
        elif loss_label == "Longueur et isolation connues":
            c1, c2 = st.columns(2)
            kwargs["solo_long_bouclage_m"] = c1.number_input(
                "Longueur de boucle (m)", min_value=0.0, value=120.0, step=5.0, key=f"{project_key}_solo_len"
            )
            kwargs["solo_kl_bouclage_w_m_k"] = c2.number_input(
                "Perte linéique (W/m/K)", min_value=0.0, value=0.30, step=0.01, key=f"{project_key}_solo_kl"
            )
        elif loss_label == "Boucle courte bien isolée":
            c1, c2 = st.columns(2)
            kwargs["solo_long1_boucle_bon_m_per_unit"] = c1.number_input(
                "Longueur boucle par logement (m/logement)", min_value=0.0, value=6.0, step=0.1, key=f"{project_key}_solo_good_len"
            )
            kwargs["solo_kl_boucle_bon_w_m_k"] = c2.number_input(
                "Perte linéique (W/m/K)", min_value=0.0, value=0.20, step=0.01, key=f"{project_key}_solo_good_kl"
            )
        elif loss_label == "Boucle qualité moyenne":
            c1, c2 = st.columns(2)
            kwargs["solo_long1_boucle_moyen_m_per_unit"] = c1.number_input(
                "Longueur boucle par logement (m/logement)", min_value=0.0, value=9.0, step=0.1, key=f"{project_key}_solo_mid_len"
            )
            kwargs["solo_kl_boucle_moyen_w_m_k"] = c2.number_input(
                "Perte linéique (W/m/K)", min_value=0.0, value=0.30, step=0.01, key=f"{project_key}_solo_mid_kl"
            )
        elif loss_label == "Boucle longue mal isolée":
            c1, c2 = st.columns(2)
            kwargs["solo_long1_boucle_mauvais_m_per_unit"] = c1.number_input(
                "Longueur boucle par logement (m/logement)", min_value=0.0, value=12.0, step=0.1, key=f"{project_key}_solo_bad_len"
            )
            kwargs["solo_kl_boucle_mauvais_w_m_k"] = c2.number_input(
                "Perte linéique (W/m/K)", min_value=0.0, value=0.40, step=0.01, key=f"{project_key}_solo_bad_kl"
            )

        with st.expander("Paramètres généraux SOLO 2018", expanded=False):
            c1, c2, c3 = st.columns(3)
            kwargs["solo_tref_bouclage_c"] = c1.number_input(
                "T° référence boucle (°C)", value=55.0, step=1.0, key=f"{project_key}_solo_tref"
            )
            kwargs["solo_tenv_bouclage_c"] = c2.number_input(
                "T° environnement (°C)", value=20.0, step=1.0, key=f"{project_key}_solo_tenv"
            )
            kwargs["solo_active_ratio"] = c3.number_input(
                "Ratio boucle active", min_value=0.0, max_value=1.0, value=1.0, step=0.05, key=f"{project_key}_solo_active"
            )
            temps = pd.DataFrame(
                [
                    {"Mois": m, "Température environnement mensuelle (°C)": DEFAULT_LOOP_AMBIENT_TEMPERATURES_C[m]}
                    for m in MONTH_NAMES
                ]
            )
            temp_edit = st.data_editor(
                temps,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_key}_solo_monthly_temps",
            )
            kwargs["solo_monthly_temperatures_c"] = {
                str(r["Mois"]): float(r["Température environnement mensuelle (°C)"]) for _, r in temp_edit.iterrows()
            }

    return LoopInputs(**kwargs)



@st.cache_data(show_spinner=False)
def _evaluate_profile_cached(
    energy_kwh: tuple[float, ...],
    months: tuple[int, ...],
    days: tuple[int, ...],
    hours: tuple[int, ...],
    cold_values: tuple[float, ...],
):
    profile = HourlyLoadProfile(
        energy_kwh=energy_kwh,
        months=months,
        days=days,
        hours=hours,
        source_name="cache",
        source_sheet="besoins_8760h",
        energy_columns=("besoin thermique",),
    )
    cold = {month: value for month, value in zip(MONTH_NAMES, cold_values)}
    return evaluate_profile_configurations(
        profile,
        cold_water_temperatures_c=cold,
        max_pac_count=DEFAULT_MAX_PAC_COUNT,
        tank_count=DEFAULT_MAX_TANK_COUNT,
        usage="Process",
    )

def render_heliocop_app() -> None:
    st.title("HelioCOP — Note d'opportunité PAC solaire")
    st.caption(
        "Deux modes de prédimensionnement : logement collectif avec méthode COSTIC 2.3.2, "
        "ou usage process avec profil thermique horaire 8760 h. Le schéma ECS2 reste l'architecture de référence."
    )

    _render_project_store_controls()

    tab_labels = [
        "1. Projet",
        "2. Orientation / surface",
        "3. Eau froide",
        "4. Besoins ECS",
        "5. Bouclage sanitaire",
        "6. PAC solaire",
        "7. Économie",
        "8. Simulation SOLOPAC",
        "9. Économie SOLOPAC",
        "10. Synthèse",
    ]
    tabs = st.tabs(tab_labels)
    (
        tab_site, tab_surface, tab_cold, tab_needs, tab_loop, tab_pac,
        tab_economics, tab_solopac, tab_solopac_economics, tab_summary,
    ) = tabs
    project_key = "heliocop_v2"

    with tab_site:
        st.subheader("Caractéristiques du site")
        identity = render_project_identity_form(
            key_prefix="heliocop",
            project_id=str(st.session_state.get("heliocop_current_project_id") or "current"),
            defaults=_identity_from_state(),
            options=ProjectIdentityOptions(
                show_typology=True,
                show_weather=True,
                typology_options=("Logement collectif", PROFILE_TYPOLOGY),
                weather_regions=DEFAULT_EPW_REGIONS,
                weather_station_aliases=WEATHER_STATION_LABEL_ALIASES,
                client_label="Maître d'ouvrage / client",
                address_help="L'adresse alimente la localisation et le choix de la station météo.",
            ),
        )
        profile_mode = identity.typology == PROFILE_TYPOLOGY
        if profile_mode:
            st.info(
                "Mode profil horaire : le besoin industriel est lu directement dans un fichier 8760 h. "
                "Les abaques COSTIC logement collectif ne sont pas utilisés."
            )
        else:
            st.info("Mode logement collectif : besoins par typologie puis prédimensionnement COSTIC 2.3.2.")

    with tab_surface:
        render_surface_orientation_measurement(state_prefix="heliocop")
    surface_payload = current_surface_orientation_payload("heliocop")
    surface_metrics = surface_payload.get("metrics", {}) if isinstance(surface_payload, dict) else {}
    max_surface_m2 = None
    if isinstance(surface_metrics, dict):
        raw = surface_metrics.get("max_collector_surface_m2")
        if isinstance(raw, (int, float)) and raw > 0:
            max_surface_m2 = float(raw)

    with tab_cold:
        st.subheader("Température d'eau froide")
        cold_mode = st.radio(
            "Mode de calcul",
            options=list(COLD_WATER_MODES),
            horizontal=True,
            key=f"{project_key}_cold_mode",
        )
        if cold_mode == "Température eau froide fixée":
            fixed_tef = st.number_input(
                "Température d'eau froide fixée (°C)",
                min_value=0.0,
                max_value=30.0,
                value=12.0,
                step=0.5,
                key=f"{project_key}_fixed_tef",
            )
            cold_water = {month: float(fixed_tef) for month in MONTH_NAMES}
            st.dataframe(
                pd.DataFrame([{"Mois": month, "T eau froide retenue (°C)": cold_water[month]} for month in MONTH_NAMES]),
                hide_index=True,
                width="stretch",
            )
        else:
            monthly_air = _monthly_air_temperatures_from_station(
                identity.weather_region or "Bretagne", identity.weather_station or "Rennes"
            )
            cold_water = _esm2_cold_water_temperatures(
                monthly_air, 3.0 if cold_mode == "Méthode ESM2 + 3 °C" else 0.0
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Mois": month,
                            "T extérieure moyenne (°C)": monthly_air[month],
                            "T eau froide retenue (°C)": cold_water[month],
                        }
                        for month in MONTH_NAMES
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        if profile_mode:
            st.caption(
                "En mode profil horaire, le fichier fournit directement les kWh thermiques appelés. "
                "La Tef sert à convertir le volume des ballons ECS2 en capacité de stockage équivalente à 60 °C."
            )

    # Valeurs communes initialisées pour les deux branches.
    housing = None
    building_state = None
    park_type = None
    counts: dict[str, int] = {}
    needs40: dict[str, float] = {}
    monthly_coefficients = dict(DEFAULT_MONTHLY_COEFFICIENTS)
    profile: HourlyLoadProfile | None = None

    with tab_needs:
        if not profile_mode:
            st.subheader("Estimation des besoins ECS — logement collectif")
            building_state = st.selectbox(
                "Nature du bâtiment",
                options=["Bâtiment neuf", "Bâtiment existant"],
                key=f"{project_key}_building_state",
            )
            if building_state == "Bâtiment existant":
                st.warning("La méthode par ratios reste une première approche. Sur existant, un comptage ECS est préférable.")
            park_type = st.radio("Type de parc", options=list(PARK_TYPES), horizontal=True, key=f"{project_key}_park_type")
            eq = HOUSING_STANDARD_EQUIVALENTS[park_type]
            needs40 = HOUSING_NEEDS_L_EQ40_DAY[park_type]
            default_counts = {"T1": 0, "T2": 0, "T3": 10, "T4": 30, "T5": 0, "T6 ou plus": 0}
            housing_df = pd.DataFrame(
                [
                    {
                        "Type de logement": kind,
                        "Nombre": default_counts.get(kind, 0),
                        "Coeff. logement standard": eq[kind],
                        "Besoin unitaire (L.eq40°C/j)": needs40[kind],
                    }
                    for kind in eq
                ]
            )
            housing_edit = st.data_editor(
                housing_df,
                hide_index=True,
                width="stretch",
                disabled=["Type de logement", "Coeff. logement standard", "Besoin unitaire (L.eq40°C/j)"],
                key=f"{project_key}_housing_editor",
            )
            counts = {str(r["Type de logement"]): max(0, int(r["Nombre"])) for _, r in housing_edit.iterrows()}
            housing = compute_housing_reference(counts, park_type)

            m1, m2, m3 = st.columns(3)
            m1.metric("Logements réels", f"{housing.actual_dwellings}")
            m2.metric(
                "Logements standards",
                _number(housing.standard_dwellings_exact, 1),
                f"Ns COSTIC = {housing.standard_dwellings_costic}",
            )
            m3.metric("Besoin ECS de référence", f"{_number(housing.daily_need_l_eq40, 0)} L.eq40°C/j")

            with st.expander("Coefficients mensuels", expanded=False):
                coeff_df = pd.DataFrame([{"Mois": m, "Coefficient": monthly_coefficients[m]} for m in MONTH_NAMES])
                coeff_edit = st.data_editor(
                    coeff_df,
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    key=f"{project_key}_coeff_editor",
                )
                monthly_coefficients = {
                    str(r["Mois"]): max(0.0, float(r["Coefficient"])) for _, r in coeff_edit.iterrows()
                }

            needs_preview = build_monthly_sizing_rows(
                daily_need_l_eq40=housing.daily_need_l_eq40,
                cold_water_temperatures_c=cold_water,
                monthly_coefficients=monthly_coefficients,
                storage_fraction=1.0,
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Mois": r.month,
                            "Coeff.": r.coefficient,
                            "Besoin moyen (L.eq40°C/j)": r.daily_need_l_eq40,
                            "T eau froide (°C)": r.cold_water_temperature_c,
                            "Besoin utile ECS (MWh/mois)": r.useful_ecs_energy_mwh,
                        }
                        for r in needs_preview
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.subheader("Besoins process — profil thermique horaire")
            st.write(
                "Le profil est interprété comme une énergie thermique utile appelée à chaque heure. "
                "Pour le fichier HelioStock transmis, HelioCOP additionne `E besoin HT kWh` et `E besoin BT kWh`."
            )
            source_mode = st.radio(
                "Source du profil",
                options=["Téléverser un fichier", "Utiliser le profil exemple Cholet fourni"],
                horizontal=True,
                key=f"{project_key}_profile_source",
            )
            profile_error = None
            try:
                if source_mode == "Utiliser le profil exemple Cholet fourni":
                    if PROFILE_EXAMPLE_FILE.exists():
                        profile = load_hourly_profile(PROFILE_EXAMPLE_FILE)
                    else:
                        profile_error = "Le fichier exemple n'est pas présent dans le package."
                else:
                    uploaded = st.file_uploader(
                        "Profil thermique 8760 h (.xlsx ou .csv)",
                        type=["xlsx", "csv"],
                        key=f"{project_key}_profile_file",
                        help=(
                            "Format recommandé : feuille besoins_8760h, 8760 lignes, colonnes month/day/hour et "
                            "E besoin HT kWh / E besoin BT kWh."
                        ),
                    )
                    if uploaded is not None:
                        profile = load_hourly_profile(uploaded, source_name=uploaded.name)
            except Exception as exc:
                profile_error = str(exc)
                profile = None

            if profile_error:
                st.error(profile_error)
            if profile is None:
                st.info("Chargez un profil 8760 h pour activer le prédimensionnement PAC / stockage dans l'onglet 6.")
            else:
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Pas horaires", f"{profile.hour_count}")
                p2.metric("Besoin annuel", f"{_number(profile.annual_energy_mwh, 1)} MWh/an")
                p3.metric("Pointe horaire", f"{_number(profile.peak_hourly_kw, 1)} kW")
                p4.metric("Heures avec besoin", f"{profile.nonzero_hours}")
                st.caption(
                    f"Source : {profile.source_name} — feuille {profile.source_sheet} — colonnes utilisées : "
                    + ", ".join(profile.energy_columns)
                )

                profile_df = pd.DataFrame(
                    {
                        "Mois": profile.months,
                        "Jour": profile.days,
                        "Heure": profile.hours,
                        "Besoin thermique (kWh/h)": profile.energy_kwh,
                    }
                )
                monthly_profile = (
                    profile_df.groupby("Mois")["Besoin thermique (kWh/h)"]
                    .agg(**{"Besoin kWh": "sum", "Pointe kW": "max"})
                    .reset_index()
                )
                monthly_profile["Mois"] = monthly_profile["Mois"].map(
                    {index + 1: month for index, month in enumerate(MONTH_NAMES)}
                )
                monthly_profile["Besoin MWh"] = monthly_profile["Besoin kWh"] / 1000.0
                st.dataframe(
                    monthly_profile[["Mois", "Besoin MWh", "Pointe kW"]],
                    hide_index=True,
                    width="stretch",
                )
                st.bar_chart(monthly_profile.set_index("Mois")["Besoin MWh"])
                with st.expander("Aperçu du profil horaire", expanded=False):
                    st.dataframe(profile_df.head(168), hide_index=True, width="stretch")

    # Bouclage : commun uniquement au mode logement. En mode process, le profil
    # fourni est considéré comme le besoin thermique à couvrir et aucun bouclage
    # sanitaire n'est ajouté automatiquement.
    annual_loop_mwh = 0.0
    loop_design_power_kw = 0.0
    common_monthly = ()
    annual_ecs_mwh = profile.annual_energy_mwh if profile_mode and profile is not None else 0.0
    if not profile_mode and housing is not None and building_state is not None and park_type is not None:
        site_inputs = SiteInputs(
            project_name=identity.project_name,
            airtable_id=identity.airtable_id,
            client_name=identity.client_name,
            city=identity.city,
            address=identity.address,
            latitude=float(identity.latitude),
            longitude=float(identity.longitude),
            weather_region=identity.weather_region or "Bretagne",
            weather_station=identity.weather_station or "Rennes",
            typology="Logement collectif",
            building_state=building_state,
            data_source="Ratio SOCOL",
        )
        needs_inputs = NeedsInputs(
            ecs_temperature_c=40.0,
            housing_counts=counts,
            housing_ratios_l_day=dict(needs40),
            monthly_coefficients=monthly_coefficients,
        )
        common_sizing_inputs = SizingInputs(
            cold_water_mode=cold_mode,
            cold_water_temperatures_c=cold_water,
        )

    with tab_loop:
        if profile_mode:
            st.subheader("Bouclage sanitaire")
            st.info(
                "Non ajouté en mode profil horaire. Le fichier importé est considéré comme le profil thermique total du procédé à couvrir. "
                "Si une boucle de maintien en température existe sur le site, elle devra être intégrée au profil ou ajoutée dans une évolution dédiée."
            )
            if profile is not None:
                st.metric("Besoin thermique du profil", f"{_number(profile.annual_energy_mwh, 1)} MWh/an")
        else:
            loop_inputs = _loop_inputs_ui(project_key)
            common_monthly = build_monthly_needs(site_inputs, needs_inputs, common_sizing_inputs, loop_inputs)
            annual_ecs_mwh = sum(r.useful_energy_mwh for r in common_monthly)
            annual_loop_mwh = sum(r.loop_losses_mwh for r in common_monthly)
            # Le livret SOCOL ECS2 adapte la méthode COSTIC en ajoutant PBoucl
            # à la puissance PAC. On prend ici la plus forte puissance moyenne
            # mensuelle de pertes de boucle comme valeur de prédimensionnement.
            loop_design_power_kw = max(
                (r.loop_losses_kwh / max(1.0, r.days * 24.0) for r in common_monthly),
                default=0.0,
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Besoin utile ECS", f"{_number(annual_ecs_mwh, 1)} MWh/an")
            c2.metric("Bouclage sanitaire", f"{_number(annual_loop_mwh, 1)} MWh/an")
            c3.metric("ECS + bouclage", f"{_number(annual_ecs_mwh + annual_loop_mwh, 1)} MWh/an")
            c4.metric("PBoucl retenue", f"{_number(loop_design_power_kw, 1)} kW")
            st.caption(
                "Schéma ECS2 SOCOL : la PAC solaire vise quasi intégralement l'ECS et la compensation du bouclage. "
                "Pour le prédimensionnement, PnomPAC = 0,7 × PECS + PBoucl. PBoucl est ici estimée par la plus forte puissance moyenne mensuelle de pertes de boucle."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Mois": r.month,
                            "ECS utile (MWh)": r.useful_energy_mwh,
                            "Bouclage (MWh)": r.loop_losses_mwh,
                            "ECS + boucle (MWh)": r.total_ecs_energy_mwh,
                        }
                        for r in common_monthly
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    # Variables de résultat communes aux deux moteurs.
    selected_pac = None
    selected_tank = None
    required_surface = 0.0
    source_type = "Moquette solaire"
    pecs_kw = None
    pac_min_kw = None
    pdim_kw = None
    target_storage = None
    sizing_rows = ()
    selected_profile_option = None
    selected_profile_simulation = None
    pareto_options = ()
    solopac_results = None
    solopac_economics = None

    with tab_pac:
        st.subheader("Prédimensionnement PAC solaire")
        with st.expander("Schéma de référence — ECS2", expanded=False):
            if ECS2_REFERENCE_IMAGE.exists():
                st.image(
                    str(ECS2_REFERENCE_IMAGE),
                    caption="Schéma ECS2 — production ECS par PAC solaire avec stockage en deux zones",
                    use_container_width=True,
                )
            st.caption(
                "HelioCOP prend ECS2 comme architecture de référence : zone prioritaire + zone de préchauffage. "
                "Le stockage est prédimensionné sous forme de deux ballons identiques."
            )

        if not profile_mode:
            with st.expander("Hypothèses de prédimensionnement", expanded=False):
                storage_fraction = st.number_input(
                    "Part du besoin journalier retenue pour le stockage",
                    min_value=0.50,
                    max_value=1.20,
                    value=DEFAULT_STORAGE_FRACTION,
                    step=0.05,
                    key=f"{project_key}_storage_fraction",
                )
                st.caption("Valeur de travail HelioCOP : 80 % du besoin journalier à 40 °C.")
                st.write("Stockage ECS2 : 2 ballons identiques, de 1 000 / 1 250 / 1 500 / 2 000 / 2 500 / 3 000 L chacun.")
                st.write(f"Sélection PAC : jusqu'à {DEFAULT_MAX_PAC_COUNT} machines identiques, sans mélange de modèle ni de marque.")

            sizing_rows = build_monthly_sizing_rows(
                daily_need_l_eq40=housing.daily_need_l_eq40,
                cold_water_temperatures_c=cold_water,
                monthly_coefficients=monthly_coefficients,
                storage_fraction=float(storage_fraction),
            )
            target_storage = weighted_annual_daily_storage_l_eq60(sizing_rows)
            lower_tank, upper_tank = nearest_tank_options(target_storage, DEFAULT_MAX_TANK_COUNT)

            st.markdown("#### 1. Conversion du stockage à 60 °C")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Mois": r.month,
                            "Besoin 40°C (L/j)": r.daily_need_l_eq40,
                            "Stock 40°C (L/j)": r.daily_storage_l_eq40,
                            "Tef (°C)": r.cold_water_temperature_c,
                            "Coeff. 40→60": r.conversion_factor_40_to_60,
                            "Stock eq.60°C (L/j)": r.daily_storage_l_eq60,
                        }
                        for r in sizing_rows
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            st.metric("Volume cible annuel moyen à 60 °C", f"{_number(target_storage, 0)} L")

            tank_choices = []
            if lower_tank is not None:
                tank_choices.append(("Stockage inférieur", lower_tank))
            if upper_tank is not None and (lower_tank is None or upper_tank.total_volume_l != lower_tank.total_volume_l):
                tank_choices.append(("Stockage supérieur", upper_tank))
            if not tank_choices:
                st.error("Aucune paire de ballons disponible pour ce volume cible.")
            else:
                default_tank_index = min(range(len(tank_choices)), key=lambda i: abs(tank_choices[i][1].difference_l))
                labels = [f"{name} — {option.label} ({option.difference_l:+.0f} L)" for name, option in tank_choices]
                tank_label = st.radio(
                    "Stockage retenu",
                    options=labels,
                    index=default_tank_index,
                    key=f"{project_key}_tank_choice",
                )
                selected_tank = tank_choices[labels.index(tank_label)][1]

                st.markdown("#### 2. Puissance ECS et puissance PAC")
                pecs_kw = costic_pecs_kw(housing.standard_dwellings_costic, selected_tank.total_volume_l)
                pdim_kw = ecs2_dimensioning_power_kw(pecs_kw, loop_design_power_kw)
                pac_min_kw = costic_pac_min_kw(pecs_kw, loop_design_power_kw)
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Ns COSTIC", f"{housing.standard_dwellings_costic}")
                p2.metric("PECS sans boucle", f"{_number(pecs_kw, 1)} kW")
                p3.metric("PDIM = PECS + PBoucl", f"{_number(pdim_kw, 1)} kW")
                p4.metric("P PAC minimale ECS2", f"{_number(pac_min_kw, 1)} kW")
                st.caption("Règle ECS2 SOCOL : Pnominale PAC = 0,7 × PECS + PBoucl.")
                if housing.standard_dwellings_costic < 10:
                    st.warning("L'abaque COSTIC 2.3.2 est donné pour au moins 10 logements standards : résultat hors domaine de référence.")

                all_pac_options = pac_options_for_minimum(pac_min_kw, max_pac_count=DEFAULT_MAX_PAC_COUNT, usage="ECS")
                best_options = best_pac_option_by_brand(all_pac_options)
                if not best_options:
                    st.error("Aucune combinaison PAC de la bibliothèque ne couvre la puissance minimale avec la limite de nombre de PAC.")
                else:
                    st.markdown("#### 3. Arrondi sur les gammes constructeur")
                    cols = st.columns(len(best_options))
                    for col, option in zip(cols, best_options):
                        with col:
                            st.markdown(f"**{option.brand}**")
                            st.metric("Configuration la plus proche", f"{option.installed_power_kw:.0f} kW", f"+{option.oversizing_kw:.1f} kW")
                            st.write(f"{option.unit_count} × {option.model} ({option.unit_power_kw:.0f} kW unitaire)")
                            if not option.dynamic_data_available:
                                st.caption("Courbes dynamiques à compléter pour ce modèle.")
                    pac_choice_labels = [option.label for option in best_options]
                    default_pac_index = min(
                        range(len(best_options)), key=lambda i: (best_options[i].installed_power_kw, best_options[i].unit_count)
                    )
                    chosen_label = st.radio(
                        "Configuration PAC retenue",
                        options=pac_choice_labels,
                        index=default_pac_index,
                        key=f"{project_key}_pac_choice",
                    )
                    selected_pac = best_options[pac_choice_labels.index(chosen_label)]
        else:
            st.markdown("#### 1. Dimensionnement direct sur le profil 8760 h")
            if profile is None:
                st.warning("Chargez le profil dans l'onglet 4 pour lancer le calcul horaire.")
            else:
                with st.expander("Hypothèses du modèle horaire simplifié", expanded=False):
                    st.write("• pas de temps fixe : 1 heure ;")
                    st.write("• profil importé = besoin thermique utile à couvrir ;")
                    st.write("• stockage ECS2 agrégé en 2 ballons identiques à 60 °C ;")
                    st.write("• Tef mensuelle = méthode choisie dans l'onglet 3 ;")
                    st.write("• PAC disponible à sa puissance nominale à chaque heure et autorisée à recharger hors puisage ;")
                    st.write("• stockage initialement chargé à 100 % ;")
                    st.write("• pas de stratification nodale, pertes ballon, variation de COP ni contrainte solaire à ce stade.")
                    st.caption("Ces phénomènes seront traités dans le futur moteur dynamique de validation.")

                with st.spinner("Test des couples PAC / paires de ballons sur 8 760 h…"):
                    evaluated = _evaluate_profile_cached(
                        profile.energy_kwh,
                        profile.months,
                        profile.days,
                        profile.hours,
                        tuple(float(cold_water[m]) for m in MONTH_NAMES),
                    )
                min_storage_options = minimum_storage_for_each_pac(evaluated)
                pareto_options = pareto_profile_options(min_storage_options)

                p1, p2, p3 = st.columns(3)
                p1.metric("Besoin annuel", f"{_number(profile.annual_energy_mwh, 1)} MWh/an")
                p2.metric("Pointe horaire du process", f"{_number(profile.peak_hourly_kw, 1)} kW")
                p3.metric("Configurations testées", f"{len(evaluated)}")

                feasible_count = sum(1 for option in evaluated if option.simulation.is_feasible)
                st.caption(
                    f"{feasible_count} couples couvrent 100 % du profil. Le tableau ci-dessous présente le front de Pareto "
                    "puissance PAC / volume de stockage."
                )

                if not pareto_options:
                    st.error(
                        "Aucune configuration de la bibliothèque actuelle ne couvre 100 % du profil avec deux ballons et "
                        f"au plus {DEFAULT_MAX_PAC_COUNT} PAC identiques."
                    )
                    best_partial = sorted(
                        evaluated,
                        key=lambda option: (
                            -option.simulation.coverage_fraction,
                            option.pac.installed_power_kw,
                            -option.tank.total_volume_l,
                        ),
                    )[:8]
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Marque": o.pac.brand,
                                    "PAC": f"{o.pac.unit_count} × {o.pac.model}",
                                    "P PAC (kW)": o.pac.installed_power_kw,
                                    "Stockage": o.tank.label,
                                    "Couverture": 100 * o.simulation.coverage_fraction,
                                    "Énergie non couverte (MWh)": o.simulation.unmet_energy_mwh,
                                }
                                for o in best_partial
                            ]
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                else:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Marque": o.pac.brand,
                                    "PAC": f"{o.pac.unit_count} × {o.pac.model}",
                                    "P PAC installée (kW)": o.pac.installed_power_kw,
                                    "Stockage ECS2": o.tank.label,
                                    "SOC mini": 100 * o.simulation.min_soc_fraction,
                                    "Équiv. pleine charge (h/an)": o.simulation.equivalent_full_load_hours,
                                }
                                for o in pareto_options
                            ]
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                    labels = [option.label for option in pareto_options]
                    selected_label = st.radio(
                        "Couple PAC / stockage retenu",
                        options=labels,
                        index=0,
                        key=f"{project_key}_profile_solution",
                    )
                    selected_profile_option = pareto_options[labels.index(selected_label)]
                    selected_pac = selected_profile_option.pac
                    selected_tank = selected_profile_option.tank
                    selected_profile_simulation, trace = simulate_hourly_profile(
                        profile,
                        pac_power_kw=selected_pac.installed_power_kw,
                        storage_volume_l=selected_tank.total_volume_l,
                        cold_water_temperatures_c=cold_water,
                        with_trace=True,
                    )

                    r1, r2, r3, r4 = st.columns(4)
                    r1.metric("PAC installée", f"{selected_pac.installed_power_kw:.0f} kW")
                    r2.metric("Stockage", selected_tank.label)
                    r3.metric("Couverture du profil", _percent(selected_profile_simulation.coverage_fraction, 2))
                    r4.metric("SOC minimal", _percent(selected_profile_simulation.min_soc_fraction, 1))
                    st.success(
                        f"Configuration retenue : {selected_pac.unit_count} × {selected_pac.model} ({selected_pac.brand}) "
                        f"avec {selected_tank.label}."
                    )

                    if trace:
                        trace_df = pd.DataFrame(
                            {
                                "Besoin thermique (kW moyen horaire)": [row.demand_kwh for row in trace],
                                "Chaleur PAC (kW moyen horaire)": [row.pac_heat_kwh for row in trace],
                                "SOC stockage (%)": [100.0 * row.storage_soc_fraction for row in trace],
                            },
                            index=pd.date_range("2025-01-01", periods=len(trace), freq="h"),
                        )
                        min_pos = int(trace_df["SOC stockage (%)"].to_numpy().argmin())
                        start = max(0, min_pos - 72)
                        end = min(len(trace_df), min_pos + 97)
                        st.markdown("##### Période la plus contraignante autour du SOC minimal")
                        st.line_chart(trace_df.iloc[start:end][["Besoin thermique (kW moyen horaire)", "Chaleur PAC (kW moyen horaire)"]])
                        st.line_chart(trace_df.iloc[start:end][["SOC stockage (%)"]])

        if selected_pac is not None:
            _render_solopac_pac_reference(selected_pac)

        st.markdown("#### Source solaire")
        source_type = st.radio(
            "Technologie de source",
            options=list(SOURCE_SURFACE_RATIO_M2_PER_KW_PPAC),
            horizontal=True,
            key=f"{project_key}_source_type",
        )
        ratio_min, ratio_max = SOURCE_SURFACE_RATIO_RANGES_M2_PER_KW_PPAC[source_type]
        ratio_default = SOURCE_SURFACE_RATIO_M2_PER_KW_PPAC[source_type]
        source_ratio = st.number_input(
            "Ratio de surface retenu (m²/kW PAC)",
            min_value=float(ratio_min),
            max_value=float(ratio_max),
            value=float(ratio_default),
            step=0.1,
            key=f"{project_key}_source_ratio",
            help=(
                "Livret SOCOL ECS2 : 4 à 6 m²/kW PAC pour les capteurs non vitrés, "
                "3 à 6 m²/kW PAC pour le PVT. La valeur proposée correspond au REX fabricant utilisé jusque-là dans HelioCOP."
            ),
        )
        if selected_pac is not None:
            required_surface = source_surface_m2(selected_pac.installed_power_kw, source_type, source_ratio)
            socol_low, socol_high = source_surface_range_m2(selected_pac.installed_power_kw, source_type)
            st.metric(
                f"Surface {source_type}",
                f"{_number(required_surface, 1)} m²",
                f"{source_ratio:.1f} m²/kW de Ppac installée",
            )
            st.caption(
                f"Plage indicative SOCOL ECS2 pour {selected_pac.installed_power_kw:.0f} kW PAC : "
                f"{socol_low:.0f} à {socol_high:.0f} m²."
            )

            if source_type == "Moquette solaire":
                collector_ref = collector_reference_for_pac_brand(selected_pac.brand, source_type)
                if collector_ref is not None:
                    rounded = round_collector_surface(required_surface, collector_ref)
                    st.info(
                        f"Référence présente dans SoloPAC 1.1 : {collector_ref.brand} {collector_ref.model} "
                        f"({collector_ref.unit_area_m2:.2f} m²/unité). Arrondi commercial : "
                        f"{rounded.collector_count} capteurs = {rounded.installed_surface_m2:.1f} m²."
                    )
            else:
                pvt_refs = available_pvt_references()
                if pvt_refs:
                    with st.expander("Références PVT présentes dans SoloPAC 1.1", expanded=False):
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Marque": ref.brand,
                                        "Modèle": ref.model,
                                        "Surface unitaire (m²)": ref.unit_area_m2,
                                        "eta0": ref.eta0,
                                        "a1 (W/m².K)": ref.a1_w_m2_k,
                                    }
                                    for ref in pvt_refs
                                ]
                            ),
                            hide_index=True,
                            width="stretch",
                        )

            if max_surface_m2 is not None:
                if required_surface <= max_surface_m2:
                    st.success(
                        f"Surface compatible avec l'emprise renseignée : {required_surface:.1f} m² ≤ {max_surface_m2:.1f} m² disponibles."
                    )
                else:
                    st.warning(
                        f"Surface requise supérieure à l'emprise estimée : {required_surface:.1f} m² > {max_surface_m2:.1f} m² disponibles."
                    )
        else:
            st.info("La surface de source sera calculée après sélection d'une PAC.")

    monthly_heat_for_economics = {month: 0.0 for month in MONTH_NAMES}
    if profile_mode and profile is not None:
        for value_kwh, month_number in zip(profile.energy_kwh, profile.months):
            if 1 <= int(month_number) <= 12:
                monthly_heat_for_economics[MONTH_NAMES[int(month_number) - 1]] += max(0.0, float(value_kwh)) / 1000.0
    elif common_monthly:
        monthly_heat_for_economics = {
            row.month: max(0.0, float(row.total_ecs_energy_mwh)) for row in common_monthly
        }

    annual_ecs_mwh_for_economics = sum(monthly_heat_for_economics.values())

    economics = None
    monthly_cop = dict(DEFAULT_MONTHLY_COP_60C)
    electricity_cost = DEFAULT_ELECTRICITY_COST_EUR_MWH
    maintenance_annual_eur = DEFAULT_MAINTENANCE_ANNUAL_EUR
    analysis_years = DEFAULT_ANALYSIS_YEARS
    aid_rate = DEFAULT_AID_EUR_PER_MWH_ENR
    uncertainty_pct = 20.0
    reference_energy_cost = DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH
    reference_efficiency = DEFAULT_REFERENCE_EFFICIENCY
    reference_inflation = DEFAULT_REFERENCE_INFLATION
    gas_reference_context = normalize_gas_reference_context(st.session_state.get(f"{project_key}_gas_reference_context", GAS_REFERENCE_EXISTING_BOILER))
    if profile_mode and profile is not None:
        _boiler_default = max(0.0, float(profile.peak_hourly_kw))
    elif pdim_kw is not None:
        _boiler_default = max(0.0, float(pdim_kw))
    elif selected_pac is not None:
        _boiler_default = max(0.0, float(selected_pac.installed_power_kw))
    else:
        _boiler_default = 0.0
    reference_boiler_power_kw = _boiler_default
    pac_scenario_boiler_power_kw = _boiler_default
    reference_boiler_p2_eur_kw_year = DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR
    reference_boiler_capex_eur_kw = DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW

    with tab_economics:
        st.subheader("Énergie et coût de chaleur PAC solaire")
        if selected_pac is None:
            st.warning("Sélectionner d'abord une configuration PAC dans l'onglet 6.")
            economics = None
        else:
            st.markdown("#### COP mensuels de référence — production à 60 °C")
            st.caption(
                "Les COP sont appliqués au besoin thermique adressé de chaque mois. "
                "Le COP annuel affiché ensuite est donc un COP saisonnier pondéré par les besoins, et non une moyenne arithmétique des 12 COP."
            )
            cop_df = pd.DataFrame(
                [{"Mois": month, "COP PAC à 60 °C": DEFAULT_MONTHLY_COP_60C[month]} for month in MONTH_NAMES]
            )
            cop_edit = st.data_editor(
                cop_df,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_key}_monthly_cop_60c",
            )
            monthly_cop = {
                str(row["Mois"]): max(1.01, float(row["COP PAC à 60 °C"]))
                for _, row in cop_edit.iterrows()
            }

            c1, c2, c3, c4 = st.columns(4)
            electricity_cost = c1.number_input(
                "Prix électricité PAC (€HT/MWh)",
                min_value=0.0,
                value=DEFAULT_ELECTRICITY_COST_EUR_MWH,
                step=10.0,
                key=f"{project_key}_electricity_cost",
            )
            maintenance_annual_eur = c2.number_input(
                "Maintenance PAC solaire (€HT/an)",
                min_value=0.0,
                value=DEFAULT_MAINTENANCE_ANNUAL_EUR,
                step=100.0,
                key=f"{project_key}_maintenance_annual_eur",
                disabled=True,
                help="Forfait HelioCOP : 2 000 € HT/an, indépendant de la taille de l'installation.",
            )
            analysis_years = c3.number_input(
                "Durée d'analyse (ans)",
                min_value=1,
                max_value=50,
                value=DEFAULT_ANALYSIS_YEARS,
                step=1,
                key=f"{project_key}_analysis_years",
            )
            aid_rate = c4.number_input(
                "Aide forfaitaire (€/MWh EnR)",
                min_value=0.0,
                value=DEFAULT_AID_EUR_PER_MWH_ENR,
                step=50.0,
                key=f"{project_key}_aid_rate",
            )

            gas_context_options = list(GAS_REFERENCE_CONTEXT_LABELS)
            gas_reference_context = st.radio(
                "Contexte de référence gaz",
                options=gas_context_options,
                format_func=gas_reference_context_label,
                index=gas_context_options.index(
                    normalize_gas_reference_context(
                        st.session_state.get(f"{project_key}_gas_reference_context", GAS_REFERENCE_EXISTING_BOILER)
                    )
                ),
                horizontal=True,
                key=f"{project_key}_gas_reference_context",
                help=GAS_REFERENCE_CONTEXT_HELP,
            )

            with st.expander("Hypothèses économiques avancées", expanded=False):
                a1, a2, a3, a4 = st.columns(4)
                uncertainty_pct = a1.number_input(
                    "Incertitude CAPEX (%)",
                    min_value=0.0,
                    max_value=50.0,
                    value=20.0,
                    step=5.0,
                    key=f"{project_key}_cost_uncertainty",
                )
                reference_energy_cost = a2.number_input(
                    "Coût énergie de référence (€HT/MWh entrée)",
                    min_value=0.0,
                    value=DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH,
                    step=5.0,
                    key=f"{project_key}_reference_energy_cost",
                )
                reference_efficiency = a3.number_input(
                    "Rendement production de référence",
                    min_value=0.01,
                    max_value=1.5,
                    value=DEFAULT_REFERENCE_EFFICIENCY,
                    step=0.01,
                    key=f"{project_key}_reference_efficiency",
                )
                reference_inflation = a4.number_input(
                    "Inflation énergie référence (%/an)",
                    min_value=-5.0,
                    max_value=20.0,
                    value=DEFAULT_REFERENCE_INFLATION * 100.0,
                    step=0.5,
                    key=f"{project_key}_reference_inflation",
                ) / 100.0

                if profile_mode and profile is not None:
                    boiler_power_default = max(0.0, float(profile.peak_hourly_kw))
                elif pdim_kw is not None:
                    boiler_power_default = max(0.0, float(pdim_kw))
                else:
                    boiler_power_default = max(0.0, float(selected_pac.installed_power_kw))
                st.markdown("**Chaudière gaz — investissement dans les deux scénarios**")
                g1, g2 = st.columns(2)
                reference_boiler_power_kw = g1.number_input(
                    "Scénario référence — puissance chaudière 100 % gaz (kW)",
                    min_value=0.0,
                    value=boiler_power_default,
                    step=10.0,
                    disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
                    key=f"{project_key}_reference_boiler_power_kw",
                )
                pac_scenario_boiler_power_kw = g2.number_input(
                    "Scénario PAC solaire — puissance chaudière appoint/secours (kW)",
                    min_value=0.0,
                    value=boiler_power_default,
                    step=10.0,
                    disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
                    key=f"{project_key}_pac_scenario_boiler_power_kw",
                    help="Par défaut identique à la chaudière de référence. Peut être ajustée si l'architecture PAC solaire justifie une puissance d'appoint différente.",
                )
                g3, g4 = st.columns(2)
                reference_boiler_p2_eur_kw_year = g3.number_input(
                    "Maintenance chaudière gaz (€/kW.an)",
                    min_value=0.0,
                    value=DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR,
                    step=1.0,
                    disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
                    key=f"{project_key}_reference_boiler_p2",
                )
                reference_boiler_capex_eur_kw = g4.number_input(
                    "Investissement chaudière gaz (€/kW)",
                    min_value=0.0,
                    value=DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW,
                    step=10.0,
                    disabled=gas_reference_context != GAS_REFERENCE_RENEWAL,
                    key=f"{project_key}_reference_boiler_capex",
                )
                if gas_reference_context == GAS_REFERENCE_RENEWAL:
                    st.caption(
                        "Ces coûts unitaires sont appliqués séparément à la puissance de chaudière de chaque scénario. "
                        "Le scénario PAC solaire n'évite donc pas artificiellement le renouvellement de la chaudière d'appoint/secours."
                    )

            # Les auxiliaires hydrauliques restent issus des données SoloPAC quand elles sont disponibles.
            aux_electricity_mwh = 0.0
            pac_ref = load_pac_reference(getattr(selected_pac, "xml_filename", "") or "")
            if pac_ref is not None and selected_pac.installed_power_kw > 0:
                if profile_mode and selected_profile_simulation is not None:
                    equivalent_hours = selected_profile_simulation.equivalent_full_load_hours
                else:
                    equivalent_hours = annual_ecs_mwh_for_economics * 1000.0 / selected_pac.installed_power_kw
                aux_electricity_mwh = (
                    pac_ref.aux_power_kw * selected_pac.unit_count * max(0.0, equivalent_hours) / 1000.0
                )
            elif selected_pac.model == "Solerpac P25":
                st.warning(
                    "La Solerpac P25 ne dispose pas encore de données auxiliaires dans la bibliothèque SoloPAC importée. "
                    "Son P1 et son COP système sont donc calculés sans consommation de circulateurs, ce qui avantage cette solution dans la comparaison."
                )

            economics = compute_pac_heat_cost_model(
                monthly_heat_mwh=monthly_heat_for_economics,
                selected_pac_power_kw=selected_pac.installed_power_kw,
                source_surface_m2=required_surface,
                monthly_cop=monthly_cop,
                auxiliary_electricity_mwh=aux_electricity_mwh,
                electricity_cost_eur_mwh=float(electricity_cost),
                maintenance_annual_eur=float(maintenance_annual_eur),
                analysis_years=int(analysis_years),
                aid_eur_per_mwh_enr=float(aid_rate),
                cost_uncertainty=float(uncertainty_pct) / 100.0,
                reference_energy_cost_eur_mwh=float(reference_energy_cost),
                reference_efficiency=float(reference_efficiency),
                reference_inflation_rate=float(reference_inflation),
                gas_reference_context=str(gas_reference_context),
                reference_boiler_power_kw=float(reference_boiler_power_kw),
                pac_scenario_boiler_power_kw=float(pac_scenario_boiler_power_kw),
                reference_boiler_p2_eur_kw_year=float(reference_boiler_p2_eur_kw_year),
                reference_boiler_capex_eur_kw=float(reference_boiler_capex_eur_kw),
            )

            monthly_energy_df = pd.DataFrame(
                [
                    {
                        "Mois": row.month,
                        "Besoin adressé (MWh)": row.heat_mwh,
                        "COP PAC": row.cop_machine,
                        "Élec. compresseur (MWh)": row.compressor_electricity_mwh,
                        "Auxiliaires (MWh)": row.auxiliary_electricity_mwh,
                        "EnR hors élec. (MWh)": row.renewable_heat_mwh,
                    }
                    for row in economics.monthly_rows
                ]
            )
            st.dataframe(monthly_energy_df, hide_index=True, width="stretch")

            e1, e2, e3, e4, e5 = st.columns(5)
            e1.metric("Besoin couvert", f"{_number(economics.annual_heat_mwh, 1)} MWh/an")
            e2.metric("Élec. compresseur", f"{_number(economics.compressor_electricity_mwh, 1)} MWh/an")
            e3.metric("Auxiliaires estimés", f"{_number(economics.auxiliary_electricity_mwh, 1)} MWh/an")
            e4.metric("COP PAC saisonnier", f"{economics.seasonal_cop_machine:.2f}")
            e5.metric("COP système incl. aux", f"{economics.system_cop_including_aux:.2f}")

            fsav, cop_socol, fpac = solopac_indicators(
                q_pac_mwh=economics.annual_heat_mwh,
                q_appoint_mwh=0.0,
                w_pac_mwh=economics.total_electricity_mwh,
            )
            st.caption(
                f"Chaleur EnR hors électricité : {_number(economics.renewable_heat_mwh, 1)} MWh/an "
                f"({_percent(economics.renewable_share)} du besoin). "
                f"Indicateurs simplifiés : COP moyen système = {cop_socol:.2f}, FPAC = {100*fpac:.1f} %."
            )

            _render_investment_scenarios(economics, gas_reference_context, key_prefix="predim")

            st.markdown("#### Coût de chaleur — logique HelioEco P1 / P2 / P4")
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("P1 — électricité", f"{_number(economics.p1_eur_mwh, 1)} €/MWh")
            h2.metric("P2 — maintenance système", f"{_number(economics.p2_eur_mwh, 1)} €/MWh")
            h3.metric("P4 — investissement net scénario", f"{_number(economics.p4_eur_mwh, 1)} €/MWh")
            h4.metric("Coût chaleur PAC solaire", f"{_number(economics.heat_cost_eur_mwh, 1)} €/MWh")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Poste": "P1 - Électricité PAC + auxiliaires", "Coût annuel (€HT/an)": economics.p1_annual_eur, "Coût chaleur (€/MWh)": economics.p1_eur_mwh},
                        {"Poste": "P2 - Maintenance PAC solaire + chaudière gaz si renouvelée", "Coût annuel (€HT/an)": economics.p2_annual_eur, "Coût chaleur (€/MWh)": economics.p2_eur_mwh},
                        {"Poste": f"P4 - Investissement net du scénario PAC / {economics.analysis_years} ans", "Coût annuel (€HT/an)": economics.pac_scenario_net_investment_eur / economics.analysis_years, "Coût chaleur (€/MWh)": economics.p4_eur_mwh},
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            _render_heat_cost_bar(economics, gas_reference_context, key_prefix="predim")
            r1, r2, r3 = st.columns(3)
            r1.metric("Référence chaleur moyenne", f"{_number(economics.average_reference_heat_cost_eur_mwh, 1)} €/MWh")
            r2.metric("Économies annuelles d'exploitation (P1+P2)", f"{_number(economics.annual_savings_eur, 0)} €HT/an")
            if includes_gas_boiler_fixed_costs(gas_reference_context):
                r3.metric("Surinvestissement initial net PAC vs référence", f"{_number(economics.incremental_net_investment_eur, 0)} €HT")
                pac_cumulative = economics.pac_scenario_net_investment_eur + (economics.p1_annual_eur + economics.p2_annual_eur) * economics.analysis_years
                gas_cumulative = economics.average_reference_heat_cost_eur_mwh * economics.annual_heat_mwh * economics.analysis_years
                cgas1, cgas2 = st.columns(2)
                cgas1.metric(f"Coût cumulé PAC solaire sur {economics.analysis_years} ans", f"{_number(pac_cumulative, 0)} €HT")
                cgas2.metric(f"Coût cumulé référence gaz sur {economics.analysis_years} ans", f"{_number(gas_cumulative, 0)} €HT")
                st.caption("Contexte chaudière gaz à renouveler : les deux scénarios intègrent leur chaudière gaz. La comparaison porte donc sur le surinvestissement net et les coûts cumulés complets, sans attribuer artificiellement le coût de chaudière à un seul scénario.")
            else:
                r3.metric(
                    "Temps de retour brut",
                    f"{_number(economics.raw_payback_years, 1)} ans" if economics.raw_payback_years is not None else "Non atteint",
                )
            st.caption(
                "P4 reprend la convention simplifiée HelioEco : CAPEX net aidé / (MWh utiles annuels × durée d'analyse). "
                "Il ne s'agit pas encore d'un LCOH actualisé avec facteur de récupération du capital."
            )

            if profile_mode and pareto_options:
                st.markdown("#### Comparaison économique des solutions Pareto")
                comparison_rows = []
                for option in pareto_options:
                    option_surface = source_surface_m2(option.pac.installed_power_kw, source_type, source_ratio)
                    option_ref = load_pac_reference(getattr(option.pac, "xml_filename", "") or "")
                    option_aux_mwh = 0.0
                    if option_ref is not None:
                        option_aux_mwh = (
                            option_ref.aux_power_kw
                            * option.pac.unit_count
                            * option.simulation.equivalent_full_load_hours
                            / 1000.0
                        )
                    option_econ = compute_pac_heat_cost_model(
                        monthly_heat_mwh=monthly_heat_for_economics,
                        selected_pac_power_kw=option.pac.installed_power_kw,
                        source_surface_m2=option_surface,
                        monthly_cop=monthly_cop,
                        auxiliary_electricity_mwh=option_aux_mwh,
                        electricity_cost_eur_mwh=float(electricity_cost),
                        maintenance_annual_eur=float(maintenance_annual_eur),
                        analysis_years=int(analysis_years),
                        aid_eur_per_mwh_enr=float(aid_rate),
                        cost_uncertainty=float(uncertainty_pct) / 100.0,
                        reference_energy_cost_eur_mwh=float(reference_energy_cost),
                        reference_efficiency=float(reference_efficiency),
                        reference_inflation_rate=float(reference_inflation),
                        gas_reference_context=gas_reference_context,
                        reference_boiler_power_kw=float(reference_boiler_power_kw),
                        pac_scenario_boiler_power_kw=float(pac_scenario_boiler_power_kw),
                        reference_boiler_p2_eur_kw_year=float(reference_boiler_p2_eur_kw_year),
                        reference_boiler_capex_eur_kw=float(reference_boiler_capex_eur_kw),
                    )
                    comparison_rows.append(
                        {
                            "Solution": f"{option.pac.unit_count} × {option.pac.model} ({option.pac.brand})",
                            "P PAC (kW)": option.pac.installed_power_kw,
                            "Stockage (L)": option.tank.total_volume_l,
                            "Surface (m²)": option_surface,
                            "CAPEX REX (€ HT)": option_econ.capex_mid_eur,
                            "Aide indicative (€)": option_econ.estimated_aid_eur,
                            "Investissement net scénario (€ HT)": option_econ.pac_scenario_net_investment_eur,
                            "COP PAC saisonnier": option_econ.seasonal_cop_machine,
                            "Auxiliaires SoloPAC": "Oui" if option_ref is not None else "Non",
                            "COP système incl. aux": option_econ.system_cop_including_aux,
                            "P1 (€/MWh)": option_econ.p1_eur_mwh,
                            "P2 (€/MWh)": option_econ.p2_eur_mwh,
                            "P4 (€/MWh)": option_econ.p4_eur_mwh,
                            "Coût chaleur (€/MWh)": option_econ.heat_cost_eur_mwh,
                        }
                    )
                comparison_rows.sort(key=lambda row: row["Coût chaleur (€/MWh)"])
                st.dataframe(pd.DataFrame(comparison_rows), hide_index=True, width="stretch")
                best_heat_cost = comparison_rows[0]
                st.success(
                    "Selon le modèle P1/P2/P4 et la loi de coût REX actuelle, la solution au coût de chaleur indicatif le plus faible est : "
                    f"{best_heat_cost['Solution']} avec {best_heat_cost['Stockage (L)']:.0f} L de stockage "
                    f"({_number(best_heat_cost['Coût chaleur (€/MWh)'], 1)} €/MWh)."
                )
                st.caption(
                    "La régression REX actuelle valorise la puissance PAC et la surface de capteurs, mais pas séparément le volume de stockage. "
                    "Le classement reste donc un outil de note d'opportunité."
                )

            st.markdown("#### CAPEX PAC solaire issu des REX")
            cap1, cap2, cap3, cap4 = st.columns(4)
            cap1.metric("CAPEX PAC solaire central", f"{_number(economics.capex_mid_eur, 0)} € HT")
            cap2.metric("Fourchette basse", f"{_number(economics.capex_low_eur, 0)} € HT")
            cap3.metric("Fourchette haute", f"{_number(economics.capex_high_eur, 0)} € HT")
            cap4.metric("Aide indicative", f"{_number(economics.estimated_aid_eur, 0)} €")
            st.metric("Reste à charge PAC solaire après aide", f"{_number(economics.net_investment_eur, 0)} € HT")
            if includes_gas_boiler_fixed_costs(gas_reference_context):
                st.metric("Investissement net total scénario PAC solaire + gaz", f"{_number(economics.pac_scenario_net_investment_eur, 0)} € HT")
            st.metric(
                "Coût chaleur avec incertitude CAPEX",
                f"{_number(economics.heat_cost_low_eur_mwh, 1)} à {_number(economics.heat_cost_high_eur_mwh, 1)} €/MWh",
            )
            st.caption(
                "Tendance REX : CAPEX = 43 854 € + 2 362 €/kW PAC installé + 300 €/m² de source solaire. "
                "P2 est fixé à un forfait de maintenance de 2 000 € HT/an, indépendant de la taille de l’installation. "
                f"L'incertitude CAPEX ±{uncertainty_pct:.0f} % encadre uniquement le CAPEX PAC solaire issu des REX : elle ne modifie ni la chaudière gaz, ni P1, ni P2, ni l'aide. "
                "Elle se propage au P4 du scénario PAC solaire et à la fourchette de coût de chaleur affichée ; la valeur centrale et le classement des solutions restent calculés sur le CAPEX central."
            )

    with tab_solopac:
        st.subheader("Simulation SOLOPAC — import et analyse technique")
        st.caption(
            "Importez le classeur de résultats mensuels exporté par SOLOPAC. HelioCOP ne conserve que les flux utiles au bilan : "
            "besoin, chaleur PAC, EnR évaporateur, électricité, auxiliaires, appoint gaz et COP."
        )
        use_solopac_example = st.checkbox(
            "Utiliser l'exemple SOLOPAC Cholet2 intégré",
            value=False,
            key=f"{project_key}_use_solopac_example",
        )
        solopac_upload = st.file_uploader(
            "Importer les résultats SOLOPAC (.xlsx)",
            type=["xlsx"],
            key=f"{project_key}_solopac_results_upload",
            disabled=use_solopac_example,
        )
        solopac_source = None
        if use_solopac_example and SOLOPAC_RESULTS_EXAMPLE_FILE.exists():
            solopac_source = SOLOPAC_RESULTS_EXAMPLE_FILE
        elif solopac_upload is not None:
            solopac_source = solopac_upload.getvalue()

        if solopac_source is None:
            st.info("Importez un export SOLOPAC pour afficher l'analyse technique et actualiser l'économie dans l'onglet 9.")
        else:
            try:
                solopac_results = load_solopac_results(solopac_source)
            except Exception as exc:
                st.error(f"Lecture des résultats SOLOPAC impossible : {exc}")
                solopac_results = None

        if solopac_results is not None:
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Besoin utile", f"{_number(solopac_results.annual_useful_need_mwh, 1)} MWh/an")
            k2.metric("Chaleur PAC", f"{_number(solopac_results.annual_pac_condenser_mwh, 1)} MWh/an")
            k3.metric("Couverture PAC", _percent(solopac_results.annual_pac_coverage_rate, 1))
            k4.metric("COP système SOLOPAC", f"{solopac_results.annual_cop_system:.2f}")
            k5.metric("Appoint gaz", f"{_number(solopac_results.annual_gas_backup_heat_mwh, 1)} MWh/an")

            k6, k7, k8, k9 = st.columns(4)
            k6.metric("EnR captée", f"{_number(solopac_results.annual_renewable_evaporator_mwh, 1)} MWh/an")
            k7.metric("Taux EnR", _percent(solopac_results.annual_renewable_rate, 1))
            k8.metric("Électricité compresseur", f"{_number(solopac_results.annual_compressor_electricity_mwh, 1)} MWh/an")
            k9.metric("Auxiliaires électriques", f"{_number(solopac_results.annual_auxiliary_electricity_mwh, 1)} MWh/an")

            _render_solopac_monthly_energy_chart(solopac_results)
            _render_solopac_cop_chart(solopac_results)

            min_cop = min(solopac_results.monthly_rows, key=lambda r: r.cop_system)
            max_cop = max(solopac_results.monthly_rows, key=lambda r: r.cop_system)
            max_gas = max(solopac_results.monthly_rows, key=lambda r: r.gas_backup_heat_mwh)
            st.markdown("#### Lecture technique")
            st.write(
                f"• Le COP système annuel simulé est **{solopac_results.annual_cop_system:.2f}** ; "
                f"il varie de **{min_cop.cop_system:.2f} en {min_cop.month}** à **{max_cop.cop_system:.2f} en {max_cop.month}**."
            )
            st.write(
                f"• La PAC fournit **{_percent(solopac_results.annual_pac_coverage_rate, 1)}** de la production thermique PAC + appoint ; "
                f"l'appoint gaz représente **{_percent(solopac_results.annual_gas_share_rate, 1)}**."
            )
            st.write(
                f"• Le mois avec le plus d'appoint gaz est **{max_gas.month}** avec "
                f"**{_number(max_gas.gas_backup_heat_mwh, 2)} MWh**."
            )
            st.dataframe(_solopac_monthly_dataframe(solopac_results), hide_index=True, width="stretch")

    with tab_solopac_economics:
        st.subheader("Bilan économique actualisé par la simulation SOLOPAC")
        if solopac_results is None:
            st.info("Importez d'abord une simulation dans l'onglet 8.")
        elif selected_pac is None:
            st.warning("Sélectionnez une configuration PAC dans l'onglet 6 pour associer les résultats SOLOPAC au CAPEX REX.")
        else:
            solopac_economics = compute_pac_heat_cost_from_solopac(
                solopac=solopac_results,
                selected_pac_power_kw=selected_pac.installed_power_kw,
                source_surface_m2=required_surface,
                electricity_cost_eur_mwh=float(electricity_cost),
                maintenance_annual_eur=float(maintenance_annual_eur),
                analysis_years=int(analysis_years),
                aid_eur_per_mwh_enr=float(aid_rate),
                cost_uncertainty=float(uncertainty_pct) / 100.0,
                reference_energy_cost_eur_mwh=float(reference_energy_cost),
                reference_efficiency=float(reference_efficiency),
                reference_inflation_rate=float(reference_inflation),
                gas_reference_context=str(gas_reference_context),
                reference_boiler_power_kw=float(reference_boiler_power_kw),
                pac_scenario_boiler_power_kw=float(pac_scenario_boiler_power_kw),
                reference_boiler_p2_eur_kw_year=float(reference_boiler_p2_eur_kw_year),
                reference_boiler_capex_eur_kw=float(reference_boiler_capex_eur_kw),
            )

            st.success(
                "Le bilan ci-dessous remplace les COP mensuels théoriques de l'onglet 7 par les consommations réellement calculées par SOLOPAC. "
                "L'appoint gaz simulé est également intégré au P1."
            )
            e1, e2, e3, e4, e5 = st.columns(5)
            e1.metric("COP système simulé", f"{solopac_economics.system_cop_including_aux:.2f}")
            e2.metric("Électricité totale", f"{_number(solopac_economics.total_electricity_mwh, 1)} MWh/an")
            e3.metric("Appoint gaz utile", f"{_number(solopac_economics.gas_backup_heat_mwh, 1)} MWh/an")
            e4.metric("EnR SOLOPAC", f"{_number(solopac_economics.renewable_heat_mwh, 1)} MWh/an")
            e5.metric("Aide indicative", f"{_number(solopac_economics.estimated_aid_eur, 0)} €")

            st.markdown("#### P1 — coût des énergies réellement consommées")
            p11, p12, p13 = st.columns(3)
            p11.metric("Électricité PAC + auxiliaires", f"{_number(solopac_economics.p1_electricity_annual_eur, 0)} €HT/an")
            p12.metric("Gaz d'appoint", f"{_number(solopac_economics.p1_gas_annual_eur, 0)} €HT/an")
            p13.metric("P1 total", f"{_number(solopac_economics.p1_eur_mwh, 1)} €/MWh utile")
            st.caption(
                "P1 SOLOPAC = coût de l'électricité compresseur + auxiliaires + coût du gaz nécessaire à l'appoint simulé. "
                "Le gaz d'appoint est converti en énergie achetée avec le rendement chaudière saisi dans l'onglet 7."
            )

            h1, h2, h3, h4 = st.columns(4)
            h1.metric("P1", f"{_number(solopac_economics.p1_eur_mwh, 1)} €/MWh")
            h2.metric("P2", f"{_number(solopac_economics.p2_eur_mwh, 1)} €/MWh")
            h3.metric("P4", f"{_number(solopac_economics.p4_eur_mwh, 1)} €/MWh")
            h4.metric("Coût chaleur actualisé SOLOPAC", f"{_number(solopac_economics.heat_cost_eur_mwh, 1)} €/MWh")

            _render_heat_cost_bar(solopac_economics, gas_reference_context, key_prefix="solopac")
            _render_investment_scenarios(solopac_economics, gas_reference_context, key_prefix="solopac")

            st.dataframe(
                pd.DataFrame(
                    [
                        {"Poste": "Électricité PAC + auxiliaires", "Valeur": solopac_economics.total_electricity_mwh, "Unité": "MWhélec/an"},
                        {"Poste": "Gaz appoint acheté", "Valeur": solopac_economics.gas_backup_fuel_mwh, "Unité": "MWh gaz/an"},
                        {"Poste": "Énergie renouvelable", "Valeur": solopac_economics.renewable_heat_mwh, "Unité": "MWh EnR/an"},
                        {"Poste": "CAPEX PAC solaire central", "Valeur": solopac_economics.capex_mid_eur, "Unité": "€HT"},
                        {"Poste": "Investissement net scénario PAC + gaz", "Valeur": solopac_economics.pac_scenario_net_investment_eur, "Unité": "€HT"},
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

            if economics is not None:
                delta = solopac_economics.heat_cost_eur_mwh - economics.heat_cost_eur_mwh
                st.metric(
                    "Écart vs prédimensionnement onglet 7",
                    f"{delta:+.1f} €/MWh",
                    help="Positif : SOLOPAC conduit à un coût de chaleur supérieur au prédimensionnement ; négatif : inférieur.",
                )

    economics_for_summary = solopac_economics if solopac_economics is not None else economics

    with tab_summary:
        st.subheader("Synthèse HelioCOP")
        if profile_mode:
            if profile is None or selected_pac is None or selected_tank is None:
                st.warning("Chargez un profil et sélectionnez un couple PAC / stockage pour obtenir la synthèse.")
            else:
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Besoin process", f"{_number(profile.annual_energy_mwh, 1)} MWh/an")
                s2.metric("Pointe horaire", f"{_number(profile.peak_hourly_kw, 1)} kW")
                s3.metric("Stockage retenu", selected_tank.label)
                s4.metric("PAC installée", f"{selected_pac.installed_power_kw:.0f} kW")
                st.success(
                    f"PAC retenue : {selected_pac.unit_count} × {selected_pac.model} ({selected_pac.brand}) = "
                    f"{selected_pac.installed_power_kw:.1f} kW."
                )
                if selected_profile_simulation is not None:
                    st.write(f"**Couverture horaire simplifiée :** {_percent(selected_profile_simulation.coverage_fraction, 2)}")
                    st.write(f"**SOC minimal du stockage :** {_percent(selected_profile_simulation.min_soc_fraction, 1)}")
                    st.write(
                        f"**Équivalent pleine charge PAC :** {_number(selected_profile_simulation.equivalent_full_load_hours, 0)} h/an"
                    )
                st.write(f"**Source solaire :** {source_type} — {_number(required_surface, 1)} m²")
        else:
            if housing is not None and selected_tank is not None:
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Besoin ECS réf.", f"{_number(housing.daily_need_l_eq40, 0)} L.eq40°C/j")
                s2.metric("Stock cible eq.60°C", f"{_number(target_storage, 0)} L")
                s3.metric("Stockage retenu", f"{selected_tank.total_volume_l:,.0f} L".replace(",", " "))
                s4.metric("Pecs COSTIC", f"{_number(pecs_kw, 1)} kW")
                if selected_pac is not None:
                    st.success(
                        f"PAC retenue : {selected_pac.unit_count} × {selected_pac.model} ({selected_pac.brand}) = "
                        f"{selected_pac.installed_power_kw:.1f} kW pour un minimum calculé de {pac_min_kw:.1f} kW."
                    )
                st.write(f"**Source solaire :** {source_type} — {_number(required_surface, 1)} m²")
                st.write(f"**Bouclage sanitaire estimé :** {_number(annual_loop_mwh, 1)} MWh/an, intégré au service thermique ECS2.")

        if economics_for_summary is not None:
            st.write(f"**Besoin annuel couvert :** {_number(economics_for_summary.annual_ecs_need_mwh, 1)} MWh/an")
            if solopac_economics is not None:
                st.write(
                    f"**Électricité PAC + auxiliaires :** {_number(economics_for_summary.pac_electricity_mwh, 1)} MWh/an "
                    f"(COP système SOLOPAC {economics_for_summary.system_cop_including_aux:.2f})"
                )
                st.write(f"**Appoint gaz simulé :** {_number(economics_for_summary.gas_backup_heat_mwh, 1)} MWh utiles/an")
            else:
                st.write(
                    f"**Électricité PAC + auxiliaires :** {_number(economics_for_summary.pac_electricity_mwh, 1)} MWh/an "
                    f"(COP machine {economics_for_summary.cop:.1f}, COP système {economics_for_summary.system_cop_including_aux:.2f})"
                )
            st.write(f"**Énergie renouvelable hors électricité :** {_number(economics_for_summary.renewable_heat_mwh, 1)} MWh/an")
            st.write(f"**Aide indicative :** {_number(economics_for_summary.estimated_aid_eur, 0)} €")
            st.write(f"**CAPEX central :** {_number(economics_for_summary.capex_mid_eur, 0)} € HT")

        summary_payload = {
            "app": APP_LABEL,
            "mode": "profil_horaire" if profile_mode else "logement_collectif",
            "project": {
                "name": identity.project_name,
                "client": identity.client_name,
                "city": identity.city,
                "typology": identity.typology,
                "park_type": park_type,
                "building_state": building_state,
            },
            "cold_water_mode": cold_mode,
            "cold_water_temperatures_c": cold_water,
            "housing": asdict(housing) if housing is not None else None,
            "profile": (
                {
                    "source_name": profile.source_name,
                    "source_sheet": profile.source_sheet,
                    "energy_columns": profile.energy_columns,
                    "hours": profile.hour_count,
                    "annual_energy_mwh": profile.annual_energy_mwh,
                    "peak_hourly_kw": profile.peak_hourly_kw,
                }
                if profile is not None
                else None
            ),
            "target_storage_l_eq60": target_storage,
            "selected_tank": asdict(selected_tank) if selected_tank is not None else None,
            "pecs_kw": pecs_kw,
            "pac_min_kw": pac_min_kw,
            "loop_design_power_kw": loop_design_power_kw,
            "selected_pac": asdict(selected_pac) if selected_pac is not None else None,
            "profile_simulation": asdict(selected_profile_simulation) if selected_profile_simulation is not None else None,
            "source_type": source_type,
            "source_ratio_m2_per_kw": source_ratio,
            "source_surface_m2": required_surface,
            "annual_loop_mwh": annual_loop_mwh,
            "solopac_results": asdict(solopac_results) if solopac_results is not None else None,
            "economics": asdict(economics_for_summary) if economics_for_summary is not None else None,
        }
        st.session_state["heliocop_last_summary_payload"] = summary_payload
        st.download_button(
            "Télécharger la synthèse JSON",
            data=json.dumps(summary_payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="heliocop_synthese.json",
            mime="application/json",
            width="stretch",
        )
        st.caption(
            "Prédimensionnement de note d'opportunité — règles ECS2 SOCOL / COSTIC et références SoloPAC 1.1. "
            "À affiner avec le futur moteur dynamique HelioCOP."
        )
