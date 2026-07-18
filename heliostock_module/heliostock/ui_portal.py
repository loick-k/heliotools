from __future__ import annotations

from dataclasses import fields, is_dataclass
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
from types import SimpleNamespace
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import streamlit as st
import pandas as pd

from .common.project_store import normalize_email, now_iso, safe_slug


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
MODULE_DIR = Path(__file__).resolve().parents[1]
HELIOSTOCK_NOTICE = MODULE_DIR / "NOTICE_MODELE_HELIOSTOCK.md"
HELIOPILOT_LOGO = ASSETS_DIR / "logo_heliopilot_v5.png"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"
PROJECTS_DIR = Path.home() / ".heliostock" / "projects"
USERS_FILE = PROJECTS_DIR / "users.json"
LOGIN_EVENTS_FILE = PROJECTS_DIR / "login_events.json"
RESULT_SIDECAR_SUFFIX = "_resultat.pkl"
RESULT_PICKLE_MAGIC = b"HELIOSTOCK_RESULT_CACHE_V1\n"
RESULT_PICKLE_MAX_BYTES = 200 * 1024 * 1024
DEFAULT_BACKUP_USERS_PATH = "seed_data/users.json"
DEFAULT_BACKUP_LOGIN_EVENTS_PATH = "seed_data/login_events.json"
DEFAULT_BACKUP_INSTALLATIONS_PATH = "seed_data/installations.json"
DEFAULT_BACKUP_PROJECTS_PATH = "seed_data/heliostock_projects.json"
PASSWORD_MIN_LENGTH = 10
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 60
LOGIN_FAILURE_STATE_KEY = "heliotools_login_failures"
LOGIN_LOCK_STATE_KEY = "heliotools_login_locked_until"
USERS_SESSION_CACHE_KEY = "heliotools_users_cache"
PROJECTS_SESSION_CACHE_KEY = "heliotools_projects_cache"
GITHUB_BACKUP_TIMEOUT_SECONDS = 3
FORBIDDEN_PROJECT_KEY_FRAGMENTS = ("token", "api_key", "apikey", "secret", "password")
APP_HOME_LABEL = "Accueil HelioTools"
APP_HELIOSTOCK_LABEL = "HelioStock"
APP_ADMIN_LABEL = "Administration HelioTools"
APP_DASHBOARD_LABEL = "Dashboard solaire thermique"
APP_OPPORTUNITY_LABEL = "HelioNOP"


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
    "demand_scope_label",
    "solar_collector_name",
    "solar_area_m2",
    "solar_eta0",
    "solar_a1",
    "solar_a2",
    "solar_daily_buffer_l_per_m2",
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


def _backup_projects_path_setting() -> str:
    return _secret_value("GITHUB_BACKUP_PROJECTS_PATH") or DEFAULT_BACKUP_PROJECTS_PATH


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


def _resolve_backup_projects_path() -> Path:
    configured = Path(_backup_projects_path_setting())
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
        with urlrequest.urlopen(req, timeout=GITHUB_BACKUP_TIMEOUT_SECONDS) as response:
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
        with urlrequest.urlopen(req, timeout=GITHUB_BACKUP_TIMEOUT_SECONDS) as response:
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
        with urlrequest.urlopen(req, timeout=GITHUB_BACKUP_TIMEOUT_SECONDS):
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


def _project_backup_slug(project: dict[str, Any]) -> str:
    slug = str(project.get("slug", "") or "").strip()
    if slug:
        return _safe_project_slug(slug)
    owner = _safe_project_slug(str(project.get("owner_email", "") or "anonymous"))
    name = _safe_project_slug(str(project.get("name", "") or "Projet HelioStock"))
    return f"{owner}_{name}"[:120]


