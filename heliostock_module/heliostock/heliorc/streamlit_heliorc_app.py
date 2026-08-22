from __future__ import annotations

import inspect
import json
import uuid
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data import load_locations
from .engine import (
    ADEME_REFERENCE_URL,
    ADEME_REFERENCE_VIGILANCES,
    AID_FORFAITS,
    DEFAULT_MONTHLY_NEEDS_MWH,
    MONTHS_FR,
    REGIMES,
    CalculationInputs,
    CalculationResults,
    calculate_opportunity,
    decentralized_branch_guard,
    estimate_monthly_needs,
)
from .report import build_opportunity_note
from ..common.project_identity import (
    DEFAULT_PROJECT_LATITUDE,
    DEFAULT_PROJECT_LONGITUDE,
    ProjectIdentity,
    ProjectIdentityOptions,
    project_context_to_payload,
    render_project_identity_form,
)
from ..common.project_store import (
    JsonProjectStore,
    normalize_email,
    now_iso,
    project_library_metadata,
    safe_slug,
)
from ..ui_surface_orientation import (
    current_surface_orientation_payload,
    render_surface_orientation_measurement,
    restore_surface_orientation_state,
)
from ..ui_architectural_constraints import PROJECT_TYPES, render_architectural_constraints_test
from .. import ui_portal

APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR.parents[1] / "assets"
ADEME_LOGO = ASSETS_DIR / "Logo_ADEME.png"
TOTAL_NEEDS_COL = "Besoins RCU (MWh)"
BRANCH_NEEDS_COL = "Besoins branche sélectionnée (MWh)"
PROJECT_STORE = JsonProjectStore("heliorc", app_label="HelioRC")
PROJECTS_SESSION_CACHE_KEY = "heliorc_projects_cache"
HELIORC_PROJECT_REGIONS = ("France métropolitaine",)
HELIORC_GROUND_AREA_M2_PER_COLLECTOR_M2 = 2.5
SIZING_STRATEGIES = (
    "Talon de dimensionnement réglable",
    "Dimensionnement max conditionné par la surface du terrain disponible",
)


