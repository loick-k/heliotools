"""Composants Streamlit pour la bibliothèque capteurs partagée."""

from __future__ import annotations

import streamlit as st

from .collector_library import CollectorReference, build_collector_library, collector_key, make_collector_reference


def _custom_collectors_state_key(key_prefix: str) -> str:
    # La bibliothèque ajoutée par l'utilisateur est partagée entre les modules.
    # Le préfixe ne sert qu'aux clés des widgets de saisie.
    return "heliotools_custom_collectors"


def get_session_custom_collectors(key_prefix: str = "heliotools") -> dict[str, CollectorReference]:
    raw = st.session_state.setdefault(_custom_collectors_state_key(key_prefix), {})
    if isinstance(raw, dict):
        return raw
    st.session_state[_custom_collectors_state_key(key_prefix)] = {}
    return st.session_state[_custom_collectors_state_key(key_prefix)]


def get_session_collector_library(key_prefix: str = "heliotools") -> dict[str, CollectorReference]:
    return build_collector_library(get_session_custom_collectors(key_prefix))


def render_add_collector_expander(key_prefix: str = "heliotools") -> dict[str, CollectorReference]:
    """Render a small UI to add a collector to the shared session library."""

    custom_collectors = get_session_custom_collectors(key_prefix)
    with st.expander("Ajouter un capteur à la bibliothèque", expanded=False):
        st.caption(
            "Le capteur ajouté est disponible dans les modules ouverts pendant la session. "
            "Il sera aussi sauvegardé dans le projet si le module stocke le nom et les coefficients retenus."
        )
        c1, c2 = st.columns(2)
        manufacturer = c1.text_input("Fabricant", key=f"{key_prefix}_new_collector_manufacturer")
        model = c2.text_input("Modèle", key=f"{key_prefix}_new_collector_model")
        c3, c4, c5, c6 = st.columns(4)
        area_m2 = c3.number_input("Surface utile (m²)", min_value=0.01, value=2.32, step=0.01, key=f"{key_prefix}_new_collector_area_m2")
        eta0 = c4.number_input("eta0", min_value=0.0, max_value=1.0, value=0.75, step=0.001, format="%.3f", key=f"{key_prefix}_new_collector_eta0")
        a1 = c5.number_input("a1 (W/m²/K)", min_value=0.0, value=3.5, step=0.001, format="%.3f", key=f"{key_prefix}_new_collector_a1")
        a2 = c6.number_input("a2 (W/m²/K²)", min_value=0.0, value=0.015, step=0.001, format="%.3f", key=f"{key_prefix}_new_collector_a2")
        notes = st.text_input("Source / note courte", key=f"{key_prefix}_new_collector_notes")

        if st.button("Ajouter ce capteur", key=f"{key_prefix}_add_collector"):
            try:
                collector = make_collector_reference(
                    manufacturer=manufacturer,
                    model=model,
                    area_m2=float(area_m2),
                    eta0=float(eta0),
                    a1_w_m2_k=float(a1),
                    a2_w_m2_k2=float(a2),
                    notes=notes,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                custom_collectors[collector_key(collector.manufacturer, collector.model)] = collector
                st.success(f"Capteur ajouté : {collector.label}")

    return get_session_collector_library(key_prefix)