def _load_project_backups() -> list[dict[str, Any]]:
    cached = st.session_state.get(PROJECTS_SESSION_CACHE_KEY)
    if isinstance(cached, list):
        return [dict(project) for project in cached if isinstance(project, dict)]

    github_projects = _github_read_json_list(_backup_projects_path_setting())
    if github_projects:
        _write_json_list(_resolve_backup_projects_path(), github_projects)
        st.session_state[PROJECTS_SESSION_CACHE_KEY] = github_projects
        return github_projects

    backup_path = _resolve_backup_projects_path()
    projects = _read_json_list(backup_path)
    if projects:
        st.session_state[PROJECTS_SESSION_CACHE_KEY] = projects
    return projects


def _save_project_backups(projects: list[dict[str, Any]]) -> None:
    clean_projects = [dict(project) for project in projects if isinstance(project, dict)]
    st.session_state[PROJECTS_SESSION_CACHE_KEY] = clean_projects
    _write_json_list(_resolve_backup_projects_path(), clean_projects)
    _github_write_json_list(
        _backup_projects_path_setting(),
        clean_projects,
        message="chore: update heliostock projects backup",
    )


def _restore_projects_from_backup() -> None:
    projects = _load_project_backups()
    if not projects:
        return
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    for project in projects:
        slug = _project_backup_slug(project)
        if not slug:
            continue
        payload = dict(project.get("payload", project))
        payload.pop("demand_excel_base64", None)
        path = PROJECTS_DIR / f"{slug}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        demand_encoded = project.get("demand_excel_base64")
        demand_path, _ = _project_sidecar_paths(path)
        if isinstance(demand_encoded, str) and demand_encoded:
            try:
                demand_path.write_bytes(base64.b64decode(demand_encoded.encode("ascii")))
            except Exception:
                demand_path.unlink(missing_ok=True)


def _upsert_project_backup(*, path: Path, payload: dict[str, Any], demand_bytes: bytes | None) -> None:
    slug = path.with_suffix("").name
    backup_item = {
        "slug": slug,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "owner_email": payload.get("owner_email", ""),
        "name": payload.get("name", slug),
        "payload": payload,
        "demand_excel_base64": (
            base64.b64encode(demand_bytes).decode("ascii")
            if isinstance(demand_bytes, (bytes, bytearray)) and demand_bytes
            else ""
        ),
    }
    projects = [project for project in _load_project_backups() if _project_backup_slug(project) != slug]
    projects.append(backup_item)
    _save_project_backups(projects)


def _delete_project_backup(path: Path) -> None:
    slug = path.with_suffix("").name
    projects = [project for project in _load_project_backups() if _project_backup_slug(project) != slug]
    _save_project_backups(projects)


def _backup_users_configured() -> bool:
    return (
        _github_backup_enabled()
        or bool(_secret_value("GITHUB_BACKUP_USERS_PATH"))
        or _resolve_backup_users_path().exists()
    )


def _email_normalise(email: str) -> str:
    return normalize_email(email)


def _load_users() -> list[dict[str, Any]]:
    cached = st.session_state.get(USERS_SESSION_CACHE_KEY)
    if isinstance(cached, list):
        return [dict(user) for user in cached if isinstance(user, dict)]
    if USERS_FILE.exists():
        users = _read_users_file(USERS_FILE)
        if users:
            st.session_state[USERS_SESSION_CACHE_KEY] = users
            return users
    users = _restore_users_from_backup()
    if users:
        st.session_state[USERS_SESSION_CACHE_KEY] = users
    return users


def _save_users(users: list[dict[str, Any]]) -> None:
    _write_users_file(USERS_FILE, users)
    st.session_state[USERS_SESSION_CACHE_KEY] = [dict(user) for user in users if isinstance(user, dict)]
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


def _load_login_events() -> list[dict[str, Any]]:
    rows = _read_json_list(LOGIN_EVENTS_FILE)
    if rows:
        return rows
    github_rows = _github_read_json_list(_backup_login_events_path_setting())
    if github_rows:
        _write_json_list(LOGIN_EVENTS_FILE, github_rows)
        return github_rows
    backup_path = _resolve_backup_login_events_path()
    return _read_json_list(backup_path)


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
    _clear_project_session_state()
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
    _clear_project_session_state()
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


