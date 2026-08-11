from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Callable

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ..geocoding_service import GeocodingServiceError, search_addresses
from .project_context import (
    DEFAULT_PROJECT_DEPARTMENTS,
    DEFAULT_PROJECT_LATITUDE,
    DEFAULT_PROJECT_LONGITUDE,
    DEFAULT_PROJECT_REGIONS,
    DEFAULT_SITE_TYPOLOGIES,
    HELIORC_SITE_TYPOLOGIES,
    project_context_to_payload,
)



@dataclass(frozen=True)
class ProjectIdentity:
    project_name: str = ""
    client_name: str = ""
    airtable_id: str = ""
    analyst: str = ""
    project_date: date | None = None
    typology: str = ""
    building_state: str = ""
    region: str = ""
    department: str = ""
    city: str = ""
    address: str = ""
    latitude: float = DEFAULT_PROJECT_LATITUDE
    longitude: float = DEFAULT_PROJECT_LONGITUDE
    weather_region: str = ""
    weather_station: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ProjectIdentityOptions:
    show_project_name: bool = True
    show_client_name: bool = True
    show_airtable_id: bool = True
    show_analyst: bool = False
    show_project_date: bool = False
    show_typology: bool = False
    show_building_state: bool = False
    show_region: bool = False
    show_department: bool = False
    show_city: bool = True
    show_address_search: bool = True
    show_map: bool = True
    show_weather: bool = False
    auto_select_nearest_weather: bool = True
    show_notes: bool = False
    typology_options: tuple[str, ...] = ()
    building_state_options: tuple[str, ...] = ()
    region_options: tuple[str, ...] = ()
    department_options: tuple[str, ...] = ()
    weather_regions: dict[str, dict[str, object]] | None = None
    weather_station_aliases: dict[str, str] | None = None
    client_label: str = "Maître d'ouvrage"
    airtable_label: str = "ID Airtable"
    city_label: str = "Commune"
    address_help: str = "Recherche une adresse pour alimenter automatiquement les contrôles cartographiques."
    map_caption: str = "Clique sur la carte pour déplacer le point exact du projet."



@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_project_address_search(query: str) -> list[dict[str, object]]:
    return search_addresses(query=query, limit=5)


def _key(prefix: str, name: str) -> str:
    return f"{prefix}_{name}" if prefix else name


def _coerce_project_date(value: object) -> date:
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


def _normalise_weather_station_label(label: str, aliases: dict[str, str] | None) -> str:
    return (aliases or {}).get(str(label), str(label))


def _station_coordinates(station: object) -> tuple[float, float] | None:
    latitude = getattr(station, "latitude_deg", None)
    longitude = getattr(station, "longitude_deg", None)
    if isinstance(station, dict):
        latitude = station.get("latitude_deg", station.get("latitude", latitude))
        longitude = station.get("longitude_deg", station.get("longitude", longitude))
    if isinstance(latitude, (float, int)) and isinstance(longitude, (float, int)):
        return float(latitude), float(longitude)
    return None


def _station_label(station: object, fallback: str) -> str:
    return str(getattr(station, "label", fallback))


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_weather_station(
    *,
    latitude: float,
    longitude: float,
    weather_regions: dict[str, dict[str, object]] | None,
) -> tuple[str, str, float] | None:
    if not weather_regions:
        return None
    best: tuple[str, str, float] | None = None
    for region_name, stations in weather_regions.items():
        for station_name, station in stations.items():
            coords = _station_coordinates(station)
            if coords is None:
                continue
            distance = _distance_km(latitude, longitude, coords[0], coords[1])
            label = _station_label(station, str(station_name))
            if best is None or distance < best[2]:
                best = (str(region_name), label, distance)
    return best


def nearest_weather_station(
    *,
    latitude: float,
    longitude: float,
    weather_regions: dict[str, dict[str, object]] | None,
) -> tuple[str, str, float] | None:
    """Return the closest configured weather station to a project point."""

    return _nearest_weather_station(
        latitude=latitude,
        longitude=longitude,
        weather_regions=weather_regions,
    )


