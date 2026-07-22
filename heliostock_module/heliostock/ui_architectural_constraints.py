from __future__ import annotations

import json
from typing import Any

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from .architectural_patrimony_service import (
    CATEGORY_CONFIG,
    PatrimoineServiceError,
    analyse_patrimoine,
    compact_feature_properties,
)
from .geocoding_service import GeocodingServiceError, search_addresses


DEFAULT_LATITUDE = 47.2184
DEFAULT_LONGITUDE = -1.5536
MAP_ZOOM = 17

CATEGORY_MAP_COLORS = {
    "AC1": "#c026d3",
    "AC2": "#15803d",
    "AC4": "#2563eb",
}

PROJECT_TYPES = (
    "Capteurs intégrés ou surimposés sur toiture inclinée",
    "Capteurs sur toiture-terrasse",
    "Capteurs au sol",
)


@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_architectural_address_search(query: str) -> list[dict[str, object]]:
    return search_addresses(query=query, limit=5)


@st.cache_data(ttl=3_600, show_spinner=False)
def _cached_architectural_analysis(latitude: float, longitude: float) -> dict[str, Any]:
    return analyse_patrimoine(latitude=latitude, longitude=longitude)


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


def _state_key(prefix: str, name: str) -> str:
    return f"{prefix}_architectural_{name}"


def _ensure_default_state(prefix: str) -> None:
    defaults = {
        "latitude": DEFAULT_LATITUDE,
        "longitude": DEFAULT_LONGITUDE,
        "address_candidates": [],
        "selected_address": "",
        "result": None,
    }
    for name, value in defaults.items():
        st.session_state.setdefault(_state_key(prefix, name), value)


def _coordinates_changed(prefix: str) -> None:
    st.session_state[_state_key(prefix, "selected_address")] = ""
    st.session_state[_state_key(prefix, "result")] = None


def _render_category_status(result: dict[str, Any]) -> None:
    for category, config in CATEGORY_CONFIG.items():
        count = int(result.get("counts", {}).get(category, 0))
        title = str(config.get("title", category))
        if count:
            st.warning(f"**{category} - {title} : détectée** ({count} objet{'s' if count > 1 else ''})")
        else:
            st.write(f"OK - **{category} - {title} : non détectée**")


def _render_interpretation(result: dict[str, Any], project_type: str) -> None:
    if result.get("has_protection"):
        st.warning(
            "Une ou plusieurs protections patrimoniales sont détectées au droit du point. "
            "Le projet solaire thermique doit être vérifié auprès de la mairie et, selon le cas, de l'UDAP ou de l'ABF."
        )
        if str(project_type).startswith("Capteurs au sol"):
            st.caption(
                "Points de vigilance : visibilité depuis l'espace public, points de vue protégés, insertion paysagère "
                "et emprise au sol."
            )
        else:
            st.caption(
                "Points de vigilance : visibilité des capteurs, teinte, implantation, saillie, regroupement sur toiture "
                "et cohérence avec le bâtiment existant."
            )
    elif result.get("errors"):
        st.warning(
            "Aucune protection n'a été détectée dans les réponses reçues, mais certaines interrogations ont échoué. "
            "Le résultat doit être considéré comme incomplet."
        )
    else:
        st.success(
            "Aucune servitude AC1, AC2 ou AC4 n'a été détectée au droit du point dans les données interrogées."
        )


