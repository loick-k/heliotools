from __future__ import annotations

from pathlib import Path

from heliostock.auth_session import (
    AUTH_SESSION_COOKIE_NAME,
    authentication_fingerprint,
    config_from_values,
    create_session_token,
    decoded_payload_unsafe_for_tests,
    normalise_session_hours,
    payload_has_sensitive_fields,
    validate_token_for_user,
    verify_session_token,
)


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (MODULE_ROOT / relative_path).read_text(encoding="utf-8")


def _config(environment: str = "production"):
    return config_from_values(
        secret="x" * 48,
        hours=12,
        environment=environment,
    )


def _user(**overrides):
    user = {
        "email": "User@Example.com",
        "nom": "User",
        "role": "admin",
        "app_access": ["HelioDyn"],
        "password_hash": "salt:hash",
        "password_updated_at": "2026-08-13T10:00:00",
        "active": True,
    }
    user.update(overrides)
    return user


def test_valid_session_token_is_signed_and_verified():
    config = _config()
    token = create_session_token(_user(), config=config, now=1000)

    validation = verify_session_token(token, config=config, now=1001)

    assert validation.ok
    assert validation.payload
    assert validation.payload["email"] == "user@example.com"
    assert validation.payload["exp"] == 1000 + 12 * 3600


def test_tampered_session_token_is_refused():
    config = _config()
    token = create_session_token(_user(), config=config, now=1000)
    tampered = token.replace("a", "b", 1)

    validation = verify_session_token(tampered, config=config, now=1001)

    assert not validation.ok


def test_expired_session_token_is_refused():
    config = _config()
    token = create_session_token(_user(), config=config, now=1000)

    validation = verify_session_token(token, config=config, now=1000 + 12 * 3600 + 1)

    assert not validation.ok
    assert validation.reason == "expired"


def test_environment_separation_refuses_other_environment():
    token = create_session_token(_user(), config=_config("preprod"), now=1000)

    validation = verify_session_token(token, config=_config("production"), now=1001)

    assert not validation.ok
    assert validation.reason == "wrong_environment"


def test_user_is_reloaded_and_permissions_are_not_read_from_cookie():
    config = _config()
    token = create_session_token(_user(role="admin", app_access=["HelioDyn"]), config=config, now=1000)
    payload = decoded_payload_unsafe_for_tests(token)

    validation = validate_token_for_user(
        token,
        _user(role="user", app_access=["HelioNOP"]),
        config=config,
        now=1001,
    )

    assert validation.ok
    assert "role" not in payload
    assert "app_access" not in payload
    assert not payload_has_sensitive_fields(payload)


def test_deleted_disabled_or_password_changed_user_revokes_cookie():
    config = _config()
    token = create_session_token(_user(), config=config, now=1000)

    assert validate_token_for_user(token, None, config=config, now=1001).reason == "user_missing"
    assert validate_token_for_user(token, _user(active=False), config=config, now=1001).reason == "user_disabled"
    changed = _user(password_hash="other:hash")
    assert validate_token_for_user(token, changed, config=config, now=1001).reason == "auth_material_changed"


def test_auth_fingerprint_is_non_reversible_and_changes_with_password_material():
    config = _config()
    first = authentication_fingerprint(_user(password_hash="salt:hash"), config.secret)
    second = authentication_fingerprint(_user(password_hash="salt:changed"), config.secret)

    assert first != second
    assert "salt:hash" not in first


def test_invalid_secret_disables_persistence_without_blocking_classic_login():
    config = config_from_values(secret="too-short", hours=12, environment="production")

    assert not config.is_enabled
    assert create_session_token(_user(), config=config, now=1000) == ""
    assert verify_session_token("", config=config, now=1001).reason == "disabled"


def test_session_hours_are_bounded():
    assert normalise_session_hours(None) == 12
    assert normalise_session_hours(0) == 1
    assert normalise_session_hours(9999) == 720


def test_portal_restores_cookie_before_auth_gate_and_deletes_on_logout():
    demo_source = _source("demo_app.py")
    portal_source = _source("heliostock/ui_portal.py")

    before_gate = demo_source.split("if not _is_user_authenticated():", 1)[0]
    logout_block = portal_source.split("def _disconnect_user", 1)[1].split("def is_admin_authenticated", 1)[0]

    assert "ui_portal.restore_persistent_auth_session()" in before_gate
    assert "def restore_persistent_auth_session" in portal_source
    assert "_clear_persistent_auth_cookie()" in logout_block
    assert AUTH_SESSION_COOKIE_NAME in portal_source


def test_portal_cookie_restore_waits_for_cookie_manager_hydration():
    portal_source = _source("heliostock/ui_portal.py")
    restore_block = portal_source.split("def restore_persistent_auth_session", 1)[1].split("def _hash_password", 1)[0]

    assert "def _cookie_snapshot" in portal_source
    assert "if cookies is None:" in restore_block
    assert 'st.session_state.pop(AUTH_SESSION_RESTORE_ATTEMPTED_KEY, None)' in restore_block
    assert 'st.session_state[AUTH_SESSION_RESTORE_ATTEMPTED_KEY] = True' in restore_block
    assert restore_block.index("token = str(cookies.get") < restore_block.index(
        'st.session_state[AUTH_SESSION_RESTORE_ATTEMPTED_KEY] = True'
    )


def test_cookie_payload_does_not_contain_sensitive_business_or_secret_data():
    config = _config()
    token = create_session_token(
        _user(
            permissions=["admin"],
            token="secret",
            api_key="secret",
            password="plain",
        ),
        config=config,
        now=1000,
    )
    payload = decoded_payload_unsafe_for_tests(token)

    assert not payload_has_sensitive_fields(payload)
    assert set(payload) == {"auth_fp", "email", "env", "exp", "iat", "user_id", "v"}