def _weather_station_map(
    *,
    weather_regions: dict[str, dict[str, object]],
    selected_region: str,
    selected_station: str,
    project_latitude: float,
    project_longitude: float,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "nom": "Projet",
            "latitude": project_latitude,
            "longitude": project_longitude,
            "taille": 150,
            "couleur": "#ef4444",
        }
    ]
    for station_name, station in weather_regions.get(selected_region, {}).items():
        coords = _station_coordinates(station)
        if coords is None:
            continue
        label = _station_label(station, str(station_name))
        rows.append(
            {
                "nom": label,
                "latitude": coords[0],
                "longitude": coords[1],
                "taille": 130 if label == selected_station else 60,
                "couleur": "#f59e0b" if label == selected_station else "#64748b",
            }
        )
    return pd.DataFrame(rows)


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


def _init_identity_state(prefix: str, defaults: ProjectIdentity, project_id: str | None) -> None:
    guard_key = _key(prefix, "project_identity_project_id")
    should_refresh = project_id is not None and st.session_state.get(guard_key) != project_id
    if project_id is not None:
        st.session_state[guard_key] = project_id

    values: dict[str, object] = {
        "project_name": defaults.project_name,
        "client_name": defaults.client_name,
        "airtable_id": defaults.airtable_id,
        "analyst": defaults.analyst,
        "project_date": _coerce_project_date(defaults.project_date),
        "typology": defaults.typology,
        "building_state": defaults.building_state,
        "region": defaults.region,
        "department": defaults.department,
        "city": defaults.city,
        "project_address_label": defaults.address,
        "project_latitude": defaults.latitude,
        "project_longitude": defaults.longitude,
        "weather_region": defaults.weather_region,
        "weather_station": defaults.weather_station,
        "notes": defaults.notes,
    }
    for name, value in values.items():
        state_key = _key(prefix, name)
        if should_refresh or state_key not in st.session_state:
            st.session_state[state_key] = value


def _render_select_or_text(
    label: str,
    *,
    key: str,
    options: tuple[str, ...],
) -> None:
    values = list(options)
    if values:
        if st.session_state.get(key) not in values:
            st.session_state[key] = values[0]
        st.selectbox(label, options=values, key=key)
    else:
        st.text_input(label, key=key)


def _render_weather_identity_fields(key_prefix: str, options: ProjectIdentityOptions) -> None:
    weather_regions = options.weather_regions or {}
    if not weather_regions:
        return
    region_names = list(weather_regions.keys())
    if not region_names:
        return

    identity = _current_identity(key_prefix)
    nearest = _nearest_weather_station(
        latitude=identity.latitude,
        longitude=identity.longitude,
        weather_regions=weather_regions,
    )

    region_key = _key(key_prefix, "weather_region")
    station_key = _key(key_prefix, "weather_station")
    location_signature_key = _key(key_prefix, "weather_auto_location_signature")
    location_signature = f"{identity.latitude:.6f}:{identity.longitude:.6f}"
    if (
        options.auto_select_nearest_weather
        and nearest is not None
        and st.session_state.get(location_signature_key) != location_signature
    ):
        st.session_state[region_key] = nearest[0]
        st.session_state[station_key] = nearest[1]
        st.session_state[location_signature_key] = location_signature

    if st.session_state.get(region_key) not in region_names:
        default_region = identity.weather_region if identity.weather_region in region_names else None
        if nearest is not None:
            default_region = nearest[0]
        st.session_state[region_key] = default_region or region_names[0]

    weather_col, map_col = st.columns([1, 1])
    with weather_col:
        st.markdown("### Station météo")
        selected_region = st.selectbox("Région météo", options=region_names, key=region_key)
        stations_by_label = weather_regions[selected_region]
        station_labels = list(stations_by_label.keys())
        current_station = _normalise_weather_station_label(str(st.session_state.get(station_key) or ""), options.weather_station_aliases)
        if current_station not in station_labels:
            default_station = _normalise_weather_station_label(identity.weather_station, options.weather_station_aliases)
            if nearest is not None and nearest[0] == selected_region:
                default_station = nearest[1]
            st.session_state[station_key] = default_station if default_station in station_labels else station_labels[0]
        selected_station = st.selectbox("Station météo", options=station_labels, key=station_key)
        if nearest is not None:
            st.caption(
                f"Station la plus proche du point projet : {nearest[1]} "
                f"({nearest[2]:.0f} km environ)."
            )
    with map_col:
        stations_df = _weather_station_map(
            weather_regions=weather_regions,
            selected_region=str(st.session_state.get(region_key)),
            selected_station=str(st.session_state.get(_key(key_prefix, "weather_station"))),
            project_latitude=identity.latitude,
            project_longitude=identity.longitude,
        )
        if not stations_df.empty:
            st.map(
                stations_df,
                latitude="latitude",
                longitude="longitude",
                size="taille",
                color="couleur",
                zoom=6,
                width="stretch",
                height=320,
            )


