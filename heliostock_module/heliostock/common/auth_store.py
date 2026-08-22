from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NeonAuthStore:
    """PostgreSQL/Neon-backed persistence for portal users and login events.

    The portal still manipulates user records as dictionaries so the migration
    remains low-risk. Neon stores the operational fields in typed columns and
    the full record in JSONB for forward compatibility with existing metadata.
    """

    database_url: str

    @property
    def is_configured(self) -> bool:
        return bool(str(self.database_url or "").strip())

    def available(self) -> bool:
        return self.is_configured and _psycopg_available()

    def ensure_schema(self) -> None:
        if not self.available():
            return
        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS heliotools_users (
                        email TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        role TEXT NOT NULL DEFAULT 'user',
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        password_updated_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS heliotools_login_events (
                        id BIGSERIAL PRIMARY KEY,
                        event_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        email TEXT NOT NULL DEFAULT '',
                        success BOOLEAN NOT NULL DEFAULT FALSE,
                        role TEXT NOT NULL DEFAULT '',
                        reason TEXT NOT NULL DEFAULT '',
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_heliotools_login_events_ts "
                    "ON heliotools_login_events (event_ts DESC)"
                )
            conn.commit()

    def load_users(self) -> list[dict[str, Any]]:
        if not self.available():
            return []
        self.ensure_schema()
        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM heliotools_users ORDER BY email")
                rows = cur.fetchall()
        return [_json_payload(row[0]) for row in rows]

    def save_users(self, users: list[dict[str, Any]]) -> None:
        if not self.available():
            return
        self.ensure_schema()
        clean_users = [dict(user) for user in users if isinstance(user, dict)]
        emails = [_normalise_email(str(user.get("email", ""))) for user in clean_users]
        emails = [email for email in emails if email]
        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for user in clean_users:
                    email = _normalise_email(str(user.get("email", "")))
                    if not email:
                        continue
                    user["email"] = email
                    cur.execute(
                        """
                        INSERT INTO heliotools_users
                            (email, payload, role, active, password_updated_at, created_at, updated_at)
                        VALUES
                            (%s, %s::jsonb, %s, %s, %s, %s, NOW())
                        ON CONFLICT (email) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            role = EXCLUDED.role,
                            active = EXCLUDED.active,
                            password_updated_at = EXCLUDED.password_updated_at,
                            created_at = COALESCE(heliotools_users.created_at, EXCLUDED.created_at),
                            updated_at = NOW()
                        """,
                        (
                            email,
                            json.dumps(user, ensure_ascii=False),
                            str(user.get("role", "user") or "user"),
                            bool(user.get("active", True) is not False),
                            _parse_datetime(user.get("password_updated_at")),
                            _parse_datetime(user.get("created_at")),
                        ),
                    )
                if emails:
                    cur.execute("DELETE FROM heliotools_users WHERE NOT (email = ANY(%s))", (emails,))
            conn.commit()

    def append_login_event(self, event: dict[str, Any]) -> None:
        if not self.available():
            return
        self.ensure_schema()
        clean_event = dict(event) if isinstance(event, dict) else {}
        email = _normalise_email(str(clean_event.get("email", "")))
        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO heliotools_login_events
                        (event_ts, email, success, role, reason, payload)
                    VALUES
                        (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        _parse_datetime(clean_event.get("timestamp")) or datetime.now(),
                        email,
                        bool(clean_event.get("success")),
                        str(clean_event.get("role", "") or ""),
                        str(clean_event.get("reason", "") or ""),
                        json.dumps(clean_event, ensure_ascii=False),
                    ),
                )
            conn.commit()

    def load_login_events(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        if not self.available():
            return []
        self.ensure_schema()
        with _connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload
                    FROM heliotools_login_events
                    ORDER BY event_ts DESC, id DESC
                    LIMIT %s
                    """,
                    (int(max(1, limit)),),
                )
                rows = cur.fetchall()
        return list(reversed([_json_payload(row[0]) for row in rows]))


def _psycopg_available() -> bool:
    try:
        import psycopg  # noqa: F401
    except Exception:
        return False
    return True


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(str(database_url), connect_timeout=5)


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _normalise_email(email: str) -> str:
    return str(email or "").strip().lower()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
