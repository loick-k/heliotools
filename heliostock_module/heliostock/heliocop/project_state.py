from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import pandas as pd


APP_KEY = "heliocop"
APP_LABEL = "HelioCOP"
PROJECT_IDENTITY_PREFIX = "heliocop_"
APP_INPUT_PREFIX = "heliocop_v2_"

_BLOCKED_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "cookie",
)


def _is_safe_project_key(key: str) -> bool:
    lowered = key.lower()
    if any(part in lowered for part in _BLOCKED_KEY_PARTS):
        return False
    return key.startswith(PROJECT_IDENTITY_PREFIX) or key.startswith(APP_INPUT_PREFIX)


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (date, datetime)):
        return {"__type__": "date", "value": value.isoformat()}
    if isinstance(value, Path):
        return {"__type__": "path", "value": str(value)}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "value": [_json_value(item) for item in value]}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, pd.DataFrame):
        return {
            "__type__": "dataframe",
            "columns": [str(column) for column in value.columns],
            "records": value.to_dict(orient="records"),
        }
    return None


def _session_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__type__") == "date":
        raw = str(value.get("value") or "")
        if not raw:
            return date.today()
        try:
            if "T" in raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            return date.fromisoformat(raw)
        except ValueError:
            return date.today()
    if isinstance(value, dict) and value.get("__type__") == "path":
        return str(value.get("value") or "")
    if isinstance(value, dict) and value.get("__type__") == "tuple":
        raw_items = value.get("value", [])
        if isinstance(raw_items, list):
            return tuple(_session_value(item) for item in raw_items)
        return tuple()
    if isinstance(value, dict) and value.get("__type__") == "dataframe":
        records = value.get("records", [])
        columns = value.get("columns", None)
        if isinstance(records, list):
            frame = pd.DataFrame(records)
            if isinstance(columns, list):
                for column in columns:
                    if column not in frame.columns:
                        frame[column] = None
                frame = frame[[column for column in columns if column in frame.columns]]
            return frame
        return pd.DataFrame()
    if isinstance(value, list):
        return [_session_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _session_value(item) for key, item in value.items()}
    return value


def build_heliocop_state_payload(session_state: Mapping[str, Any]) -> dict[str, Any]:
    """Extract JSON-safe HelioCOP widget state.

    The payload intentionally contains only UI state needed to reload a project.
    Sensitive keys and non-serializable runtime objects are ignored.
    """

    values: dict[str, Any] = {}
    skipped: list[str] = []
    for key, value in session_state.items():
        if not _is_safe_project_key(str(key)):
            continue
        encoded = _json_value(value)
        if encoded is None and value is not None:
            skipped.append(str(key))
            continue
        values[str(key)] = encoded
    return {
        "schema_version": 1,
        "app_key": APP_KEY,
        "app_label": APP_LABEL,
        "state_values": values,
        "skipped_state_keys": sorted(skipped),
    }


def restore_heliocop_state_payload(payload: Mapping[str, Any], session_state: MutableMapping[str, Any]) -> None:
    values = payload.get("state_values", {})
    if not isinstance(values, Mapping):
        return
    for key, value in values.items():
        if not _is_safe_project_key(str(key)):
            continue
        session_state[str(key)] = _session_value(value)