def render_project_identity_form(
    *,
    key_prefix: str,
    defaults: ProjectIdentity | None = None,
    project_id: str | None = None,
    options: ProjectIdentityOptions | None = None,
    on_location_change: Callable[[ProjectIdentity], None] | None = None,
) -> ProjectIdentity:
    defaults = defaults or ProjectIdentity()
    options = options or ProjectIdentityOptions()
    _init_identity_state(key_prefix, defaults, project_id)
    pending_city_key = _key(key_prefix, "pending_city")
    city_key = _key(key_prefix, "city")
    if pending_city_key in st.session_state:
        st.session_state[city_key] = str(st.session_state.pop(pending_city_key) or "")

    visible_core_fields = [
        options.show_project_name,
        options.show_airtable_id,
        options.show_client_name,
        options.show_analyst,
        options.show_project_date,
    ]
    if any(visible_core_fields):
        col_a, col_b = st.columns(2)
        with col_a:
            if options.show_project_name:
                st.text_input("Nom du projet", key=_key(key_prefix, "project_name"))
            if options.show_airtable_id:
                st.text_input(options.airtable_label, key=_key(key_prefix, "airtable_id"))
            if options.show_analyst:
                st.text_input("Analyste / rédacteur", key=_key(key_prefix, "analyst"))
        with col_b:
            if options.show_client_name:
                st.text_input(options.client_label, key=_key(key_prefix, "client_name"))
            if options.show_project_date:
                project_date_key = _key(key_prefix, "project_date")
                st.session_state[project_date_key] = _coerce_project_date(
                    st.session_state.get(project_date_key)
                )
                st.date_input("Date de l'étude", key=project_date_key)

    visible_location_fields = []
    if options.show_typology:
        visible_location_fields.append(("select", "Typologie d'établissement", "typology", options.typology_options))
    if options.show_building_state:
        visible_location_fields.append(("select", "Nature du bâtiment", "building_state", options.building_state_options))
    if options.show_region:
        visible_location_fields.append(("select", "Région", "region", options.region_options))
    if options.show_department:
        visible_location_fields.append(("select", "Département", "department", options.department_options))
    if options.show_city:
        visible_location_fields.append(("text", options.city_label, "city", ()))

    if visible_location_fields:
        columns = st.columns(min(3, len(visible_location_fields)))
        for index, (field_type, label, name, field_options) in enumerate(visible_location_fields):
            with columns[index % len(columns)]:
                if field_type == "select":
                    _render_select_or_text(label, key=_key(key_prefix, name), options=field_options)
                else:
                    st.text_input(label, key=_key(key_prefix, name))

    if options.show_address_search:
        with st.form(_key(key_prefix, "project_address_form"), clear_on_submit=False):
            address_query = st.text_input(
                "Adresse",
                placeholder="Ex. 10 rue de Strasbourg, 44000 Nantes",
                key=_key(key_prefix, "project_address_query"),
            )
            search_submitted = st.form_submit_button("Rechercher l'adresse", width="stretch")

        if search_submitted:
            try:
                with st.spinner("Recherche dans la Base Adresse Nationale..."):
                    st.session_state[_key(key_prefix, "project_address_candidates")] = _cached_project_address_search(address_query)
            except (GeocodingServiceError, ValueError) as exc:
                st.session_state[_key(key_prefix, "project_address_candidates")] = []
                st.error(str(exc))
            else:
                if not st.session_state[_key(key_prefix, "project_address_candidates")]:
                    st.warning("Aucune adresse correspondante n'a été trouvée.")

        candidates = st.session_state.get(_key(key_prefix, "project_address_candidates"), [])
        if candidates:
            selected_index = st.selectbox(
                "Adresse proposée",
                options=range(len(candidates)),
                format_func=lambda index: _candidate_label(candidates[index]),
                key=_key(key_prefix, "project_selected_address_candidate"),
            )
            selected_candidate = candidates[int(selected_index)]
            if st.button("Utiliser cette adresse", width="stretch", key=_key(key_prefix, "project_use_selected_address")):
                st.session_state[_key(key_prefix, "project_latitude")] = float(selected_candidate["latitude"])
                st.session_state[_key(key_prefix, "project_longitude")] = float(selected_candidate["longitude"])
                st.session_state[_key(key_prefix, "project_address_label")] = str(selected_candidate["label"])
                if selected_candidate.get("city"):
                    st.session_state[pending_city_key] = str(selected_candidate["city"])
                identity = _current_identity(key_prefix)
                if on_location_change is not None:
                    on_location_change(identity)
                st.rerun()

    identity = _current_identity(key_prefix)
    if options.show_map and identity.address:
        st.success(f"Adresse retenue : {identity.address}")
        map_state = st_folium(
            _project_map(identity.latitude, identity.longitude, identity.address),
            height=360,
            width="stretch",
            returned_objects=["last_clicked"],
            key=_key(key_prefix, "project_address_map"),
        )
        st.caption(options.map_caption)
        clicked = map_state.get("last_clicked") if isinstance(map_state, dict) else None
        if isinstance(clicked, dict) and clicked.get("lat") is not None and clicked.get("lng") is not None:
            clicked_latitude = float(clicked["lat"])
            clicked_longitude = float(clicked["lng"])
            if abs(clicked_latitude - identity.latitude) > 1e-7 or abs(clicked_longitude - identity.longitude) > 1e-7:
                st.session_state[_key(key_prefix, "project_latitude")] = clicked_latitude
                st.session_state[_key(key_prefix, "project_longitude")] = clicked_longitude
                identity = _current_identity(key_prefix)
                if on_location_change is not None:
                    on_location_change(identity)
                st.rerun()
        identity = _current_identity(key_prefix)
        coord_col_a, coord_col_b = st.columns(2)
        coord_col_a.metric("Latitude", f"{identity.latitude:.6f}")
        coord_col_b.metric("Longitude", f"{identity.longitude:.6f}")
    elif options.show_address_search:
        st.info(options.address_help)

    if options.show_weather:
        _render_weather_identity_fields(key_prefix, options)

    if options.show_notes:
        st.text_area("Commentaire projet", key=_key(key_prefix, "notes"), height=90)

    return _current_identity(key_prefix)


