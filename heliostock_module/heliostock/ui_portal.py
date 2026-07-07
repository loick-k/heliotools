from __future__ import annotations

import json
import pickle
import re
import hashlib
import hmac
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
HELIOPILOT_LOGO = ASSETS_DIR / "logo_heliopilot_v5.png"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"
PROJECTS_DIR = Path.home() / ".heliostock" / "projects"
USERS_FILE = PROJECTS_DIR / "users.json"
PASSWORD_MIN_LENGTH = 10
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60
LOGIN_FAILURE_STATE_KEY = "heliotools_login_failures"
LOGIN_LOCK_STATE_KEY = "heliotools_login_locked_until"


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


def _email_normalise(email: str) -> str:
    return str(email or "").strip().lower()


def _load_users() -> list[dict[str, Any]]:
    if not USERS_FILE.exists():
        return []
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_users(users: list[dict[str, Any]]) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def _user_by_email(email: str) -> dict[str, Any] | None:
    email_norm = _email_normalise(email)
    for user in _load_users():
        if _email_normalise(str(user.get("email", ""))) == email_norm:
            return user
    return None


def _hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        bytes.fromhex(salt),
        120_000,
    ).hex()
    return f"{salt}:{digest}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, expected = str(password_hash).split(":")
        calculated = _hash_password(password, salt).split(":")[1]
        return hmac.compare_digest(calculated, expected)
    except Exception:
        return False


def _validate_password(password: str) -> None:
    if len(str(password or "")) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères.")


