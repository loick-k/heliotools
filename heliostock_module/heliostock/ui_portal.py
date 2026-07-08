from __future__ import annotations

import json
import pickle
import re
import base64
import hashlib
import hmac
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import streamlit as st


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
HELIOPILOT_LOGO = ASSETS_DIR / "logo_heliopilot_v5.png"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"
PROJECTS_DIR = Path.home() / ".heliostock" / "projects"
USERS_FILE = PROJECTS_DIR / "users.json"
LOGIN_EVENTS_FILE = PROJECTS_DIR / "login_events.json"
RESULT_SIDECAR_SUFFIX = "_resultat.pkl"
DEFAULT_BACKUP_USERS_PATH = "seed_data/users.json"
DEFAULT_BACKUP_LOGIN_EVENTS_PATH = "seed_data/login_events.json"
DEFAULT_BACKUP_INSTALLATIONS_PATH = "seed_data/installations.json"
PASSWORD_MIN_LENGTH = 10
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60
LOGIN_FAILURE_STATE_KEY = "heliotools_login_failures"
LOGIN_LOCK_STATE_KEY = "heliotools_login_locked_until"


SAVEABLE_WIDGET_KEYS = [
    "airtable_base_id",
    "airtable_table_id",
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


def _github_backup_repo() -> str:
    return _secret_value("GITHUB_BACKUP_REPO")


def _github_backup_branch() -> str:
    return _secret_value("GITHUB_BACKUP_BRANCH") or "main"


def _github_backup_token() -> str:
    return _secret_value("GITHUB_BACKUP_TOKEN")


def _backup_users_path_setting() -> str:
    return _secret_value("GITHUB_BACKUP_USERS_PATH") or DEFAULT_BACKUP_USERS_PATH


def _backup_login_events_path_setting() -> str:
    return _secret_value("GITHUB_BACKUP_LOGIN_EVENTS_PATH") or DEFAULT_BACKUP_LOGIN_EVENTS_PATH


def _backup_installations_path_setting() -> str:
    return _secret_value("GITHUB_BACKUP_INSTALLATIONS_PATH") or DEFAULT_BACKUP_INSTALLATIONS_PATH


def _github_backup_enabled() -> bool:
    return bool(_github_backup_repo() and _github_backup_branch() and _github_backup_token())


def _resolve_backup_users_path() -> Path:
    configured = Path(_backup_users_path_setting())
    if configured.is_absolute():
        return configured

    candidates = [
        Path.cwd() / configured,
        Path(__file__).resolve().parents[1] / configured,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_backup_login_events_path() -> Path:
    configured = Path(_backup_login_events_path_setting())
    if configured.is_absolute():
        return configured

    candidates = [
        Path.cwd() / configured,
        Path(__file__).resolve().parents[1] / configured,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _read_users_file(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_users_file(path: Path, users: list[dict[str, Any]]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _write_json_list(path: Path, rows: list[dict[str, Any]]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _github_api_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {_github_backup_token()}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "HelioTools-Streamlit",
    }


def _github_contents_url(path: str) -> str:
    repo = _github_backup_repo().strip().strip("/")
    safe_path = str(path or "").strip().lstrip("/")
    return f"https://api.github.com/repos/{repo}/contents/{safe_path}"


def _github_read_json_list(path: str) -> list[dict[str, Any]]:
    if not _github_backup_enabled():
        return []
    url = f"{_github_contents_url(path)}?ref={_github_backup_branch()}"
    req = urlrequest.Request(url, headers=_github_api_headers(), method="GET")
    try:
        with urlrequest.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    encoded = str(payload.get("content", "") or "")
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        data = json.loads(decoded)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _github_file_sha(path: str) -> str | None:
    if not _github_backup_enabled():
        return None
    url = f"{_github_contents_url(path)}?ref={_github_backup_branch()}"
    req = urlrequest.Request(url, headers=_github_api_headers(), method="GET")
    try:
        with urlrequest.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        if exc.code == 404:
            return None
        return None
    except Exception:
        return None
    sha = payload.get("sha")
    return str(sha) if sha else None


def _github_write_json_list(path: str, rows: list[dict[str, Any]], *, message: str) -> bool:
    if not _github_backup_enabled():
        return False
    content = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": _github_backup_branch(),
    }
    sha = _github_file_sha(path)
    if sha:
        body["sha"] = sha
    req = urlrequest.Request(
        _github_contents_url(path),
        data=json.dumps(body).encode("utf-8"),
        headers={**_github_api_headers(), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urlrequest.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def _restore_users_from_backup() -> list[dict[str, Any]]:
    github_users = _github_read_json_list(_backup_users_path_setting())
    if github_users:
        _write_users_file(USERS_FILE, github_users)
        return github_users

    backup_path = _resolve_backup_users_path()
    if not backup_path.exists():
        return []
    users = _read_users_file(backup_path)
    if users:
        _write_users_file(USERS_FILE, users)
    return users


def _backup_users_configured() -> bool:
    return (
        _github_backup_enabled()
        or bool(_secret_value("GITHUB_BACKUP_USERS_PATH"))
        or _resolve_backup_users_path().exists()
    )


def _email_normalise(email: str) -> str:
    return str(email or "").strip().lower()


def _load_users() -> list[dict[str, Any]]:
    if USERS_FILE.exists():
        users = _read_users_file(USERS_FILE)
        if users:
            return users
    return _restore_users_from_backup()


def _save_users(users: list[dict[str, Any]]) -> None:
    _write_users_file(USERS_FILE, users)
    _write_users_file(_resolve_backup_users_path(), users)
    _github_write_json_list(
        _backup_users_path_setting(),
        users,
        message="chore: update heliotools users backup",
    )


def _append_login_event(*, email: str, success: bool, reason: str = "", role: str = "") -> None:
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "email": _email_normalise(email),
        "success": bool(success),
        "reason": str(reason or ""),
        "role": str(role or ""),
    }
    rows = _read_json_list(LOGIN_EVENTS_FILE)
    rows.append(event)
    rows = rows[-1000:]
    _write_json_list(LOGIN_EVENTS_FILE, rows)
    _write_json_list(_resolve_backup_login_events_path(), rows)
    _github_write_json_list(
        _backup_login_events_path_setting(),
        rows,
        message="chore: update heliotools login events",
    )


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


def _create_user(email: str, name: str, password: str, *, role: str = "user") -> None:
    email_norm = _email_normalise(email)
    if not email_norm:
        raise ValueError("Email utilisateur requis.")
    _validate_password(password)
    if _user_by_email(email_norm) is not None:
        raise ValueError("Ce compte existe déjà.")
    role_value = "admin" if str(role).strip().lower() == "admin" else "user"
    users = _load_users()
    users.append(
        {
            "email": email_norm,
            "nom": str(name or "").strip() or email_norm,
            "role": role_value,
            "password_hash": _hash_password(password),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "active": True,
        }
    )
    _save_users(users)


def _create_admin_user(email: str, name: str, password: str) -> None:
    _create_user(email=email, name=name, password=password, role="admin")


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
        _append_login_event(email=email_norm, success=False, reason="locked")
        return False

    user = _user_by_email(email_norm)
    if not user or not _verify_password(password, str(user.get("password_hash", ""))):
        _record_login_failure(email_norm)
        st.session_state["heliotools_login_error"] = "Identifiants incorrects."
        _append_login_event(email=email_norm, success=False, reason="invalid_credentials")
        return False

    if user.get("active") is False:
        st.session_state["heliotools_login_error"] = "Compte désactivé."
        _append_login_event(email=email_norm, success=False, reason="disabled", role=str(user.get("role", "")))
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
    _append_login_event(email=email_norm, success=True, reason="login", role=str(user.get("role", "")))
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


def is_user_authenticated() -> bool:
    user = st.session_state.get("user")
    return isinstance(user, dict) and bool(user.get("email"))


def _render_user_admin_panel() -> None:
    with st.expander("Utilisateurs", expanded=False):
        users = _load_users()
        if users:
            st.caption(f"{len(users)} compte(s) enregistré(s)")
            for user in users[-8:]:
                status = "actif" if user.get("active", True) is not False else "désactivé"
                st.write(f"- {user.get('email', '')} · {user.get('role', 'user')} · {status}")
        else:
            st.caption("Aucun utilisateur enregistré.")

        with st.form("form_create_portal_user"):
            email = st.text_input("Email utilisateur", key="portal_new_user_email")
            name = st.text_input("Nom utilisateur", key="portal_new_user_name")
            role = st.selectbox("Rôle", options=["user", "admin"], key="portal_new_user_role")
            password = st.text_input("Mot de passe temporaire", type="password", key="portal_new_user_password")
            submitted = st.form_submit_button("Créer l'utilisateur")
        if submitted:
            try:
                _create_user(email=email, name=name, password=password, role=role)
                st.success("Utilisateur créé.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        events = _read_json_list(LOGIN_EVENTS_FILE)
        if events:
            st.caption("Dernières connexions")
            for event in events[-5:][::-1]:
                outcome = "OK" if event.get("success") else "KO"
                st.write(f"- {event.get('timestamp', '')} · {outcome} · {event.get('email', '')}")


def _safe_project_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    slug = slug.strip("._-")
    return slug[:80] or "projet_heliostock"


def _project_files() -> list[Path]:
    if not PROJECTS_DIR.exists():
        return []
    users_path = USERS_FILE.resolve()
    files = [
        path
        for path in PROJECTS_DIR.glob("*.json")
        if path.resolve() != users_path
    ]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def _has_existing_project_data() -> bool:
    if not PROJECTS_DIR.exists():
        return False
    users_path = USERS_FILE.resolve()
    for path in PROJECTS_DIR.iterdir():
        if path.resolve() == users_path:
            continue
        if path.is_file():
            return True
    return False


def _assert_local_project_path(path: Path) -> Path:
    project_root = PROJECTS_DIR.resolve()
    resolved = path.resolve()
    if project_root != resolved and project_root not in resolved.parents:
        raise ValueError("Le fichier projet doit se trouver dans le dossier local HelioStock.")
    return resolved


def _project_label(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.stem
    if not isinstance(data, dict):
        return path.stem
    return str(data.get("name") or path.stem)


def _project_sidecar_paths(path: Path) -> tuple[Path, Path]:
    _assert_local_project_path(path)
    stem = path.with_suffix("")
    return (
        stem.with_name(f"{stem.name}_besoins.xlsx"),
        stem.with_name(f"{stem.name}{RESULT_SIDECAR_SUFFIX}"),
    )


def _load_local_result_pickle(path: Path) -> Any:
    """Charge un résultat généré localement par HelioStock.

    Le format pickle est conservé provisoirement parce que les résultats
    contiennent des objets Python complexes. Ne jamais brancher cette fonction
    sur un upload utilisateur ou un fichier externe non maîtrisé.
    """
    resolved = _assert_local_project_path(path)
    if not resolved.name.endswith(RESULT_SIDECAR_SUFFIX):
        raise ValueError("Cache résultat HelioStock non reconnu.")
    with resolved.open("rb") as handle:
        return pickle.load(handle)


def _save_local_result_pickle(path: Path, result: Any) -> None:
    """Sauvegarde locale du dernier résultat calculé par HelioStock."""
    resolved = _assert_local_project_path(path)
    if not resolved.name.endswith(RESULT_SIDECAR_SUFFIX):
        raise ValueError("Chemin de cache résultat HelioStock invalide.")
    with resolved.open("wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)


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
    path = _assert_local_project_path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        st.warning("Ce fichier projet utilise un ancien format non compatible.")
        return
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
        try:
            st.session_state["heliostock_last_result"] = _load_local_result_pickle(result_path)
        except Exception:
            st.session_state.pop("heliostock_last_result", None)
            st.warning(
                "Le cache résultat local n'a pas pu être chargé. Relance un calcul pour régénérer les résultats."
            )
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

    if is_user_authenticated():
        return True

    if _bootstrap_admin_from_secrets():
        st.success("Compte administrateur restauré automatiquement.")
        st.rerun()

    container = st.container() if compact else st.columns([1, 1.2, 1])[1]
    with container:
        if not compact:
            render_brand_header()

        if not _load_users():
            if _has_existing_project_data() or _backup_users_configured():
                st.error(
                    "Aucun compte utilisateur n'a pu être restauré depuis la sauvegarde configurée. "
                    "Par sécurité, la création libre d'un nouvel administrateur est bloquée."
                )
                st.info(
                    "Vérifie le secret Streamlit `GITHUB_BACKUP_USERS_PATH` "
                    "(par exemple `seed_data/users.json`) ou restaure l'accès avec "
                    "`HELIOSTOCK_ADMIN_EMAIL` et `HELIOSTOCK_ADMIN_PASSWORD`."
                )
                return False

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
        if is_user_authenticated():
            user = st.session_state.get("user") if isinstance(st.session_state.get("user"), dict) else {}
            st.write(f"Connecté : {user.get('nom') or user.get('email') or st.session_state.get('heliostock_admin_email', 'admin')}")
            st.caption(f"Rôle : {user.get('role', 'admin')}")
            if st.button("Se déconnecter", use_container_width=True):
                _disconnect_user()
                st.session_state.pop("heliostock_last_result", None)
                st.rerun()
            if user.get("role") == "admin":
                _render_user_admin_panel()
            st.divider()
        app_options = ["HelioStock"]
        if is_admin_authenticated():
            app_options.append("Dashboard solaire thermique")
        app_name = st.selectbox(
            "Application",
            options=app_options,
            key="portal_app",
        )

        if app_name == "HelioStock":
            st.markdown("### Projets")
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

            st.caption(
                "Les projets sauvegardent les paramètres, le fichier Excel de besoins "
                "et le dernier résultat calculé."
            )

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
            demand_path, result_path = _project_sidecar_paths(path)
            demand_bytes = st.session_state.get("heliostock_demand_file_bytes")
            if demand_bytes:
                demand_path.write_bytes(bytes(demand_bytes))
            else:
                demand_path.unlink(missing_ok=True)
            cached_result = st.session_state.get("heliostock_last_result")
            if cached_result is not None:
                _save_local_result_pickle(result_path, cached_result)
            else:
                result_path.unlink(missing_ok=True)
            st.session_state["heliostock_current_project_name"] = str(payload["name"])
            st.success(f"Projet enregistré : {payload['name']}")
