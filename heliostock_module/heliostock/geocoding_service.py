from __future__ import annotations

import math

import requests


GEOCODING_URL = "https://data.geopf.fr/geocodage/search"
REQUEST_TIMEOUT = (8, 30)
USER_AGENT = "HelioTools-GMI/0.1"


class GeocodingServiceError(RuntimeError):
    """Erreur lisible liée au géocodage d'une adresse."""


def _as_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_candidates(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise GeocodingServiceError("La réponse du géocodeur n'est pas un objet JSON valide.")

    raw_features = payload.get("features", [])
    if not isinstance(raw_features, list):
        raise GeocodingServiceError("La réponse du géocodeur ne contient pas de liste de résultats.")

    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, float, float]] = set()
    for feature in raw_features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            continue

        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            continue
        longitude = _as_float(coordinates[0])
        latitude = _as_float(coordinates[1])
        if longitude is None or latitude is None:
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue

        label = str(properties.get("label") or properties.get("name") or "Adresse trouvée").strip()
        context = str(properties.get("context") or "").strip()
        score = _as_float(properties.get("score"))
        dedup_key = (label, round(latitude, 7), round(longitude, 7))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        candidates.append(
            {
                "label": label,
                "context": context,
                "latitude": latitude,
                "longitude": longitude,
                "score": score,
                "postcode": str(properties.get("postcode") or "").strip(),
                "city": str(properties.get("city") or "").strip(),
            }
        )
    return candidates


def search_addresses(query: str, limit: int = 5) -> list[dict[str, object]]:
    cleaned_query = " ".join(str(query or "").split())
    if len(cleaned_query) < 3:
        raise ValueError("Saisissez au moins 3 caractères pour rechercher une adresse.")
    if not 1 <= limit <= 10:
        raise ValueError("Le nombre de résultats doit être compris entre 1 et 10.")

    try:
        response = requests.get(
            GEOCODING_URL,
            params={"q": cleaned_query, "limit": limit},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 429:
            raise GeocodingServiceError("Le service de géocodage est momentanément trop sollicité.")
        response.raise_for_status()
    except requests.Timeout as exc:
        raise GeocodingServiceError("Le service de géocodage n'a pas répondu dans le délai prévu.") from exc
    except requests.RequestException as exc:
        raise GeocodingServiceError(f"Connexion au service de géocodage impossible : {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise GeocodingServiceError("Le service de géocodage a renvoyé une réponse illisible.") from exc
    return _parse_candidates(payload)