def _create_admin_user(email: str, name: str, password: str) -> None:
    email_norm = _email_normalise(email)
    if not email_norm:
        raise ValueError("Email administrateur requis.")
    _validate_password(password)
    if _user_by_email(email_norm) is not None:
        raise ValueError("Ce compte existe déjà.")
    users = _load_users()
    users.append(
        {
            "email": email_norm,
            "nom": str(name or "").strip() or email_norm,
            "role": "admin",
            "password_hash": _hash_password(password),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_users(users)


def _bootstrap_admin_from_secrets() -> bool:
    if _load_users():
        return False

    email = ""
    name = ""
    password = ""
    try:
        cfg = st.secrets.get("bootstrap_admin", {})
        if isinstance(cfg, dict):
            email = str(cfg.get("email", "") or "")
            name = str(cfg.get("nom", "") or cfg.get("name", "") or "")
            password = str(cfg.get("password", "") or "")
    except Exception:
        pass

    email = email or _admin_email()
    password = password or _admin_password()
    name = name or email
    if not email or not password:
        return False
    try:
        _create_admin_user(email=email, name=name, password=password)
    except ValueError:
        return False
    return True


def _login_failures() -> dict[str, int]:
    state = st.session_state.setdefault(LOGIN_FAILURE_STATE_KEY, {})
    return state if isinstance(state, dict) else {}


def _login_locks() -> dict[str, float]:
    state = st.session_state.setdefault(LOGIN_LOCK_STATE_KEY, {})
    return state if isinstance(state, dict) else {}


def _locked_remaining_seconds(email: str) -> int:
    email_norm = _email_normalise(email)
    locks = _login_locks()
    locked_until = float(locks.get(email_norm, 0) or 0)
    remaining = int(max(0, locked_until - time.time()))
    if remaining <= 0:
        locks.pop(email_norm, None)
    return remaining


def _record_login_failure(email: str) -> None:
    email_norm = _email_normalise(email)
    failures = _login_failures()
    failures[email_norm] = int(failures.get(email_norm, 0) or 0) + 1
    if failures[email_norm] >= LOGIN_MAX_FAILURES:
        _login_locks()[email_norm] = time.time() + LOGIN_LOCK_SECONDS
        failures[email_norm] = 0


def _clear_login_failures(email: str) -> None:
    email_norm = _email_normalise(email)
    _login_failures().pop(email_norm, None)
    _login_locks().pop(email_norm, None)


def _connect_user(email: str, password: str) -> bool:
    email_norm = _email_normalise(email)
    remaining = _locked_remaining_seconds(email_norm)
    if remaining > 0:
        st.session_state["heliotools_login_error"] = (
            f"Trop de tentatives de connexion. Réessaie dans {remaining} seconde(s)."
        )
        return False

    user = _user_by_email(email_norm)
    if not user or not _verify_password(password, str(user.get("password_hash", ""))):
        _record_login_failure(email_norm)
        st.session_state["heliotools_login_error"] = "Identifiants incorrects."
        return False

    _clear_login_failures(email_norm)
    st.session_state["user"] = {
        "email": user.get("email"),
        "nom": user.get("nom") or user.get("email"),
        "role": user.get("role", "user"),
    }
    st.session_state["heliostock_admin_authenticated"] = user.get("role") == "admin"
    st.session_state["heliostock_admin_email"] = str(user.get("email", ""))
    st.session_state.pop("heliotools_login_error", None)
    return True


def _disconnect_user() -> None:
    st.session_state.pop("user", None)
    st.session_state["heliostock_admin_authenticated"] = False
    st.session_state.pop("heliostock_admin_email", None)


def is_admin_authenticated() -> bool:
    user = st.session_state.get("user")
    return bool(
        st.session_state.get("heliostock_admin_authenticated")
        or (isinstance(user, dict) and user.get("role") == "admin")
    )


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


def render_brand_header(*, subtitle: str = "Portail des outils solaires Atlansun") -> None:
    col_title, col_logo = st.columns([2, 1])
    with col_title:
        logo_col, _ = st.columns([9, 11])
        if HELIOPILOT_LOGO.exists():
            with logo_col:
                st.image(str(HELIOPILOT_LOGO), use_container_width=True, output_format="PNG")
        else:
            st.title("HelioTools")
        st.markdown(f"##### {subtitle}")
    with col_logo:
        logo_left, _ = st.columns(2)
        with logo_left:
            if ATLANSUN_LOGO.exists():
                st.image(str(ATLANSUN_LOGO), use_container_width=True)


def render_admin_login(*, compact: bool = False) -> bool:
    """Render admin login and return authentication state."""

    if is_admin_authenticated():
        return True

    if _bootstrap_admin_from_secrets():
        st.success("Compte administrateur restauré automatiquement.")
        st.rerun()

    container = st.container() if compact else st.columns([1, 1.2, 1])[1]
    with container:
        if not compact:
            render_brand_header()

        if not _load_users():
            st.subheader("Initialisation administrateur")
            st.info("Aucun compte n'existe encore. Crée le premier compte administrateur.")
            with st.form(f"form_init_admin_{'compact' if compact else 'page'}"):
                email = st.text_input("Email administrateur")
                name = st.text_input("Nom")
                password = st.text_input("Mot de passe", type="password")
                submitted = st.form_submit_button("Créer le compte administrateur")
            if submitted:
                try:
                    _create_admin_user(email=email, name=name, password=password)
                    st.success("Compte administrateur créé. Tu peux maintenant te connecter.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            return False

        if not compact:
            st.markdown(
                "Connecte-toi pour accéder aux espaces protégés : dashboard solaire thermique, "
                "projets sauvegardés et futures passerelles Heliopilot."
            )
        st.subheader("Connexion")
        with st.form(f"form_login_{'compact' if compact else 'page'}"):
            email = st.text_input("Email", value=st.session_state.get("saved_login_email", ""))
            password = st.text_input("Mot de passe", type="password")
            submitted = st.form_submit_button("Se connecter")
        if submitted:
            if _connect_user(email, password):
                st.session_state["saved_login_email"] = _email_normalise(email)
                st.rerun()
            st.error(st.session_state.get("heliotools_login_error", "Identifiants incorrects."))

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
            user = st.session_state.get("user") if isinstance(st.session_state.get("user"), dict) else {}
            st.write(f"Connecté : {user.get('nom') or user.get('email') or st.session_state.get('heliostock_admin_email', 'admin')}")
            st.caption(f"Rôle : {user.get('role', 'admin')}")
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
            _disconnect_user()
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
