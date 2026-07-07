from __future__ import annotations

import json
import pickle
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
    "airtable_api_key",
    "airtable_base_id",
    "airtable_table_id",
    "dashboard_google_api_key",
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


def _secret_value(name: str) -> str:
    try:
        return str(st.secrets.get(name, "") or "")
    except Exception:
        return ""


def _admin_email() -> str:
    return _secret_value("HELIOSTOCK_ADMIN_EMAIL")


def _admin_password() -> str:
    return _secret_value("HELIOSTOCK_ADMIN_PASSWORD")


def is_admin_authenticated() -> bool:
    return bool(st.session_state.get("heliostock_admin_authenticated"))


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


def _project_sidecar_paths(path: Path) -> tuple[Path, Path]:
    stem = path.with_suffix("")
    return (
        stem.with_name(f"{stem.name}_besoins.xlsx"),
        stem.with_name(f"{stem.name}_resultat.pkl"),
    )


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
        "schema_version": 2,
        "name": name.strip() or "Projet HelioStock",
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "app": "HelioStock",
        "widget_values": widget_values,
        "has_demand_excel": bool(st.session_state.get("heliostock_demand_file_bytes")),
        "has_cached_result": bool(st.session_state.get("heliostock_last_result")),
        "note": "Le fichier Excel de besoins horaires et le dernier resultat calcule sont stockes avec le projet.",
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
    demand_path, result_path = _project_sidecar_paths(path)
    if demand_path.exists():
        st.session_state["heliostock_demand_file_bytes"] = demand_path.read_bytes()
        st.session_state["heliostock_demand_file_name"] = demand_path.name
    else:
        st.session_state.pop("heliostock_demand_file_bytes", None)
        st.session_state.pop("heliostock_demand_file_name", None)
    if result_path.exists():
        with result_path.open("rb") as handle:
            st.session_state["heliostock_last_result"] = pickle.load(handle)
    else:
        st.session_state.pop("heliostock_last_result", None)


def render_admin_login(*, compact: bool = False) -> bool:
    """Render admin login and return authentication state."""

    if is_admin_authenticated():
        return True

    configured_email = _admin_email()
    configured_password = _admin_password()
    if not configured_email or not configured_password:
        st.warning(
            "Accès admin non configuré. Ajoute `HELIOSTOCK_ADMIN_EMAIL` et "
            "`HELIOSTOCK_ADMIN_PASSWORD` dans les secrets Streamlit."
        )
        return False

    container = st.container() if compact else st.columns([1, 1.2, 1])[1]
    with container:
        if HELIOPILOT_LOGO.exists():
            st.image(str(HELIOPILOT_LOGO), use_container_width=True)
        if not compact:
            st.title("Portail HelioTools")
        st.caption("Connexion admin requise pour le dashboard solaire et les projets sauvegardés.")
        email = st.text_input("Email admin", key=f"portal_admin_email_{'compact' if compact else 'page'}")
        password = st.text_input("Mot de passe", type="password", key=f"portal_admin_password_{'compact' if compact else 'page'}")

        if st.button("Se connecter", type="primary", use_container_width=True, key=f"portal_admin_login_{'compact' if compact else 'page'}"):
            if email.strip().lower() != configured_email.strip().lower():
                st.error("Email admin non autorisé.")
                return False
            if password != configured_password:
                st.error("Mot de passe incorrect.")
                return False
            st.session_state["heliostock_admin_authenticated"] = True
            st.session_state["heliostock_admin_email"] = email.strip()
            st.rerun()

    return False


def render_login_portal() -> bool:
    """Backward-compatible admin login entrypoint."""

    return render_admin_login(compact=False)


def render_portal_sidebar() -> str:
    """Render left navigation and project loading controls."""

    with st.sidebar:
        if HELIOPILOT_LOGO.exists():
            st.image(str(HELIOPILOT_LOGO), use_container_width=True)
        if is_admin_authenticated():
            st.caption(f"Admin connecté : {st.session_state.get('heliostock_admin_email', 'admin')}")
        else:
            st.caption("HelioStock accessible sans compte.")
        app_name = st.selectbox(
            "Application",
            options=["HelioStock", "Dashboard solaire thermique"],
            key="portal_app",
        )

        st.markdown("### Projets")
        if is_admin_authenticated():
            project_files = _project_files()
            if project_files:
                labels = [_project_label(path) for path in project_files]
                selected_label = st.selectbox("Projet sauvegardé", labels, key="portal_project_to_load")
                selected_index = labels.index(selected_label)
                selected_path = project_files[selected_index]
                c1, c2 = st.columns(2)
                if c1.button("Charger", use_container_width=True):
                    _load_project(selected_path)
                    st.success("Projet chargé.")
                    st.rerun()
                if c2.button("Supprimer", use_container_width=True):
                    demand_path, result_path = _project_sidecar_paths(selected_path)
                    demand_path.unlink(missing_ok=True)
                    result_path.unlink(missing_ok=True)
                    selected_path.unlink(missing_ok=True)
                    st.session_state.pop("heliostock_current_project_name", None)
                    st.rerun()
            else:
                st.info("Aucun projet sauvegardé.")
        else:
            st.info("Connexion admin requise pour charger ou supprimer des projets.")
            with st.expander("Connexion admin", expanded=False):
                render_admin_login(compact=True)

        st.caption(
            "Les projets sauvegardent les paramètres, le fichier Excel de besoins "
            "et le dernier résultat calculé."
        )
        if is_admin_authenticated() and st.button("Se déconnecter", use_container_width=True):
            st.session_state["heliostock_admin_authenticated"] = False
            st.session_state.pop("heliostock_last_result", None)
            st.rerun()

    return app_name


def render_project_save_controls() -> None:
    """Render project save controls in the sidebar after widgets have been created."""

    with st.sidebar:
        st.markdown("### Enregistrer")
        if not is_admin_authenticated():
            st.info("Connexion admin requise pour enregistrer un projet.")
            return
        default_name = st.session_state.get("heliostock_current_project_name", "")
        project_name = st.text_input("Nom du projet", value=str(default_name), key="portal_project_name")
        if st.button("Enregistrer le projet", type="primary", use_container_width=True):
            PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            payload = _project_payload(project_name)
            path = PROJECTS_DIR / f"{_safe_project_slug(str(payload['name']))}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            demand_path, result_path = _project_sidecar_paths(path)
            demand_bytes = st.session_state.get("heliostock_demand_file_bytes")
            if demand_bytes:
                demand_path.write_bytes(bytes(demand_bytes))
            else:
                demand_path.unlink(missing_ok=True)
            cached_result = st.session_state.get("heliostock_last_result")
            if cached_result is not None:
                with result_path.open("wb") as handle:
                    pickle.dump(cached_result, handle, protocol=pickle.HIGHEST_PROTOCOL)
            else:
                result_path.unlink(missing_ok=True)
            st.session_state["heliostock_current_project_name"] = str(payload["name"])
            st.success(f"Projet enregistré : {payload['name']}")