def _current_identity(prefix: str) -> ProjectIdentity:
    return ProjectIdentity(
        project_name=str(st.session_state.get(_key(prefix, "project_name")) or ""),
        client_name=str(st.session_state.get(_key(prefix, "client_name")) or ""),
        airtable_id=str(st.session_state.get(_key(prefix, "airtable_id")) or ""),
        analyst=str(st.session_state.get(_key(prefix, "analyst")) or ""),
        project_date=_coerce_project_date(st.session_state.get(_key(prefix, "project_date"))),
        typology=str(st.session_state.get(_key(prefix, "typology")) or ""),
        building_state=str(st.session_state.get(_key(prefix, "building_state")) or ""),
        region=str(st.session_state.get(_key(prefix, "region")) or ""),
        department=str(st.session_state.get(_key(prefix, "department")) or ""),
        city=str(st.session_state.get(_key(prefix, "city")) or ""),
        address=str(st.session_state.get(_key(prefix, "project_address_label")) or ""),
        latitude=float(st.session_state.get(_key(prefix, "project_latitude"), DEFAULT_PROJECT_LATITUDE)),
        longitude=float(st.session_state.get(_key(prefix, "project_longitude"), DEFAULT_PROJECT_LONGITUDE)),
        weather_region=str(st.session_state.get(_key(prefix, "weather_region")) or ""),
        weather_station=str(st.session_state.get(_key(prefix, "weather_station")) or ""),
        notes=str(st.session_state.get(_key(prefix, "notes")) or ""),
    )