def _iter_result_features(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    collections = result.get("feature_collections")
    if not isinstance(collections, dict):
        return []
    features: list[dict[str, Any]] = []
    for category in CATEGORY_CONFIG:
        collection = collections.get(category)
        if not isinstance(collection, dict):
            continue
        for feature in collection.get("features", []):
            if isinstance(feature, dict):
                features.append(feature)
    return features


def _feature_popup_html(feature: dict[str, Any]) -> str:
    properties = dict(feature.get("properties") or {})
    title = str(properties.get("_display_title") or properties.get("_category_title") or "Protection patrimoniale")
    category = str(properties.get("_category") or "")
    details = str(properties.get("_display_details") or "")
    endpoint = str(properties.get("_source_endpoint") or "")
    parts = [f"<b>{category} - {title}</b>" if category else f"<b>{title}</b>"]
    if details and details != title:
        parts.append(details)
    if endpoint:
        parts.append(f"Source GPU : {endpoint}")
    return "<br>".join(parts)


def _build_architectural_map(
    *,
    latitude: float,
    longitude: float,
    address: str,
    result: dict[str, Any] | None,
) -> folium.Map:
    map_object = folium.Map(
        location=[latitude, longitude],
        zoom_start=MAP_ZOOM,
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.Marker(
        [latitude, longitude],
        tooltip=address or "Projet",
        popup=folium.Popup(f"<b>{address or 'Projet'}</b><br>{latitude:.6f}, {longitude:.6f}", max_width=280),
        icon=folium.Icon(color="red", icon="info-sign"),
    ).add_to(map_object)

    bounds: list[list[float]] = [[latitude, longitude]]
    has_geojson_layer = False
    for feature in _iter_result_features(result):
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        category = str((feature.get("properties") or {}).get("_category") or "")
        color = CATEGORY_MAP_COLORS.get(category, "#64748b")
        layer = folium.GeoJson(
            feature,
            name=f"{category} - {CATEGORY_CONFIG.get(category, {}).get('short_title', 'Protection')}",
            style_function=lambda _feature, color=color: {
                "fillColor": color,
                "color": color,
                "weight": 2,
                "fillOpacity": 0.22,
            },
            marker=folium.CircleMarker(
                radius=7,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.75,
            ),
            tooltip=folium.Tooltip(_feature_popup_html(feature), sticky=True),
            popup=folium.Popup(_feature_popup_html(feature), max_width=360),
        )
        layer.add_to(map_object)
        has_geojson_layer = True
        try:
            feature_bounds = layer.get_bounds()
        except Exception:
            feature_bounds = []
        for point in feature_bounds or []:
            if isinstance(point, list) and len(point) >= 2:
                bounds.append([float(point[0]), float(point[1])])

    folium.Circle(
        [latitude, longitude],
        radius=25,
        color="#ef4444",
        fill=False,
        weight=2,
        tooltip="Repère projet",
    ).add_to(map_object)

    if has_geojson_layer:
        folium.LayerControl(collapsed=False).add_to(map_object)
    if len(bounds) > 1:
        map_object.fit_bounds(bounds, padding=(24, 24))
    return map_object


def render_architectural_constraints_test(
    *,
    state_prefix: str = "shared",
    show_address_inputs: bool = True,
    show_map: bool = True,
) -> None:
    """Render a preliminary heritage constraint check for solar thermal projects."""

    _ensure_default_state(state_prefix)

    st.subheader("Test contraintes architecturales solaire thermique")
    st.caption(
        "Pré-vérification des servitudes patrimoniales AC1, AC2 et AC4 à partir des données du Géoportail de "
        "l'Urbanisme. Cette analyse ne vaut pas autorisation d'urbanisme ni avis de l'Architecte des bâtiments de France."
    )

    if show_address_inputs:
        with st.form(f"{state_prefix}_architectural_address_form", clear_on_submit=False):
            address_query = st.text_input(
                "Adresse du projet",
                placeholder="Ex. 10 rue de Strasbourg, 44000 Nantes",
                key=_state_key(state_prefix, "address_query"),
            )
            search_submitted = st.form_submit_button("Rechercher l'adresse", width="stretch")

        if search_submitted:
            try:
                with st.spinner("Recherche de l'adresse..."):
                    st.session_state[_state_key(state_prefix, "address_candidates")] = _cached_architectural_address_search(
                        address_query
                    )
            except (GeocodingServiceError, ValueError) as exc:
                st.session_state[_state_key(state_prefix, "address_candidates")] = []
                st.error(str(exc))
            else:
                if not st.session_state[_state_key(state_prefix, "address_candidates")]:
                    st.warning("Aucune adresse correspondante n'a été trouvée.")

        candidates = st.session_state.get(_state_key(state_prefix, "address_candidates"), [])
        if candidates:
            selected_index = st.selectbox(
                "Adresse proposée",
                options=range(len(candidates)),
                format_func=lambda index: _candidate_label(candidates[index]),
                key=_state_key(state_prefix, "selected_address_candidate"),
            )
            if st.button("Utiliser cette adresse", width="stretch", key=_state_key(state_prefix, "use_selected_address")):
                candidate = candidates[int(selected_index)]
                st.session_state[_state_key(state_prefix, "latitude")] = float(candidate["latitude"])
                st.session_state[_state_key(state_prefix, "longitude")] = float(candidate["longitude"])
                st.session_state[_state_key(state_prefix, "selected_address")] = str(candidate["label"])
                st.session_state[_state_key(state_prefix, "result")] = None
                st.rerun()

    selected_address = str(st.session_state.get(_state_key(state_prefix, "selected_address")) or "")
    if selected_address:
        st.success(f"Adresse retenue : {selected_address}")

    if show_address_inputs:
        with st.expander("Saisie manuelle des coordonnées", expanded=False):
            col_lat, col_lon = st.columns(2)
            latitude = col_lat.number_input(
                "Latitude",
                min_value=-90.0,
                max_value=90.0,
                format="%.7f",
                key=_state_key(state_prefix, "latitude"),
                on_change=_coordinates_changed,
                args=(state_prefix,),
            )
            longitude = col_lon.number_input(
                "Longitude",
                min_value=-180.0,
                max_value=180.0,
                format="%.7f",
                key=_state_key(state_prefix, "longitude"),
                on_change=_coordinates_changed,
                args=(state_prefix,),
            )

    else:
        latitude = float(st.session_state.get(_state_key(state_prefix, "latitude"), DEFAULT_LATITUDE))
        longitude = float(st.session_state.get(_state_key(state_prefix, "longitude"), DEFAULT_LONGITUDE))
    st.write(f"**Coordonnées :** {float(latitude):.7f}, {float(longitude):.7f}")

    project_type = st.selectbox(
        "Configuration envisagée",
        options=PROJECT_TYPES,
        key=_state_key(state_prefix, "project_type"),
    )

    if st.button(
        "Analyser les contraintes patrimoniales",
        type="primary",
        width="stretch",
        key=_state_key(state_prefix, "run_analysis"),
    ):
        try:
            with st.spinner("Interrogation des servitudes patrimoniales du Géoportail de l'Urbanisme..."):
                st.session_state[_state_key(state_prefix, "result")] = _cached_architectural_analysis(
                    round(float(latitude), 7),
                    round(float(longitude), 7),
                )
        except (PatrimoineServiceError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.rerun()

    result = st.session_state.get(_state_key(state_prefix, "result"))
    if isinstance(result, dict):
        _render_interpretation(result, project_type)
        _render_category_status(result)
        st.write(f"**Configuration étudiée :** {project_type}")

        if result.get("errors"):
            with st.expander("Erreurs techniques", expanded=False):
                for error in result["errors"]:
                    st.write(f"- {error}")

    if show_map:
        st.markdown("#### Carte")
    if show_map and (selected_address or isinstance(result, dict)):
        map_key = (
            f"{_state_key(state_prefix, 'map')}_"
            f"{float(latitude):.5f}_{float(longitude):.5f}_{1 if isinstance(result, dict) else 0}"
        )
        st_folium(
            _build_architectural_map(
                latitude=float(latitude),
                longitude=float(longitude),
                address=selected_address,
                result=result if isinstance(result, dict) else None,
            ),
            height=420,
            # Folium peut mal s'initialiser dans un onglet Streamlit caché si
            # la largeur du conteneur vaut 0. Une largeur explicite rend le
            # premier chargement fiable, sans attendre un redimensionnement.
            width=1000,
            returned_objects=[],
            key=map_key,
        )
        st.caption(
            "Le marqueur rouge correspond au projet. Les protections détectées sont superposées lorsqu'une "
            "géométrie est disponible."
        )
    elif show_map:
        st.caption("La carte s'affichera après sélection d'une adresse ou analyse du point.")

    if isinstance(result, dict):
        with st.expander("Détail des données patrimoniales", expanded=False):
            counts_df = pd.DataFrame(
                [
                    {
                        "Catégorie": category,
                        "Protection": str(config["title"]),
                        "Objets détectés": int(result.get("counts", {}).get(category, 0)),
                    }
                    for category, config in CATEGORY_CONFIG.items()
                ]
            )
            st.dataframe(counts_df, width="stretch", hide_index=True)
            displayed_feature_count = 0
            for category, config in CATEGORY_CONFIG.items():
                features = result["feature_collections"][category]["features"]
                if not features:
                    continue
                displayed_feature_count += len(features)
                st.markdown(f"**{category} - {config['title']} ({len(features)})**")
                for index, feature in enumerate(features, start=1):
                    st.write(f"Objet {index}")
                    st.json(compact_feature_properties(feature))
            if displayed_feature_count == 0:
                st.info(
                    "Aucune protection patrimoniale AC1, AC2 ou AC4 n'a été retournée au droit du point interrogé."
                )
            query_scope = result.get("query_scope")
            if isinstance(query_scope, dict):
                st.caption(
                    "Périmètre interrogé : "
                    + " ; ".join(f"{key} = {value}" for key, value in query_scope.items())
                )

        export_payload = {
            "address": selected_address,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "project_type": project_type,
            "analysis": result,
        }
        st.download_button(
            "Télécharger le résultat JSON",
            data=json.dumps(export_payload, ensure_ascii=False, indent=2, default=str),
            file_name="analyse_contraintes_architecturales_solaire.json",
            mime="application/json",
            width="stretch",
        )

    col_atlas, col_gpu = st.columns(2)
    with col_atlas:
        st.link_button("Ouvrir l'Atlas des patrimoines", "https://atlas.patrimoines.culture.fr/", width="stretch")
    with col_gpu:
        st.link_button(
            "Ouvrir le Géoportail de l'Urbanisme",
            "https://www.geoportail-urbanisme.gouv.fr/",
            width="stretch",
        )