def _current_user_email() -> str:
    user = st.session_state.get("user")
    if isinstance(user, dict):
        return _email_normalise(str(user.get("email", "")))
    return ""


def _clear_project_session_state() -> None:
    for key in (
        "heliostock_last_result",
        "heliostock_current_project_name",
        "heliostock_demand_file_bytes",
        "heliostock_demand_file_name",
        "portal_project_to_load",
        "portal_project_name",
    ):
        st.session_state.pop(key, None)


def _safe_project_slug(name: str) -> str:
    return safe_slug(name, fallback="projet_heliostock")


def _owned_project_slug(name: str) -> str:
    owner = _safe_project_slug(_current_user_email() or "anonymous")
    project = _safe_project_slug(name)
    return f"{owner}_{project}"[:120]


def _project_owner_email(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return _email_normalise(str(data.get("owner_email", "") or data.get("created_by_email", "")))


def _is_system_project_file(path: Path) -> bool:
    resolved = path.resolve()
    system_files = {
        USERS_FILE.resolve(),
        LOGIN_EVENTS_FILE.resolve(),
    }
    return resolved in system_files


def _is_heliostock_project_file(path: Path) -> bool:
    if _is_system_project_file(path):
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and data.get("app") == "HelioStock" and isinstance(data.get("widget_values"), dict)


def _can_access_project(path: Path) -> bool:
    if is_admin_authenticated():
        return True
    owner_email = _project_owner_email(path)
    return bool(owner_email and owner_email == _current_user_email())


def _project_files() -> list[Path]:
    _restore_projects_from_backup()
    if not PROJECTS_DIR.exists():
        return []
    files = [
        path
        for path in PROJECTS_DIR.glob("*.json")
        if _is_heliostock_project_file(path)
        and _can_access_project(path)
    ]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def _has_existing_project_data() -> bool:
    if not PROJECTS_DIR.exists():
        return False
    for path in PROJECTS_DIR.iterdir():
        if _is_system_project_file(path):
            continue
        if path.is_file() and _is_heliostock_project_file(path):
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
    contiennent des objets Python complexes. La désérialisation reste limitée
    aux caches locaux générés par l'outil, avec chemin local contrôlé, suffixe
    dédié, taille plafonnée et en-tête signé HelioStock. Ne jamais brancher
    cette fonction sur un upload utilisateur ou un fichier externe non maîtrisé.
    """
    resolved = _assert_local_project_path(path)
    if not resolved.name.endswith(RESULT_SIDECAR_SUFFIX):
        raise ValueError("Cache résultat HelioStock non reconnu.")
    payload = resolved.read_bytes()
    if len(payload) > RESULT_PICKLE_MAX_BYTES:
        raise ValueError("Cache résultat HelioStock trop volumineux.")
    if not payload.startswith(RESULT_PICKLE_MAGIC):
        raise ValueError("Cache résultat HelioStock non signé par cette version.")
    return _restore_result_cache_payload(pickle.loads(payload[len(RESULT_PICKLE_MAGIC) :]))


def _prepare_result_cache_payload(value: Any) -> Any:
    """Convertit les dataclasses HelioStock en structures stables pour pickle.

    Streamlit Cloud peut recharger les modules entre deux exécutions. Pickle
    échoue alors si un objet dataclass a été créé avec une ancienne référence
    de classe. On sauvegarde donc les champs plutôt que l'objet Python exact.
    """
    if isinstance(value, pd.DataFrame):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__heliostock_dataclass__": f"{value.__class__.__module__}.{value.__class__.__qualname__}",
            "fields": {
                field.name: _prepare_result_cache_payload(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, dict):
        return {key: _prepare_result_cache_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_prepare_result_cache_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_prepare_result_cache_payload(item) for item in value)
    return value


def _restore_result_cache_payload(value: Any) -> Any:
    if isinstance(value, dict) and "__heliostock_dataclass__" in value and isinstance(value.get("fields"), dict):
        restored_fields = {
            key: _restore_result_cache_payload(item)
            for key, item in value["fields"].items()
        }
        return SimpleNamespace(**restored_fields)
    if isinstance(value, dict):
        return {key: _restore_result_cache_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore_result_cache_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_restore_result_cache_payload(item) for item in value)
    return value


def _save_local_result_pickle(path: Path, result: Any) -> None:
    """Sauvegarde locale du dernier résultat calculé par HelioStock."""
    resolved = _assert_local_project_path(path)
    if not resolved.name.endswith(RESULT_SIDECAR_SUFFIX):
        raise ValueError("Chemin de cache résultat HelioStock invalide.")
    payload = pickle.dumps(_prepare_result_cache_payload(result), protocol=pickle.HIGHEST_PROTOCOL)
    if len(payload) > RESULT_PICKLE_MAX_BYTES:
        raise ValueError("Cache résultat HelioStock trop volumineux.")
    resolved.write_bytes(RESULT_PICKLE_MAGIC + payload)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_safe_project_widget_key(key: str) -> bool:
    lowered = str(key or "").lower()
    return not any(fragment in lowered for fragment in FORBIDDEN_PROJECT_KEY_FRAGMENTS)


def _project_payload(name: str) -> dict[str, Any]:
    widget_values = {
        key: _jsonable(st.session_state[key])
        for key in SAVEABLE_WIDGET_KEYS
        if key in st.session_state and _is_safe_project_widget_key(key)
    }
    return {
        "schema_version": 2,
        "name": name.strip() or "Projet HelioStock",
        "owner_email": _current_user_email(),
        "created_by_email": _current_user_email(),
        "saved_at": now_iso(),
        "app": "HelioStock",
        "widget_values": widget_values,
        "has_demand_excel": bool(st.session_state.get("heliostock_demand_file_bytes")),
        "has_cached_result": bool(st.session_state.get("heliostock_last_result")),
        "note": "Le fichier Excel de besoins horaires et le dernier résultat calculé sont stockés avec le projet.",
    }


def _load_project(path: Path) -> None:
    path = _assert_local_project_path(path)
    if not _can_access_project(path):
        st.error("Tu n'as pas accès à ce projet.")
        return
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
                st.image(str(HELIOPILOT_LOGO), width="stretch", output_format="PNG")
        else:
            st.title("HelioTools")
        st.markdown(f"##### {subtitle}")
    with col_logo:
        logo_left, _ = st.columns(2)
        with logo_left:
            if ATLANSUN_LOGO.exists():
                st.image(str(ATLANSUN_LOGO), width="stretch")


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


def _format_event_outcome(event: dict[str, Any]) -> str:
    return "Connexion réussie" if event.get("success") else "Échec"


def render_heliotools_home_page() -> None:
    """Page d'accueil du portail HelioTools après authentification."""

    render_brand_header(subtitle="Suite d'outils solaires Atlansun")
    user = st.session_state.get("user") if isinstance(st.session_state.get("user"), dict) else {}
    role = str(user.get("role", "user"))
    st.caption(
        "HelioTools regroupe les applications de pré-dimensionnement, de suivi et de production "
        "de livrables. HelioStock est désormais une application du portail."
    )

    st.markdown("### Applications disponibles")
    cards = [
        (
            APP_HELIOSTOCK_LABEL,
            "Pré-dimensionnement solaire thermique, géothermie et recharge du champ de sondes.",
            "Ouvrir HelioStock",
        )
    ]
    if is_admin_authenticated():
        cards.extend(
            [
                (
                    APP_DASHBOARD_LABEL,
                    "Pilotage du parc solaire thermique depuis les données Airtable.",
                    "Ouvrir le dashboard",
                ),
                (
                    APP_OPPORTUNITY_LABEL,
                    "Réalisation de notes d'opportunité solaire thermique.",
                    "Ouvrir HelioNOP",
                ),
                (
                    APP_ADMIN_LABEL,
                    "Gestion des comptes, rôles et connexions au portail.",
                    "Administrer",
                ),
            ]
        )

    columns = st.columns(2)
    for index, (title, description, button_label) in enumerate(cards):
        with columns[index % 2]:
            with st.container(border=True):
                st.subheader(title)
                st.write(description)
                if st.button(button_label, key=f"home_open_{index}", width="stretch"):
                    st.session_state["portal_app"] = title
                    st.rerun()

    st.info(
        "Session connectée en mode administrateur."
        if role == "admin"
        else "Session connectée en mode utilisateur. Les applications d'administration restent masquées."
    )


def render_admin_dashboard_page() -> None:
    """Page pleine largeur de gestion des utilisateurs et des connexions."""

    if not is_admin_authenticated():
        st.error("Accès réservé aux administrateurs.")
        return

    st.title("Administration HelioTools")
    st.caption("Gestion des comptes, rôles et connexions du portail.")

    users = _load_users()
    events = _load_login_events()
    active_users = [user for user in users if user.get("active", True) is not False]
    admin_users = [user for user in users if str(user.get("role", "")) == "admin"]
    successful_events = [event for event in events if event.get("success")]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Comptes", len(users))
    k2.metric("Comptes actifs", len(active_users))
    k3.metric("Administrateurs", len(admin_users))
    k4.metric("Connexions réussies", len(successful_events))

    st.markdown("### Créer un compte")
    with st.form("form_create_portal_user_page"):
        c1, c2 = st.columns(2)
        email = c1.text_input("Email utilisateur", key="portal_admin_new_user_email")
        name = c2.text_input("Nom utilisateur", key="portal_admin_new_user_name")
        c3, c4 = st.columns(2)
        role = c3.selectbox("Rôle", options=["user", "admin"], key="portal_admin_new_user_role")
        password = c4.text_input(
            "Mot de passe temporaire",
            type="password",
            key="portal_admin_new_user_password",
        )
        submitted = st.form_submit_button("Créer l'utilisateur", type="primary")
    if submitted:
        try:
            _create_user(email=email, name=name, password=password, role=role)
            st.success("Utilisateur créé.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.markdown("### Comptes utilisateurs")
    if users:
        users_df = pd.DataFrame(
            [
                {
                    "Email": user.get("email", ""),
                    "Nom": user.get("nom", ""),
                    "Rôle": user.get("role", "user"),
                    "Statut": "actif" if user.get("active", True) is not False else "désactivé",
                    "Créé le": user.get("created_at", ""),
                }
                for user in users
            ]
        )
        st.dataframe(users_df, hide_index=True, width="stretch")
    else:
        st.info("Aucun utilisateur enregistré.")

    st.markdown("### Connexions récentes")
    if events:
        events_df = pd.DataFrame(
            [
                {
                    "Date": event.get("timestamp", ""),
                    "Email": event.get("email", ""),
                    "Résultat": _format_event_outcome(event),
                    "Rôle": event.get("role", ""),
                    "Motif": event.get("reason", ""),
                }
                for event in events[-100:][::-1]
            ]
        )
        st.dataframe(events_df, hide_index=True, width="stretch")
    else:
        st.info("Aucune connexion enregistrée.")


def render_portal_sidebar() -> str:
    """Render left navigation and project loading controls."""

    with st.sidebar:
        if HELIOPILOT_LOGO.exists():
            st.image(str(HELIOPILOT_LOGO), width="stretch")
        if is_user_authenticated():
            user = st.session_state.get("user") if isinstance(st.session_state.get("user"), dict) else {}
            st.write(f"Connecté : {user.get('nom') or user.get('email') or st.session_state.get('heliostock_admin_email', 'admin')}")
            st.caption(f"Rôle : {user.get('role', 'admin')}")
            if st.button("Se déconnecter", width="stretch"):
                _disconnect_user()
                st.session_state.pop("heliostock_last_result", None)
                st.rerun()
            st.divider()

        app_options = [APP_HOME_LABEL, APP_HELIOSTOCK_LABEL]
        if is_admin_authenticated():
            app_options.append(APP_ADMIN_LABEL)
            app_options.append(APP_DASHBOARD_LABEL)
            app_options.append(APP_OPPORTUNITY_LABEL)
        if st.session_state.get("portal_app") not in app_options:
            st.session_state["portal_app"] = app_options[0]
        app_name = st.selectbox(
            "Application",
            options=app_options,
            key="portal_app",
        )

        if app_name == APP_HELIOSTOCK_LABEL:
            current_view = st.session_state.get("heliostock_view", "solver")
            if current_view not in {"solver", "notice"}:
                current_view = "solver"

            if current_view == "solver":
                st.markdown("### Projets")
                project_files = _project_files()
                if project_files:
                    labels = [_project_label(path) for path in project_files]
                    selected_label = st.selectbox("Projet sauvegardé", labels, key="portal_project_to_load")
                    selected_index = labels.index(selected_label)
                    selected_path = project_files[selected_index]
                    c1, c2 = st.columns(2)
                    if c1.button("Charger", width="stretch"):
                        _load_project(selected_path)
                        st.success("Projet chargé.")
                        st.rerun()
                    if c2.button("Supprimer", width="stretch"):
                        demand_path, result_path = _project_sidecar_paths(selected_path)
                        demand_path.unlink(missing_ok=True)
                        result_path.unlink(missing_ok=True)
                        _delete_project_backup(selected_path)
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


def render_heliostock_notice_page() -> None:
    """Affiche la notice HelioStock en pleine page."""

    if not HELIOSTOCK_NOTICE.exists():
        st.error("La notice HelioStock est introuvable dans le dépôt.")
        return
    notice_text = HELIOSTOCK_NOTICE.read_text(encoding="utf-8")
    st.title("Notice HelioStock")
    solver_col, notice_col, spacer = st.columns([1, 1, 4])
    if solver_col.button(
        "Solveur HelioStock",
        key="heliostock_notice_view_solver",
        type="secondary",
        width="stretch",
    ):
        st.session_state["heliostock_view"] = "solver"
        st.rerun()
    notice_col.button(
        "Notice HelioStock",
        key="heliostock_notice_view_notice",
        type="primary",
        width="stretch",
        disabled=True,
    )
    spacer.empty()
    st.caption("Notice méthodologique et limites d'utilisation du modèle.")
    st.download_button(
        "Télécharger la notice",
        data=notice_text.encode("utf-8"),
        file_name=HELIOSTOCK_NOTICE.name,
        mime="text/markdown",
        width="stretch",
    )
    st.divider()
    st.markdown(notice_text)


def render_project_save_controls() -> None:
    """Render project save controls in the sidebar after widgets have been created."""

    with st.sidebar:
        st.markdown("### Enregistrer")
        default_name = st.session_state.get("heliostock_current_project_name", "")
        project_name = st.text_input("Nom du projet", value=str(default_name), key="portal_project_name")
        if st.button("Enregistrer le projet", type="primary", width="stretch"):
            PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            payload = _project_payload(project_name)
            path = PROJECTS_DIR / f"{_owned_project_slug(str(payload['name']))}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            demand_path, result_path = _project_sidecar_paths(path)
            demand_bytes = st.session_state.get("heliostock_demand_file_bytes")
            if demand_bytes:
                demand_path.write_bytes(bytes(demand_bytes))
            else:
                demand_path.unlink(missing_ok=True)
            _upsert_project_backup(
                path=path,
                payload=payload,
                demand_bytes=bytes(demand_bytes) if demand_bytes else None,
            )
            cached_result = st.session_state.get("heliostock_last_result")
            if cached_result is not None:
                _save_local_result_pickle(result_path, cached_result)
            else:
                result_path.unlink(missing_ok=True)
            st.session_state["heliostock_current_project_name"] = str(payload["name"])
            st.success(f"Projet enregistré : {payload['name']}")


