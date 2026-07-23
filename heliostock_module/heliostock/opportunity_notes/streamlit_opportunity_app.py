"""Outil d'aide à la note d'opportunité solaire thermique.

Lancement local :
    python -m streamlit run streamlit_opportunity_demo.py

Version V18 :
- suppression du champ "Type de bouclage" dans l'estimation des pertes ;
- le volume ECS de référence SOLO est déduit automatiquement de la conso ECS moyenne journalière divisée par le nombre d'unités ;
- conservation du bouclage SOLO complet, du collage Excel et du prédimensionnement.
"""

from __future__ import annotations

import json
import re
import uuid
from io import BytesIO, StringIO
from dataclasses import asdict
from pathlib import Path
from typing import Any

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:  # pragma: no cover
    go = None

from .cesc_economic_model import (
    ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY,
    CescEconomicInputs,
    DEFAULT_AUXILIARY_ELECTRICITY_COST_EUR_MWH,
    DEFAULT_AUXILIARY_ELECTRICITY_RATIO,
    TYPOLOGY_LABELS as ECONOMIC_SCENARIOS,
    build_yearly_cashflow_projection,
    compute_cesc_economic_model,
)
from .opportunity_model import (
    BUILDING_STATES,
    CAMPING_DEFAULT_L_PER_PERSON_NIGHT,
    CAR_WASH_DEFAULT_L_PER_VEHICLE,
    CP_WHLK,
    DATA_SOURCES,
    DAYS_BY_MONTH,
    DEFAULT_LOOP_AMBIENT_TEMPERATURES_C,
    DEFAULT_MONTHLY_COEFFICIENTS,
    DEFAULT_PRODUCTIVITY_KWH_M2_YEAR,
    EHPAD_DEFAULT_L_PER_RESIDENT_DAY,
    HOSPITAL_DEFAULT_L_PER_BED_DAY,
    HOTEL_RATIOS_L_PER_ROOM_NIGHT,
    HOUSING_RATIOS_L_PER_DWELLING_DAY,
    LOOP_METHODS,
    MONTH_NAMES,
    SITE_TYPOLOGIES,
    SOLO_LOSS_INPUT_MODES,
    SOLO_LOOP_LOSS_MODE_LABELS,
    LoopInputs,
    NeedsInputs,
    SiteInputs,
    SizingInputs,
    compute_opportunity_results,
    dict_to_loop_inputs,
    dict_to_needs_inputs,
    dict_to_sizing_inputs,
    dict_to_site_inputs,
)
from .pdf_export import build_opportunity_note_pdf
from ..collector_library import COLLECTOR_LIBRARY, DEFAULT_COLLECTOR_NAME, get_collector_reference
from ..common.project_store import JsonProjectStore, normalize_email, now_iso, safe_slug
from ..common.solar_thermal_cost_reference import (
    SOLAR_THERMAL_COST_REFERENCE_NOTE,
    build_solar_thermal_cost_reference_plotly,
)
from ..epw_reader import read_epw_hourly_weather_from_zip
from ..geocoding_service import GeocodingServiceError, search_addresses
from ..ui_architectural_constraints import PROJECT_TYPES, render_architectural_constraints_test
from ..ui_inputs import DEFAULT_EPW_REGIONS, WEATHER_STATION_LABEL_ALIASES
from .. import ui_portal

APP_KEY = "helionop"
APP_LABEL = "HelioNOP"
PROJECT_STORE = JsonProjectStore(APP_KEY, app_label=APP_LABEL)
DEFAULT_BACKUP_PROJECTS_PATH = "seed_data/helionop_projects.json"
PROJECTS_SESSION_CACHE_KEY = "helionop_projects_cache"
ECS_PROFILE_INPUT_MODES: tuple[str, ...] = (
    "Profil L/jour moyen",
    "Volume m³/mois",
    "Consommation ECS MWh/mois",
    "Consommation ECS kWh/jour",
)
COLD_WATER_MODES: tuple[str, ...] = (
    "Température eau froide manuelle",
    "Méthode ESM2",
    "Méthode ESM2 + 3 °C",
)
DEFAULT_PROJECT_LATITUDE = 47.2184
DEFAULT_PROJECT_LONGITUDE = -1.5536


@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_project_address_search(query: str) -> list[dict[str, object]]:
    return search_addresses(query=query, limit=5)


def _candidate_label(candidate: dict[str, object]) -> str:
    label = str(candidate.get("label") or "Adresse trouvée")
    context = str(candidate.get("context") or "")
    score = candidate.get("score")
    parts: list[str] = []
    if context and context.lower() not in label.lower():
        parts.append(context)
    if isinstance(score, (float, int)):
        parts.append(f"pertinence {score * 100:.0f} %")
    return f"{label} - {' · '.join(parts)}" if parts else label


