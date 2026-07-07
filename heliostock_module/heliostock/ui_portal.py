from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
HELIOPILOT_LOGO = ASSETS_DIR / "logo_heliopilot_v5.png"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"
PROJECTS_DIR = Path.home() / ".heliostock" / "projects"


SAVEABLE_WIDGET_KEYS = [
    "weather_tilt_deg",
    "weather_azimuth_deg_south",
    "weather_albedo",
    "weather_region",
    "weather_station",
    "process_bt_target_c",
    "process_ht_target_c",
    "solar_collector_name",
    "solar_area_m2",
    "solar_eta0",
    "solar_a1",
    "solar_a2",
    "solar_daily_buffer_ambient_temp_c",
    "solar_daily_buffer_max_temp_c",
    "geo_pac_power_fraction_pct",
    "geo_probe_unit_depth_m",
    "geo_boreholes",
    "geo_savings_method",
    "eco_eta_appoint",
    "eco_reference_energy_inflation_pct",
    "eco_reference_energy_cost_eur_mwh",
    "eco_electricity_cost_eur_mwh",
    "eco_auxiliary_electricity_ratio_pct",
    "eco_backup_p2_eur_kw_year",
    "param_pac_enabled",
    "param_pac_min_pct",
    "param_pac_max_pct",
    "param_pac_step_pct",
    "param_solar_enabled",
    "param_surface_min_m2",
    "param_surface_max_m2",
    "param_surface_step_m2",
]


def _configured_password() -> str:
    try:
        return str(st.secrets.get("HELIOSTOCK_PASSWORD", "") or "")
    except Exception:
        return ""


def _safe_project_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    slug = slug.strip("._-")
    return slug[:80] or "projet_heliostock"


def _project_files() -> list[Path]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(PROJECTS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def _project_label(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.stem
    return str(data.get("name") or path.stem)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _project_payload(name: str) -> dict[str, Any]:
    widget_values = {
        key: _jsonable(st.session_state[key])
        for key in SAVEABLE_WIDGET_KEYS
        if key in st.session_state
    }
    return {
        "schema_version": 1,
        "name": name.strip() or "Projet HelioStock",
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "app": "HelioStock",
        "widget_values": widget_values,
        "note": "Le fichier Excel de besoins horaires n'est pas stocke dans le projet.",
    }


def _load_project(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = data.get("widget_values", {})
    if not isinstance(values, dict):
        values = {}
    for key, value in values.items():
        if key in SAVEABLE_WIDGET_KEYS:
            st.session_state[key] = value
    st.session_state["heliostock_current_project_name"] = str(data.get("name") or path.stem)
    st.session_state.pop("heliostock_last_result", None)


def render_login_portal() -> bool:
    """Render the HelioPilot-like access portal and return authentication state."""

    if st.session_state.get("heliostock_authenticated"):
        return True

    left, center, right = st.columns([1, 1.2, 1])
    with center:
        if HELIOPILOT_LOGO.exists():
            st.image(str(HELIOPILOT_LOGO), use_container_width=True)
        st.title("Portail HelioTools")
        st.caption("Accede aux outils de pre-dimensionnement et retrouve tes projets sauvegardes.")
        user_name = st.text_input("Utilisateur", key="portal_user_name")
        configured_password = _configured_password()
        password = ""
        if configured_password:
            password = st.text_input("Mot de passe", type="password", key="portal_password")
        else:
            st.info("Aucun mot de passe Streamlit n'est configure : acces simplifie active.")

        if st.button("Se connecter", type="primary", use_container_width=True):
            if not user_name.strip():
                st.error("Renseigne un nom d'utilisateur.")
                return False
            if configured_password and password != configured_password:
                st.error("Mot de passe incorrect.")
                return False
            st.session_state["heliostock_authenticated"] = True
            st.session_state["heliostock_user_name"] = user_name.strip()
            st.rerun()

    return False


def render_portal_sidebar() -> str:
    """Render left navigation and project loading controls."""

    with st.sidebar:
        if HELIOPILOT_LOGO.exists():
            st.image(str(HELIOPILOT_LOGO), use_container_width=True)
        st.caption(f"Connecte : {st.session_state.get('heliostock_user_name', 'utilisateur')}")
        app_name = st.selectbox("Application", options=["HelioStock"], key="portal_app")

        st.markdown("### Projets")
        project_files = _project_files()
        if project_files:
            labels = [_project_label(path) for path in project_files]
            selected_label = st.selectbox("Projet sauvegarde", labels, key="portal_project_to_load")
            selected_index = labels.index(selected_label)
            selected_path = project_files[selected_index]
            c1, c2 = st.columns(2)
            if c1.button("Charger", use_container_width=True):
                _load_project(selected_path)
                st.success("Projet charge.")
                st.rerun()
            if c2.button("Supprimer", use_container_width=True):
                selected_path.unlink(missing_ok=True)
                st.session_state.pop("heliostock_current_project_name", None)
                st.rerun()
        else:
            st.info("Aucun projet sauvegarde.")

        st.caption(
            "Les projets sauvegardent les parametres d'interface. "
            "Le fichier Excel de besoins reste a recharger manuellement."
        )
        if st.button("Se deconnecter", use_container_width=True):
            st.session_state["heliostock_authenticated"] = False
            st.session_state.pop("heliostock_last_result", None)
            st.rerun()

    return app_name


def render_project_save_controls() -> None:
    """Render project save controls in the sidebar after widgets have been created."""

    with st.sidebar:
        st.markdown("### Enregistrer")
        default_name = st.session_state.get("heliostock_current_project_name", "")
        project_name = st.text_input("Nom du projet", value=str(default_name), key="portal_project_name")
        if st.button("Enregistrer le projet", type="primary", use_container_width=True):
            PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            payload = _project_payload(project_name)
            path = PROJECTS_DIR / f"{_safe_project_slug(str(payload['name']))}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            st.session_state["heliostock_current_project_name"] = str(payload["name"])
            st.success(f"Projet enregistre : {payload['name']}")
