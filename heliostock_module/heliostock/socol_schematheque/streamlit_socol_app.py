from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import streamlit as st

from .socol_engine import (
    BACKUP_ENERGIES,
    BACKUP_TYPES,
    CIRCUITS,
    ECS_PRODUCTION_TYPES,
    EXCHANGERS,
    LOOP_TYPES,
    STORAGE_FLUIDS,
    TANK_COUNTS,
    ComponentCatalog,
    Selection,
    closest_valid_selections,
    compose_diagram,
    configuration_payload,
    image_to_png_bytes,
    resolve_diagram,
)


ROOT = Path(__file__).resolve().parent
SESSION_PREFIX = "socol_"


@st.cache_resource
def _load_catalog() -> ComponentCatalog:
    return ComponentCatalog(ROOT)


def _key(name: str) -> str:
    return f"{SESSION_PREFIX}{name}"


def _selection_defaults() -> dict[str, str]:
    return asdict(Selection())


def _init_selection_state() -> None:
    for name, value in _selection_defaults().items():
        st.session_state.setdefault(_key(name), value)


def _reset_selection() -> None:
    for name, value in _selection_defaults().items():
        st.session_state[_key(name)] = value


def _selectbox(label: str, options: tuple[str, ...], name: str) -> str:
    current = st.session_state.get(_key(name))
    index = options.index(current) if current in options else 0
    return st.selectbox(label, options, index=index, key=_key(name))