def _project_map(latitude: float, longitude: float, address: str) -> folium.Map:
    map_object = folium.Map(
        location=[latitude, longitude],
        zoom_start=16,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.Marker(
        [latitude, longitude],
        tooltip=address or "Adresse du projet",
        popup=folium.Popup(f"<b>{address or 'Adresse du projet'}</b><br>{latitude:.6f}, {longitude:.6f}", max_width=280),
        icon=folium.Icon(color="red", icon="info-sign"),
    ).add_to(map_object)
    folium.Circle(
        [latitude, longitude],
        radius=35,
        color="#ef4444",
        fill=False,
        weight=2,
    ).add_to(map_object)
    return map_object


def _propagate_helionop_project_location() -> None:
    latitude = float(st.session_state.get("helionop_project_latitude", DEFAULT_PROJECT_LATITUDE))
    longitude = float(st.session_state.get("helionop_project_longitude", DEFAULT_PROJECT_LONGITUDE))
    address = str(st.session_state.get("helionop_project_address_label") or "")

    st.session_state["helionop_architectural_selected_address"] = address
    st.session_state["helionop_architectural_latitude"] = latitude
    st.session_state["helionop_architectural_longitude"] = longitude


def _initialise_helionop_project_location(site_default: SiteInputs, project_id: str) -> None:
    if st.session_state.get("helionop_project_location_project_id") == project_id:
        return
    st.session_state["helionop_project_location_project_id"] = project_id
    st.session_state["helionop_project_address_label"] = str(site_default.address or "")
    st.session_state["helionop_project_latitude"] = float(site_default.latitude or DEFAULT_PROJECT_LATITUDE)
    st.session_state["helionop_project_longitude"] = float(site_default.longitude or DEFAULT_PROJECT_LONGITUDE)
    _propagate_helionop_project_location()


def _restore_helionop_architectural_state(payload: dict[str, Any], project_id: str) -> None:
    if st.session_state.get("helionop_architectural_payload_project_id") == project_id:
        return
    st.session_state["helionop_architectural_payload_project_id"] = project_id
    saved = payload.get("architectural_constraints", {})
    if not isinstance(saved, dict):
        return
    if saved.get("selected_address") is not None:
        st.session_state["helionop_architectural_selected_address"] = str(saved.get("selected_address") or "")
    if saved.get("latitude") is not None:
        st.session_state["helionop_architectural_latitude"] = float(saved.get("latitude") or DEFAULT_PROJECT_LATITUDE)
    if saved.get("longitude") is not None:
        st.session_state["helionop_architectural_longitude"] = float(saved.get("longitude") or DEFAULT_PROJECT_LONGITUDE)
    if saved.get("project_type") in PROJECT_TYPES:
        st.session_state["helionop_architectural_project_type"] = str(saved.get("project_type"))
    result = saved.get("result")
    st.session_state["helionop_architectural_result"] = result if isinstance(result, dict) else None


def _current_helionop_architectural_payload() -> dict[str, Any]:
    return {
        "selected_address": str(st.session_state.get("helionop_architectural_selected_address") or ""),
        "latitude": float(st.session_state.get("helionop_architectural_latitude", DEFAULT_PROJECT_LATITUDE)),
        "longitude": float(st.session_state.get("helionop_architectural_longitude", DEFAULT_PROJECT_LONGITUDE)),
        "project_type": str(st.session_state.get("helionop_architectural_project_type") or PROJECT_TYPES[0]),
        "result": st.session_state.get("helionop_architectural_result"),
    }


def _render_project_location_form() -> tuple[str, float, float]:
    with st.form("helionop_project_address_form", clear_on_submit=False):
        address_query = st.text_input(
            "Adresse",
            placeholder="Ex. 10 rue de Strasbourg, 44000 Nantes",
            key="helionop_project_address_query",
        )
        search_submitted = st.form_submit_button("Rechercher l'adresse", width="stretch")

    if search_submitted:
        try:
            with st.spinner("Recherche dans la Base Adresse Nationale..."):
                st.session_state["helionop_project_address_candidates"] = _cached_project_address_search(address_query)
        except (GeocodingServiceError, ValueError) as exc:
            st.session_state["helionop_project_address_candidates"] = []
            st.error(str(exc))
        else:
            if not st.session_state["helionop_project_address_candidates"]:
                st.warning("Aucune adresse correspondante n'a été trouvée.")

    candidates = st.session_state.get("helionop_project_address_candidates", [])
    if candidates:
        selected_index = st.selectbox(
            "Adresse proposée",
            options=range(len(candidates)),
            format_func=lambda index: _candidate_label(candidates[index]),
            key="helionop_project_selected_address_candidate",
        )
        selected_candidate = candidates[int(selected_index)]
        if st.button("Utiliser cette adresse", width="stretch", key="helionop_project_use_selected_address"):
            st.session_state["helionop_project_latitude"] = float(selected_candidate["latitude"])
            st.session_state["helionop_project_longitude"] = float(selected_candidate["longitude"])
            st.session_state["helionop_project_address_label"] = str(selected_candidate["label"])
            st.session_state.pop("helionop_architectural_result", None)
            _propagate_helionop_project_location()
            st.rerun()

    latitude = float(st.session_state.get("helionop_project_latitude", DEFAULT_PROJECT_LATITUDE))
    longitude = float(st.session_state.get("helionop_project_longitude", DEFAULT_PROJECT_LONGITUDE))
    address = str(st.session_state.get("helionop_project_address_label") or "")
    if address:
        st.success(f"Adresse retenue : {address}")
        _propagate_helionop_project_location()
        map_state = st_folium(
            _project_map(latitude, longitude, address),
            height=360,
            width="stretch",
            returned_objects=["last_clicked"],
            key="helionop_project_address_map",
        )
        st.caption("Clique sur la carte pour déplacer le point exact du projet. Le test de contraintes architecturales utilisera ce point.")
        clicked = map_state.get("last_clicked") if isinstance(map_state, dict) else None
        if isinstance(clicked, dict) and clicked.get("lat") is not None and clicked.get("lng") is not None:
            clicked_latitude = float(clicked["lat"])
            clicked_longitude = float(clicked["lng"])
            if abs(clicked_latitude - latitude) > 1e-7 or abs(clicked_longitude - longitude) > 1e-7:
                st.session_state["helionop_project_latitude"] = clicked_latitude
                st.session_state["helionop_project_longitude"] = clicked_longitude
                st.session_state.pop("helionop_architectural_result", None)
                _propagate_helionop_project_location()
                st.rerun()
    else:
        st.info("Recherche une adresse pour alimenter automatiquement le test de contraintes architecturales.")

    return address, latitude, longitude


def _render_project_weather_selection(site_default: SiteInputs, project_ui_key: str) -> tuple[str, str]:
    region_names = list(DEFAULT_EPW_REGIONS.keys())
    default_region = site_default.weather_region if site_default.weather_region in DEFAULT_EPW_REGIONS else region_names[0]
    region_key = f"{project_ui_key}_nop_cold_weather_region"
    if st.session_state.get(region_key) not in region_names:
        st.session_state[region_key] = default_region

    region_name = st.selectbox(
        "Région météo",
        options=region_names,
        key=region_key,
    )

    station_labels = list(DEFAULT_EPW_REGIONS[region_name].keys())
    station_key = f"{project_ui_key}_nop_cold_weather_station"
    saved_station = WEATHER_STATION_LABEL_ALIASES.get(str(site_default.weather_station), str(site_default.weather_station))
    legacy_station = st.session_state.get(station_key)
    if legacy_station in WEATHER_STATION_LABEL_ALIASES:
        st.session_state[station_key] = WEATHER_STATION_LABEL_ALIASES[str(legacy_station)]
    if st.session_state.get(station_key) not in station_labels:
        st.session_state[station_key] = saved_station if saved_station in station_labels else station_labels[0]

    station_label = st.selectbox(
        "Station météo",
        options=station_labels,
        key=station_key,
    )
    st.caption("Cette station sert au calcul ESM2 de température d'eau froide dans l'onglet 2.")
    return str(region_name), str(station_label)


def eur(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f} €".replace(",", " ").replace(".", ",")


def eur_mwh(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f} €/MWh".replace(",", " ").replace(".", ",")


def number(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def parse_decimal(value: str) -> float | None:
    """Parse un nombre copié depuis Excel, avec virgule ou point décimal."""
    token = value.strip()
    if not token:
        return None
    token = token.replace("\u202f", " ").replace("\xa0", " ")
    token = re.sub(r"\s+", "", token)
    if "," in token and "." in token:
        # Format le plus courant en français : 1.234,56 ou 1 234,56.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    else:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def parse_pasted_numeric_values(text: str) -> list[float]:
    """Extrait des valeurs numériques depuis un collage Excel/LibreOffice.

    Formats acceptés :
    - une colonne de 12 valeurs ;
    - deux colonnes Mois + valeur ;
    - valeurs séparées par tabulation, point-virgule ou retour ligne.
    """
    values: list[float] = []
    header_words = (
        "mois",
        "conso",
        "consommation",
        "volume",
        "coefficient",
        "température",
        "temperature",
        "pertes",
        "perte",
        "facture",
        "facturée",
        "facturee",
        "nuitées",
        "nuitees",
        "l/j",
        "kwh",
        "mwh",
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(word in lower for word in header_words) and not any(month.lower() in lower for month in MONTH_NAMES):
            continue
        parts = [part.strip() for part in re.split(r"\t|;", line) if part.strip()]
        candidates: list[float] = []
        if len(parts) > 1:
            for part in parts:
                parsed = parse_decimal(part)
                if parsed is not None:
                    candidates.append(parsed)
        else:
            # Recherche les nombres dans la ligne. Compatible avec "Janvier 1 234,5".
            for match in re.finditer(r"[-+]?\d[\d\s\u202f\xa0.,]*", line):
                parsed = parse_decimal(match.group(0))
                if parsed is not None:
                    candidates.append(parsed)
        if candidates:
            # Si la ligne contient le mois puis la valeur, on retient la dernière valeur.
            values.append(candidates[-1])
    return values


def add_excel_paste_box(df: pd.DataFrame, value_column: str, key: str, label: str | None = None) -> pd.DataFrame:
    """Ajoute un bloc permettant de coller des valeurs Excel avant un data_editor.

    Important : ce composant n'utilise pas st.expander, car Streamlit interdit
    les expanders imbriqués. Il peut donc être appelé aussi bien dans une page
    simple que dans une section déjà repliable.
    """
    label = label or value_column
    st.markdown(f"**Coller des valeurs depuis Excel - {label}**")
    st.caption(
        "Colle soit une colonne de valeurs, soit deux colonnes Mois + valeur. "
        "Les 12 premières valeurs reconnues sont appliquées dans l'ordre des mois."
    )
    pasted = st.text_area(
        "Collage Excel / LibreOffice",
        key=f"{key}_paste_text",
        height=90,
        placeholder="Janvier\t1234\nFévrier\t1250\n...",
    )
    if st.button("Appliquer le collage", key=f"{key}_paste_button", width="stretch"):
        values = parse_pasted_numeric_values(pasted)
        if not values:
            st.warning("Aucune valeur numérique reconnue dans le collage.")
        else:
            updated = df.copy()
            count = min(len(updated), len(values))
            for idx, value in enumerate(values[:count]):
                updated.loc[idx, value_column] = value
            st.success(f"{count} valeur(s) appliquée(s) dans le tableau.")
            return updated
    return df


def _read_monthly_profile_upload(uploaded_file: Any, value_column: str) -> pd.DataFrame | None:
    if uploaded_file is None:
        return None
    raw = uploaded_file.getvalue()
    suffix = str(getattr(uploaded_file, "name", "")).lower()
    if suffix.endswith((".xlsx", ".xls")):
        df = pd.read_excel(BytesIO(raw))
    else:
        text = raw.decode("utf-8-sig", errors="ignore")
        df = pd.read_csv(StringIO(text), sep=None, engine="python")
    if df.empty:
        return None
    month_col = next((col for col in df.columns if str(col).strip().lower() in {"mois", "month"}), None)
    numeric_cols = [col for col in df.columns if col != month_col and pd.to_numeric(df[col], errors="coerce").notna().any()]
    if not numeric_cols:
        return None
    selected_col = numeric_cols[0]
    values_by_month: dict[str, float] = {}
    if month_col is not None:
        for _, row in df.iterrows():
            month_label = str(row.get(month_col, "")).strip()
            matched_month = next((month for month in MONTH_NAMES if month.lower() == month_label.lower()), None)
            if matched_month:
                raw_value = pd.to_numeric(row.get(selected_col), errors="coerce")
                values_by_month[matched_month] = 0.0 if pd.isna(raw_value) else float(max(0.0, raw_value))
    else:
        numeric_values = pd.to_numeric(df[selected_col], errors="coerce").dropna().tolist()
        for month, value in zip(MONTH_NAMES, numeric_values):
            values_by_month[month] = float(max(0.0, value))
    if not values_by_month:
        return None
    return pd.DataFrame(
        [
            {"Mois": month, value_column: float(values_by_month.get(month, 0.0))}
            for month in MONTH_NAMES
        ]
    )


def _value_to_daily_l_60c(
    *,
    value: float,
    input_mode: str,
    month: str,
    cold_water_temperature_c: float,
    ecs_temperature_c: float,
) -> float:
    value = max(0.0, float(value))
    days = DAYS_BY_MONTH[month]
    delta_t = max(1e-6, float(ecs_temperature_c) - float(cold_water_temperature_c))
    if input_mode == "Profil L/jour moyen":
        return value
    if input_mode == "Volume m³/mois":
        return value * 1000.0 / days
    if input_mode == "Consommation ECS MWh/mois":
        month_volume_l = value * 1000.0 * 1000.0 / (CP_WHLK * delta_t)
        return month_volume_l / days
    if input_mode == "Consommation ECS kWh/jour":
        return value * 1000.0 / (CP_WHLK * delta_t)
    return value


def _daily_l_to_monthly_mwh(
    *,
    daily_l_60c: float,
    month: str,
    cold_water_temperature_c: float,
    ecs_temperature_c: float,
) -> float:
    delta_t = max(0.0, float(ecs_temperature_c) - float(cold_water_temperature_c))
    return max(0.0, daily_l_60c) * DAYS_BY_MONTH[month] * CP_WHLK * delta_t / 1000.0 / 1000.0


def _daily_l_to_daily_kwh(*, daily_l_60c: float, cold_water_temperature_c: float, ecs_temperature_c: float) -> float:
    delta_t = max(0.0, float(ecs_temperature_c) - float(cold_water_temperature_c))
    return max(0.0, daily_l_60c) * CP_WHLK * delta_t / 1000.0


def _monthly_air_temperatures_from_station(region_name: str, station_label: str) -> dict[str, float]:
    station_label = WEATHER_STATION_LABEL_ALIASES.get(station_label, station_label)
    station = DEFAULT_EPW_REGIONS.get(region_name, {}).get(station_label)
    if station is None or not station.path.exists():
        return {month: 12.0 for month in MONTH_NAMES}
    _location, hourly_weather = read_epw_hourly_weather_from_zip(
        station.path,
        tilt_deg=35.0,
        azimuth_deg_south=0.0,
        albedo=0.2,
    )
    rows = [{"Mois": MONTH_NAMES[item.month - 1], "Tair": float(item.tair_c)} for item in hourly_weather if 1 <= item.month <= 12]
    if not rows:
        return {month: 12.0 for month in MONTH_NAMES}
    df = pd.DataFrame(rows)
    means = df.groupby("Mois")["Tair"].mean().to_dict()
    return {month: float(means.get(month, 12.0)) for month in MONTH_NAMES}


def _esm2_cold_water_temperatures(monthly_air_temperatures_c: dict[str, float], offset_c: float = 0.0) -> dict[str, float]:
    annual_mean = sum(monthly_air_temperatures_c.get(month, 12.0) for month in MONTH_NAMES) / 12.0
    return {
        month: min(25.0, max(5.0, 0.6 * annual_mean + 0.4 * monthly_air_temperatures_c.get(month, annual_mean) + offset_c))
        for month in MONTH_NAMES
    }


def percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{100 * value:.{digits}f} %".replace(".", ",")


def slugify(text: str) -> str:
    return safe_slug(text)


def current_owner_email() -> str:
    user = st.session_state.get("user")
    if isinstance(user, dict):
        return normalize_email(str(user.get("email", "")))
    return ""


def empty_project_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app_key": APP_KEY,
        "app_label": APP_LABEL,
        "project_id": str(uuid.uuid4()),
        "name": "Nouveau projet",
        "owner_email": current_owner_email(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "site": asdict(SiteInputs()),
        "needs": asdict(NeedsInputs()),
        "sizing": asdict(SizingInputs()),
        "loop": asdict(LoopInputs()),
        "economic": {},
    }


def _backup_projects_path_setting() -> str:
    return (
        ui_portal._secret_value("GITHUB_BACKUP_HELIONOP_PROJECTS_PATH")
        or ui_portal._secret_value("GITHUB_BACKUP_PROJECTS_PATH_HELIONOP")
        or DEFAULT_BACKUP_PROJECTS_PATH
    )


def _resolve_backup_projects_path():
    configured = Path(_backup_projects_path_setting())
    if configured.is_absolute():
        return configured
    candidates = [
        Path.cwd() / configured,
        Path(__file__).resolve().parents[2] / configured,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _project_backup_slug(project: dict[str, Any]) -> str:
    slug = str(project.get("slug", "") or "").strip()
    if slug:
        return safe_slug(slug, fallback="projet_helionop")
    owner = safe_slug(str(project.get("owner_email", "") or "anonymous"), fallback="anonymous")
    project_id = str(project.get("project_id", "") or "")[:8]
    name = safe_slug(str(project.get("name", "") or "Projet HelioNOP"), fallback="projet_helionop")
    suffix = f"_{project_id}" if project_id else ""
    return f"{owner}_{name}{suffix}"[:120]


def _load_project_backups() -> list[dict[str, Any]]:
    cached = st.session_state.get(PROJECTS_SESSION_CACHE_KEY)
    if isinstance(cached, list):
        return [dict(project) for project in cached if isinstance(project, dict)]

    github_projects = ui_portal._github_read_json_list(_backup_projects_path_setting())
    if github_projects:
        ui_portal._write_json_list(_resolve_backup_projects_path(), github_projects)
        st.session_state[PROJECTS_SESSION_CACHE_KEY] = github_projects
        return github_projects

    projects = ui_portal._read_json_list(_resolve_backup_projects_path())
    if projects:
        st.session_state[PROJECTS_SESSION_CACHE_KEY] = projects
    return projects


def _save_project_backups(projects: list[dict[str, Any]]) -> None:
    clean_projects = [dict(project) for project in projects if isinstance(project, dict)]
    st.session_state[PROJECTS_SESSION_CACHE_KEY] = clean_projects
    ui_portal._write_json_list(_resolve_backup_projects_path(), clean_projects)
    ui_portal._github_write_json_list(
        _backup_projects_path_setting(),
        clean_projects,
        message="chore: update helionop projects backup",
    )


def _restore_projects_from_backup() -> None:
    for project in _load_project_backups():
        payload = dict(project.get("payload", project)) if isinstance(project, dict) else {}
        if not payload or str(payload.get("app_key", APP_KEY)) != APP_KEY:
            continue
        owner_email = normalize_email(str(payload.get("owner_email", "")))
        if not owner_email:
            continue
        project_id = str(payload.get("project_id", "") or uuid.uuid4())
        name = str(payload.get("name") or payload.get("site", {}).get("project_name") or "Projet HelioNOP")
        PROJECT_STORE.ensure_owner_dir(owner_email)
        path = PROJECT_STORE.project_path(owner_email=owner_email, project_id=project_id, project_name=name)
        if not path.exists():
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _upsert_project_backup(*, path, payload: dict[str, Any]) -> None:
    backup_item = {
        "slug": path.with_suffix("").name,
        "saved_at": now_iso(),
        "owner_email": payload.get("owner_email", ""),
        "project_id": payload.get("project_id", ""),
        "name": payload.get("name", path.stem),
        "payload": payload,
    }
    slug = _project_backup_slug(backup_item)
    projects = [project for project in _load_project_backups() if _project_backup_slug(project) != slug]
    projects.append(backup_item)
    _save_project_backups(projects)


def list_project_files():
    _restore_projects_from_backup()
    return PROJECT_STORE.list_projects(owner_email=current_owner_email())


def load_project(path) -> dict[str, Any]:
    return PROJECT_STORE.load_project(path=path, owner_email=current_owner_email())


def save_project(payload: dict[str, Any]):
    payload = dict(payload)
    site = payload.get("site", {}) if isinstance(payload.get("site"), dict) else {}
    project_name = str(site.get("project_name") or payload.get("name") or "Nouveau projet")
    path = PROJECT_STORE.save_project(
        payload=payload,
        owner_email=current_owner_email(),
        project_name=project_name,
        project_id=str(payload.get("project_id", "")) or None,
    )
    saved_payload = PROJECT_STORE.load_project(path=path, owner_email=current_owner_email())
    _upsert_project_backup(path=path, payload=saved_payload)
    return path


def _project_label(project_file) -> str:
    try:
        data = project_file.payload
        site = data.get("site", {})
        name = site.get("project_name") or data.get("name") or project_file.name
        airtable_id = site.get("airtable_id", "")
        updated = data.get("updated_at", "") or project_file.updated_at
        label = f"{name}"
        if airtable_id:
            label += f" | Airtable {airtable_id}"
        if updated:
            label += f" - {updated}"
        return label
    except Exception:
        return project_file.path.stem


def _project_options() -> tuple[list[str], dict[str, Any]]:
    labels: list[str] = []
    paths_by_label: dict[str, Any] = {}
    for project_file in list_project_files():
        base_label = _project_label(project_file)
        label = base_label
        if label in paths_by_label:
            label = f"{base_label} ({project_file.path.stem[-8:]})"
        labels.append(label)
        paths_by_label[label] = project_file.path
    return labels, paths_by_label


def render_project_load_save_bar() -> None:
    if "save_notice" in st.session_state:
        st.success(st.session_state.pop("save_notice"))

    project_labels, project_by_label = _project_options()
    select_col, load_col, new_col, save_col = st.columns([5, 1, 1, 1])
    selected_project_label = select_col.selectbox(
        "Projet enregistré",
        options=["-"] + project_labels,
        index=0,
        key="helionop_project_selector",
        label_visibility="collapsed",
    )
    with load_col:
        if st.button("Charger", width="stretch", disabled=selected_project_label == "-"):
            loaded_payload = load_project(project_by_label[selected_project_label])
            loaded_project_key = str(loaded_payload.get("project_id", "projet"))[:8]
            st.session_state.pop(f"{loaded_project_key}_cold_water_mode", None)
            st.session_state.project_payload = loaded_payload
            st.rerun()
    with new_col:
        if st.button("Nouveau", width="stretch"):
            new_payload = empty_project_payload()
            new_project_key = str(new_payload.get("project_id", "projet"))[:8]
            st.session_state.pop(f"{new_project_key}_cold_water_mode", None)
            st.session_state.project_payload = new_payload
            st.rerun()
    with save_col:
        if st.button("Enregistrer", type="primary", width="stretch"):
            st.session_state.helionop_save_requested = True



def init_session() -> None:
    if "project_payload" not in st.session_state:
        st.session_state.project_payload = empty_project_payload()


def monthly_needs_dataframe(results) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Mois": row.month,
                "Volume ECS (L/mois)": row.volume_l_60c,
                "Volume moyen (L/j)": row.average_l_day_60c,
                "Tef (°C)": row.cold_water_temperature_c,
                "Besoin utile (MWh)": row.useful_energy_mwh,
                "Bouclage sanitaire (MWh)": row.loop_losses_mwh,
                "Chauffage estimé (MWh)": row.heating_after_boiler_mwh,
                "Besoin total ECS + bouclage (MWh)": row.total_ecs_energy_mwh,
            }
            for row in results.monthly_needs
        ]
    )


def loop_dataframe(results) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Mois": row.month,
                "Jours": row.days,
                "Conso gaz facturée (kWh/mois)": row.gas_consumption_kwh,
                "Facture gaz talon estimée (kWh/mois)": row.gas_baseload_kwh,
                "Énergie ECS globale après rendement chaudière (kWh/mois)": row.global_ecs_after_boiler_kwh,
                "Besoin utile ECS (kWh/j)": row.useful_energy_kwh / row.days if row.days else 0.0,
                "Besoin utile ECS (kWh/mois)": row.useful_energy_kwh,
                "Bouclage sanitaire estimé (kWh/j)": row.loop_losses_kwh / row.days if row.days else 0.0,
                "Bouclage sanitaire estimé (kWh/mois)": row.loop_losses_kwh,
                "Chauffage estimé après rendement chaudière (kWh/mois)": row.heating_after_boiler_kwh,
            }
            for row in results.monthly_needs
        ]
    )


