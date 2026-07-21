from __future__ import annotations

import json
from typing import Any

import streamlit as st

from .architectural_patrimony_service import (
    CATEGORY_CONFIG,
    PatrimoineServiceError,
    analyse_patrimoine,
    compact_feature_properties,
)
from .architectural_static_map import StaticMapError, render_static_map
from .geocoding_service import GeocodingServiceError, search_addresses


DEFAULT_LATITUDE = 47.2184
DEFAULT_LONGITUDE = -1.5536
MAP_ZOOM = 17

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


def render_architectural_constraints_test(*, state_prefix: str = "shared") -> None:
    """Render a preliminary heritage constraint check for solar thermal projects."""

    _ensure_default_state(state_prefix)

    st.subheader("Test contraintes architecturales solaire thermique")
    st.caption(
        "Pré-vérification des servitudes patrimoniales AC1, AC2 et AC4 à partir des données du Géoportail de "
        "l'Urbanisme. Cette analyse ne vaut pas autorisation d'urbanisme ni avis de l'Architecte des bâtiments de France."
    )

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

    st.markdown("#### Carte")
    if selected_address or isinstance(result, dict):
        try:
            map_image = render_static_map(
                latitude=float(latitude),
                longitude=float(longitude),
                result=result if isinstance(result, dict) else None,
                address=selected_address,
                zoom=MAP_ZOOM,
                width=900,
                height=560,
            )
        except (StaticMapError, ValueError) as exc:
            st.error(f"Impossible de générer la carte : {exc}")
        else:
            st.image(
                map_image,
                width="stretch",
                caption=(
                    "Le marqueur rouge correspond au projet. Les protections détectées sont superposées lorsqu'une "
                    "géométrie est disponible."
                ),
            )
    else:
        st.caption("La carte s'affichera après sélection d'une adresse ou analyse du point.")

    if isinstance(result, dict):
        with st.expander("Détail des données patrimoniales", expanded=False):
            for category, config in CATEGORY_CONFIG.items():
                features = result["feature_collections"][category]["features"]
                if not features:
                    continue
                st.markdown(f"**{category} - {config['title']} ({len(features)})**")
                for index, feature in enumerate(features, start=1):
                    st.write(f"Objet {index}")
                    st.json(compact_feature_properties(feature))

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
