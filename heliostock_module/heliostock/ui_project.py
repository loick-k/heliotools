from __future__ import annotations

from dataclasses import dataclass

import folium
import streamlit as st
from streamlit_folium import st_folium

from .geocoding_service import GeocodingServiceError, search_addresses


DEFAULT_PROJECT_LATITUDE = 47.2184
DEFAULT_PROJECT_LONGITUDE = -1.5536


@dataclass(frozen=True)
class HelioStockProjectForm:
    project_name: str
    client_name: str
    airtable_id: str
    city: str
    address: str
    latitude: float
    longitude: float


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


def _propagate_project_location_to_checks() -> None:
    latitude = float(st.session_state.get("heliostock_project_latitude", DEFAULT_PROJECT_LATITUDE))
    longitude = float(st.session_state.get("heliostock_project_longitude", DEFAULT_PROJECT_LONGITUDE))
    address = str(st.session_state.get("heliostock_project_address_label") or "")

    st.session_state["gmi_address_query"] = address
    st.session_state["gmi_selected_address_label"] = address
    st.session_state["gmi_latitude"] = latitude
    st.session_state["gmi_longitude"] = longitude

    st.session_state["heliostock_architectural_selected_address"] = address
    st.session_state["heliostock_architectural_latitude"] = latitude
    st.session_state["heliostock_architectural_longitude"] = longitude


def render_heliostock_project_form() -> HelioStockProjectForm:
    """Render the HelioStock project identity and shared address block."""

    st.subheader("Projet")
    st.caption(
        "Ces informations décrivent le projet étudié. L'adresse retenue est réutilisée par la vérification GMI "
        "et par le test de contraintes architecturales."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        project_name = st.text_input("Nom du projet", key="heliostock_project_name")
        airtable_id = st.text_input("ID Airtable", key="heliostock_airtable_id")
    with col_b:
        client_name = st.text_input("Maître d'ouvrage", key="heliostock_client_name")
        city = st.text_input("Commune", key="heliostock_city")

    with st.form("heliostock_project_address_form", clear_on_submit=False):
        address_query = st.text_input(
            "Adresse",
            placeholder="Ex. 10 rue de Strasbourg, 44000 Nantes",
            key="heliostock_project_address_query",
        )
        search_submitted = st.form_submit_button("Rechercher l'adresse", width="stretch")

    if search_submitted:
        try:
            with st.spinner("Recherche dans la Base Adresse Nationale..."):
                st.session_state["heliostock_project_address_candidates"] = _cached_project_address_search(address_query)
        except (GeocodingServiceError, ValueError) as exc:
            st.session_state["heliostock_project_address_candidates"] = []
            st.error(str(exc))
        else:
            if not st.session_state["heliostock_project_address_candidates"]:
                st.warning("Aucune adresse correspondante n'a été trouvée.")

    candidates = st.session_state.get("heliostock_project_address_candidates", [])
    if candidates:
        selected_index = st.selectbox(
            "Adresse proposée",
            options=range(len(candidates)),
            format_func=lambda index: _candidate_label(candidates[index]),
            key="heliostock_project_selected_address_candidate",
        )
        selected_candidate = candidates[int(selected_index)]
        if st.button("Utiliser cette adresse", width="stretch", key="heliostock_project_use_selected_address"):
            st.session_state["heliostock_project_latitude"] = float(selected_candidate["latitude"])
            st.session_state["heliostock_project_longitude"] = float(selected_candidate["longitude"])
            st.session_state["heliostock_project_address_label"] = str(selected_candidate["label"])
            if selected_candidate.get("city"):
                st.session_state["heliostock_city"] = str(selected_candidate["city"])
            st.session_state.pop("gmi_result", None)
            st.session_state.pop("heliostock_architectural_result", None)
            _propagate_project_location_to_checks()
            st.rerun()

    latitude = float(st.session_state.get("heliostock_project_latitude", DEFAULT_PROJECT_LATITUDE))
    longitude = float(st.session_state.get("heliostock_project_longitude", DEFAULT_PROJECT_LONGITUDE))
    address = str(st.session_state.get("heliostock_project_address_label") or "")
    if address:
        st.success(f"Adresse retenue : {address}")
        _propagate_project_location_to_checks()
        st_folium(
            _project_map(latitude, longitude, address),
            height=360,
            width="stretch",
            returned_objects=[],
            key="heliostock_project_address_map",
        )
    else:
        st.info("Recherche une adresse pour alimenter automatiquement les blocs GMI et contraintes architecturales.")

    return HelioStockProjectForm(
        project_name=str(project_name or ""),
        client_name=str(client_name or ""),
        airtable_id=str(airtable_id or ""),
        city=str(city or ""),
        address=address,
        latitude=latitude,
        longitude=longitude,
    )