def render_monthly_needs_chart(results):
    if go is None:
        return None
    rows = list(results.monthly_needs)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.average_l_day_60c for row in rows],
            name="Volume moyen ECS",
            hovertemplate="%{x}<br>%{y:,.0f} L/j<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[row.month for row in rows],
            y=[row.useful_energy_mwh for row in rows],
            name="Besoin utile ECS",
            mode="lines+markers",
            yaxis="y2",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[row.month for row in rows],
            y=[row.total_ecs_energy_mwh for row in rows],
            name="ECS + bouclage",
            mode="lines+markers",
            yaxis="y2",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.update_layout(
        height=420,
        margin={"l": 10, "r": 20, "t": 45, "b": 40},
        xaxis_title="Mois",
        yaxis={"title": "Volume moyen (L/j)"},
        yaxis2={"title": "Énergie (MWh/mois)", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
    )
    return fig


def render_loop_chart(results):
    if go is None:
        return None
    rows = list(results.monthly_needs)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.useful_energy_mwh for row in rows],
            name="Besoin utile ECS",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.loop_losses_mwh for row in rows],
            name="Bouclage sanitaire",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.heating_after_boiler_mwh for row in rows],
            name="Chauffage estimé",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.update_layout(
        barmode="stack",
        height=360,
        margin={"l": 10, "r": 20, "t": 45, "b": 40},
        xaxis_title="Mois",
        yaxis_title="Besoin énergétique (MWh/mois)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
    )
    return fig


def render_ecs_loop_pie_chart(results):
    if go is None:
        return None
    useful = max(0.0, float(results.annual_useful_energy_mwh or 0.0))
    loop = max(0.0, float(results.annual_loop_losses_mwh or 0.0))
    if useful + loop <= 0 or loop <= 0:
        return None
    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Besoin utile ECS", "Bouclage sanitaire"],
                values=[useful, loop],
                hole=0.35,
                sort=False,
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.1f} MWh/an<br>%{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title="Répartition annuelle ECS utile / bouclage",
        height=340,
        margin={"l": 10, "r": 20, "t": 55, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.05, "xanchor": "center", "x": 0.5},
    )
    return fig


def render_ecs_loop_heating_pie_chart(results):
    if go is None:
        return None
    useful = max(0.0, float(results.annual_useful_energy_mwh or 0.0))
    loop = max(0.0, float(results.annual_loop_losses_mwh or 0.0))
    heating = max(0.0, float(results.annual_heating_after_boiler_mwh or 0.0))
    if useful + loop + heating <= 0 or loop <= 0 or heating <= 0:
        return None
    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Besoin utile ECS", "Bouclage sanitaire", "Chauffage estimé"],
                values=[useful, loop, heating],
                hole=0.35,
                sort=False,
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.1f} MWh/an<br>%{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title="Répartition annuelle ECS utile / bouclage / chauffage",
        height=340,
        margin={"l": 10, "r": 20, "t": 55, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.05, "xanchor": "center", "x": 0.5},
    )
    return fig


def build_heat_cost_breakdown_rows(results) -> list[dict[str, float | str]]:
    return [
        {"Poste": "P1' - Auxiliaires électriques", "Famille": "P1'", "Coût chaleur (€/MWh)": results.heat_cost_p1_eur_mwh or 0.0},
        {"Poste": "P2 - Suivi et maintenance", "Famille": "P2", "Coût chaleur (€/MWh)": results.heat_cost_p2_eur_mwh or 0.0},
        {"Poste": "P4 - Investissement net aidé", "Famille": "P4", "Coût chaleur (€/MWh)": results.heat_cost_p4_eur_mwh or 0.0},
    ]


def render_heat_cost_breakdown_plotly(results):
    if go is None:
        return None
    rows = build_heat_cost_breakdown_rows(results)
    total_cost = results.solar_heat_cost_eur_mwh
    reference_cost = results.average_reference_energy_cost_eur_mwh
    y_max = max(total_cost, reference_cost, 1.0) * 1.25
    fig = go.Figure()
    for row in rows:
        value = float(row["Coût chaleur (€/MWh)"])
        fig.add_trace(
            go.Bar(
                x=["Coût chaleur solaire"],
                y=[value],
                name=str(row["Poste"]),
                text=[f"{value:.1f} €/MWh"],
                textposition="inside",
                hovertemplate="%{fullData.name}<br>%{y:.1f} €/MWh<extra></extra>",
            )
        )
    fig.add_hline(
        y=reference_cost,
        line_dash="dash",
        annotation_text=f"Référence moyenne : {reference_cost:.1f} €/MWh",
        annotation_position="top right",
    )
    fig.update_layout(
        barmode="stack",
        height=560,
        margin={"l": 58, "r": 8, "t": 82, "b": 32},
        legend={"orientation": "v", "yanchor": "top", "y": 1.18, "xanchor": "left", "x": 0},
        xaxis_title=None,
        yaxis_title="Coût de la chaleur (€/MWh utile)",
    )
    fig.update_xaxes(showticklabels=False)
    fig.update_yaxes(range=[0, y_max], ticksuffix=" €/MWh")
    return fig


def first_positive_year(rows: list[dict[str, float | int]], cumulative_key: str) -> int | None:
    for row in rows:
        if float(row[cumulative_key]) >= 0:
            return int(row["Année"])
    return None