def _render_styles() -> None:
    st.markdown(
        """
        <style>
          .block-container {padding-top: 1.35rem; padding-bottom: 3rem;}
          [data-testid="stMetric"] {
            background: #f7faf9;
            border: 1px solid #dce8e6;
            border-radius: 0.65rem;
            padding: 0.8rem 0.9rem;
          }
          [data-testid="stMetricValue"] {
            font-size: clamp(1.55rem, 2.3vw, 2.2rem);
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.15;
          }
          [data-testid="stMetricLabel"] {
            min-height: 2.2rem;
          }
          .small-muted {color: #667085; font-size: 0.88rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _initial_monthly_dataframe(values: list[float] | None = None) -> pd.DataFrame:
    data = values if values is not None else DEFAULT_MONTHLY_NEEDS_MWH
    return pd.DataFrame({"Mois": MONTHS_FR, TOTAL_NEEDS_COL: data})


def _initial_branch_monthly_dataframe(values: list[float] | None = None) -> pd.DataFrame:
    data = values if values is not None else [0.0] * 12
    return pd.DataFrame({"Mois": MONTHS_FR, BRANCH_NEEDS_COL: data})


def _coerce_monthly_values(source: object) -> list[float]:
    series = pd.Series(source)
    cleaned = (
        series.astype(str)
        .str.replace("\u202f", "", regex=False)
        .str.replace("\xa0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.strip()
    )
    values = pd.to_numeric(cleaned, errors="coerce").fillna(0.0).astype(float).tolist()
    return (values + [0.0] * 12)[:12]


def _format_monthly_value_for_editor(value: object) -> str:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(numeric_value - round(numeric_value)) < 1e-9:
        return f"{numeric_value:.0f}"
    return f"{numeric_value:.1f}".replace(".", ",")


def _editor_monthly_dataframe(frame: pd.DataFrame, value_col: str) -> pd.DataFrame:
    display = frame.copy()
    if value_col in display.columns:
        display[value_col] = display[value_col].map(_format_monthly_value_for_editor)
    return display


def _apply_monthly_editor_changes(
    *,
    editor_key: str,
    target_state_key: str,
    value_col: str,
    normalise: Callable[[object, pd.DataFrame | None], pd.DataFrame],
) -> None:
    editor_state = st.session_state.get(editor_key)
    if not isinstance(editor_state, dict):
        return
    edited_rows = editor_state.get("edited_rows")
    if not isinstance(edited_rows, dict) or not edited_rows:
        return

    base = normalise(st.session_state.get(target_state_key), None)
    display = _editor_monthly_dataframe(base, value_col)
    for row_index, changes in edited_rows.items():
        if not isinstance(changes, dict) or value_col not in changes:
            continue
        try:
            index = int(row_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(display):
            display.at[index, value_col] = changes[value_col]
    st.session_state[target_state_key] = normalise(display, base)


def _normalise_manual_needs_dataframe(value: object, fallback: pd.DataFrame | None = None) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
    else:
        frame = fallback.copy() if isinstance(fallback, pd.DataFrame) else _initial_monthly_dataframe()

    if TOTAL_NEEDS_COL not in frame.columns:
        values = [0.0] * 12
    else:
        values = _coerce_monthly_values(frame[TOTAL_NEEDS_COL])
    return _initial_monthly_dataframe(values)


def _normalise_branch_needs_dataframe(value: object, fallback: pd.DataFrame | None = None) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
    else:
        frame = fallback.copy() if isinstance(fallback, pd.DataFrame) else _initial_branch_monthly_dataframe()

    if BRANCH_NEEDS_COL in frame.columns:
        source = frame[BRANCH_NEEDS_COL]
    elif TOTAL_NEEDS_COL in frame.columns:
        # Anciennes sessions/projets : une colonne "Besoins RCU" ne doit pas
        # être interprétée comme besoin de branche, sinon la branche reprend
        # silencieusement le réseau complet.
        source = pd.Series([0.0] * 12)
    else:
        source = pd.Series([0.0] * 12)
    values = _coerce_monthly_values(source)
    return _initial_branch_monthly_dataframe(values)


def _monthly_values_from_frame(frame: object) -> list[float]:
    normalised = _normalise_manual_needs_dataframe(frame)
    return normalised[TOTAL_NEEDS_COL].astype(float).tolist()


def _branch_monthly_values_from_frame(frame: object) -> list[float]:
    normalised = _normalise_branch_needs_dataframe(frame)
    return normalised[BRANCH_NEEDS_COL].astype(float).tolist()


def _sync_branch_defaults_from_total_if_needed() -> None:
    branch_df = st.session_state.get("branch_needs_df")
    if isinstance(branch_df, pd.DataFrame) and BRANCH_NEEDS_COL in branch_df.columns:
        manual_values = _monthly_values_from_frame(st.session_state.get("manual_needs_df"))
        branch_values = _branch_monthly_values_from_frame(branch_df)
        if branch_values != manual_values:
            return
        # En décentralisé, la branche doit être strictement inférieure au RCU.
        # Si l'ancien état a recopié le réseau complet, on évite de conserver
        # cette valeur trompeuse dans le tableau de saisie.
        st.session_state["branch_needs_df"] = _initial_branch_monthly_dataframe()
        st.session_state.pop("branch_needs_editor_form_v3", None)
        st.session_state.pop("branch_needs_editor_v4", None)
        return
    # Migration douce des anciens projets : si l'ancien champ branche était vide ou absent,
    # on démarre sur zéro pour éviter de reprendre silencieusement le besoin du RCU complet.
    st.session_state["branch_needs_df"] = _initial_branch_monthly_dataframe()
    st.session_state.pop("branch_needs_editor", None)
    st.session_state.pop("branch_needs_editor_form", None)


def _ensure_branch_editor_schema() -> None:
    if st.session_state.get("_heliorc_branch_editor_schema") == 4:
        return
    branch_df = st.session_state.get("branch_needs_df")
    manual_values = _monthly_values_from_frame(st.session_state.get("manual_needs_df"))
    branch_values = _branch_monthly_values_from_frame(branch_df)
    if branch_values == manual_values:
        st.session_state["branch_needs_df"] = _initial_branch_monthly_dataframe()
    elif not (isinstance(branch_df, pd.DataFrame) and BRANCH_NEEDS_COL in branch_df.columns):
        st.session_state["branch_needs_df"] = _initial_branch_monthly_dataframe()
    st.session_state.pop("branch_needs_editor", None)
    st.session_state.pop("branch_needs_editor_form", None)
    st.session_state.pop("manual_needs_editor_form", None)
    st.session_state.pop("manual_needs_editor_form_v3", None)
    st.session_state.pop("branch_needs_editor_form_v3", None)
    st.session_state.pop("manual_needs_editor_v4", None)
    st.session_state.pop("branch_needs_editor_v4", None)
    st.session_state["_heliorc_branch_editor_schema"] = 4



def _current_connection_mode() -> str:
    return str(st.session_state.get("solar_connection_mode") or "Installation centralisée")


def _is_decentralized_connection() -> bool:
    return _current_connection_mode().startswith("Installation décentralisée")


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "project_name": "Étude d'opportunité solaire thermique",
        "client": "",
        "airtable_id": "",
        "analyst": "",
        "project_date": date.today(),
        "project_city": "",
        "project_address_label": "",
        "project_latitude": DEFAULT_PROJECT_LATITUDE,
        "project_longitude": DEFAULT_PROJECT_LONGITUDE,
        "project_typology": "Réseau de chaleur",
        "project_region": "France métropolitaine",
        "project_department": "01 - Bourg-en-Bresse",
        "weather_region": "Bretagne",
        "weather_station": "Rennes",
        "location_label": "1 - Bourg-en-Bresse",
        "zone": "Nord",
        "regime_label": "Moyen (75°C/55°C)",
        "mean_temp": 65.0,
        "calculation_mode": "excel_v5_3",
        "base_load_percent": 90,
        "sizing_strategy": SIZING_STRATEGIES[0],
        "needs_mode": "Besoins mensuels connus",
        "annual_heating": 10000.0,
        "annual_ecs": 2000.0,
        "network_efficiency_percent": 85,
        "manual_needs_df": _initial_monthly_dataframe(),
        "branch_needs_df": _initial_branch_monthly_dataframe(),
        "solar_connection_mode": "Installation centralisée",
        "network_operates_summer": True,
        "summer_excess_enr": False,
        "land_identified": True,
        "other_aid": 0.0,
        "electricity_price": 245.1,
        "project_lifetime": 30,
        "override_discount_rate": False,
        "discount_rate_percent": 6.0,
        "last_results": None,
        "last_monthly": None,
        "last_inputs": None,
        "last_project": None,
        "last_sizing_context": None,
        "heliorc_current_project_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _current_owner_email() -> str:
    user = st.session_state.get("user")
    if isinstance(user, dict):
        return normalize_email(str(user.get("email", "")))
    return ""


def _project_identity_from_state() -> ProjectIdentity:
    return ProjectIdentity(
        project_name=str(st.session_state.get("heliorc_project_name") or st.session_state.get("project_name") or ""),
        client_name=str(st.session_state.get("heliorc_client_name") or st.session_state.get("client") or ""),
        airtable_id=str(st.session_state.get("heliorc_airtable_id") or st.session_state.get("airtable_id") or ""),
        analyst=str(st.session_state.get("heliorc_analyst") or st.session_state.get("analyst") or ""),
        project_date=st.session_state.get("heliorc_project_date") or st.session_state.get("project_date"),
        typology="Réseau de chaleur",
        region=str(st.session_state.get("heliorc_region") or st.session_state.get("project_region") or ""),
        department=str(st.session_state.get("heliorc_department") or st.session_state.get("project_department") or ""),
        city=str(st.session_state.get("heliorc_city") or st.session_state.get("project_city") or ""),
        address=str(st.session_state.get("heliorc_project_address_label") or st.session_state.get("project_address_label") or ""),
        latitude=float(
            st.session_state.get("heliorc_project_latitude", st.session_state.get("project_latitude", DEFAULT_PROJECT_LATITUDE))
        ),
        longitude=float(
            st.session_state.get(
                "heliorc_project_longitude", st.session_state.get("project_longitude", DEFAULT_PROJECT_LONGITUDE)
            )
        ),
        weather_region=str(st.session_state.get("heliorc_weather_region") or st.session_state.get("weather_region") or "Bretagne"),
        weather_station=str(st.session_state.get("heliorc_weather_station") or st.session_state.get("weather_station") or "Rennes"),
    )


def _sync_project_identity_to_legacy_state(identity: ProjectIdentity) -> None:
    st.session_state["project_name"] = identity.project_name
    st.session_state["client"] = identity.client_name
    st.session_state["airtable_id"] = identity.airtable_id
    st.session_state["analyst"] = identity.analyst
    st.session_state["project_date"] = identity.project_date or date.today()
    st.session_state["project_city"] = identity.city
    st.session_state["project_address_label"] = identity.address
    st.session_state["project_latitude"] = identity.latitude
    st.session_state["project_longitude"] = identity.longitude
    st.session_state["project_typology"] = "Réseau de chaleur"
    st.session_state["project_region"] = identity.region
    st.session_state["project_department"] = identity.department
    st.session_state["weather_region"] = identity.weather_region
    st.session_state["weather_station"] = identity.weather_station


def _propagate_heliorc_project_location() -> None:
    identity = _project_identity_from_state()
    st.session_state["heliorc_architectural_selected_address"] = identity.address
    st.session_state["heliorc_architectural_latitude"] = float(identity.latitude)
    st.session_state["heliorc_architectural_longitude"] = float(identity.longitude)


def _on_heliorc_location_change(identity: ProjectIdentity) -> None:
    _sync_project_identity_to_legacy_state(identity)
    _propagate_heliorc_project_location()
    st.session_state.pop("heliorc_architectural_result", None)


def _current_heliorc_architectural_payload() -> dict[str, Any]:
    return {
        "selected_address": str(st.session_state.get("heliorc_architectural_selected_address") or ""),
        "latitude": float(st.session_state.get("heliorc_architectural_latitude", DEFAULT_PROJECT_LATITUDE)),
        "longitude": float(st.session_state.get("heliorc_architectural_longitude", DEFAULT_PROJECT_LONGITUDE)),
        "project_type": str(st.session_state.get("heliorc_architectural_project_type") or PROJECT_TYPES[0]),
        "result": st.session_state.get("heliorc_architectural_result"),
    }


def _restore_heliorc_architectural_state(payload: dict[str, Any], project_id: str) -> None:
    if st.session_state.get("heliorc_architectural_payload_project_id") == project_id:
        return
    st.session_state["heliorc_architectural_payload_project_id"] = project_id
    saved = payload.get("architectural_constraints") if isinstance(payload, dict) else None
    if not isinstance(saved, dict):
        _propagate_heliorc_project_location()
        st.session_state["heliorc_architectural_result"] = None
        return
    if saved.get("selected_address") is not None:
        st.session_state["heliorc_architectural_selected_address"] = str(saved.get("selected_address") or "")
    if saved.get("latitude") is not None:
        st.session_state["heliorc_architectural_latitude"] = float(saved.get("latitude") or DEFAULT_PROJECT_LATITUDE)
    if saved.get("longitude") is not None:
        st.session_state["heliorc_architectural_longitude"] = float(saved.get("longitude") or DEFAULT_PROJECT_LONGITUDE)
    if saved.get("project_type") in PROJECT_TYPES:
        st.session_state["heliorc_architectural_project_type"] = str(saved.get("project_type"))
    result = saved.get("result")
    st.session_state["heliorc_architectural_result"] = result if isinstance(result, dict) else None


def _current_project_data() -> dict[str, Any]:
    identity = _project_identity_from_state()
    project_date = identity.project_date or date.today()
    if isinstance(project_date, date):
        project_date_value = project_date.isoformat()
    else:
        project_date_value = str(project_date)
    return {
        "project_name": identity.project_name or "Nouveau projet HelioRC",
        "client": identity.client_name,
        "airtable_id": identity.airtable_id,
        "analyst": identity.analyst,
        "date": project_date_value,
        "typology": "Réseau de chaleur",
        "region": identity.region,
        "department": identity.department,
        "city": identity.city,
        "address": identity.address,
        "latitude": identity.latitude,
        "longitude": identity.longitude,
        "weather_region": identity.weather_region,
        "weather_station": identity.weather_station,
        "needs_mode": str(st.session_state.get("needs_mode") or ""),
    }


def _current_inputs_data() -> dict[str, Any]:
    manual_df = st.session_state.get("manual_needs_df")
    monthly_needs = DEFAULT_MONTHLY_NEEDS_MWH
    if isinstance(manual_df, pd.DataFrame) and TOTAL_NEEDS_COL in manual_df:
        monthly_needs = manual_df[TOTAL_NEEDS_COL].astype(float).tolist()
    branch_df = st.session_state.get("branch_needs_df")
    branch_monthly_needs = _branch_monthly_values_from_frame(branch_df)
    return {
        "location_label": st.session_state.get("location_label"),
        "zone": st.session_state.get("zone"),
        "regime_label": st.session_state.get("regime_label"),
        "mean_network_temperature_c": float(st.session_state.get("mean_temp", 65.0)),
        "base_load_fraction": float(st.session_state.get("base_load_percent", 90)) / 100,
        "sizing_strategy": st.session_state.get("sizing_strategy", SIZING_STRATEGIES[0]),
        "monthly_needs_mwh": monthly_needs,
        "branch_monthly_needs_mwh": branch_monthly_needs,
        "solar_connection_mode": _current_connection_mode(),
        "needs_mode": st.session_state.get("needs_mode"),
        "annual_heating_mwh": float(st.session_state.get("annual_heating", 0.0)),
        "annual_ecs_mwh": float(st.session_state.get("annual_ecs", 0.0)),
        "network_efficiency": float(st.session_state.get("network_efficiency_percent", 85)) / 100,
        "calculation_mode": "excel_v5_3",
        "other_aid_eur": float(st.session_state.get("other_aid", 0.0)),
        "electricity_price_eur_mwh": float(st.session_state.get("electricity_price", 0.0)),
        "project_lifetime_years": int(st.session_state.get("project_lifetime", 30)),
        "discount_rate_override": (
            float(st.session_state.get("discount_rate_percent", 0.0)) / 100
            if st.session_state.get("override_discount_rate")
            else None
        ),
        "network_operates_summer": bool(st.session_state.get("network_operates_summer", True)),
        "summer_excess_enr": bool(st.session_state.get("summer_excess_enr", False)),
        "land_identified": bool(st.session_state.get("land_identified", True)),
    }


def _available_ground_area_m2_from_orientation() -> float | None:
    payload = current_surface_orientation_payload("heliorc")
    metrics = payload.get("metrics") if isinstance(payload, dict) else {}
    if not isinstance(metrics, dict):
        return None
    surface_m2 = metrics.get("surface_m2")
    if isinstance(surface_m2, (int, float)) and float(surface_m2) > 0:
        return float(surface_m2)
    return None


def _heliorc_max_collector_area_from_ground(available_ground_m2: float | None) -> float | None:
    if available_ground_m2 is None or available_ground_m2 <= 0:
        return None
    return available_ground_m2 / HELIORC_GROUND_AREA_M2_PER_COLLECTOR_M2


def _render_heliorc_surface_orientation_measurement() -> dict[str, Any]:
    signature = inspect.signature(render_surface_orientation_measurement)
    if "ground_area_m2_per_collector_m2" in signature.parameters:
        return render_surface_orientation_measurement(
            state_prefix="heliorc",
            ground_area_m2_per_collector_m2=HELIORC_GROUND_AREA_M2_PER_COLLECTOR_M2,
        )
    return render_surface_orientation_measurement(state_prefix="heliorc")


def _build_calculation_inputs(monthly_needs: list[float], *, base_load_fraction: float) -> CalculationInputs:
    return CalculationInputs(
        location_label=st.session_state.location_label,
        zone=st.session_state.zone,
        regime_label=st.session_state.regime_label,
        mean_network_temperature_c=float(st.session_state.mean_temp),
        base_load_fraction=base_load_fraction,
        monthly_needs_mwh=monthly_needs,
        other_aid_eur=float(st.session_state.other_aid),
        electricity_price_eur_mwh=float(st.session_state.electricity_price),
        project_lifetime_years=int(st.session_state.project_lifetime),
        discount_rate_override=(
            float(st.session_state.discount_rate_percent) / 100
            if st.session_state.override_discount_rate
            else None
        ),
        calculation_mode="excel_v5_3",
        network_operates_summer=bool(st.session_state.network_operates_summer),
        summer_excess_enr=bool(st.session_state.summer_excess_enr),
        land_identified=bool(st.session_state.land_identified),
    )


def _calculate_with_sizing_strategy(monthly_needs: list[float]) -> tuple[CalculationInputs, CalculationResults, pd.DataFrame, dict[str, Any]]:
    strategy = str(st.session_state.get("sizing_strategy") or SIZING_STRATEGIES[0])
    requested_fraction = float(st.session_state.base_load_percent) / 100
    if strategy == SIZING_STRATEGIES[0]:
        inputs = _build_calculation_inputs(monthly_needs, base_load_fraction=requested_fraction)
        results, monthly = calculate_opportunity(inputs)
        return inputs, results, monthly, {
            "strategy": strategy,
            "requested_base_load_fraction": requested_fraction,
            "effective_base_load_fraction": requested_fraction,
            "available_ground_area_m2": None,
            "max_collector_area_m2": None,
            "constrained_by_ground": False,
        }

    available_ground_m2 = _available_ground_area_m2_from_orientation()
    max_collector_area_m2 = _heliorc_max_collector_area_from_ground(available_ground_m2)
    if available_ground_m2 is None or max_collector_area_m2 is None:
        raise ValueError(
            "Le dimensionnement conditionné par la surface disponible nécessite de dessiner une emprise dans l'onglet Orientation / surface."
        )

    target_fraction = 0.95
    target_inputs = _build_calculation_inputs(monthly_needs, base_load_fraction=target_fraction)
    target_results, target_monthly = calculate_opportunity(target_inputs)
    target_ground_m2 = target_results.land_area_ha * 10000.0
    if available_ground_m2 >= target_ground_m2:
        return target_inputs, target_results, target_monthly, {
            "strategy": strategy,
            "requested_base_load_fraction": target_fraction,
            "effective_base_load_fraction": target_fraction,
            "available_ground_area_m2": available_ground_m2,
            "max_collector_area_m2": max_collector_area_m2,
            "constrained_by_ground": False,
            "target_ground_area_m2": target_ground_m2,
        }

    low = 0.01
    high = target_fraction
    best_inputs: CalculationInputs | None = None
    best_results: CalculationResults | None = None
    best_monthly: pd.DataFrame | None = None
    for _ in range(28):
        mid = (low + high) / 2.0
        trial_inputs = _build_calculation_inputs(monthly_needs, base_load_fraction=mid)
        trial_results, trial_monthly = calculate_opportunity(trial_inputs)
        trial_ground_m2 = trial_results.land_area_ha * 10000.0
        if trial_ground_m2 <= available_ground_m2:
            low = mid
            best_inputs = trial_inputs
            best_results = trial_results
            best_monthly = trial_monthly
        else:
            high = mid
        if abs(trial_ground_m2 - available_ground_m2) <= 2.0:
            break

    if best_inputs is None or best_results is None or best_monthly is None:
        best_inputs = _build_calculation_inputs(monthly_needs, base_load_fraction=low)
        best_results, best_monthly = calculate_opportunity(best_inputs)

    best_results.warnings.append(
        "Surface de capteurs limitée par l'emprise disponible mesurée : le talon de dimensionnement a été réduit automatiquement."
    )
    return best_inputs, best_results, best_monthly, {
        "strategy": strategy,
        "requested_base_load_fraction": target_fraction,
        "effective_base_load_fraction": best_inputs.base_load_fraction,
        "available_ground_area_m2": available_ground_m2,
        "max_collector_area_m2": max_collector_area_m2,
        "constrained_by_ground": True,
        "target_ground_area_m2": target_ground_m2,
    }


def _normalise_department_code(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    code = text.split("-", 1)[0].strip().split(" ", 1)[0].strip().upper()
    return code.lstrip("0") if code.isdigit() else code


def _heliorc_department_options(locations: pd.DataFrame) -> tuple[str, ...]:
    rows = locations[["department", "city"]].drop_duplicates("department", keep="first").copy()
    rows["_sort"] = rows["department"].astype(str).map(lambda value: int(value) if str(value).isdigit() else 999)
    rows = rows.sort_values(["_sort", "city"], kind="stable")
    labels: list[str] = []
    for _, row in rows.iterrows():
        code = str(row["department"])
        display_code = code.zfill(2) if code.isdigit() and len(code) < 2 else code
        labels.append(f"{display_code} - {row['city']}")
    return tuple(labels)


def _department_option_from_code(options: tuple[str, ...], department: object) -> str | None:
    code = _normalise_department_code(department)
    if not code:
        return None
    for option in options:
        if _normalise_department_code(option) == code:
            return option
    return None


def _location_label_from_department(locations: pd.DataFrame, department: object) -> str | None:
    code = _normalise_department_code(department)
    if not code:
        return None
    normalised = locations["department"].map(_normalise_department_code)
    selected = locations.loc[normalised == code]
    if selected.empty:
        return None
    return str(selected.iloc[0]["label"])


def _sync_location_from_project_department(locations: pd.DataFrame) -> dict[str, object] | None:
    department = st.session_state.get("heliorc_department") or st.session_state.get("project_department")
    label = _location_label_from_department(locations, department)
    if label:
        st.session_state["location_label"] = label
    selected = locations.loc[locations["label"] == st.session_state.get("location_label")]
    if selected.empty:
        return None
    return selected.iloc[0].to_dict()


def _current_project_payload() -> dict[str, Any]:
    project = _current_project_data()
    saved_at = now_iso()
    previous_project_id = str(st.session_state.get("heliorc_current_project_id") or "")
    library_id = str(st.session_state.get("heliorc_project_library_id") or previous_project_id or uuid.uuid4())
    metadata = project_library_metadata(
        project_name=project["project_name"],
        project_reference=project.get("airtable_id"),
        saved_at=saved_at,
        library_id=library_id,
    )
    versioned_project_id = f"{metadata['version_id']}-{safe_slug(metadata['library_id'], fallback='heliorc')}"
    return {
        "schema_version": 1,
        "app_key": PROJECT_STORE.app_key,
        "app_label": PROJECT_STORE.app_label,
        "project_id": versioned_project_id,
        "name": project["project_name"],
        "owner_email": _current_owner_email(),
        "created_at": str(st.session_state.get("heliorc_project_created_at") or saved_at),
        "updated_at": saved_at,
        **metadata,
        "project_context": project_context_to_payload(
            _project_identity_from_state(),
            app_key=PROJECT_STORE.app_key,
            app_label=PROJECT_STORE.app_label,
            geographic_scope="France",
            weather_source="PVGIS",
            extra={"needs_mode": project.get("needs_mode", "")},
        ),
        "surface_orientation": current_surface_orientation_payload("heliorc"),
        "architectural_constraints": _current_heliorc_architectural_payload(),
        "project": project,
        "inputs": _current_inputs_data(),
    }


def _project_file_label(project_file) -> str:
    payload = project_file.payload
    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    name = str(payload.get("library_name") or project.get("project_name") or payload.get("name") or project_file.name)
    library_ref = str(payload.get("library_reference") or project.get("airtable_id") or "").strip()
    library_id = str(payload.get("library_id") or payload.get("project_id") or "").strip()
    version = str(payload.get("version_label") or payload.get("updated_at") or project_file.updated_at or "").strip()
    parts = [name]
    if library_ref:
        parts.append(f"ID {library_ref}")
    elif library_id:
        parts.append(f"ID {library_id[:8]}")
    if version:
        parts.append(f"v{version}")
    return " | ".join(parts)



def _project_backup_slug(project: dict[str, Any]) -> str:
    slug = str(project.get("slug", "") or "").strip()
    if slug:
        return safe_slug(slug, fallback="projet_heliorc")
    owner = safe_slug(str(project.get("owner_email", "") or "anonymous"), fallback="anonymous")
    project_id = str(project.get("project_id", "") or "")[:8]
    name = safe_slug(str(project.get("name", "") or "Projet HelioRC"), fallback="projet_heliorc")
    suffix = f"_{project_id}" if project_id else ""
    return f"{owner}_{name}{suffix}"[:120]


def _load_project_backups() -> list[dict[str, Any]]:
    cached = st.session_state.get(PROJECTS_SESSION_CACHE_KEY)
    if isinstance(cached, list):
        return [dict(project) for project in cached if isinstance(project, dict)]

    projects = []
    for project in ui_portal._load_project_backups():
        payload = project.get("payload", project) if isinstance(project, dict) else {}
        if not isinstance(payload, dict):
            continue
        app_key = ui_portal._normalise_project_app_key(
            str(project.get("app_key") or payload.get("app_key") or ""),
            str(project.get("app_label") or payload.get("app_label") or payload.get("app") or ""),
        )
        if app_key == PROJECT_STORE.app_key:
            projects.append(dict(project))
    st.session_state[PROJECTS_SESSION_CACHE_KEY] = projects
    return projects


def _save_project_backups(projects: list[dict[str, Any]]) -> None:
    clean_projects = [dict(project) for project in projects if isinstance(project, dict)]
    st.session_state[PROJECTS_SESSION_CACHE_KEY] = clean_projects
    others = []
    for project in ui_portal._load_project_backups():
        payload = project.get("payload", project) if isinstance(project, dict) else {}
        if not isinstance(project, dict) or not isinstance(payload, dict):
            continue
        app_key = ui_portal._normalise_project_app_key(
            str(project.get("app_key") or payload.get("app_key") or ""),
            str(project.get("app_label") or payload.get("app_label") or payload.get("app") or ""),
        )
        if app_key != PROJECT_STORE.app_key:
            others.append(dict(project))
    ui_portal._save_project_backups(others + clean_projects)


def _restore_projects_from_backup() -> None:
    for project in _load_project_backups():
        payload = dict(project.get("payload", project)) if isinstance(project, dict) else {}
        app_key = ui_portal._normalise_project_app_key(
            str(project.get("app_key") or payload.get("app_key") or ""),
            str(project.get("app_label") or payload.get("app_label") or payload.get("app") or ""),
        )
        if not payload or app_key != PROJECT_STORE.app_key:
            continue
        owner_email = normalize_email(str(payload.get("owner_email", "")))
        if not owner_email:
            continue
        project_id = str(payload.get("project_id", "") or uuid.uuid4())
        project_data = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
        name = str(payload.get("name") or project_data.get("project_name") or "Projet HelioRC")
        PROJECT_STORE.ensure_owner_dir(owner_email)
        path = PROJECT_STORE.project_path(owner_email=owner_email, project_id=project_id, project_name=name)
        if not path.exists():
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _upsert_project_backup(*, path: Path, payload: dict[str, Any]) -> None:
    backup_item = {
        "slug": path.with_suffix("").name,
        "saved_at": now_iso(),
        "app_key": PROJECT_STORE.app_key,
        "app_label": PROJECT_STORE.app_label,
        "owner_email": payload.get("owner_email", ""),
        "project_id": payload.get("project_id", ""),
        "name": payload.get("name", path.stem),
        "payload": payload,
    }
    slug = _project_backup_slug(backup_item)
    projects = [project for project in _load_project_backups() if _project_backup_slug(project) != slug]
    projects.append(backup_item)
    _save_project_backups(projects)


def _project_backup_matches_path(
    project: dict[str, Any],
    *,
    path: Path,
    payload: dict[str, Any] | None,
) -> bool:
    payload = payload or {}
    slug = path.with_suffix("").name
    if _project_backup_slug(project) == slug:
        return True
    target_project_id = str(payload.get("project_id") or "").strip()
    if not target_project_id:
        return False
    target_owner = normalize_email(str(payload.get("owner_email") or ""))
    backup_payload = project.get("payload", project)
    if not isinstance(backup_payload, dict):
        backup_payload = {}
    backup_project_id = str(project.get("project_id") or backup_payload.get("project_id") or "").strip()
    backup_owner = normalize_email(str(project.get("owner_email") or backup_payload.get("owner_email") or ""))
    return bool(
        backup_project_id
        and backup_project_id == target_project_id
        and (not target_owner or not backup_owner or backup_owner == target_owner)
    )


def _delete_project_backup(*, payload: dict[str, Any] | None, path: Path) -> None:
    projects = [
        project
        for project in _load_project_backups()
        if not _project_backup_matches_path(project, path=path, payload=payload)
    ]
    _save_project_backups(projects)


def _list_project_files():
    _restore_projects_from_backup()
    return PROJECT_STORE.list_projects(owner_email=_current_owner_email())


def _load_heliorc_project_payload(payload: dict[str, Any]) -> None:
    _load_imported_project(payload)
    st.session_state["heliorc_current_project_id"] = str(payload.get("project_id") or "")
    st.session_state["heliorc_project_library_id"] = str(
        payload.get("library_id") or payload.get("project_id") or ""
    )
    st.session_state["heliorc_project_created_at"] = str(payload.get("created_at") or "")
    restore_surface_orientation_state(payload, project_id=str(payload.get("project_id", "projet")), state_prefix="heliorc")
    _restore_heliorc_architectural_state(payload, str(payload.get("project_id", "projet")))


def _reset_heliorc_project_state() -> None:
    defaults = {
        "project_name": "Étude d'opportunité solaire thermique",
        "client": "",
        "airtable_id": "",
        "analyst": "",
        "project_date": date.today(),
        "project_city": "",
        "project_address_label": "",
        "project_latitude": DEFAULT_PROJECT_LATITUDE,
        "project_longitude": DEFAULT_PROJECT_LONGITUDE,
        "project_region": "France métropolitaine",
        "project_department": "01 - Bourg-en-Bresse",
        "heliorc_project_name": "Étude d'opportunité solaire thermique",
        "heliorc_client_name": "",
        "heliorc_airtable_id": "",
        "heliorc_analyst": "",
        "heliorc_city": "",
        "heliorc_project_address_label": "",
        "heliorc_project_latitude": DEFAULT_PROJECT_LATITUDE,
        "heliorc_project_longitude": DEFAULT_PROJECT_LONGITUDE,
        "heliorc_region": "France métropolitaine",
        "heliorc_department": "01 - Bourg-en-Bresse",
        "location_label": "1 - Bourg-en-Bresse",
        "last_results": None,
        "last_monthly": None,
        "last_inputs": None,
        "last_project": None,
        "last_sizing_context": None,
        "heliorc_current_project_id": "",
        "heliorc_project_library_id": "",
        "heliorc_project_created_at": "",
        "sizing_strategy": SIZING_STRATEGIES[0],
        "heliorc_architectural_selected_address": "",
        "heliorc_architectural_latitude": DEFAULT_PROJECT_LATITUDE,
        "heliorc_architectural_longitude": DEFAULT_PROJECT_LONGITUDE,
        "heliorc_architectural_project_type": PROJECT_TYPES[0],
        "heliorc_architectural_result": None,
    }
    for key, value in defaults.items():
        st.session_state[key] = value


def _render_project_store_controls() -> None:
    owner_email = _current_owner_email()
    if not owner_email:
        st.info("Connecte-toi pour enregistrer et recharger les projets HelioRC.")
        return

    project_files = _list_project_files()
    labels_by_path = {
        str(project_file.path): _project_file_label(project_file)
        for project_file in project_files
    }
    path_by_label = {
        f"{label} [{index + 1}]": path
        for index, (path, label) in enumerate(labels_by_path.items())
    }

    st.markdown("#### Projets HelioRC")
    if st.session_state.pop("heliorc_project_saved_message", False):
        st.success("Projet HelioRC enregistré.")

    select_col, load_col, new_col, save_col, delete_col = st.columns([3.2, 0.9, 0.9, 0.9, 0.9])
    with select_col:
        selected_label = st.selectbox(
            "Projet enregistré",
            options=["-"] + list(path_by_label),
            key="heliorc_project_store_selected",
            label_visibility="collapsed",
        )
    selected_path = path_by_label.get(selected_label)
    with load_col:
        load_clicked = st.button("Charger", width="stretch", disabled=not selected_path)
    with new_col:
        new_clicked = st.button("Nouveau", width="stretch")
    with save_col:
        save_clicked = st.button("Enregistrer", type="primary", width="stretch")
    with delete_col:
        delete_clicked = st.button("Supprimer", width="stretch", disabled=not selected_path)

    if load_clicked and selected_path:
        try:
            payload = PROJECT_STORE.load_project(path=Path(selected_path), owner_email=owner_email)
            _load_heliorc_project_payload(payload)
            st.success("Projet HelioRC chargé.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Chargement impossible : {exc}")

    if new_clicked:
        _reset_heliorc_project_state()
        st.rerun()

    if save_clicked:
        try:
            payload = _current_project_payload()
            path = PROJECT_STORE.save_project(
                payload=payload,
                owner_email=owner_email,
                project_name=str(payload.get("name") or "Projet HelioRC"),
                project_id=str(payload.get("project_id") or "") or None,
            )
            saved_payload = PROJECT_STORE.load_project(path=path, owner_email=owner_email)
            st.session_state["heliorc_current_project_id"] = str(saved_payload.get("project_id") or "")
            st.session_state["heliorc_project_library_id"] = str(
                saved_payload.get("library_id") or saved_payload.get("project_id") or ""
            )
            st.session_state["heliorc_project_created_at"] = str(saved_payload.get("created_at") or "")
            _upsert_project_backup(path=path, payload=saved_payload)
            st.session_state["heliorc_project_saved_message"] = True
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Enregistrement impossible : {exc}")

    if delete_clicked and selected_path:
        try:
            resolved = PROJECT_STORE.assert_project_path(Path(selected_path))
            deleted_payload = None
            try:
                deleted_payload = PROJECT_STORE.load_project(path=resolved, owner_email=owner_email)
            except Exception:
                deleted_payload = None
            PROJECT_STORE.delete_project(path=resolved, owner_email=owner_email)
            _delete_project_backup(payload=deleted_payload, path=resolved)
            st.success("Projet HelioRC supprimé.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Suppression impossible : {exc}")


def _load_imported_project(payload: dict[str, Any]) -> None:
    project_data = payload.get("project", {})
    input_data = payload.get("inputs", {})
    st.session_state["heliorc_current_project_id"] = str(payload.get("project_id") or "")
    st.session_state["heliorc_project_library_id"] = str(
        payload.get("library_id") or payload.get("project_id") or ""
    )
    st.session_state["heliorc_project_created_at"] = str(payload.get("created_at") or "")
    for key in ["project_name", "client", "airtable_id", "analyst"]:
        if key in project_data:
            st.session_state[key] = project_data[key]
    st.session_state["heliorc_project_name"] = st.session_state.get("project_name", "")
    st.session_state["heliorc_client_name"] = st.session_state.get("client", "")
    st.session_state["heliorc_airtable_id"] = st.session_state.get("airtable_id", "")
    st.session_state["heliorc_analyst"] = st.session_state.get("analyst", "")
    if "city" in project_data:
        st.session_state["heliorc_city"] = project_data["city"]
    if "address" in project_data:
        st.session_state["heliorc_project_address_label"] = project_data["address"]
    if "latitude" in project_data:
        st.session_state["heliorc_project_latitude"] = float(project_data["latitude"])
    if "longitude" in project_data:
        st.session_state["heliorc_project_longitude"] = float(project_data["longitude"])
    st.session_state["heliorc_typology"] = "Réseau de chaleur"
    if "region" in project_data:
        st.session_state["heliorc_region"] = project_data["region"]
    if "department" in project_data:
        st.session_state["heliorc_department"] = project_data["department"]
    if "weather_region" in project_data:
        st.session_state["heliorc_weather_region"] = project_data["weather_region"]
        st.session_state["weather_region"] = project_data["weather_region"]
    if "weather_station" in project_data:
        st.session_state["heliorc_weather_station"] = project_data["weather_station"]
        st.session_state["weather_station"] = project_data["weather_station"]
    if project_data.get("date"):
        st.session_state["project_date"] = date.fromisoformat(project_data["date"])
        st.session_state["heliorc_project_date"] = st.session_state["project_date"]
    mapping = {
        "location_label": "location_label",
        "zone": "zone",
        "regime_label": "regime_label",
        "mean_network_temperature_c": "mean_temp",
        "other_aid_eur": "other_aid",
        "electricity_price_eur_mwh": "electricity_price",
        "project_lifetime_years": "project_lifetime",
        "network_operates_summer": "network_operates_summer",
        "summer_excess_enr": "summer_excess_enr",
        "land_identified": "land_identified",
    }
    for source_key, state_key in mapping.items():
        if source_key in input_data:
            st.session_state[state_key] = input_data[source_key]
    if "base_load_fraction" in input_data:
        st.session_state["base_load_percent"] = round(float(input_data["base_load_fraction"]) * 100)
    if input_data.get("sizing_strategy") in SIZING_STRATEGIES:
        st.session_state["sizing_strategy"] = input_data["sizing_strategy"]
    if input_data.get("solar_connection_mode") in (
        "Installation centralisée",
        "Installation décentralisée sur une branche du réseau",
    ):
        st.session_state["solar_connection_mode"] = input_data["solar_connection_mode"]
    restore_surface_orientation_state(payload, project_id=str(payload.get("project_id", "projet")), state_prefix="heliorc")
    _restore_heliorc_architectural_state(payload, str(payload.get("project_id", "projet")))
    monthly_values = input_data.get("monthly_needs_mwh")
    if isinstance(monthly_values, list) and len(monthly_values) == 12:
        st.session_state["manual_needs_df"] = _initial_monthly_dataframe([float(value) for value in monthly_values])
        st.session_state.pop("manual_needs_editor", None)
        st.session_state.pop("manual_needs_editor_form", None)
        st.session_state.pop("manual_needs_editor_form_v3", None)
        st.session_state.pop("manual_needs_editor_v4", None)
    branch_monthly_values = input_data.get("branch_monthly_needs_mwh")
    if isinstance(branch_monthly_values, list) and len(branch_monthly_values) == 12:
        st.session_state["branch_needs_df"] = _initial_branch_monthly_dataframe([float(value) for value in branch_monthly_values])
        st.session_state.pop("branch_needs_editor", None)
        st.session_state.pop("branch_needs_editor_form", None)
        st.session_state.pop("branch_needs_editor_form_v3", None)
        st.session_state.pop("branch_needs_editor_v4", None)
    rate = input_data.get("discount_rate_override")
    st.session_state["override_discount_rate"] = rate is not None
    if rate is not None:
        st.session_state["discount_rate_percent"] = float(rate) * 100


def _render_project_tab(locations: pd.DataFrame) -> None:
    st.subheader("Contexte")
    department_options = _heliorc_department_options(locations)
    normalised_department = _department_option_from_code(
        department_options,
        st.session_state.get("heliorc_department") or st.session_state.get("project_department"),
    )
    if normalised_department:
        st.session_state["heliorc_department"] = normalised_department
        st.session_state["project_department"] = normalised_department

    project_identity = render_project_identity_form(
        key_prefix="heliorc",
        defaults=_project_identity_from_state(),
        options=ProjectIdentityOptions(
            show_analyst=True,
            show_project_date=True,
            show_typology=False,
            show_region=False,
            show_department=True,
            region_options=HELIORC_PROJECT_REGIONS,
            department_options=department_options,
            client_label="Maître d'ouvrage / territoire",
            airtable_label="Référence / ID Airtable",
        ),
        on_location_change=_on_heliorc_location_change,
    )
    _sync_project_identity_to_legacy_state(project_identity)
    _propagate_heliorc_project_location()
    _sync_location_from_project_department(locations)
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.checkbox(
            "Le réseau fonctionne en été",
            key="network_operates_summer",
            help="Condition indispensable du cadre d'application du modèle.",
        )
    with col_b:
        st.checkbox(
            "Présence d'une EnR&R excédentaire en été",
            key="summer_excess_enr",
            help="Une autre production excédentaire en été peut réduire ou annuler le talon disponible pour le solaire.",
        )
    with col_c:
        st.checkbox("Un foncier potentiel est identifié", key="land_identified")



def render_heliorc_app() -> None:
    """Render HelioRC inside the HelioTools portal."""

    _render_styles()
    _init_state()
    _ensure_branch_editor_schema()
    locations = load_locations()

    title_col, logo_col = st.columns([0.78, 0.22], vertical_alignment="center")
    with title_col:
        st.title("HelioRC")
        st.caption("Note d'opportunité pour l'intégration du solaire thermique sur un réseau de chaleur urbain.")
    with logo_col:
        if ADEME_LOGO.exists():
            st.image(str(ADEME_LOGO), width=155)

    st.caption(
        "Méthode de prédimensionnement : talon estival, productivité paramétrique, stockage journalier, CAPEX, aide indicative et coût de chaleur."
    )
    st.caption(f"Documentation de référence ADEME : {ADEME_REFERENCE_URL}")

    _render_project_store_controls()
    st.divider()

    st.session_state["heliorc_surface_orientation_tab_label"] = "2. Orientation / surface"
    tab_labels = [
        "1. Contexte",
        "2. Orientation / surface",
        "3. Besoins du RCU",
        "4. Contraintes architecturales",
        "5. Hypothèses techniques",
        "6. Hypothèses économiques",
        "7. Calcul et résultats",
    ]
    default_tab = st.session_state.get("heliorc_default_tab")
    if default_tab not in tab_labels:
        default_tab = tab_labels[0]
    input_tabs = st.tabs(
        tab_labels,
        default=default_tab,
    )

    with input_tabs[0]:
        _render_project_tab(locations)

    with input_tabs[2]:
        st.radio(
            "Mode de saisie",
            ["Besoins mensuels connus", "Estimation depuis les besoins annuels"],
            horizontal=True,
            key="needs_mode",
        )
        if st.session_state.needs_mode == "Besoins mensuels connus":
            st.markdown(
                "Saisir les besoins mensuels **au niveau du réseau**, pertes comprises, comme dans l'onglet principal du classeur."
            )
            edited = st.data_editor(
                    _editor_monthly_dataframe(
                        _normalise_manual_needs_dataframe(st.session_state.manual_needs_df),
                        TOTAL_NEEDS_COL,
                    ),
                key="manual_needs_editor_v4",
                on_change=_apply_monthly_editor_changes,
                kwargs={
                    "editor_key": "manual_needs_editor_v4",
                    "target_state_key": "manual_needs_df",
                    "value_col": TOTAL_NEEDS_COL,
                    "normalise": _normalise_manual_needs_dataframe,
                },
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    column_config={
                        "Mois": st.column_config.TextColumn("Mois"),
                        TOTAL_NEEDS_COL: st.column_config.TextColumn(
                            TOTAL_NEEDS_COL,
                            help="Collage Excel accepté avec virgule ou point décimal. Exemple : 410,5",
                        ),
                    },
            )
            st.session_state.manual_needs_df = _normalise_manual_needs_dataframe(
                edited,
                st.session_state.manual_needs_df,
            )
            needs_preview = st.session_state.manual_needs_df.copy()
        else:
            col_1, col_2, col_3 = st.columns(3)
            with col_1:
                st.number_input(
                    "Besoins annuels de chauffage des abonnés (MWh/an)",
                    min_value=0.0,
                    step=100.0,
                    key="annual_heating",
                )
            with col_2:
                st.number_input(
                    "Besoins annuels d'ECS des abonnés (MWh/an)",
                    min_value=0.0,
                    step=50.0,
                    key="annual_ecs",
                )
            with col_3:
                st.slider(
                    "Rendement moyen du réseau",
                    min_value=50,
                    max_value=100,
                    step=1,
                    key="network_efficiency_percent",
                    format="%d %%",
                )
            try:
                estimated = estimate_monthly_needs(
                    location_label=st.session_state.location_label,
                    annual_heating_mwh=float(st.session_state.annual_heating),
                    annual_ecs_mwh=float(st.session_state.annual_ecs),
                    network_efficiency=float(st.session_state.network_efficiency_percent) / 100,
                    calculation_mode="excel_v5_3",
                )
                needs_preview = estimated
                st.dataframe(
                    estimated.style.format(
                        {
                            "Température extérieure moyenne (°C)": "{:.1f}",
                            "Chauffage (MWh)": "{:.1f}",
                            "ECS (MWh)": "{:.1f}",
                            "Pertes réseau (MWh)": "{:.1f}",
                            "Besoins RCU (MWh)": "{:.1f}",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )
            except ValueError as exc:
                needs_preview = pd.DataFrame()
                st.error(str(exc))

        if _is_decentralized_connection():
            _sync_branch_defaults_from_total_if_needed()
            st.markdown("### Besoins de la branche sélectionnée")
            st.caption(
                "Ces valeurs servent au dimensionnement de la centrale décentralisée. "
                "Les résultats finaux restent ensuite comparés au besoin total du RCU."
            )
            branch_edited = st.data_editor(
                    _editor_monthly_dataframe(
                        _normalise_branch_needs_dataframe(st.session_state.branch_needs_df),
                        BRANCH_NEEDS_COL,
                    ),
                key="branch_needs_editor_v4",
                on_change=_apply_monthly_editor_changes,
                kwargs={
                    "editor_key": "branch_needs_editor_v4",
                    "target_state_key": "branch_needs_df",
                    "value_col": BRANCH_NEEDS_COL,
                    "normalise": _normalise_branch_needs_dataframe,
                },
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    column_config={
                        "Mois": st.column_config.TextColumn("Mois"),
                        BRANCH_NEEDS_COL: st.column_config.TextColumn(
                            BRANCH_NEEDS_COL,
                            help="Collage Excel accepté avec virgule ou point décimal. Exemple : 410,5",
                        ),
                    },
            )
            st.session_state.branch_needs_df = _normalise_branch_needs_dataframe(
                branch_edited,
                st.session_state.branch_needs_df,
            )
            if isinstance(needs_preview, pd.DataFrame) and TOTAL_NEEDS_COL in needs_preview:
                total_monthly_values = _monthly_values_from_frame(needs_preview)
                branch_monthly_values = _branch_monthly_values_from_frame(st.session_state.branch_needs_df)
                for guard_message in decentralized_branch_guard(total_monthly_values, branch_monthly_values):
                    st.error(guard_message)
                total_summer = float(pd.to_numeric(needs_preview[TOTAL_NEEDS_COL], errors="coerce").fillna(0.0).iloc[4:9].sum())
                branch_summer = float(_normalise_branch_needs_dataframe(st.session_state.branch_needs_df)[BRANCH_NEEDS_COL].astype(float).iloc[4:9].sum())
                if total_summer > 0:
                    branch_share = branch_summer / total_summer
                    st.metric("Part estivale de la branche sélectionnée", f"{branch_share:.1%}")
                    if branch_share < 0.50:
                        st.warning(
                            "Pour une centrale décentralisée sur branche, il est recommandé que la branche sélectionnée "
                            "représente au moins 50 % des besoins estivaux qu'elle dessert."
                        )

    with input_tabs[1]:
        st.radio(
            "Position de la centrale solaire thermique",
            [
                "Installation centralisée",
                "Installation décentralisée sur une branche du réseau",
            ],
            key="solar_connection_mode",
            horizontal=True,
            help=(
                "Centralisée : la centrale est à proximité directe de la chaufferie principale. "
                "Décentralisée : la centrale est éloignée de la chaufferie mais proche d'une branche du réseau ; "
                "la branche doit idéalement représenter au moins 50 % des besoins estivaux qu'elle dessert."
            ),
        )
        if _is_decentralized_connection():
            st.info(
                "Mode décentralisé : le prédimensionnement solaire est calculé sur les besoins de la branche sélectionnée. "
                "Les résultats globaux restent ensuite rapportés au besoin total du RCU."
            )
        orientation_payload = _render_heliorc_surface_orientation_measurement()
        metrics = orientation_payload.get("metrics") if isinstance(orientation_payload, dict) else {}
        available_ground_m2 = None
        if isinstance(metrics, dict) and isinstance(metrics.get("surface_m2"), (float, int)):
            available_ground_m2 = float(metrics["surface_m2"])
        max_collector_area_m2 = _heliorc_max_collector_area_from_ground(available_ground_m2)
        if max_collector_area_m2 is not None:
            st.info(
                f"Pour HelioRC, l'emprise retenue est de {HELIORC_GROUND_AREA_M2_PER_COLLECTOR_M2:.1f} m² au sol "
                f"par m² de capteur, soit environ {max_collector_area_m2:.1f} m² de capteurs maximum sur la surface dessinée."
            )

    with input_tabs[3]:
        render_architectural_constraints_test(state_prefix="heliorc", show_address_inputs=False, show_map=True)

    with input_tabs[4]:
        tech_col, _ = st.columns(2)
        with tech_col:
            selected_regime = st.selectbox(
                "Régime moyen du réseau",
                list(REGIMES),
                key="regime_label",
            )
            suggested_temp = REGIMES[selected_regime]
            if st.session_state.get("_last_regime") != selected_regime:
                st.session_state.mean_temp = suggested_temp
                st.session_state._last_regime = selected_regime
            st.number_input(
                "Température moyenne estivale départ-retour (°C)",
                min_value=35.0,
                max_value=100.0,
                step=1.0,
                key="mean_temp",
            )
            st.radio(
                "Mode de dimensionnement",
                list(SIZING_STRATEGIES),
                key="sizing_strategy",
                help=(
                    "Le mode réglable applique le talon choisi ci-dessous. Le mode surface disponible recherche "
                    "automatiquement le plus grand talon compatible avec l'emprise dessinée dans Orientation / surface."
                ),
            )
            if st.session_state.sizing_strategy == SIZING_STRATEGIES[0]:
                st.slider(
                    "Talon de dimensionnement",
                    min_value=50,
                    max_value=100,
                    step=1,
                    key="base_load_percent",
                    format="%d %%",
                )
            else:
                st.caption(
                    "Le calcul vise 95 % du talon si le terrain disponible le permet. Sinon, il réduit automatiquement le talon "
                    "pour respecter l'emprise disponible avec 2,5 m² au sol par m² de capteur."
                )
    with input_tabs[5]:
        eco_col, _ = st.columns(2)
        with eco_col:
            st.selectbox("Zone géographique de l'aide", list(AID_FORFAITS), key="zone")
            st.number_input(
                "Autres aides (régionales, CEE, etc.) (€ HT)",
                min_value=0.0,
                step=10000.0,
                key="other_aid",
            )
            st.number_input(
                "Prix de l'électricité (€ HT/MWh)",
                min_value=0.0,
                step=1.0,
                key="electricity_price",
            )
            st.number_input(
                "Durée de vie économique (années)",
                min_value=1,
                max_value=50,
                step=1,
                key="project_lifetime",
            )
            st.checkbox("Forcer le taux d'actualisation", key="override_discount_rate")
            if st.session_state.override_discount_rate:
                st.number_input(
                    "Taux d'actualisation (%)",
                    min_value=0.0,
                    max_value=20.0,
                    step=0.1,
                    key="discount_rate_percent",
                )
            else:
                st.caption("Taux automatique du classeur : 5 % sous 500 m², 6 % au-delà.")

    with input_tabs[6]:
        calculate_clicked = st.button(
            "Lancer le calcul HelioRC",
            type="primary",
            width="stretch",
        )

        if calculate_clicked:
            progress = st.progress(0, text="Contrôle des données...")
            try:
                progress.progress(25, text="Construction du profil mensuel...")
                if st.session_state.needs_mode == "Besoins mensuels connus":
                    total_monthly_needs = (
                        st.session_state.manual_needs_df[TOTAL_NEEDS_COL]
                        .astype(float)
                        .tolist()
                    )
                else:
                    estimated = estimate_monthly_needs(
                        location_label=st.session_state.location_label,
                        annual_heating_mwh=float(st.session_state.annual_heating),
                        annual_ecs_mwh=float(st.session_state.annual_ecs),
                        network_efficiency=float(st.session_state.network_efficiency_percent) / 100,
                        calculation_mode="excel_v5_3",
                    )
                    total_monthly_needs = estimated[TOTAL_NEEDS_COL].astype(float).tolist()

                progress.progress(60, text="Prédimensionnement technique...")
                calculation_monthly_needs = total_monthly_needs
                if _is_decentralized_connection():
                    calculation_monthly_needs = _branch_monthly_values_from_frame(st.session_state.branch_needs_df)
                    guard_messages = decentralized_branch_guard(total_monthly_needs, calculation_monthly_needs)
                    if guard_messages:
                        for guard_message in guard_messages:
                            st.error(guard_message)
                        st.stop()
                inputs, results, monthly, sizing_context = _calculate_with_sizing_strategy(calculation_monthly_needs)
                annual_total_need = float(sum(total_monthly_needs))
                annual_calculation_need = float(sum(calculation_monthly_needs))
                global_solar_fraction = results.annual_solar_production_mwh / annual_total_need if annual_total_need > 0 else 0.0
                calculation_solar_fraction = (
                    results.annual_solar_production_mwh / annual_calculation_need if annual_calculation_need > 0 else 0.0
                )
                sizing_context.update(
                    {
                        "solar_connection_mode": _current_connection_mode(),
                        "total_monthly_needs_mwh": total_monthly_needs,
                        "calculation_monthly_needs_mwh": calculation_monthly_needs,
                        "annual_total_need_mwh": annual_total_need,
                        "annual_calculation_need_mwh": annual_calculation_need,
                        "global_solar_fraction": global_solar_fraction,
                        "calculation_solar_fraction": calculation_solar_fraction,
                    }
                )
                if _is_decentralized_connection():
                    monthly[BRANCH_NEEDS_COL] = calculation_monthly_needs
                    monthly["Taux de couverture mensuel branche"] = monthly["Taux de couverture mensuel"].astype(float)
                    monthly["Besoins RCU total (MWh)"] = total_monthly_needs
                    monthly[TOTAL_NEEDS_COL] = total_monthly_needs
                    total_need_series = pd.Series(total_monthly_needs, dtype=float).replace(0.0, pd.NA)
                    monthly["Taux de couverture mensuel"] = (
                        monthly["Production solaire (MWh)"].astype(float).div(total_need_series).fillna(0.0)
                    )
                progress.progress(85, text="Analyse économique et interprétation...")
                project = _current_project_data()
                st.session_state.last_results = results
                st.session_state.last_monthly = monthly
                st.session_state.last_inputs = inputs
                st.session_state.last_project = project
                st.session_state.last_sizing_context = sizing_context
                progress.progress(100, text="Calcul terminé.")
                progress.empty()
                st.success("Calcul terminé. Les résultats ci-dessous correspondent au dernier lancement.")
            except Exception as exc:  # noqa: BLE001
                progress.empty()
                st.error(f"Calcul impossible : {exc}")

        results = st.session_state.last_results
        monthly = st.session_state.last_monthly
        inputs = st.session_state.last_inputs
        project = st.session_state.last_project
        sizing_context = st.session_state.get("last_sizing_context")

        if results is None or monthly is None or inputs is None or project is None:
            st.info("Renseignez les hypothèses puis lancez le calcul pour afficher la note d'opportunité.")
            return

        display_solar_fraction = results.solar_fraction
        calculation_solar_fraction = results.solar_fraction
        if isinstance(sizing_context, dict):
            if isinstance(sizing_context.get("global_solar_fraction"), (float, int)):
                display_solar_fraction = float(sizing_context["global_solar_fraction"])
            if isinstance(sizing_context.get("calculation_solar_fraction"), (float, int)):
                calculation_solar_fraction = float(sizing_context["calculation_solar_fraction"])

        st.markdown("## Résultats du dernier calcul")
        status_lower = results.opportunity_status.lower()
        if "favorable" in status_lower:
            st.success(f"**{results.opportunity_status}** - {results.scope_status}")
        elif "intermédiaire" in status_lower:
            st.warning(f"**{results.opportunity_status}** - {results.scope_status}")
        else:
            st.error(f"**{results.opportunity_status}** - {results.scope_status}")

        result_tabs = st.tabs(["Synthèse", "Profil mensuel", "Détail des calculs", "Exports", "Méthode et limites"])

        with result_tabs[0]:
            st.markdown("### Analyse technique")
            if isinstance(sizing_context, dict):
                strategy = str(sizing_context.get("strategy") or "")
                effective_fraction = sizing_context.get("effective_base_load_fraction")
                available_ground = sizing_context.get("available_ground_area_m2")
                max_collector = sizing_context.get("max_collector_area_m2")
                if strategy:
                    st.caption(
                        "Dimensionnement appliqué : "
                        + strategy
                        + (
                            f" ; talon effectif {float(effective_fraction) * 100:.1f} %."
                            if isinstance(effective_fraction, (float, int))
                            else "."
                        )
                    )
                if isinstance(available_ground, (float, int)) and isinstance(max_collector, (float, int)):
                    st.caption(
                        f"Surface terrain mesurée : {float(available_ground):.1f} m² ; "
                        f"surface capteurs compatible HelioRC : {float(max_collector):.1f} m² "
                        f"avec {HELIORC_GROUND_AREA_M2_PER_COLLECTOR_M2:.1f} m² au sol par m² de capteur."
                    )
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Surface de capteurs", f"{results.collector_area_m2:,.0f} m²".replace(",", " "))
            m2.metric("Production solaire", f"{results.annual_solar_production_mwh:,.0f} MWh/an".replace(",", " "))
            m3.metric("Fraction solaire RCU global", f"{display_solar_fraction:.1%}")
            m4.metric("Productivité", f"{results.productivity_kwh_m2_year:,.0f} kWh/m²/an".replace(",", " "))
            m5, m6, m7, m8 = st.columns(4)
            m5.metric("Stockage journalier", f"{results.storage_volume_m3:,.0f} m³".replace(",", " "))
            m6.metric("Emprise foncière", f"{results.land_area_ha:.2f} ha")
            m7.metric(
                "Distance maximum de raccordement conseillée",
                f"{results.recommended_connection_distance_m:,.0f} m".replace(",", " "),
            )
            m8.metric("Panneaux de 15 m²", f"{results.panel_count_15m2}")

            st.markdown("### Première analyse économique")
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("CAPEX indicatif", f"{results.capex_eur / 1_000:,.0f} k€ HT".replace(",", " "))
            with e2:
                st.metric("Aide ADEME indicative", f"{results.ademe_aid_eur / 1_000:,.0f} k€".replace(",", " "))
                if results.collector_area_m2 > 1500:
                    st.warning("Au-delà de 1 500 m², l'aide ADEME affichée est seulement indicative.")
            e3.metric("Reste à charge", f"{results.remaining_cost_eur / 1_000:,.0f} k€ HT".replace(",", " "))
            e4.metric("LCOH aidé", f"{results.lcoh_aided_eur_mwh:.1f} € HT/MWh")

            with st.expander("Vigilances identifiées", expanded=True):
                if isinstance(sizing_context, dict) and str(sizing_context.get("solar_connection_mode", "")).startswith(
                    "Installation décentralisée"
                ):
                    st.write(
                        f"- Mode décentralisé : la cohérence technique est contrôlée sur la branche sélectionnée "
                        f"(fraction solaire branche : {calculation_solar_fraction:.1%}). "
                        f"La fraction solaire affichée en synthèse est rapportée au RCU global."
                    )
                for warning in results.warnings:
                    st.write(f"- {warning}")
                st.markdown("**Points de vigilance issus de la documentation ADEME**")
                for vigilance in ADEME_REFERENCE_VIGILANCES:
                    st.write(f"- {vigilance}")

        with result_tabs[1]:
            needs_mwh = monthly["Besoins RCU (MWh)"].astype(float)
            solar_mwh = monthly["Production solaire (MWh)"].astype(float).clip(lower=0)
            solar_covered_mwh = solar_mwh.clip(upper=needs_mwh)
            backup_mwh = (needs_mwh - solar_covered_mwh).clip(lower=0)
            display_monthly = monthly[
                [
                    "Mois",
                    "Besoins RCU (MWh)",
                    "Production solaire (MWh)",
                    "Taux de couverture mensuel",
                ]
            ].copy()
            graph_col, table_col = st.columns(2)
            with graph_col:
                figure = go.Figure()
                figure.add_trace(
                    go.Bar(
                        x=monthly["Mois"],
                        y=solar_covered_mwh,
                        name="Couverture solaire thermique",
                        marker_color="#FCBF24",
                        hovertemplate="%{x}<br>Solaire thermique : %{y:.1f} MWh<extra></extra>",
                    )
                )
                figure.add_trace(
                    go.Bar(
                        x=monthly["Mois"],
                        y=backup_mwh,
                        name="Appoint / réseau existant",
                        marker_color="#98A2B3",
                        hovertemplate="%{x}<br>Appoint : %{y:.1f} MWh<extra></extra>",
                    )
                )
                figure.update_layout(
                    title="Couverture mensuelle des besoins RCU",
                    xaxis_title="Mois",
                    yaxis_title="Énergie (MWh/mois)",
                    barmode="stack",
                    hovermode="x unified",
                    legend={"orientation": "h", "y": 1.14, "x": 0},
                    margin={"l": 30, "r": 20, "t": 85, "b": 35},
                    height=520,
                )
                st.plotly_chart(figure, width="stretch")

            with table_col:
                st.dataframe(
                    display_monthly.style.format(
                        {
                            "Besoins RCU (MWh)": "{:.1f}",
                            "Production solaire (MWh)": "{:.1f}",
                            "Taux de couverture mensuel": "{:.1%}",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )

            if BRANCH_NEEDS_COL in monthly.columns:
                st.markdown("### Production solaire thermique sur les besoins de la branche")
                st.caption(
                    "En mode décentralisé, ce graphique vérifie la production solaire sur la branche réellement desservie. "
                    "Le graphique précédent reste rapporté au besoin total du RCU."
                )
                branch_needs_mwh = monthly[BRANCH_NEEDS_COL].astype(float)
                branch_solar_covered_mwh = solar_mwh.clip(upper=branch_needs_mwh)
                branch_backup_mwh = (branch_needs_mwh - branch_solar_covered_mwh).clip(lower=0)
                branch_display_monthly = monthly[
                    [
                        "Mois",
                        BRANCH_NEEDS_COL,
                        "Production solaire (MWh)",
                        "Taux de couverture mensuel branche",
                    ]
                ].copy()
                branch_graph_col, branch_table_col = st.columns(2)
                with branch_graph_col:
                    branch_figure = go.Figure()
                    branch_figure.add_trace(
                        go.Bar(
                            x=monthly["Mois"],
                            y=branch_solar_covered_mwh,
                            name="Couverture solaire thermique",
                            marker_color="#FCBF24",
                            hovertemplate="%{x}<br>Solaire thermique : %{y:.1f} MWh<extra></extra>",
                        )
                    )
                    branch_figure.add_trace(
                        go.Bar(
                            x=monthly["Mois"],
                            y=branch_backup_mwh,
                            name="Appoint / réseau existant",
                            marker_color="#98A2B3",
                            hovertemplate="%{x}<br>Appoint : %{y:.1f} MWh<extra></extra>",
                        )
                    )
                    branch_figure.update_layout(
                        title="Couverture mensuelle des besoins de la branche",
                        xaxis_title="Mois",
                        yaxis_title="Énergie (MWh/mois)",
                        barmode="stack",
                        hovermode="x unified",
                        legend={"orientation": "h", "y": 1.14, "x": 0},
                        margin={"l": 30, "r": 20, "t": 85, "b": 35},
                        height=520,
                    )
                    st.plotly_chart(branch_figure, width="stretch")
                with branch_table_col:
                    st.dataframe(
                        branch_display_monthly.style.format(
                            {
                                BRANCH_NEEDS_COL: "{:.1f}",
                                "Production solaire (MWh)": "{:.1f}",
                                "Taux de couverture mensuel branche": "{:.1%}",
                            }
                        ),
                        hide_index=True,
                        width="stretch",
                    )

        with result_tabs[2]:
            display_annual_need = (
                float(sizing_context["annual_total_need_mwh"])
                if isinstance(sizing_context, dict) and isinstance(sizing_context.get("annual_total_need_mwh"), (float, int))
                else results.annual_need_mwh
            )
            technical_rows = {
                "Besoin annuel du RCU (MWh/an)": display_annual_need,
                "Part des besoins estivaux mai-septembre": results.summer_need_share,
                "Fraction solaire RCU global": display_solar_fraction,
                "Fraction solaire utilisée pour la cohérence": calculation_solar_fraction,
                "Talon mensuel minimal (MWh)": results.minimum_monthly_need_mwh,
                "Talon de dimensionnement appliqué": inputs.base_load_fraction,
                "Gisement horizontal (kWh/m².an)": results.annual_horizontal_irradiation_kwh_m2,
                "Production solaire (MWh/an)": results.annual_solar_production_mwh,
                "Productivité (kWh/m².an)": results.productivity_kwh_m2_year,
                "Surface de capteurs (m²)": results.collector_area_m2,
                "Stockage (m³)": results.storage_volume_m3,
                "Emprise (ha)": results.land_area_ha,
                "Distance de raccordement (m)": results.recommended_connection_distance_m,
                "Coût surfacique (€ HT/m²)": results.unit_capex_eur_m2,
                "CAPEX (€ HT)": results.capex_eur,
                "Aide ADEME (€)": results.ademe_aid_eur,
                "Autres aides (€)": results.other_aid_eur,
                "Taux d'aide total": results.aid_rate,
                "Reste à charge (€ HT)": results.remaining_cost_eur,
                "P1' (€ HT/MWh)": results.p1_eur_mwh,
                "P2/P3 (€ HT/MWh)": results.opex_eur_mwh,
                "P4 (€ HT/MWh)": results.capital_recovery_eur_mwh,
                "LCOH aidé (€ HT/MWh)": results.lcoh_aided_eur_mwh,
                "Taux d'actualisation": results.discount_rate,
            }
            details_df = pd.DataFrame(
                [{"Indicateur": key, "Valeur": value} for key, value in technical_rows.items()]
            )
            st.dataframe(details_df, hide_index=True, width="stretch")
            st.markdown("#### Table mensuelle complète")
            st.dataframe(monthly, hide_index=True, width="stretch")

        with result_tabs[3]:
            csv_bytes = monthly.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
            try:
                pdf_bytes = build_opportunity_note(
                    project=project,
                    inputs=inputs,
                    results=results,
                    monthly=monthly,
                    sizing_context=sizing_context if isinstance(sizing_context, dict) else {},
                    surface_orientation=current_surface_orientation_payload("heliorc"),
                    architectural_constraints=_current_heliorc_architectural_payload(),
                )
            except Exception as exc:  # noqa: BLE001
                pdf_bytes = None
                st.error(f"La note PDF n'a pas pu être générée : {exc}")

            export_slug = safe_slug(str(project.get("project_name") or "projet"), fallback="projet")
            export_date = date.today().strftime("%Y%m%d")
            export_basename = f"{export_slug}_HelioRC_{export_date}"
            export_col_1, export_col_2 = st.columns(2)
            with export_col_1:
                if pdf_bytes is not None:
                    st.download_button(
                        "Télécharger la note PDF",
                        data=pdf_bytes,
                        file_name=f"{export_basename}_note_opportunite.pdf",
                        mime="application/pdf",
                        width="stretch",
                    )
            with export_col_2:
                st.download_button(
                    "Télécharger le détail CSV",
                    data=csv_bytes,
                    file_name=f"{export_basename}_resultats_mensuels.csv",
                    mime="text/csv",
                    width="stretch",
                )
            st.caption(
                "Le PDF est une note de premier niveau et doit rester accompagné des limites du modèle."
            )

        with result_tabs[4]:
            st.markdown(
                r"""
        ### Méthode de calcul

        1. Le profil de production mensuel est obtenu à partir de l'irradiation sur le plan optimal, corrigée par les 12 coefficients saisonniers du classeur, puis normalisée sur son maximum.
        2. La production mensuelle vaut : **taux de talon × minimum mensuel des besoins × profil solaire normalisé**.
        3. La productivité annuelle est calculée par l'équation paramétrique :

        $$P = (0{,}4818G - 503{,}1B_e + 1{,}1244B_eG - 199{,}6)\,[1 + 0{,}014(55-T_m)]$$

        avec $G$ le gisement horizontal annuel, $B_e$ la part des besoins de mai à septembre et $T_m$ la température moyenne du réseau.

        4. La surface est déduite de la production annuelle et de la productivité. Le stockage vaut environ **0,2 m³/m²**, l'emprise **2,5 m² de terrain par m² de capteur**.
        5. Le CAPEX surfacique suit la courbe par morceaux du classeur. Le LCOH additionne P1', P2/P3 et le facteur de récupération du capital P4.

        ### Cadre d'utilisation

        - Centrale avec stockage journalier et capteurs plans vitrés haute performance.
        - Plage de référence : surface de capteurs > 100 m² et fraction solaire entre 10 et 30 %.
        - Outil de priorisation et de discussion en amont d'une étude de faisabilité.
        - Point de vigilance : si la surface est ≤ 100 m² ou si la fraction solaire sort de 10-30 %, la précision attendue diminue et le résultat doit être confirmé par une étude de faisabilité.
        - Configurations particulières à confirmer par une étude dédiée : stockage intersaisonnier, tracker, capteurs sous vide, recharge géothermique, raccordement complexe ou foncier atypique.
        - L'objectif est un ordre de grandeur technique ; l'économie reste particulièrement sensible aux hypothèses de CAPEX, d'aides, de financement et de raccordement.

        """
            )
            st.info(
                "Étape suivante recommandée lorsque l'opportunité est confirmée : étude de faisabilité avec modélisation dynamique et analyse du réseau, du foncier, de l'hydraulique et du montage économique."
            )
