from __future__ import annotations

from datetime import date
from typing import Any, Mapping


DEFAULT_PROJECT_LATITUDE = 47.2184
DEFAULT_PROJECT_LONGITUDE = -1.5536
DEFAULT_PROJECT_REGIONS: tuple[str, ...] = ("Bretagne", "Pays de la Loire")
DEFAULT_PROJECT_DEPARTMENTS: tuple[str, ...] = (
    "22 - Côtes-d'Armor",
    "29 - Finistère",
    "35 - Ille-et-Vilaine",
    "44 - Loire-Atlantique",
    "49 - Maine-et-Loire",
    "53 - Mayenne",
    "56 - Morbihan",
    "72 - Sarthe",
    "85 - Vendée",
)
DEFAULT_SITE_TYPOLOGIES: tuple[str, ...] = (
    "Industrie",
    "Logement collectif",
    "EHPAD",
    "Hôpital",
    "Hôtel",
    "Camping",
    "Piscine et centre aquatique",
    "Bâtiment public",
    "Bâtiment sportif et loisirs",
    "Station de lavage",
    "Réseau de chaleur",
    "Autre",
)
HELIORC_SITE_TYPOLOGIES: tuple[str, ...] = (
    "Réseau de chaleur",
    "Logement collectif",
    "EHPAD",
    "Hôpital",
    "Piscine et centre aquatique",
    "Bâtiment public",
    "Industrie",
    "Autre",
)


def _project_value(source: Mapping[str, Any] | object, *names: str, default: Any = "") -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        return default
    for name in names:
        if hasattr(source, name):
            value = getattr(source, name)
            if value is not None:
                return value
    return default


def _project_date_iso(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _project_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def project_context_to_payload(
    source: Mapping[str, Any] | object,
    *,
    app_key: str,
    app_label: str,
    geographic_scope: str,
    weather_source: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the normalized project context shared by HelioTools apps."""

    payload: dict[str, Any] = {
        "schema_version": 1,
        "app_key": str(app_key or ""),
        "app_label": str(app_label or ""),
        "geographic_scope": str(geographic_scope or ""),
        "project_name": str(_project_value(source, "project_name", "name", default="") or ""),
        "client_name": str(_project_value(source, "client_name", "client", "owner_name", default="") or ""),
        "airtable_id": str(_project_value(source, "airtable_id", default="") or ""),
        "analyst": str(_project_value(source, "analyst", default="") or ""),
        "project_date": _project_date_iso(_project_value(source, "project_date", "date", default="")),
        "typology": str(_project_value(source, "typology", default="") or ""),
        "building_state": str(_project_value(source, "building_state", default="") or ""),
        "region": str(_project_value(source, "region", default="") or ""),
        "department": str(_project_value(source, "department", default="") or ""),
        "city": str(_project_value(source, "city", default="") or ""),
        "address": str(_project_value(source, "address", default="") or ""),
        "latitude": _project_float(
            _project_value(source, "latitude", default=DEFAULT_PROJECT_LATITUDE),
            DEFAULT_PROJECT_LATITUDE,
        ),
        "longitude": _project_float(
            _project_value(source, "longitude", default=DEFAULT_PROJECT_LONGITUDE),
            DEFAULT_PROJECT_LONGITUDE,
        ),
        "weather": {
            "source": str(weather_source or ""),
            "region": str(_project_value(source, "weather_region", default="") or ""),
            "station": str(_project_value(source, "weather_station", default="") or ""),
        },
        "notes": str(_project_value(source, "notes", default="") or ""),
    }
    if extra:
        payload["extra"] = dict(extra)
    return payload