def render_cumulative_cashflow_plotly(cashflow_rows: list[dict[str, float | int]]):
    if go is None:
        return None
    years = [int(row["Année"]) for row in cashflow_rows]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[float(row["Flux cumulé moyen (€)"]) for row in cashflow_rows],
            name="Flux cumulé moyen/lissé",
            mode="lines+markers",
            hovertemplate="Année %{x}<br>%{y:,.0f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[float(row["Flux cumulé inflation annuelle (€)"]) for row in cashflow_rows],
            name="Flux cumulé avec inflation annuelle",
            mode="lines+markers",
            hovertemplate="Année %{x}<br>%{y:,.0f} €<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dash", annotation_text="Retour à zéro", annotation_position="bottom right")
    payback_avg = first_positive_year(cashflow_rows, "Flux cumulé moyen (€)")
    payback_inflation = first_positive_year(cashflow_rows, "Flux cumulé inflation annuelle (€)")
    if payback_avg is not None:
        fig.add_vline(x=payback_avg, line_dash="dot", annotation_text=f"Retour moyen : {payback_avg} ans")
    if payback_inflation is not None and payback_inflation != payback_avg:
        fig.add_vline(x=payback_inflation, line_dash="dot", annotation_text=f"Retour inflation : {payback_inflation} ans")
    fig.update_layout(
        height=390,
        margin={"l": 10, "r": 20, "t": 45, "b": 40},
        xaxis_title="Année",
        yaxis_title="Flux cumulé (€)",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    )
    fig.update_yaxes(ticksuffix=" €")
    return fig


