from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import time
from typing import Any


AUTH_SESSION_COOKIE_NAME = "heliotools_auth_session"
AUTH_SESSION_MIN_SECRET_LENGTH = 32
AUTH_SESSION_DEFAULT_HOURS = 12
AUTH_SESSION_MIN_HOURS = 1
AUTH_SESSION_MAX_HOURS = 720
AUTH_SESSION_DEFAULT_ENV = "production"

SENSITIVE_COOKIE_KEYS = {
    "password",
    "password_hash",
    "permissions",
    "app_access",
    "role",
    "secret",
    "token",
    "api_key",
}


@dataclass(frozen=True)
class AuthSessionConfig:
    secret: str
    hours: int = AUTH_SESSION_DEFAULT_HOURS
    environment: str = AUTH_SESSION_DEFAULT_ENV

    @property
    def is_enabled(self) -> bool:
        return is_valid_secret(self.secret)


@dataclass(frozen=True)
class AuthSessionValidation:
    ok: bool
    payload: dict[str, Any] | None = None
    reason: str = ""


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def is_valid_secret(secret: str) -> bool:
    return len(str(secret or "")) >= AUTH_SESSION_MIN_SECRET_LENGTH


def normalise_session_hours(value: Any) -> int:
    try:
        hours = int(float(value))
    except Exception:
        hours = AUTH_SESSION_DEFAULT_HOURS
    return max(AUTH_SESSION_MIN_HOURS, min(AUTH_SESSION_MAX_HOURS, hours))


def environment_name(value: str | None = None) -> str:
    env = str(value or os.environ.get("AUTH_SESSION_ENV") or os.environ.get("APP_ENV") or "").strip()
    return env or AUTH_SESSION_DEFAULT_ENV


def config_from_values(secret: str = "", hours: Any = None, environment: str = "") -> AuthSessionConfig:
    return AuthSessionConfig(
        secret=str(secret or ""),
        hours=normalise_session_hours(hours if hours is not None else AUTH_SESSION_DEFAULT_HOURS),
        environment=environment_name(environment),
    )


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _stable_json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def user_identifier(user: dict[str, Any]) -> str:
    for key in ("id", "user_id", "uid"):
        value = str(user.get(key, "") or "").strip()
        if value:
            return value
    return normalize_email(str(user.get("email", "")))


def authentication_fingerprint(user: dict[str, Any], secret: str) -> str:
    """Return a non-reversible fingerprint that changes when auth material changes."""

    email = normalize_email(str(user.get("email", "")))
    security_material = "|".join(
        [
            email,
            str(user.get("password_hash", "") or ""),
            str(user.get("password_updated_at", "") or ""),
            str(user.get("auth_updated_at", "") or ""),
        ]
    )
    digest = hmac.new(
        str(secret).encode("utf-8"),
        security_material.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def create_session_token(
    user: dict[str, Any],
    *,
    config: AuthSessionConfig,
    now: float | None = None,
) -> str:
    if not config.is_enabled:
        return ""

    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + config.hours * 3600
    payload = {
        "v": 1,
        "user_id": user_identifier(user),
        "email": normalize_email(str(user.get("email", ""))),
        "iat": issued_at,
        "exp": expires_at,
        "env": config.environment,
        "auth_fp": authentication_fingerprint(user, config.secret),
    }
    payload_segment = _b64url_encode(_stable_json(payload))
    signature = hmac.new(config.secret.encode("utf-8"), payload_segment.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_segment}.{_b64url_encode(signature)}"


def verify_session_token(
    token: str,
    *,
    config: AuthSessionConfig,
    now: float | None = None,
) -> AuthSessionValidation:
    if not config.is_enabled:
        return AuthSessionValidation(False, reason="disabled")
    if not token or "." not in str(token):
        return AuthSessionValidation(False, reason="missing")
    try:
        payload_segment, signature_segment = str(token).split(".", 1)
        expected = hmac.new(
            config.secret.encode("utf-8"),
            payload_segment.encode("ascii"),
            hashlib.sha256,
        ).digest()
        received = _b64url_decode(signature_segment)
        if not hmac.compare_digest(expected, received):
            return AuthSessionValidation(False, reason="bad_signature")
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except Exception:
        return AuthSessionValidation(False, reason="invalid")

    if not isinstance(payload, dict):
        return AuthSessionValidation(False, reason="invalid_payload")
    if str(payload.get("env", "")) != config.environment:
        return AuthSessionValidation(False, reason="wrong_environment")
    expires_at = int(payload.get("exp", 0) or 0)
    current_time = int(now if now is not None else time.time())
    if expires_at <= current_time:
        return AuthSessionValidation(False, payload=payload, reason="expired")
    if not normalize_email(str(payload.get("email", ""))):
        return AuthSessionValidation(False, payload=payload, reason="missing_email")
    return AuthSessionValidation(True, payload=payload)


def validate_token_for_user(
    token: str,
    user: dict[str, Any] | None,
    *,
    config: AuthSessionConfig,
    now: float | None = None,
) -> AuthSessionValidation:
    validation = verify_session_token(token, config=config, now=now)
    if not validation.ok or not validation.payload:
        return validation
    if not isinstance(user, dict):
        return AuthSessionValidation(False, payload=validation.payload, reason="user_missing")
    if user.get("active") is False:
        return AuthSessionValidation(False, payload=validation.payload, reason="user_disabled")
    token_email = normalize_email(str(validation.payload.get("email", "")))
    user_email = normalize_email(str(user.get("email", "")))
    if token_email != user_email:
        return AuthSessionValidation(False, payload=validation.payload, reason="user_mismatch")
    expected_fingerprint = authentication_fingerprint(user, config.secret)
    if not hmac.compare_digest(str(validation.payload.get("auth_fp", "")), expected_fingerprint):
        return AuthSessionValidation(False, payload=validation.payload, reason="auth_material_changed")
    return validation


def decoded_payload_unsafe_for_tests(token: str) -> dict[str, Any]:
    payload_segment = str(token).split(".", 1)[0]
    data = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    return data if isinstance(data, dict) else {}


def payload_has_sensitive_fields(payload: dict[str, Any]) -> bool:
    lowered = {str(key).lower() for key in payload}
    return bool(lowered & SENSITIVE_COOKIE_KEYS)
