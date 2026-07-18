import importlib.util
from pathlib import Path

import pytest


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (MODULE_ROOT / relative_path).read_text(encoding="utf-8")


def test_heliotools_portal_password_hashing_helpers():
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock import ui_portal

    password_hash = ui_portal._hash_password("motdepasse-solide")
    assert password_hash != "motdepasse-solide"
    assert ui_portal._verify_password("motdepasse-solide", password_hash)
    assert not ui_portal._verify_password("mauvais", password_hash)
    assert ui_portal._safe_project_slug("Projet test / 01") == "Projet_test_01"
    with pytest.raises(ValueError):
        ui_portal._validate_password("court")


def test_airtable_token_is_not_project_saveable():
    source = _source("heliostock/ui_portal.py")
    saveable_block = source.split("SAVEABLE_WIDGET_KEYS = [", 1)[1].split("]", 1)[0]
    assert '"airtable_api_key"' not in saveable_block
    assert '"dashboard_google_api_key"' not in saveable_block
    assert '"airtable_base_id"' in saveable_block
    assert '"airtable_table_id"' in saveable_block
    assert '"solar_daily_buffer_l_per_m2"' in saveable_block
    assert "FORBIDDEN_PROJECT_KEY_FRAGMENTS" in source
    assert "_is_safe_project_widget_key(key)" in source


def test_project_payload_filters_secret_like_widget_keys(monkeypatch):
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock import ui_portal

    monkeypatch.setattr(
        ui_portal,
        "SAVEABLE_WIDGET_KEYS",
        [
            "solar_area_m2",
            "airtable_api_key",
            "github_token",
            "admin_password",
            "client_secret",
            "custom_apikey",
        ],
    )
    monkeypatch.setattr(ui_portal, "_current_user_email", lambda: "user@example.com")
    monkeypatch.setitem(ui_portal.st.session_state, "solar_area_m2", 500.0)
    monkeypatch.setitem(ui_portal.st.session_state, "airtable_api_key", "secret-airtable")
    monkeypatch.setitem(ui_portal.st.session_state, "github_token", "secret-github")
    monkeypatch.setitem(ui_portal.st.session_state, "admin_password", "secret-password")
    monkeypatch.setitem(ui_portal.st.session_state, "client_secret", "secret-client")
    monkeypatch.setitem(ui_portal.st.session_state, "custom_apikey", "secret-apikey")

    payload = ui_portal._project_payload("demo")

    assert payload["widget_values"] == {"solar_area_m2": 500.0}


def test_readme_documents_project_secret_filtering_and_json_cache():
    readme = _source("README.md")
    assert "Les secrets ne sont pas sauvegardes dans les fichiers projet" in readme
    for fragment in ["`token`", "`api_key`", "`apikey`", "`secret`", "`password`"]:
        assert fragment in readme
    assert "latest_result.json" in readme


def test_project_result_cache_uses_stable_json_artifact():
    source = _source("heliostock/ui_portal.py")
    assert "RESULT_CACHE_FILENAME" in source
    assert "RESULT_JSON_SCHEMA_VERSION" in source
    assert "RESULT_JSON_MAX_BYTES" in source
    assert "DEMAND_INPUT_FILENAME" in source
    assert "def _project_artifact_paths" in source
    assert "def _assert_local_project_path" in source
    assert "_assert_local_project_path(path)" in source
    assert "_assert_local_project_path(path: Path)" in source
    assert "def _save_local_result_json" in source
    assert "def _load_local_result_json" in source
    assert "project_input_path(path, DEMAND_INPUT_FILENAME)" in source
    assert "project_result_path(path, RESULT_CACHE_FILENAME)" in source
    assert "pickle.dumps" not in source
    assert "pickle.loads" not in source