def render_opportunity_notes_app() -> None:
    init_session()
    
    st.title("Note d'opportunité solaire thermique")
    st.caption(
        "Version de travail : estimation ECS, bouclage sanitaire, prédimensionnement CESC et raccord au modèle économique. "
        "La productivité est fixée par défaut à 500 kWh/m².an avant branchement du moteur SOLO 2018."
    )
    render_project_load_save_bar()
    
    payload = st.session_state.project_payload
    site_default = dict_to_site_inputs(payload.get("site"))
    needs_default = dict_to_needs_inputs(payload.get("needs"))
    sizing_default = dict_to_sizing_inputs(payload.get("sizing"))
    loop_default = dict_to_loop_inputs(payload.get("loop"))
    economic_default = payload.get("economic", {}) or {}
    project_ui_key = str(payload.get("project_id", "projet"))[:8]
    _initialise_helionop_project_location(site_default, str(payload.get("project_id", "projet")))
    _restore_helionop_architectural_state(payload, str(payload.get("project_id", "projet")))
    
    # ---------------------------------------------------------------------------
    # Onglets de saisie et résultats.
    # ---------------------------------------------------------------------------
    tab_site, tab_energy, tab_needs, tab_loop, tab_sizing, tab_architecture, tab_economics, tab_export = st.tabs(
        [
            "1. Projet",
            "2. Eau froide",
            "3. Besoins ECS",
            "4. Bouclage sanitaire",
            "5. Prédimensionnement",
            "6. Contraintes architecturales",
            "7. Économie",
            "8. Synthèse / export",
        ]
    )

    housing_counts = dict(needs_default.housing_counts)
    housing_ratios = dict(needs_default.housing_ratios_l_day)
    residents_or_beds = needs_default.residents_or_beds
    liters_per_resident_or_bed_day = needs_default.liters_per_resident_or_bed_day
    monthly_occupancy = dict(needs_default.monthly_occupancy)
    liters_per_occupied_unit = needs_default.liters_per_occupied_unit
    hotel_category = needs_default.hotel_category
    car_wash_vehicles_per_day = needs_default.car_wash_vehicles_per_day
    car_wash_liters_per_vehicle = needs_default.car_wash_liters_per_vehicle
    measured_daily = dict(needs_default.measured_daily_l_60c_by_month)
    monthly_coefficients = dict(needs_default.monthly_coefficients)
    
    with tab_site:
        st.subheader("Caractéristiques du site")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            project_name = st.text_input("Nom du projet", value=site_default.project_name)
            airtable_id = st.text_input("ID Airtable", value=site_default.airtable_id)
        with col_b:
            client_name = st.text_input("Maître d'ouvrage / client", value=site_default.client_name)
            city = st.text_input("Commune", value=site_default.city)
        with col_c:
            typology = st.selectbox(
                "Typologie d'établissement",
                options=list(SITE_TYPOLOGIES),
                index=list(SITE_TYPOLOGIES).index(site_default.typology) if site_default.typology in SITE_TYPOLOGIES else 0,
            )
            building_state = st.radio(
                "Nature du bâtiment",
                options=list(BUILDING_STATES),
                index=list(BUILDING_STATES).index(site_default.building_state)
                if site_default.building_state in BUILDING_STATES
                else 0,
            )
    
        data_source = st.radio(
            "Mode de détermination de la consommation ECS journalière",
            options=list(DATA_SOURCES),
            index=list(DATA_SOURCES).index(site_default.data_source) if site_default.data_source in DATA_SOURCES else 0,
            horizontal=True,
        )
        if typology == "Station de lavage" and data_source != "Mesure de consommation ECS":
            st.info(
                "Station de lavage : aucun ratio SOCOL standard n'est appliqué. "
                "Renseigne un profil mesuré ou estimé dans l'onglet Besoins ECS."
            )
            data_source = "Mesure de consommation ECS"
    
        if building_state == "Bâtiment existant" and data_source != "Mesure de consommation ECS":
            st.warning(
                "Bâtiment existant : comptage ECS obligatoire / fortement attendu pour fiabiliser la note d'opportunité. "
                "Les ratios SOCOL peuvent servir à une première approche mais doivent être confrontés à des mesures."
            )
        if data_source == "Mesure de consommation ECS":
            st.markdown("### Unité de référence")
            st.caption(
                "Cette unité ne recalcule pas la consommation mesurée. Elle sert à exprimer le besoin ECS par unité "
                "et à alimenter les hypothèses de bouclage."
            )
            if typology == "Logement collectif":
                housing_unit_rows = pd.DataFrame(
                    [
                        {"Typologie": kind, "Nombre": int(housing_counts.get(kind, 0))}
                        for kind in HOUSING_RATIOS_L_PER_DWELLING_DAY
                    ]
                )
                edited_housing_units = st.data_editor(
                    housing_unit_rows,
                    hide_index=True,
                    width="stretch",
                    disabled=["Typologie"],
                    key=f"{project_ui_key}_project_housing_units_editor",
                )
                housing_counts = {
                    str(row["Typologie"]): int(max(0, row["Nombre"])) for _, row in edited_housing_units.iterrows()
                }
            elif typology in {"EHPAD", "Hôpital"}:
                residents_or_beds = st.number_input(
                    "Nombre de résidents / lits",
                    min_value=0,
                    value=int(residents_or_beds),
                    step=1,
                    key=f"{project_ui_key}_project_residents_or_beds",
                )
            elif typology == "Hôtel":
                st.caption("Renseigner les nuitées chambres si elles sont disponibles.")
                occupancy_rows = pd.DataFrame(
                    [{"Mois": month, "Nuitées chambres": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
                )
                edited_occupancy = st.data_editor(
                    occupancy_rows,
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    key=f"{project_ui_key}_project_hotel_occupancy_editor",
                )
                monthly_occupancy = {
                    str(row["Mois"]): float(max(0.0, row["Nuitées chambres"])) for _, row in edited_occupancy.iterrows()
                }
            elif typology == "Camping":
                st.caption("Renseigner les personnes-nuitées si elles sont disponibles.")
                occupancy_rows = pd.DataFrame(
                    [{"Mois": month, "Personnes-nuitées": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
                )
                edited_occupancy = st.data_editor(
                    occupancy_rows,
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    key=f"{project_ui_key}_project_camping_occupancy_editor",
                )
                monthly_occupancy = {
                    str(row["Mois"]): float(max(0.0, row["Personnes-nuitées"])) for _, row in edited_occupancy.iterrows()
                }
            elif typology == "Station de lavage":
                car_wash_vehicles_per_day = st.number_input(
                    "Nombre de véhicules lavés par jour",
                    min_value=0.0,
                    value=float(car_wash_vehicles_per_day),
                    step=1.0,
                    key=f"{project_ui_key}_project_car_wash_vehicles_per_day",
                    help="Cette valeur sert à exprimer la consommation ECS équivalente en L/véhicule à 60 °C.",
                )
        st.markdown("### Localisation")
        st.caption(
            "L'adresse du projet est utilisée par l'onglet Contraintes architecturales. "
            "Le point peut être ajusté manuellement en cliquant sur la carte."
        )
        address, latitude, longitude = _render_project_location_form()

        st.markdown("### Station météo")
        weather_region, weather_station = _render_project_weather_selection(site_default, project_ui_key)
    
    site_inputs = SiteInputs(
        project_name=project_name,
        airtable_id=airtable_id,
        client_name=client_name,
        city=city,
        address=address,
        latitude=latitude,
        longitude=longitude,
        weather_region=weather_region,
        weather_station=weather_station,
        typology=typology,
        building_state=building_state,
        data_source=data_source,
    )

    # ---------------------------------------------------------------------------
    # Eau froide et paramètres de prédimensionnement.
    # ---------------------------------------------------------------------------
    cold_water_temperatures = dict(sizing_default.cold_water_temperatures_c)
    with tab_energy:
        st.subheader("Température d'eau froide")
        cold_water_mode_default = (
            sizing_default.cold_water_mode
            if sizing_default.cold_water_mode in COLD_WATER_MODES
            else "Température eau froide manuelle"
        )
        cold_water_mode = st.radio(
            "Mode de calcul de la température d'eau froide",
            options=list(COLD_WATER_MODES),
            index=list(COLD_WATER_MODES).index(cold_water_mode_default),
            horizontal=True,
            key=f"{project_ui_key}_cold_water_mode",
        )
        if cold_water_mode == "Température eau froide manuelle":
            st.caption("Saisir une température moyenne mensuelle d'eau froide.")
            tef_rows = pd.DataFrame(
                [
                    {"Mois": month, "Température eau froide (°C)": float(cold_water_temperatures.get(month, 15.0))}
                    for month in MONTH_NAMES
                ]
            )
            edited_tef = st.data_editor(
                tef_rows,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_ui_key}_cold_water_editor",
            )
            cold_water_temperatures = {
                str(row["Mois"]): float(row["Température eau froide (°C)"]) for _, row in edited_tef.iterrows()
            }
        else:
            station_col, info_col = st.columns(2)
            with station_col:
                region_name = site_inputs.weather_region
                station_label = site_inputs.weather_station
                st.write(f"**Région météo :** {region_name}")
                st.write(f"**Station météo :** {station_label}")
                st.caption("La région et la station météo se règlent dans l'onglet 1. Projet.")
            monthly_air = _monthly_air_temperatures_from_station(region_name, station_label)
            cold_water_temperatures = _esm2_cold_water_temperatures(
                monthly_air,
                offset_c=3.0 if cold_water_mode == "Méthode ESM2 + 3 °C" else 0.0,
            )
            with info_col:
                st.info(
                    "La méthode ESM2 estime l'eau froide à partir des températures extérieures mensuelles "
                    "de la station EPW sélectionnée. La variante + 3 °C ajoute une marge si le réseau ou le "
                    "local technique est plus tempéré."
                )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Mois": month,
                            "Température extérieure moyenne (°C)": monthly_air[month],
                            "Température eau froide retenue (°C)": cold_water_temperatures[month],
                        }
                        for month in MONTH_NAMES
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    # ---------------------------------------------------------------------------
    # Besoins ECS.
    # ---------------------------------------------------------------------------
    with tab_needs:
        st.subheader("Estimation des volumes ECS")
        ecs_temperature_c = st.number_input(
            "Température ECS de référence (°C)",
            min_value=30.0,
            max_value=90.0,
            value=float(needs_default.ecs_temperature_c or 60.0),
            step=1.0,
            key=f"{project_ui_key}_ecs_temperature_c",
            help="Température de livraison ECS utilisée pour convertir les volumes en énergie utile. 60 °C reste la valeur par défaut.",
        )
        ecs_temperature_label = f"{number(ecs_temperature_c, 0)} °C"
    
        if data_source == "Mesure de consommation ECS":
            st.markdown("**Saisie d'une consommation ECS mesurée ou estimée**")
            st.caption(
                "Importer un profil mensuel ou saisir les valeurs dans le tableau. "
                f"Le calcul convertit automatiquement vers un volume ECS équivalent à {ecs_temperature_label}."
            )
            ecs_input_mode = st.radio(
                "Format du profil ECS",
                options=list(ECS_PROFILE_INPUT_MODES),
                horizontal=True,
                key=f"{project_ui_key}_ecs_profile_input_mode",
            )
            input_col = {
                "Profil L/jour moyen": f"Profil ECS {ecs_temperature_label} (L/jour moyen)",
                "Volume m³/mois": f"Volume ECS {ecs_temperature_label} (m³/mois)",
                "Consommation ECS MWh/mois": "Consommation ECS utile (MWh/mois)",
                "Consommation ECS kWh/jour": "Consommation ECS utile (kWh/jour)",
            }[ecs_input_mode]
            default_values = []
            for month in MONTH_NAMES:
                daily_l = float(measured_daily.get(month, 0.0))
                if ecs_input_mode == "Profil L/jour moyen":
                    value = daily_l
                elif ecs_input_mode == "Volume m³/mois":
                    value = daily_l * DAYS_BY_MONTH[month] / 1000.0
                elif ecs_input_mode == "Consommation ECS MWh/mois":
                    value = _daily_l_to_monthly_mwh(
                        daily_l_60c=daily_l,
                        month=month,
                        cold_water_temperature_c=cold_water_temperatures.get(month, 15.0),
                        ecs_temperature_c=ecs_temperature_c,
                    )
                else:
                    value = _daily_l_to_daily_kwh(
                        daily_l_60c=daily_l,
                        cold_water_temperature_c=cold_water_temperatures.get(month, 15.0),
                        ecs_temperature_c=ecs_temperature_c,
                    )
                default_values.append({"Mois": month, input_col: float(value)})

            uploaded_profile = st.file_uploader(
                "Importer un profil ECS mensuel",
                type=["xlsx", "xls", "csv"],
                key=f"{project_ui_key}_ecs_profile_upload",
                help="Fichier avec 12 lignes. Une colonne 'Mois' est optionnelle ; la première colonne numérique est utilisée.",
            )
            imported_rows = _read_monthly_profile_upload(uploaded_profile, input_col)
            measured_rows = imported_rows if imported_rows is not None else pd.DataFrame(default_values)
            edited_measured = st.data_editor(
                measured_rows,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_ui_key}_measured_daily_editor",
            )
            measured_daily = {}
            conversion_rows = []
            for _, row in edited_measured.iterrows():
                month = str(row["Mois"])
                daily_l = _value_to_daily_l_60c(
                    value=float(max(0.0, row[input_col])),
                    input_mode=ecs_input_mode,
                    month=month,
                    cold_water_temperature_c=cold_water_temperatures.get(month, 15.0),
                    ecs_temperature_c=ecs_temperature_c,
                )
                measured_daily[month] = daily_l
                conversion_rows.append(
                    {
                        "Mois": month,
                        f"Volume équivalent ECS {ecs_temperature_label} (L/j)": daily_l,
                        f"Volume équivalent ECS {ecs_temperature_label} (m³/mois)": daily_l * DAYS_BY_MONTH[month] / 1000.0,
                        "Besoin utile ECS (kWh/j)": _daily_l_to_daily_kwh(
                            daily_l_60c=daily_l,
                            cold_water_temperature_c=cold_water_temperatures.get(month, 15.0),
                            ecs_temperature_c=ecs_temperature_c,
                        ),
                        "Besoin utile ECS (MWh/mois)": _daily_l_to_monthly_mwh(
                            daily_l_60c=daily_l,
                            month=month,
                            cold_water_temperature_c=cold_water_temperatures.get(month, 15.0),
                            ecs_temperature_c=ecs_temperature_c,
                        ),
                    }
                )
            st.markdown("**Conversions utilisées par le calcul**")
            st.dataframe(pd.DataFrame(conversion_rows), hide_index=True, width="stretch")
    
        elif typology == "Logement collectif":
            st.markdown("**Approche détaillée par typologie de logements**")
            housing_rows = pd.DataFrame(
                [
                    {
                        "Typologie": kind,
                        "Nombre": int(housing_counts.get(kind, 0)),
                        f"L/logement/j à {ecs_temperature_label}": float(housing_ratios.get(kind, default_ratio)),
                    }
                    for kind, default_ratio in HOUSING_RATIOS_L_PER_DWELLING_DAY.items()
                ]
            )
            edited_housing = st.data_editor(
                housing_rows,
                hide_index=True,
                width="stretch",
                disabled=["Typologie"],
                key=f"{project_ui_key}_housing_editor",
            )
            housing_counts = {str(row["Typologie"]): int(max(0, row["Nombre"])) for _, row in edited_housing.iterrows()}
            housing_ratios = {
                str(row["Typologie"]): float(max(0.0, row[f"L/logement/j à {ecs_temperature_label}"]))
                for _, row in edited_housing.iterrows()
            }
    
        elif typology in {"EHPAD", "Hôpital"}:
            if typology == "Hôpital" and (
                site_default.typology != "Hôpital" or liters_per_resident_or_bed_day == EHPAD_DEFAULT_L_PER_RESIDENT_DAY
            ):
                default_ratio = HOSPITAL_DEFAULT_L_PER_BED_DAY
            elif typology == "EHPAD" and (
                site_default.typology != "EHPAD" or liters_per_resident_or_bed_day == HOSPITAL_DEFAULT_L_PER_BED_DAY
            ):
                default_ratio = EHPAD_DEFAULT_L_PER_RESIDENT_DAY
            else:
                default_ratio = liters_per_resident_or_bed_day
            col_a, col_b = st.columns(2)
            with col_a:
                residents_or_beds = st.number_input("Nombre de résidents / lits", min_value=0, value=int(residents_or_beds), step=1)
            with col_b:
                liters_per_resident_or_bed_day = st.number_input(
                    f"Conso ECS à {ecs_temperature_label} (L/résident ou lit/j)", min_value=0.0, value=float(default_ratio), step=1.0
                )
    
        elif typology == "Hôtel":
            col_a, col_b = st.columns(2)
            with col_a:
                hotel_category = st.selectbox(
                    "Catégorie hôtel",
                    options=list(HOTEL_RATIOS_L_PER_ROOM_NIGHT),
                    index=list(HOTEL_RATIOS_L_PER_ROOM_NIGHT).index(hotel_category)
                    if hotel_category in HOTEL_RATIOS_L_PER_ROOM_NIGHT
                    else 1,
                )
            with col_b:
                default_hotel_ratio = HOTEL_RATIOS_L_PER_ROOM_NIGHT[hotel_category]
                liters_per_occupied_unit = st.number_input(
                    f"Conso ECS à {ecs_temperature_label} (L/chambre-nuit)",
                    min_value=0.0,
                    value=float(liters_per_occupied_unit or default_hotel_ratio),
                    step=1.0,
                )
                st.caption(f"Valeur SOCOL proposée pour cette catégorie : {default_hotel_ratio:.0f} L/chambre-nuit.")
    
            occupancy_rows = pd.DataFrame(
                [{"Mois": month, "Nuitées chambres": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
            )
            edited_occupancy = st.data_editor(
                occupancy_rows,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_ui_key}_hotel_occupancy_editor",
            )
            monthly_occupancy = {
                str(row["Mois"]): float(max(0.0, row["Nuitées chambres"])) for _, row in edited_occupancy.iterrows()
            }
    
        elif typology == "Camping":
            liters_per_occupied_unit = st.number_input(
                f"Conso ECS à {ecs_temperature_label} (L/personne-nuitée)",
                min_value=0.0,
                value=float(liters_per_occupied_unit or CAMPING_DEFAULT_L_PER_PERSON_NIGHT),
                step=1.0,
            )
            st.caption(f"Valeur proposée par défaut : {CAMPING_DEFAULT_L_PER_PERSON_NIGHT:.0f} L/personne-nuitée.")
            occupancy_rows = pd.DataFrame(
                [{"Mois": month, "Personnes-nuitées": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
            )
            edited_occupancy = st.data_editor(
                occupancy_rows,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_ui_key}_camping_occupancy_editor",
            )
            monthly_occupancy = {
                str(row["Mois"]): float(max(0.0, row["Personnes-nuitées"])) for _, row in edited_occupancy.iterrows()
            }

        elif typology == "Station de lavage":
            col_a, col_b = st.columns(2)
            with col_a:
                car_wash_vehicles_per_day = st.number_input(
                    "Nombre de véhicules lavés par jour",
                    min_value=0.0,
                    value=float(car_wash_vehicles_per_day),
                    step=1.0,
                    key=f"{project_ui_key}_car_wash_vehicles_per_day",
                )
            with col_b:
                car_wash_liters_per_vehicle = st.number_input(
                    f"Conso ECS à {ecs_temperature_label} (L/véhicule)",
                    min_value=0.0,
                    value=float(car_wash_liters_per_vehicle or CAR_WASH_DEFAULT_L_PER_VEHICLE),
                    step=1.0,
                    key=f"{project_ui_key}_car_wash_liters_per_vehicle",
                )
    
        if data_source == "Ratio SOCOL" and typology in {"Logement collectif", "EHPAD", "Hôpital"}:
            with st.expander("Coefficient mensuel de modulation", expanded=False):
                coeff_rows = pd.DataFrame(
                    [
                        {"Mois": month, "Coefficient": float(monthly_coefficients.get(month, DEFAULT_MONTHLY_COEFFICIENTS[month]))}
                        for month in MONTH_NAMES
                    ]
                )
                edited_coeff = st.data_editor(
                    coeff_rows,
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    key=f"{project_ui_key}_monthly_coeff_editor",
                )
                monthly_coefficients = {
                    str(row["Mois"]): float(max(0.0, row["Coefficient"])) for _, row in edited_coeff.iterrows()
                }
    
    needs_inputs = NeedsInputs(
        ecs_temperature_c=float(ecs_temperature_c),
        housing_counts=housing_counts,
        housing_ratios_l_day=housing_ratios,
        residents_or_beds=int(residents_or_beds),
        liters_per_resident_or_bed_day=float(liters_per_resident_or_bed_day),
        monthly_occupancy=monthly_occupancy,
        liters_per_occupied_unit=float(liters_per_occupied_unit),
        hotel_category=hotel_category,
        car_wash_vehicles_per_day=float(car_wash_vehicles_per_day),
        car_wash_liters_per_vehicle=float(car_wash_liters_per_vehicle),
        measured_daily_l_60c_by_month=measured_daily,
        monthly_coefficients=monthly_coefficients,
    )
    
    # ---------------------------------------------------------------------------
    # Bouclage sanitaire.
    # ---------------------------------------------------------------------------
    with tab_loop:
        st.subheader("Bouclage sanitaire")
        loop_method = st.radio(
            "Méthode de calcul du bouclage",
            options=list(LOOP_METHODS),
            index=list(LOOP_METHODS).index(loop_default.method) if loop_default.method in LOOP_METHODS else 0,
            horizontal=True,
        )
    
        gas_monthly_kwh = dict(loop_default.gas_monthly_kwh)
        boiler_efficiency = loop_default.boiler_efficiency
        include_heating_estimate_without_loop = loop_default.include_heating_estimate_without_loop
    
        solo_type_bouclage_label = loop_default.solo_type_bouclage_label
        solo_loss_mode_label = loop_default.solo_loss_mode_label
        solo_losses_input_mode = loop_default.solo_losses_input_mode
        solo_losses_annual_kwh = loop_default.solo_losses_annual_kwh
        solo_losses_monthly_kwh_day = dict(loop_default.solo_losses_monthly_kwh_day)
        solo_debit_bouclage_l_h = loop_default.solo_debit_bouclage_l_h
        solo_delta_tmax_bouclage_k = loop_default.solo_delta_tmax_bouclage_k
        solo_long_bouclage_m = loop_default.solo_long_bouclage_m
        solo_kl_bouclage_w_m_k = loop_default.solo_kl_bouclage_w_m_k
        solo_long1_boucle_bon = loop_default.solo_long1_boucle_bon_m_per_unit
        solo_long1_boucle_moyen = loop_default.solo_long1_boucle_moyen_m_per_unit
        solo_long1_boucle_mauvais = loop_default.solo_long1_boucle_mauvais_m_per_unit
        solo_kl_boucle_bon = loop_default.solo_kl_boucle_bon_w_m_k
        solo_kl_boucle_moyen = loop_default.solo_kl_boucle_moyen_w_m_k
        solo_kl_boucle_mauvais = loop_default.solo_kl_boucle_mauvais_w_m_k
        solo_tref = loop_default.solo_tref_bouclage_c
        solo_tenv = loop_default.solo_tenv_bouclage_c
        solo_monthly_temperatures = dict(loop_default.solo_monthly_temperatures_c)
        solo_vecs_ref = loop_default.solo_vecs_unit_ref_l_day
        solo_active_ratio = loop_default.solo_active_ratio
    
        if loop_method == "Aucun bouclage sanitaire":
            st.info(
                "Aucun bouclage sanitaire n'est pris en compte. "
                "Le besoin ECS total est donc égal au besoin utile ECS, hors chauffage estimé."
            )
            include_heating_estimate_without_loop = st.checkbox(
                "Estimer également un chauffage depuis les factures gaz",
                value=bool(include_heating_estimate_without_loop),
                key=f"{project_ui_key}_heating_without_loop",
                help=(
                    "À utiliser si les factures gaz contiennent de l'ECS utile et du chauffage, "
                    "mais pas de pertes de bouclage sanitaire."
                ),
            )
            if include_heating_estimate_without_loop:
                boiler_efficiency = st.number_input(
                    "Rendement chaudière gaz retenu",
                    min_value=0.0,
                    max_value=1.0,
                    value=float(boiler_efficiency or 0.85),
                    step=0.01,
                    key=f"{project_ui_key}_no_loop_boiler_efficiency",
                )
                gas_rows = pd.DataFrame(
                    [
                        {"Mois": month, "Conso gaz facturée (kWh/mois)": float(gas_monthly_kwh.get(month, 0.0))}
                        for month in MONTH_NAMES
                    ]
                )
                edited_gas = st.data_editor(
                    gas_rows,
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    key=f"{project_ui_key}_no_loop_gas_invoices_editor",
                )
                gas_monthly_kwh = {
                    str(row["Mois"]): float(max(0.0, row["Conso gaz facturée (kWh/mois)"]))
                    for _, row in edited_gas.iterrows()
                }
                st.markdown(
                    "Calcul appliqué : "
                    "`chauffage_mois = max(0 ; conso_gaz_mois × rendement_chaudière - besoin_ECS_utile_mois)`."
                )
        elif loop_method == "Analyse factures gaz":
            st.caption(
                "Saisir les consommations gaz mensuelles. L'outil calcule le talon minimal journalier sur juin-septembre, "
                "applique le rendement chaudière, puis en déduit une perte de bouclage journalière constante. "
                "Le besoin utile ECS continue de varier chaque mois avec le coefficient de modulation et le nombre exact de jours."
            )
            boiler_efficiency = st.number_input(
                "Rendement chaudière gaz retenu",
                min_value=0.0,
                max_value=1.0,
                value=float(boiler_efficiency or 0.85),
                step=0.01,
            )
            gas_rows = pd.DataFrame(
                [{"Mois": month, "Conso gaz facturée (kWh/mois)": float(gas_monthly_kwh.get(month, 0.0))} for month in MONTH_NAMES]
            )
            edited_gas = st.data_editor(
                gas_rows,
                hide_index=True,
                width="stretch",
                disabled=["Mois"],
                key=f"{project_ui_key}_gas_invoices_editor",
            )
            gas_monthly_kwh = {
                str(row["Mois"]): float(max(0.0, row["Conso gaz facturée (kWh/mois)"]))
                for _, row in edited_gas.iterrows()
            }
            st.markdown(
                "Calcul appliqué sur une base journalière : "
                "`Bbouclage_j = talon_gaz_j × rendement_chaudière - Becs_utile_j_du_mois_talon`. "
                "Puis `Bbouclage_mois = Bbouclage_j × nombre_de_jours_du_mois`."
            )
        else:
            st.caption(
                "Bloc bouclage repris du module SOLO 2018 fourni : mêmes modes de saisie, mêmes constantes par défaut "
                "et même logique de calcul des pertes journalières."
            )
    
            solo_loss_mode_label = st.selectbox(
                "Calcul des pertes de bouclage",
                options=list(SOLO_LOOP_LOSS_MODE_LABELS),
                index=list(SOLO_LOOP_LOSS_MODE_LABELS).index(solo_loss_mode_label)
                if solo_loss_mode_label in SOLO_LOOP_LOSS_MODE_LABELS
                else 5,
            )
            st.caption(
                "Le choix de valorisation du bouclage par le solaire n'est pas demandé ici : "
                "il servira plus tard pour le calcul SOLO/productivité, pas pour estimer les pertes de bouclage."
            )
    
            if solo_loss_mode_label == "Saisie pertes (kWh/j)":
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    solo_losses_input_mode = st.selectbox(
                        "Mode de saisie des pertes",
                        options=list(SOLO_LOSS_INPUT_MODES),
                        index=list(SOLO_LOSS_INPUT_MODES).index(solo_losses_input_mode)
                        if solo_losses_input_mode in SOLO_LOSS_INPUT_MODES
                        else 0,
                    )
                if solo_losses_input_mode == "Saisie annuelle":
                    with col_s2:
                        solo_losses_annual_kwh = st.number_input(
                            "Pertes bouclage annuelles (kWh/an)",
                            min_value=0.0,
                            value=float(solo_losses_annual_kwh or 0.0),
                            step=100.0,
                        )
                else:
                    losses_rows = pd.DataFrame(
                        [
                            {"Mois": month, "Pertes bouclage (kWh/j)": float(solo_losses_monthly_kwh_day.get(month, 0.0))}
                            for month in MONTH_NAMES
                        ]
                    )
                    edited_losses = st.data_editor(
                        losses_rows,
                        hide_index=True,
                        width="stretch",
                        disabled=["Mois"],
                        key=f"{project_ui_key}_loop_losses_editor",
                    )
                    solo_losses_monthly_kwh_day = {
                        str(row["Mois"]): float(max(0.0, row["Pertes bouclage (kWh/j)"]))
                        for _, row in edited_losses.iterrows()
                    }
    
            elif solo_loss_mode_label == "Débit et delta T connus":
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    solo_debit_bouclage_l_h = st.number_input(
                        "Débit de bouclage (L/h)", min_value=0.0, value=float(solo_debit_bouclage_l_h or 300.0), step=10.0
                    )
                with col_d2:
                    solo_delta_tmax_bouclage_k = st.number_input(
                        "Delta T max bouclage (°C)", min_value=0.0, value=float(solo_delta_tmax_bouclage_k or 5.0), step=0.5
                    )
    
            elif solo_loss_mode_label == "Longueur et isolation connues":
                col_l1, col_l2 = st.columns(2)
                with col_l1:
                    solo_long_bouclage_m = st.number_input(
                        "Longueur de boucle (m)", min_value=0.0, value=float(solo_long_bouclage_m or 120.0), step=5.0
                    )
                with col_l2:
                    solo_kl_bouclage_w_m_k = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_bouclage_w_m_k or 0.3),
                        step=0.01,
                        format="%.2f",
                    )
    
            elif solo_loss_mode_label == "Boucle courte bien isolée":
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    solo_long1_boucle_bon = st.number_input(
                        "Longueur boucle par unité (m/unité)",
                        min_value=0.0,
                        value=float(solo_long1_boucle_bon or 6.0),
                        step=0.1,
                    )
                with col_b2:
                    solo_kl_boucle_bon = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_boucle_bon or 0.2),
                        step=0.01,
                        format="%.2f",
                    )
    
            elif solo_loss_mode_label == "Boucle qualité moyenne":
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    solo_long1_boucle_moyen = st.number_input(
                        "Longueur boucle par unité (m/unité)",
                        min_value=0.0,
                        value=float(solo_long1_boucle_moyen or 9.0),
                        step=0.1,
                    )
                with col_m2:
                    solo_kl_boucle_moyen = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_boucle_moyen or 0.3),
                        step=0.01,
                        format="%.2f",
                    )
    
            elif solo_loss_mode_label == "Boucle longue mal isolée":
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    solo_long1_boucle_mauvais = st.number_input(
                        "Longueur boucle par unité (m/unité)",
                        min_value=0.0,
                        value=float(solo_long1_boucle_mauvais or 12.0),
                        step=0.1,
                    )
                with col_v2:
                    solo_kl_boucle_mauvais = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_boucle_mauvais or 0.4),
                        step=0.01,
                        format="%.2f",
                    )
    
            with st.expander("Paramètres généraux SOLO 2018 du bouclage", expanded=False):
                st.caption(
                    "Le volume ECS de référence par unité n'est pas saisi ici : il est repris automatiquement "
                    "depuis la consommation ECS moyenne journalière calculée dans l'onglet Besoins ECS."
                )
                col_g1, col_g2, col_g3 = st.columns(3)
                with col_g1:
                    solo_tref = st.number_input("Température de référence bouclage (°C)", value=float(solo_tref or 55.0), step=1.0)
                with col_g2:
                    solo_tenv = st.number_input("Température environnement bouclage (°C)", value=float(solo_tenv or 20.0), step=1.0)
                with col_g3:
                    solo_active_ratio = st.number_input(
                        "Ratio bouclage actif",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(solo_active_ratio or 1.0),
                        step=0.05,
                    )
    
                loop_temp_rows = pd.DataFrame(
                    [
                        {"Mois": month, "Température mensuelle utilisée (°C)": float(solo_monthly_temperatures.get(month, 20.0))}
                        for month in MONTH_NAMES
                    ]
                )
                edited_loop_temp = st.data_editor(
                    loop_temp_rows,
                    hide_index=True,
                    width="stretch",
                    disabled=["Mois"],
                    key=f"{project_ui_key}_loop_temps_editor",
                )
                solo_monthly_temperatures = {
                    str(row["Mois"]): float(row["Température mensuelle utilisée (°C)"]) for _, row in edited_loop_temp.iterrows()
                }
    
    loop_inputs = LoopInputs(
        method=loop_method,
        include_heating_estimate_without_loop=bool(include_heating_estimate_without_loop),
        gas_monthly_kwh=gas_monthly_kwh,
        boiler_efficiency=float(boiler_efficiency),
        solo_type_bouclage_label=solo_type_bouclage_label,
        solo_loss_mode_label=solo_loss_mode_label,
        solo_losses_input_mode=solo_losses_input_mode,
        solo_losses_annual_kwh=float(solo_losses_annual_kwh),
        solo_losses_monthly_kwh_day=solo_losses_monthly_kwh_day,
        solo_debit_bouclage_l_h=float(solo_debit_bouclage_l_h),
        solo_delta_tmax_bouclage_k=float(solo_delta_tmax_bouclage_k),
        solo_long_bouclage_m=float(solo_long_bouclage_m),
        solo_kl_bouclage_w_m_k=float(solo_kl_bouclage_w_m_k),
        solo_long1_boucle_bon_m_per_unit=float(solo_long1_boucle_bon),
        solo_long1_boucle_moyen_m_per_unit=float(solo_long1_boucle_moyen),
        solo_long1_boucle_mauvais_m_per_unit=float(solo_long1_boucle_mauvais),
        solo_kl_boucle_bon_w_m_k=float(solo_kl_boucle_bon),
        solo_kl_boucle_moyen_w_m_k=float(solo_kl_boucle_moyen),
        solo_kl_boucle_mauvais_w_m_k=float(solo_kl_boucle_mauvais),
        solo_tref_bouclage_c=float(solo_tref),
        solo_tenv_bouclage_c=float(solo_tenv),
        solo_monthly_temperatures_c=solo_monthly_temperatures,
        solo_vecs_unit_ref_l_day=float(solo_vecs_ref),
        solo_active_ratio=float(solo_active_ratio),
    )
    
    with tab_sizing:
        st.subheader("Paramètres de prédimensionnement")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            collector_names = list(COLLECTOR_LIBRARY.keys())
            saved_collector_name = sizing_default.collector_name if sizing_default.collector_name in COLLECTOR_LIBRARY else DEFAULT_COLLECTOR_NAME
            collector_name = st.selectbox(
                "Bibliothèque capteur",
                options=collector_names,
                index=collector_names.index(saved_collector_name),
                key=f"{project_ui_key}_collector_name",
            )
            collector_ref = get_collector_reference(collector_name)
            st.caption(
                f"Capteur retenu : {collector_ref.manufacturer} {collector_ref.model}, "
                f"surface unitaire {collector_ref.area_m2:.2f} m²."
            )
            collector_unit_area_default = (
                float(sizing_default.collector_unit_area_m2)
                if sizing_default.collector_name == collector_name and sizing_default.collector_unit_area_m2
                else float(collector_ref.area_m2)
            )
            collector_unit_area = st.number_input(
                "Surface unitaire capteur (m²)",
                min_value=0.1,
                value=collector_unit_area_default,
                step=0.01,
                key=f"{project_ui_key}_collector_unit_area_{safe_slug(collector_name)}",
                help="Valeur initialisée depuis la bibliothèque capteurs. À modifier seulement si la fiche technique retenue diffère.",
            )
        with col_b:
            target_ratio = st.number_input(
                "Ratio stockage cible (L/m²)",
                min_value=40.0,
                max_value=90.0,
                value=float(sizing_default.target_storage_ratio_l_m2),
                step=1.0,
            )
        with col_c:
            max_tank_count = st.number_input(
                "Nombre max. de ballons combinés", min_value=1, max_value=6, value=int(sizing_default.max_tank_count or 3), step=1
            )
            productivity_default = st.number_input(
                "Productivité par défaut (kWh/m².an)",
                min_value=0.0,
                value=float(sizing_default.productivity_kwh_m2_year or DEFAULT_PRODUCTIVITY_KWH_M2_YEAR),
                step=10.0,
            )
    
    sizing_inputs = SizingInputs(
        cold_water_mode=str(cold_water_mode),
        cold_water_temperatures_c=cold_water_temperatures,
        collector_name=str(collector_name),
        collector_unit_area_m2=float(collector_unit_area),
        target_storage_ratio_l_m2=float(target_ratio),
        max_tank_count=int(max_tank_count),
        productivity_kwh_m2_year=float(productivity_default),
    )
    
    try:
        opportunity_results = compute_opportunity_results(site_inputs, needs_inputs, sizing_inputs, loop_inputs)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    with tab_needs:
        st.markdown("### Synthèse du besoin ECS")
        target_temperature_l_day = sum(row.volume_l_60c for row in opportunity_results.monthly_needs) / 365.0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Consommation moyenne à la température cible",
            f"{number(target_temperature_l_day, 0)} L/j à {number(needs_inputs.ecs_temperature_c, 0)} °C",
        )
        k2.metric(
            "Équivalent dimensionnant à 60 °C",
            f"{number(opportunity_results.average_daily_volume_l_60c, 0)} L/j à 60 °C",
        )
        k3.metric(
            "Besoin utile ECS moyen",
            f"{number(opportunity_results.annual_useful_energy_mwh * 1000.0 / 365.0, 1)} kWh/j",
        )
        reference_unit_value = opportunity_results.solo_reference_volume_l_day_per_unit
        if site_inputs.typology == "Station de lavage":
            reference_label = "Valeur par véhicule lavé"
            reference_value = f"{number(reference_unit_value, 1)} L/véhicule à 60 °C"
            reference_caption = (
                f"Unité de référence : {number(opportunity_results.reference_unit_count, 1)} "
                "véhicule(s) lavé(s) par jour."
            )
        else:
            reference_label = "Valeur par unité de référence"
            reference_value = f"{number(reference_unit_value, 1)} L/unité/j"
            reference_caption = (
                f"Unité de référence estimée : {number(opportunity_results.reference_unit_count, 1)} "
                "unité(s) selon la typologie du site."
            )
        k4.metric(
            reference_label,
            reference_value,
        )
        if opportunity_results.reference_unit_count > 0:
            st.caption(reference_caption)
        else:
            st.caption("Aucune unité de référence exploitable n'est renseignée ; la valeur par unité reprend le volume moyen total.")
    
    with tab_loop:
        st.markdown("### Résultat bouclage")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Besoin utile ECS", f"{number(opportunity_results.annual_useful_energy_mwh, 1)} MWh/an")
        col2.metric("Bouclage sanitaire", f"{number(opportunity_results.annual_loop_losses_mwh, 1)} MWh/an")
        col3.metric("Besoin ECS + bouclage", f"{number(opportunity_results.annual_total_ecs_energy_mwh, 1)} MWh/an")
        col4.metric("Chauffage estimé", f"{number(opportunity_results.annual_heating_after_boiler_mwh, 1)} MWh/an")
        if loop_method == "Analyse factures gaz":
            loop_daily_kwh = opportunity_results.annual_loop_losses_mwh * 1000.0 / 365.0 if opportunity_results.annual_loop_losses_mwh > 0 else 0.0
            st.info(
                f"Talon gaz estival retenu : {number(opportunity_results.gas_summer_baseload_daily_kwh, 1)} kWh/j gaz, "
                f"avec un rendement chaudière de {number(loop_inputs.boiler_efficiency * 100, 0)} %. "
                f"Bouclage retenu : {number(loop_daily_kwh, 1)} kWh/j, soit une valeur journalière constante multipliée par le nombre de jours de chaque mois. "
                "Le chauffage estimé correspond à la part de facture gaz située au-dessus de ce talon, après application du rendement chaudière."
            )
        elif loop_method == "Hypothèses SOLO 2018":
            if opportunity_results.reference_unit_count > 0:
                st.info(
                    "Volume ECS de référence SOLO utilisé automatiquement : "
                    f"{number(opportunity_results.solo_reference_volume_l_day_per_unit, 1)} L/j/unité à 60 °C, "
                    f"calculé à partir de {number(opportunity_results.average_daily_volume_l_60c, 0)} L/j "
                    f"et {number(opportunity_results.reference_unit_count, 1)} unité(s)."
                )
            else:
                st.info(
                    "Volume ECS de référence SOLO utilisé automatiquement : "
                    f"{number(opportunity_results.solo_reference_volume_l_day_per_unit, 0)} L/j à 60 °C. "
                    "Aucune unité de référence n'est renseignée, donc l'outil utilise la consommation journalière totale comme valeur de repli."
                )
        pie_col1, pie_col2 = st.columns(2)
        fig_pie = render_ecs_loop_pie_chart(opportunity_results)
        if fig_pie is not None:
            pie_col1.plotly_chart(fig_pie, width="stretch")
        fig_pie_heating = render_ecs_loop_heating_pie_chart(opportunity_results)
        if fig_pie_heating is not None:
            pie_col2.plotly_chart(fig_pie_heating, width="stretch")
    
        fig_loop = render_loop_chart(opportunity_results)
        if fig_loop is not None:
            st.plotly_chart(fig_loop, width="stretch")
        st.dataframe(loop_dataframe(opportunity_results), hide_index=True, width="stretch")
    
    with tab_sizing:
        st.markdown("### Proposition centrale")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Volume ECS dimensionnant", f"{number(opportunity_results.average_daily_volume_l_60c, 0)} L/j à 60 °C")
        col2.metric("Stockage proposé", f"{opportunity_results.storage.total_volume_l:,.0f} L".replace(",", " "))
        col3.metric("Surface proposée", f"{number(opportunity_results.collectors.surface_m2, 1)} m²")
        col4.metric("Ratio V/S", f"{number(opportunity_results.collectors.storage_ratio_l_m2, 1)} L/m²")
    
        st.write(f"**Ballons proposés :** {opportunity_results.storage.label}")
        st.write(
            "**Capteurs proposés :** "
            f"{opportunity_results.collectors.collector_count} capteurs × "
            f"{sizing_inputs.collector_name} ({opportunity_results.collectors.collector_unit_area_m2:.2f} m²) = "
            f"{opportunity_results.collectors.surface_m2:.2f} m²"
        )
        st.caption(
            "La surface est choisie pour être la plus proche possible de 60 L/m², "
            "avec un nombre de capteurs divisible par 2 ou par 3 lorsque c'est possible. "
            "Le stockage privilégie les multiples de ballons de même taille."
        )
        solar_coverage_ratio = (
            min(
                1.0,
                opportunity_results.estimated_solar_production_mwh_year
                / opportunity_results.annual_total_ecs_energy_mwh,
            )
            if opportunity_results.annual_total_ecs_energy_mwh > 0
            else None
        )
        prod_col, coverage_col = st.columns(2)
        prod_col.metric(
            "Production solaire provisoire",
            f"{number(opportunity_results.estimated_solar_production_mwh_year, 1)} MWh/an",
            f"{number(sizing_inputs.productivity_kwh_m2_year, 0)} kWh/m².an",
        )
        coverage_col.metric(
            "Taux de couverture ECS provisoire",
            percent(solar_coverage_ratio),
            f"sur {number(opportunity_results.annual_total_ecs_energy_mwh, 1)} MWh/an ECS + bouclage",
        )

    with tab_architecture:
        render_architectural_constraints_test(state_prefix="helionop", show_address_inputs=False, show_map=True)

    # ---------------------------------------------------------------------------
    # Modèle économique raccordé au pré-dimensionnement.
    # ---------------------------------------------------------------------------
    with tab_economics:
        st.subheader("Modèle économique")
        st.caption("Les valeurs sont préremplies avec le prédimensionnement et les hypothèses économiques par défaut de l'onglet CESC.")
        recommended_economic_surface = float(opportunity_results.collectors.surface_m2)
        recommended_economic_productivity = float(sizing_inputs.productivity_kwh_m2_year)
        use_predesign_for_economics = st.checkbox(
            "Reprendre la surface et la productivité du prédimensionnement",
            value=bool(economic_default.get("use_predesign_for_economics", True)),
            key=f"{project_ui_key}_use_predesign_for_economics",
            help=(
                "Activé par défaut : l'économie utilise la surface proposée dans l'onglet Prédimensionnement, "
                "elle-même calculée à partir du volume ECS équivalent à 60 °C."
            ),
        )
    
        inputs_col, reference_col = st.columns([2, 1])
        with inputs_col:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                economic_typology = st.selectbox(
                    "Scénario d'aide ADEME",
                    options=list(ECONOMIC_SCENARIOS),
                    index=list(ECONOMIC_SCENARIOS).index(economic_default.get("typologie", "CESC"))
                    if economic_default.get("typologie", "CESC") in ECONOMIC_SCENARIOS
                    else 0,
                )
                if use_predesign_for_economics:
                    economic_surface = recommended_economic_surface
                    economic_productivity = recommended_economic_productivity
                    st.metric("Surface économique (m²)", f"{number(economic_surface, 1)} m²")
                    st.metric("Productivité économique", f"{number(economic_productivity, 0)} kWh/m².an")
                    st.caption(
                        "Ces valeurs sont reprises automatiquement depuis le prédimensionnement calculé "
                        "sur le volume ECS équivalent à 60 °C."
                    )
                else:
                    economic_surface = st.number_input(
                        "Surface économique (m²)",
                        min_value=0.0,
                        value=float(economic_default.get("surface_m2", recommended_economic_surface)),
                        step=1.0,
                        key=f"{project_ui_key}_economic_surface_m2",
                    )
                    economic_productivity = st.number_input(
                        "Productivité économique (kWh/m².an)",
                        min_value=0.0,
                        value=float(economic_default.get("productivity_kwh_m2_year", recommended_economic_productivity)),
                        step=10.0,
                        key=f"{project_ui_key}_economic_productivity_kwh_m2_year",
                    )
            with col_b:
                reference_energy_cost = st.number_input(
                    "Coût énergie de référence (€HT/MWh)",
                    min_value=0.0,
                    value=float(economic_default.get("reference_energy_cost_eur_mwh", 75.0)),
                    step=5.0,
                )
                inflation = st.number_input(
                    "Inflation énergie référence (%/an)",
                    value=float(economic_default.get("reference_energy_inflation_percent", 3.0)),
                    step=0.5,
                ) / 100.0
                years = st.number_input("Durée d'analyse (ans)", min_value=1, value=int(economic_default.get("years", 20)), step=1)
            with col_c:
                works_cost = st.number_input(
                    "Coût travaux installation (€HT/m²)",
                    min_value=0.0,
                    value=float(economic_default.get("works_cost_eur_m2", 1563.0)),
                    step=50.0,
                )
                eta_appoint = st.number_input(
                    "Rendement appoint global",
                    min_value=0.01,
                    max_value=1.5,
                    value=float(economic_default.get("eta_appoint", 0.82)),
                    step=0.01,
                )
                electricity_cost = st.number_input(
                    "Coût électricité auxiliaires (€HT/MWh)",
                    min_value=0.0,
                    value=float(economic_default.get("electricity_cost_eur_mwh", DEFAULT_AUXILIARY_ELECTRICITY_COST_EUR_MWH)),
                    step=10.0,
                    help="Utilisé pour calculer le P1' : consommation électrique des auxiliaires solaires × coût de l'électricité.",
                )

        with reference_col:
            fig_cost_reference = build_solar_thermal_cost_reference_plotly(go, selected_cost_eur_m2=float(works_cost))
            if fig_cost_reference is not None:
                fig_cost_reference.update_layout(height=280, margin=dict(l=12, r=12, t=46, b=38))
                st.plotly_chart(fig_cost_reference, width="stretch")
                st.caption(SOLAR_THERMAL_COST_REFERENCE_NOTE)
    
        with st.expander("Hypothèses économiques avancées", expanded=False):
            col_1, col_2, col_3 = st.columns(3)
            with col_1:
                legacy_direct_p1 = float(economic_default.get("auxiliary_electricity_cost_eur_mwh", 0.0))
                legacy_ratio_percent = (
                    100.0 * legacy_direct_p1 / electricity_cost
                    if legacy_direct_p1 > 0 and electricity_cost > 0
                    else DEFAULT_AUXILIARY_ELECTRICITY_RATIO * 100.0
                )
                auxiliary_ratio = st.number_input(
                    "Consommation électrique des auxiliaires (% de la production solaire)",
                    value=float(
                        economic_default.get(
                            "auxiliary_ratio_percent",
                            legacy_ratio_percent,
                        )
                    ),
                    step=0.5,
                ) / 100.0
                st.caption(
                    f"P1' auxiliaires = {auxiliary_ratio * 100.0:.1f} % × {electricity_cost:.0f} €/MWh = "
                    f"{auxiliary_ratio * electricity_cost:.1f} €/MWh solaire utile."
                )
            with col_2:
                maintenance_cost = st.number_input(
                    "Maintenance (€/m².an)", value=float(economic_default.get("maintenance_cost_eur_m2_year", 22.0)), step=1.0
                )
                fae_cost = st.number_input("FAE (€HT)", value=float(economic_default.get("fae_cost_eur", 4929.0)), step=100.0)
            with col_3:
                fae_aid_rate = st.number_input(
                    "Taux aide FAE (%)", value=float(economic_default.get("fae_aid_rate_percent", 70.0)), step=5.0
                ) / 100.0
                ademe_cap = st.number_input(
                    "Plafond aide travaux (% coût)", value=float(economic_default.get("ademe_cap_percent", 65.0)), step=5.0
                ) / 100.0
    
        economic_inputs = CescEconomicInputs(
            typologie=economic_typology,
            surface_m2=economic_surface,
            productivity_kwh_m2_year=economic_productivity,
            reference_energy_cost_eur_mwh=reference_energy_cost,
            reference_energy_inflation_rate=inflation,
            years=int(years),
            works_cost_eur_m2=works_cost,
            eta_appoint=eta_appoint,
            auxiliary_electricity_ratio=auxiliary_ratio,
            electricity_cost_eur_mwh=electricity_cost,
            maintenance_cost_eur_m2_year=maintenance_cost,
            fae_cost_eur=fae_cost,
            fae_aid_rate=fae_aid_rate,
            ademe_aid_max_rate_on_works=ademe_cap,
        )
        economic_results = compute_cesc_economic_model(economic_inputs)
    
        st.caption(
            f"Forfait ADEME appliqué : {ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY[economic_typology]:,.0f} €/MWh.an".replace(
                ",", " "
            )
        )
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Production solaire", f"{number(economic_results.annual_production_mwh, 1)} MWh/an")
        col2.metric("Investissement", eur(economic_results.investment_cost_eur, 0))
        col3.metric("Aides", eur(economic_results.aid_total_eur, 0), percent(economic_results.aid_rate))
        col4.metric("Reste à charge", eur(economic_results.net_investment_eur, 0))

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Économies annuelles", eur(economic_results.annual_savings_eur, 0))
        col6.metric("Temps retour brut", f"{number(economic_results.raw_payback_years, 1)} ans")
        col7.metric("Coût chaleur solaire", eur_mwh(economic_results.solar_heat_cost_eur_mwh, 1))
        col8.metric(f"Économies sur {economic_inputs.years} ans", eur(economic_results.savings_over_period_eur, 0))

        heat_cost_col, cashflow_col = st.columns([1, 3])
        with heat_cost_col:
            fig_breakdown = render_heat_cost_breakdown_plotly(economic_results)
            if fig_breakdown is not None:
                st.plotly_chart(fig_breakdown, width="stretch")

        with cashflow_col:
            cashflow_rows = list(build_yearly_cashflow_projection(economic_inputs, economic_results))
            fig_cashflow = render_cumulative_cashflow_plotly(cashflow_rows)
            if fig_cashflow is not None:
                st.plotly_chart(fig_cashflow, width="stretch")
    
    # ---------------------------------------------------------------------------
    # Synthèse et export.
    # ---------------------------------------------------------------------------
    economic_payload = {
        "typologie": economic_typology,
        "use_predesign_for_economics": use_predesign_for_economics,
        "surface_m2": economic_surface,
        "productivity_kwh_m2_year": economic_productivity,
        "reference_energy_cost_eur_mwh": reference_energy_cost,
        "reference_energy_inflation_percent": inflation * 100.0,
        "years": int(years),
        "works_cost_eur_m2": works_cost,
        "eta_appoint": eta_appoint,
        "auxiliary_ratio_percent": auxiliary_ratio * 100.0,
        "electricity_cost_eur_mwh": electricity_cost,
        "maintenance_cost_eur_m2_year": maintenance_cost,
        "fae_cost_eur": fae_cost,
        "fae_aid_rate_percent": fae_aid_rate * 100.0,
        "ademe_cap_percent": ademe_cap * 100.0,
    }
    
    current_payload = {
        "schema_version": 1,
        "app_key": APP_KEY,
        "app_label": APP_LABEL,
        "project_id": payload.get("project_id", str(uuid.uuid4())),
        "name": site_inputs.project_name or "Nouveau projet",
        "owner_email": current_owner_email(),
        "created_at": payload.get("created_at", now_iso()),
        "updated_at": now_iso(),
        "site": asdict(site_inputs),
        "needs": asdict(needs_inputs),
        "sizing": asdict(sizing_inputs),
        "loop": asdict(loop_inputs),
        "economic": economic_payload,
        "architectural_constraints": _current_helionop_architectural_payload(),
        "results": {"opportunity": opportunity_results.as_dict(), "economic": economic_results.as_dict()},
    }
    
    with tab_export:
        st.subheader("Synthèse")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Volume ECS annuel", f"{number(opportunity_results.annual_volume_l_60c / 1000.0, 1)} m³/an")
        col2.metric("Besoin utile ECS", f"{number(opportunity_results.annual_useful_energy_mwh, 1)} MWh/an")
        col3.metric("Bouclage", f"{number(opportunity_results.annual_loop_losses_mwh, 1)} MWh/an")
        col4.metric("Surface capteurs", f"{number(opportunity_results.collectors.surface_m2, 1)} m²")
    
        st.markdown(
            f"""
    **Projet :** {site_inputs.project_name}  
    **ID Airtable :** {site_inputs.airtable_id or "-"}  
    **Typologie :** {site_inputs.typology}  
    **Nature du bâtiment :** {site_inputs.building_state}  
    **Mode ECS :** {site_inputs.data_source}  
    **Méthode bouclage :** {loop_inputs.method}  
    
    **Besoin utile ECS :** {opportunity_results.annual_useful_energy_mwh:.1f} MWh/an.  
    **Bouclage sanitaire estimé :** {opportunity_results.annual_loop_losses_mwh:.1f} MWh/an.  
    **Besoin ECS total avec bouclage :** {opportunity_results.annual_total_ecs_energy_mwh:.1f} MWh/an.  
    
    **Prédimensionnement proposé :** {opportunity_results.storage.label}, avec {opportunity_results.collectors.collector_count} capteurs {sizing_inputs.collector_name} de {opportunity_results.collectors.collector_unit_area_m2:.2f} m², soit {opportunity_results.collectors.surface_m2:.2f} m².  
    **Ratio V/S :** {opportunity_results.collectors.storage_ratio_l_m2:.1f} L/m².  
    **Productivité provisoire :** {sizing_inputs.productivity_kwh_m2_year:.0f} kWh/m².an, à remplacer ensuite par le calcul SOLO 2018.
    """
        )
    
        st.download_button(
            "Télécharger le projet JSON",
            data=json.dumps(current_payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"{slugify(site_inputs.project_name)}.json",
            mime="application/json",
        )
        st.download_button(
            "Télécharger la note d'opportunité en PDF",
            data=build_opportunity_note_pdf(
                site_inputs=site_inputs,
                needs_inputs=needs_inputs,
                sizing_inputs=sizing_inputs,
                loop_inputs=loop_inputs,
                economic_inputs=economic_inputs,
                opportunity_results=opportunity_results,
                economic_results=economic_results,
                architectural_constraints=_current_helionop_architectural_payload(),
            ),
            file_name=f"{slugify(site_inputs.project_name)}_note_opportunite.pdf",
            mime="application/pdf",
        )
        with st.expander("Voir le JSON complet", expanded=False):
            st.code(json.dumps(current_payload, ensure_ascii=False, indent=2), language="json")
    
    if st.session_state.pop("helionop_save_requested", False):
        saved_path = save_project(current_payload)
        st.session_state.project_payload = current_payload
        st.session_state.save_notice = f"Projet enregistré : {saved_path.name}"
        st.rerun()