def _render_styles() -> None:
    st.markdown(
        """
        <style>
          .socol-kicker {
            font-size: .78rem;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: #486DAC;
            font-weight: 700;
            margin-bottom: .15rem;
          }
          .socol-title {
            font-size: 2rem;
            line-height: 1.15;
            font-weight: 760;
            color: #2d3040;
            margin: 0 0 .35rem 0;
          }
          .socol-subtitle {
            font-size: 1rem;
            color: #707684;
            margin-bottom: .8rem;
          }
          .socol-card {
            border: 1px solid #d8e2ea;
            border-radius: 8px;
            padding: .85rem 1rem;
            background: #fbfdfe;
            min-height: 116px;
          }
          .socol-label {
            font-size: .75rem;
            text-transform: uppercase;
            letter-spacing: .06em;
            color: #557382;
            font-weight: 700;
          }
          .socol-code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: .91rem;
            color: #163a4b;
            margin-top: .4rem;
            overflow-wrap: anywhere;
          }
          .socol-pill-ok {
            display:inline-block;
            border-radius:999px;
            padding:.25rem .65rem;
            background:#e6f6ed;
            color:#176a3a;
            font-weight:700;
            font-size:.82rem;
          }
          .socol-pill-ko {
            display:inline-block;
            border-radius:999px;
            padding:.25rem .65rem;
            background:#fff0ec;
            color:#a43b22;
            font-weight:700;
            font-size:.82rem;
          }
          .socol-note {
            font-size:.78rem;
            color:#6c7d85;
            border-top:1px solid #e1e8ec;
            margin-top:1.5rem;
            padding-top:.8rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_socol_schematheque_app() -> None:
    """Render the SOCOL dynamic solar thermal schematics module."""

    _render_styles()
    _init_selection_state()
    catalog = _load_catalog()

    header_left, header_right = st.columns([5, 1.2], vertical_alignment="center")
    with header_left:
        st.markdown('<div class="socol-title">Schémathèque SOCOL solaire thermique</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="socol-subtitle">Sélectionnez les caractéristiques de l’installation : le schéma est recomposé automatiquement à partir des briques du classeur SOCOL.</div>',
            unsafe_allow_html=True,
        )
    with header_right:
        logo = ROOT / "assets" / "socol_logo.jpg"
        if not logo.exists():
            logo = ROOT / "assets" / "socol_logo.png"
        if logo.exists():
            st.image(str(logo), width="stretch")

    with st.container(border=True):
        c0, c1, c2, c3 = st.columns([1.15, 1.15, 1.35, 1.0])
        with c0:
            st.markdown("**1. Circuit solaire**")
            circuit = _selectbox("Circuit", CIRCUITS, "circuit")
            exchanger = _selectbox("Échangeur", EXCHANGERS, "exchanger")
        with c1:
            st.markdown("**2. Appoint**")
            backup_energy = _selectbox("Énergie de l’appoint", BACKUP_ENERGIES, "backup_energy")
            backup_type = _selectbox("Position de l’appoint", BACKUP_TYPES, "backup_type")
        with c2:
            st.markdown("**3. Stockage**")
            storage_fluid = _selectbox("Fluide de stockage", STORAGE_FLUIDS, "storage_fluid")
            tank_count = _selectbox("Nombre de ballons", TANK_COUNTS, "tank_count")
            if storage_fluid == STORAGE_FLUIDS[1]:
                ecs_production = _selectbox(
                    "Production d’ECS depuis l’eau technique",
                    ECS_PRODUCTION_TYPES,
                    "ecs_production",
                )
            else:
                ecs_production = ECS_PRODUCTION_TYPES[1]
                st.session_state[_key("ecs_production")] = ecs_production
        with c3:
            st.markdown("**4. Bouclage**")
            loop_type = _selectbox("Configuration", LOOP_TYPES, "loop_type")
            st.write("")
            st.button("Réinitialiser", on_click=_reset_selection, width="stretch")

    selection = Selection(
        circuit=circuit,
        exchanger=exchanger,
        backup_energy=backup_energy,
        storage_fluid=storage_fluid,
        backup_type=backup_type,
        tank_count=tank_count,
        ecs_production=ecs_production,
        loop_type=loop_type,
    )
    result = resolve_diagram(selection, catalog)
    diagram = compose_diagram(result)
    png_bytes = image_to_png_bytes(diagram)
    payload = configuration_payload(result, catalog)

    if not result.valid:
        st.markdown('<div class="socol-pill-ko">Configuration non référencée</div>', unsafe_allow_html=True)
        invalid_parts = [
            label
            for label, component in (
                ("production", result.production),
                ("stockage", result.storage),
                ("distribution", result.distribution),
            )
            if not component.valid
        ]
        st.error(
            "Cette combinaison ne possède pas de brique SOCOL référencée pour : "
            + ", ".join(invalid_parts)
            + ". L’image d’erreur du classeur source est affichée à la place."
        )
        with st.expander("Voir des configurations proches disponibles"):
            suggestions = closest_valid_selections(selection, catalog, limit=5)
            for distance, suggestion in suggestions:
                fields = asdict(suggestion)
                changes = [
                    f"**{key.replace('_', ' ')}** → {value}"
                    for key, value in fields.items()
                    if value != asdict(selection)[key]
                ]
                st.markdown(f"**{distance} modification(s)** — " + " ; ".join(changes))

    st.image(diagram, width="stretch")

    button_left, button_middle, button_right = st.columns([1, 1, 2.2])
    with button_left:
        st.download_button(
            "Télécharger le schéma PNG",
            data=png_bytes,
            file_name="schema_solaire_thermique.png",
            mime="image/png",
            width="stretch",
        )
    with button_middle:
        st.download_button(
            "Télécharger la configuration JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="configuration_schema_solaire.json",
            mime="application/json",
            width="stretch",
        )
    with button_right:
        st.caption(
            f"Image recomposée : {diagram.width} x {diagram.height} px - "
            f"source ligne(s) {result.production.source_row}, {result.storage.source_row}, {result.distribution.source_row}."
        )

    with st.expander("Détail de la configuration"):
        left, right = st.columns(2)
        with left:
            st.markdown("**Choix utilisateur**")
            st.json(asdict(selection), expanded=True)
        with right:
            st.markdown("**Résolution dans la schémathèque**")
            st.json(payload["resolved_components"], expanded=True)

    st.markdown(
        """
        <div class="socol-note">
          Prototype non officiel réalisé à partir du classeur « SélectionSchemaCompresse » SOCOL, version 1.1 du 7 mars 2024, fourni avec la demande.
          Il reproduit la logique de sélection et l’assemblage des briques graphiques du classeur ; il ne constitue ni une validation de conception, ni une étude hydraulique, ni un document d’exécution.
        </div>
        """,
        unsafe_allow_html=True,
    )