def test_project_result_json_roundtrip_handles_dataframes(tmp_path, monkeypatch):
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock import ui_portal
    import pandas as pd

    projects_dir = tmp_path / "projects"
    store = ui_portal.JsonProjectStore("heliostock", app_label="HelioStock", root_dir=projects_dir)
    monkeypatch.setattr(ui_portal, "HELIOSTOCK_PROJECT_STORE", store)
    project_path = store.save_project(
        payload={"app": "HelioStock", "widget_values": {}},
        owner_email="user@example.com",
        project_name="demo",
        project_id="aaaaaaaa-0000-0000-0000-000000000000",
    )
    _, result_path = ui_portal._project_artifact_paths(project_path)
    source_df = pd.DataFrame({"A": [1.0, 2.0], "B": ["x", "y"]})

    ui_portal._save_local_result_json(result_path, {"ok": True, "df": source_df})
    restored = ui_portal._load_local_result_json(result_path)

    assert restored["ok"] is True
    pd.testing.assert_frame_equal(restored["df"], source_df)

    invalid_path = result_path
    invalid_path.write_text('{"app":"Autre"}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalide"):
        ui_portal._load_local_result_json(invalid_path)


def test_admin_creation_is_blocked_when_project_data_already_exists():
    source = _source("heliostock/ui_portal.py")
    assert "def _has_existing_project_data" in source
    assert "if _has_existing_project_data() or _backup_users_configured():" in source
    assert "nouvel administrateur est" in source
    assert "HELIOSTOCK_ADMIN_EMAIL" in source
    assert "HELIOSTOCK_ADMIN_PASSWORD" in source
    assert "def _is_system_project_file" in source
    assert "LOGIN_EVENTS_FILE.resolve()" in source


def test_users_are_restored_from_configured_backup_path():
    source = _source("heliostock/ui_portal.py")
    assert 'DEFAULT_BACKUP_USERS_PATH = "seed_data/users.json"' in source
    assert "GITHUB_BACKUP_USERS_PATH" in source
    assert "GITHUB_BACKUP_REPO" in source
    assert "GITHUB_BACKUP_BRANCH" in source
    assert "GITHUB_BACKUP_TOKEN" in source
    assert "def _restore_users_from_backup" in source
    assert "_github_read_json_list(_backup_users_path_setting())" in source
    assert "users = _restore_users_from_backup()" in source
    assert "_write_users_file(_resolve_backup_users_path(), users)" in source
    assert "_github_write_json_list(" in source


def test_projects_are_backed_up_to_github_json_without_result_pickle():
    source = _source("heliostock/ui_portal.py")
    readme = _source("README.md")

    assert 'DEFAULT_BACKUP_PROJECTS_PATH = "seed_data/heliostock_projects.json"' in source
    assert "GITHUB_BACKUP_PROJECTS_PATH" in source
    assert "def _restore_projects_from_backup" in source
    assert "def _upsert_project_backup" in source
    assert "demand_excel_base64" in source
    assert "_restore_projects_from_backup()" in source
    assert "_upsert_project_backup(" in source
    assert "_delete_project_backup(selected_path)" in source
    assert "_save_local_result_json(result_path, cached_result)" in source
    assert "heliostock_projects.json" in readme
    assert "Le cache resultat JSON" in readme
    assert "results/latest_result.json" in readme


def test_login_events_are_recorded_without_secret_values():
    source = _source("heliostock/ui_portal.py")
    assert "LOGIN_EVENTS_FILE" in source
    assert 'DEFAULT_BACKUP_LOGIN_EVENTS_PATH = "seed_data/login_events.json"' in source
    assert "def _append_login_event" in source
    assert '"email": _email_normalise(email)' in source
    assert '"success": bool(success)' in source
    assert '"role": str(role or "")' in source
    assert "_github_write_json_list(" in source


def test_solar_dashboard_access_is_configurable_and_airtable_inputs_are_hidden():
    portal_source = _source("heliostock/ui_portal.py")
    dashboard_source = _source("heliostock/solar_thermal_dashboard.py")

    assert "APP_HOME_LABEL" in portal_source
    assert "APP_HELIOSTOCK_LABEL" in portal_source
    assert "APP_ACCESS_LABELS" in portal_source
    assert "APP_DASHBOARD_LABEL" in portal_source
    assert "_current_user_allowed_apps()" in portal_source
    assert '"Personal Access Token Airtable"' not in dashboard_source
    assert 'st.sidebar.text_input("Base ID"' not in dashboard_source
    assert 'st.sidebar.text_input("Table ID' not in dashboard_source
    assert '_dashboard_secret("AIRTABLE_TOKEN")' in dashboard_source


def test_opportunity_notes_app_access_is_configurable_and_callable():
    portal_source = _source("heliostock/ui_portal.py")
    demo_source = _source("demo_app.py")
    app_source = _source("heliostock/opportunity_notes/streamlit_opportunity_app.py")

    assert "APP_OPPORTUNITY_LABEL" in portal_source
    assert "APP_OPPORTUNITY_LABEL" in " ".join(portal_source.split("APP_ACCESS_LABELS", 1)[1].splitlines()[:4])
    assert "ui_portal.APP_OPPORTUNITY_LABEL" in demo_source
    assert "from heliostock.opportunity_notes import render_opportunity_notes_app" in demo_source
    assert "def render_opportunity_notes_app() -> None:" in app_source
    assert "st.set_page_config" not in app_source
    assert 'APP_KEY = "helionop"' in app_source
    assert 'APP_LABEL = "HelioNOP"' in app_source
    assert "PROJECT_STORE = JsonProjectStore(APP_KEY, app_label=APP_LABEL)" in app_source


def test_helionop_projects_are_restored_from_github_backup():
    app_source = _source("heliostock/opportunity_notes/streamlit_opportunity_app.py")

    assert 'DEFAULT_BACKUP_PROJECTS_PATH = "seed_data/helionop_projects.json"' in app_source
    assert "GITHUB_BACKUP_HELIONOP_PROJECTS_PATH" in app_source
    assert "def _restore_projects_from_backup" in app_source
    assert "def _upsert_project_backup" in app_source
    assert "ui_portal._github_read_json_list(_backup_projects_path_setting())" in app_source
    assert "ui_portal._github_write_json_list(" in app_source
    assert "_restore_projects_from_backup()" in app_source
    assert "_upsert_project_backup(path=path, payload=saved_payload)" in app_source


def test_helioeco_app_is_registered_in_portal():
    portal_source = _source("heliostock/ui_portal.py")
    demo_source = _source("demo_app.py")
    app_source = _source("heliostock/helioeco/streamlit_helioeco_app.py")

    assert "APP_HELIOECO_LABEL" in portal_source
    assert "APP_HELIOECO_LABEL" in " ".join(portal_source.split("APP_ACCESS_LABELS", 1)[1].splitlines()[:4])
    assert "ui_portal.APP_HELIOECO_LABEL" in demo_source
    assert "from heliostock.helioeco import render_helioeco_app" in demo_source
    assert "def render_helioeco_app() -> None:" in app_source
    assert "st.set_page_config" not in app_source


def test_admin_panel_is_rendered_as_full_page_not_sidebar():
    portal_source = _source("heliostock/ui_portal.py")
    demo_source = _source("demo_app.py")
    sidebar_block = portal_source.split("def render_portal_sidebar", 1)[1].split(
        "def render_heliostock_notice_page",
        1,
    )[0]

    assert "def render_admin_dashboard_page" in portal_source
    assert "Administration HelioTools" in portal_source
    assert "_render_user_admin_panel()" not in sidebar_block
    assert "elif selected_app == ui_portal.APP_ADMIN_LABEL:" in demo_source
    assert "ui_portal.render_admin_dashboard_page()" in demo_source


def test_projects_are_scoped_to_owner_for_non_admin_users():
    source = _source("heliostock/ui_portal.py")
    assert '"owner_email": _current_user_email()' in source
    assert '"shared_with_emails": sorted({_email_normalise(str(email)) for email in current_shared' in source
    assert "def _can_access_project" in source
    assert "if is_admin_authenticated():" in source
    assert "owner_email == current_email" in source
    assert "current_email in shared_emails" in source
    assert "and _can_access_project(path)" in source
    assert "_is_heliostock_project_file(path)" in source
    assert "HELIOSTOCK_PROJECT_STORE = JsonProjectStore" in source
    assert "HELIOSTOCK_PROJECT_STORE.save_project(" in source
    assert "HELIOSTOCK_PROJECT_STORE.app_dir().rglob(\"*.json\")" in source
    assert "HELIOSTOCK_PROJECT_STORE.list_projects(owner_email=current_email)" in source
    assert '"project_id": str(st.session_state.get("heliostock_current_project_id") or uuid.uuid4())' in source
    assert "ce projet." in source


def test_admin_can_manage_app_and_project_access():
    source = _source("heliostock/ui_portal.py")
    assert "APP_ACCESS_LABELS" in source
    assert "def _user_app_access" in source
    assert "def _update_user_app_access" in source
    assert "def _render_app_access_admin" in source
    assert "def _render_project_access_admin" in source
    assert "Applications autorisées" in source
    assert "Utilisateurs autorisés en plus du propriétaire" in source
    assert "_render_app_access_admin(users)" in source
    assert "_render_project_access_admin(users)" in source
    assert "selected_access = st.multiselect" in source
    assert "_set_project_shared_emails(selected_path, selected_shared)" in source


def test_project_access_accepts_shared_users(tmp_path, monkeypatch):
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock import ui_portal

    store = ui_portal.JsonProjectStore("heliostock", app_label="HelioStock", root_dir=tmp_path)
    monkeypatch.setattr(ui_portal, "HELIOSTOCK_PROJECT_STORE", store)
    monkeypatch.setattr(ui_portal, "PROJECTS_DIR", tmp_path / "legacy")
    project_path = store.save_project(
        payload={
            "app": "HelioStock",
            "widget_values": {},
            "shared_with_emails": ["bob@example.com"],
        },
        owner_email="alice@example.com",
        project_name="Demo",
        project_id="aaaaaaaa-0000-0000-0000-000000000000",
    )

    monkeypatch.setitem(ui_portal.st.session_state, "user", {"email": "bob@example.com", "role": "user"})
    monkeypatch.setitem(ui_portal.st.session_state, "heliostock_admin_authenticated", False)

    assert ui_portal._can_access_project(project_path)


def test_login_events_file_is_not_listed_as_project():
    source = _source("heliostock/ui_portal.py")
    assert "USERS_FILE.resolve()" in source
    assert "LOGIN_EVENTS_FILE.resolve()" in source
    assert "def _is_heliostock_project_file" in source
    assert 'data.get("app") == "HelioStock"' in source


def test_project_state_is_cleared_on_login_and_logout():
    source = _source("heliostock/ui_portal.py")
    assert "def _clear_project_session_state" in source
    assert '"heliostock_last_result"' in source
    assert '"heliostock_current_project_name"' in source
    assert '"heliostock_demand_file_bytes"' in source
    assert '"portal_project_to_load"' in source
    connect_block = source.split("def _connect_user", 1)[1].split("def _disconnect_user", 1)[0]
    disconnect_block = source.split("def _disconnect_user", 1)[1].split("def is_admin_authenticated", 1)[0]
    assert "_clear_project_session_state()" in connect_block
    assert "_clear_project_session_state()" in disconnect_block


def test_app_gate_accepts_non_admin_authenticated_users():
    source = _source("demo_app.py")
    assert "getattr(ui_portal, \"is_user_authenticated\", None)" in source
    assert "if not _is_user_authenticated():" in source
    assert "if not is_admin_authenticated():" not in source


def test_app_lazily_imports_heavy_dashboards_after_login():
    source = _source("demo_app.py")
    before_auth_gate = source.split("if not _is_user_authenticated():", 1)[0]
    assert "from heliostock.streamlit_module import render_heliostock_hourly" not in before_auth_gate
    assert "from heliostock.streamlit_module import render_heliostock_hourly" in source


def test_home_cards_do_not_mutate_selectbox_state_after_widget_creation():
    source = _source("heliostock/ui_portal.py")
    home_block = source.split("def render_heliotools_home_page", 1)[1].split(
        "def render_admin_dashboard_page",
        1,
    )[0]
    sidebar_block = source.split("def render_portal_sidebar", 1)[1].split(
        "def render_heliostock_solver_selector",
        1,
    )[0]
    assert 'st.session_state["portal_app_requested"] = title' in home_block
    assert 'st.session_state["portal_app"] = title' not in home_block
    assert 'requested_app = st.session_state.pop("portal_app_requested", None)' in sidebar_block
    assert 'st.session_state["portal_app"] = requested_app' in sidebar_block


def test_login_portal_uses_discreet_beta_copy():
    source = _source("heliostock/ui_portal.py")
    login_block = source.split("def render_admin_login", 1)[1].split("def render_login_portal", 1)[0]
    assert "Outil en bêta test" in source
    assert "Version bêta test" in login_block
    assert "espaces protégés" not in login_block
    assert "Atlansun" not in login_block


def test_portal_uses_short_github_timeout_and_session_user_cache():
    source = _source("heliostock/ui_portal.py")
    assert "GITHUB_BACKUP_TIMEOUT_SECONDS = 3" in source
    assert "USERS_SESSION_CACHE_KEY" in source
    assert "st.session_state[USERS_SESSION_CACHE_KEY]" in source
    assert "timeout=GITHUB_BACKUP_TIMEOUT_SECONDS" in source
