from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (MODULE_ROOT / relative_path).read_text(encoding="utf-8")


def test_auth_store_defines_neon_schema_without_project_secrets():
    source = _source("heliostock/common/auth_store.py")

    assert "CREATE TABLE IF NOT EXISTS heliotools_users" in source
    assert "CREATE TABLE IF NOT EXISTS heliotools_login_events" in source
    assert "CREATE TABLE IF NOT EXISTS heliotools_project_backups" in source
    assert "payload JSONB NOT NULL" in source
    assert "password_updated_at TIMESTAMPTZ" in source
    assert "event_ts TIMESTAMPTZ" in source
    assert "GITHUB_BACKUP_TOKEN" not in source


def test_seed_auth_files_are_not_versioned_defaults():
    portal_source = _source("heliostock/ui_portal.py")
    gitignore = (MODULE_ROOT.parent / ".gitignore").read_text(encoding="utf-8")

    assert "DEFAULT_BACKUP_USERS_PATH" not in portal_source
    assert "DEFAULT_BACKUP_LOGIN_EVENTS_PATH" not in portal_source
    assert "seed_data/users.json" not in portal_source
    assert "seed_data/login_events.json" not in portal_source
    assert "heliostock_module/seed_data/users.json" in gitignore
    assert "heliostock_module/seed_data/login_events.json" in gitignore


def test_auth_fixtures_are_synthetic_examples_only():
    users_fixture = _source("tests/fixtures/auth_users.example.json")
    events_fixture = _source("tests/fixtures/login_events.example.json")

    assert "example.test" in users_fixture
    assert "fixture-only:not-a-real-password-hash" in users_fixture
    assert "atlansun.fr" not in users_fixture
    assert "nrg-conseils.com" not in users_fixture
    assert "crer.info.fr" not in users_fixture
    assert "example.test" in events_fixture
