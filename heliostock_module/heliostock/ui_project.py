from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from .common.project_identity import (
    DEFAULT_PROJECT_DEPARTMENTS,
    DEFAULT_PROJECT_LATITUDE,
    DEFAULT_PROJECT_LONGITUDE,
    DEFAULT_PROJECT_REGIONS,
    DEFAULT_SITE_TYPOLOGIES,
    ProjectIdentity,
    ProjectIdentityOptions,
    render_project_identity_form,
)
from .ui_inputs import DEFAULT_EPW_REGIONS, WEATHER_STATION_LABEL_ALIASES


@dataclass(frozen=True)
class HelioStockProjectForm:
    project_name: str
    client_name: str
    airtable_id: str
    analyst: str
    project_date: object
    typology: str
    region: str
    department: str
    city: str
    address: str
    latitude: float
    longitude: float
    weather_region: str
    weather_station: str


def _propagate_project_location_to_checks(identity: ProjectIdentity | None = None) -> None:
    if identity is None:
        latitude = float(st.session_state.get("heliostock_project_latitude", DEFAULT_PROJECT_LATITUDE))
        longitude = float(st.session_state.get("heliostock_project_longitude", DEFAULT_PROJECT_LONGITUDE))
        address = str(st.session_state.get("heliostock_project_address_label") or "")
    else:
        latitude = identity.latitude
        longitude = identity.longitude
        address = identity.address

    st.session_state["gmi_address_query"] = address
    st.session_state["gmi_selected_address_label"] = address
    st.session_state["gmi_latitude"] = latitude
    st.session_state["gmi_longitude"] = longitude

    st.session_state["heliostock_architectural_selected_address"] = address
    st.session_state["heliostock_architectural_latitude"] = latitude
    st.session_state["heliostock_architectural_longitude"] = longitude


def _propagate_project_weather(identity: ProjectIdentity) -> None:
    if identity.weather_region:
        st.session_state["weather_region"] = identity.weather_region
    if identity.weather_station:
        st.session_state["weather_station"] = identity.weather_station


def _on_location_change(identity: ProjectIdentity) -> None:
    st.session_state.pop("gmi_result", None)
    st.session_state.pop("heliostock_architectural_result", None)
    st.session_state.pop("heliostock_architectural_analysed_at", None)
    st.session_state.pop("heliostock_architectural_analysis_latitude", None)
    st.session_state.pop("heliostock_architectural_analysis_longitude", None)
    _propagate_project_location_to_checks(identity)
    _propagate_project_weather(identity)


def render_heliostock_project_form() -> HelioStockProjectForm:
    """Render the shared project identity block used by HelioStock."""

    st.subheader("Projet")
    st.caption(
        "Ces informations décrivent le projet étudié. L'adresse retenue est réutilisée par la vérification GMI "
        "et par le test de contraintes architecturales."
    )

    identity = render_project_identity_form(
        key_prefix="heliostock",
        defaults=ProjectIdentity(
            project_name=str(st.session_state.get("heliostock_project_name") or ""),
            client_name=str(st.session_state.get("heliostock_client_name") or ""),
            airtable_id=str(st.session_state.get("heliostock_airtable_id") or ""),
            analyst=str(st.session_state.get("heliostock_analyst") or ""),
            project_date=st.session_state.get("heliostock_project_date"),
            typology=str(st.session_state.get("heliostock_typology") or "Industrie"),
            region=str(st.session_state.get("heliostock_region") or "Bretagne"),
            department=str(st.session_state.get("heliostock_department") or "35 - Ille-et-Vilaine"),
            city=str(st.session_state.get("heliostock_city") or ""),
            address=str(st.session_state.get("heliostock_project_address_label") or ""),
            latitude=float(st.session_state.get("heliostock_project_latitude", DEFAULT_PROJECT_LATITUDE)),
            longitude=float(st.session_state.get("heliostock_project_longitude", DEFAULT_PROJECT_LONGITUDE)),
            weather_region=str(st.session_state.get("weather_region") or "Bretagne"),
            weather_station=str(st.session_state.get("weather_station") or "Rennes"),
        ),
        options=ProjectIdentityOptions(
            show_analyst=True,
            show_project_date=True,
            show_typology=True,
            show_region=True,
            show_department=True,
            show_weather=True,
            typology_options=DEFAULT_SITE_TYPOLOGIES,
            region_options=DEFAULT_PROJECT_REGIONS,
            department_options=DEFAULT_PROJECT_DEPARTMENTS,
            weather_regions=DEFAULT_EPW_REGIONS,
            weather_station_aliases=WEATHER_STATION_LABEL_ALIASES,
            client_label="Maître d'ouvrage",
            address_help="Recherche une adresse pour alimenter automatiquement les blocs GMI et contraintes architecturales.",
            map_caption=(
                "Clique sur la carte pour déplacer le point exact du projet. Les contrôles GMI et patrimoniaux "
                "utiliseront ce point."
            ),
        ),
        on_location_change=_on_location_change,
    )
    if identity.address:
        _propagate_project_location_to_checks(identity)
    _propagate_project_weather(identity)

    return HelioStockProjectForm(
        project_name=identity.project_name,
        client_name=identity.client_name,
        airtable_id=identity.airtable_id,
        analyst=identity.analyst,
        project_date=identity.project_date,
        typology=identity.typology,
        region=identity.region,
        department=identity.department,
        city=identity.city,
        address=identity.address,
        latitude=identity.latitude,
        longitude=identity.longitude,
        weather_region=identity.weather_region,
        weather_station=identity.weather_station,
    )
