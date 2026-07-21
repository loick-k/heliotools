from __future__ import annotations

import json
import math
from typing import Any

import requests


GPU_API_BASE = "https://apicarto.ign.fr/api/gpu"
REQUEST_TIMEOUT = (8, 45)
USER_AGENT = "HelioTools-Architectural-Constraints/0.1"

CATEGORY_CONFIG: dict[str, dict[str, str]] = {
    "AC1": {
        "title": "Monuments historiques et abords",
        "short_title": "Monuments historiques / abords",
        "description": (
            "Servitudes de protection des monuments historiques classés ou inscrits "
            "et de leurs abords."
        ),
    },
    "AC2": {
        "title": "Sites classés ou inscrits",
        "short_title": "Sites classés / inscrits",
        "description": (
            "Servitudes relatives aux sites inscrits et classés."
        ),
    },
    "AC4": {
        "title": "Sites patrimoniaux remarquables",
        "short_title": "Site patrimonial remarquable",
        "description": (
            "Servitudes relatives aux sites patrimoniaux remarquables."
        ),
    },
}

# Les zones importantes pour la pré-vérification sont surfaciques.
# Pour AC1, on ajoute aussi les assiettes ponctuelles et linéaires autour du point.
QUERY_PLAN: tuple[tuple[str, str, str], ...] = (
    ("AC1", "assiette-sup-s", "point"),
    ("AC1", "assiette-sup-l", "small_polygon"),
    ("AC1", "assiette-sup-p", "small_polygon"),
    ("AC2", "assiette-sup-s", "point"),
    ("AC4", "assiette-sup-s", "point"),
)


class PatrimoineServiceError(RuntimeError):
    """Erreur lisible liée à l'interrogation des données patrimoniales."""


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Latitude invalide.")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("Longitude invalide.")


def _point_geometry(latitude: float, longitude: float) -> dict[str, Any]:
    _validate_coordinates(latitude, longitude)
    return {
        "type": "Point",
        "coordinates": [longitude, latitude],
    }


def _small_square_geometry(
    latitude: float,
    longitude: float,
    radius_m: float = 12.0,
) -> dict[str, Any]:
    """
    Produit un petit polygone carré autour du point.

    Il sert uniquement à retrouver des assiettes ponctuelles ou linéaires
    quasiment confondues avec l'emplacement du projet.
    """
    _validate_coordinates(latitude, longitude)

    safe_radius = min(max(float(radius_m), 1.0), 100.0)
    lat_delta = safe_radius / 111_320.0
    cos_lat = max(abs(math.cos(math.radians(latitude))), 0.01)
    lon_delta = safe_radius / (111_320.0 * cos_lat)

    west = longitude - lon_delta
    east = longitude + lon_delta
    south = latitude - lat_delta
    north = latitude + lat_delta

    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }


def _parse_feature_collection(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PatrimoineServiceError(
            "L'API d'urbanisme a renvoyé une réponse JSON inattendue."
        )

    raw_features = payload.get("features", [])
    if not isinstance(raw_features, list):
        raise PatrimoineServiceError(
            "La réponse GeoJSON ne contient pas de liste de données."
        )

    valid_features: list[dict[str, Any]] = []

    for raw_feature in raw_features:
        if not isinstance(raw_feature, dict):
            continue
        if raw_feature.get("type") != "Feature":
            continue

        geometry = raw_feature.get("geometry")
        properties = raw_feature.get("properties")

        if geometry is not None and not isinstance(geometry, dict):
            continue
        if not isinstance(properties, dict):
            properties = {}

        valid_features.append(
            {
                "type": "Feature",
                "id": raw_feature.get("id"),
                "geometry": geometry,
                "properties": dict(properties),
            }
        )

    total = payload.get("totalFeatures")
    try:
        total_features = int(total)
    except (TypeError, ValueError):
        total_features = len(valid_features)

    return {
        "type": "FeatureCollection",
        "totalFeatures": total_features,
        "features": valid_features,
    }


def _query_gpu(
    endpoint: str,
    category: str,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    if category not in CATEGORY_CONFIG:
        raise ValueError(f"Catégorie patrimoniale inconnue : {category}")

    try:
        response = requests.get(
            f"{GPU_API_BASE}/{endpoint}",
            params={
                "geom": json.dumps(geometry, separators=(",", ":")),
                "categorie": category,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise PatrimoineServiceError(
            f"Le service GPU n'a pas répondu pour {category} / {endpoint}."
        ) from exc
    except requests.RequestException as exc:
        raise PatrimoineServiceError(
            f"Interrogation GPU impossible pour {category} / {endpoint} : {exc}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise PatrimoineServiceError(
            f"La réponse GPU est illisible pour {category} / {endpoint}."
        ) from exc

    return _parse_feature_collection(payload)


def _feature_title(properties: dict[str, Any], category: str) -> str:
    candidates = (
        properties.get("nomass"),
        properties.get("typeass"),
        properties.get("nomgen"),
        properties.get("nom"),
        properties.get("libelle"),
        properties.get("fichier"),
    )

    for value in candidates:
        text = " ".join(str(value or "").split())
        if text:
            return text

    return CATEGORY_CONFIG[category]["short_title"]


def _prepare_feature(
    feature: dict[str, Any],
    category: str,
    endpoint: str,
) -> dict[str, Any]:
    prepared = {
        "type": "Feature",
        "id": feature.get("id"),
        "geometry": feature.get("geometry"),
        "properties": dict(feature.get("properties") or {}),
    }

    properties = prepared["properties"]
    properties["_category"] = category
    properties["_category_title"] = CATEGORY_CONFIG[category]["title"]
    properties["_source_endpoint"] = endpoint
    properties["_display_title"] = _feature_title(properties, category)

    # Folium attend que les champs déclarés dans les popups existent
    # dans chaque objet de la collection.
    for popup_key in ("suptype", "typeass", "nomass", "partition"):
        properties.setdefault(popup_key, "")

    details: list[str] = [properties["_display_title"]]

    typeass = " ".join(str(properties.get("typeass") or "").split())
    if typeass and typeass.lower() not in properties["_display_title"].lower():
        details.append(typeass)

    properties["_display_details"] = " - ".join(details)
    return prepared


def analyse_patrimoine(
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """
    Recherche les servitudes patrimoniales AC1, AC2 et AC4 au droit du projet.

    Les assiettes surfaciques sont interrogées avec le point exact.
    Les assiettes linéaires/ponctuelles AC1 sont interrogées avec un petit carré.
    """
    _validate_coordinates(latitude, longitude)

    point = _point_geometry(latitude, longitude)
    small_polygon = _small_square_geometry(latitude, longitude)

    by_category: dict[str, list[dict[str, Any]]] = {
        category: [] for category in CATEGORY_CONFIG
    }
    errors: list[str] = []
    successful_queries = 0

    for category, endpoint, geometry_kind in QUERY_PLAN:
        geometry = point if geometry_kind == "point" else small_polygon

        try:
            collection = _query_gpu(
                endpoint=endpoint,
                category=category,
                geometry=geometry,
            )
        except PatrimoineServiceError as exc:
            errors.append(str(exc))
            continue

        successful_queries += 1

        for feature in collection["features"]:
            by_category[category].append(
                _prepare_feature(
                    feature=feature,
                    category=category,
                    endpoint=endpoint,
                )
            )

    if successful_queries == 0:
        raise PatrimoineServiceError(
            "Aucune interrogation du Géoportail de l'Urbanisme n'a abouti. "
            "Le service est peut-être temporairement indisponible."
        )

    feature_collections: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}

    for category, features in by_category.items():
        # Déduplication prudente par id, sinon par propriétés + géométrie.
        unique_features: list[dict[str, Any]] = []
        seen: set[str] = set()

        for feature in features:
            identity = str(feature.get("id") or "")
            if not identity:
                identity = json.dumps(
                    {
                        "geometry": feature.get("geometry"),
                        "properties": feature.get("properties"),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )

            if identity in seen:
                continue
            seen.add(identity)
            unique_features.append(feature)

        feature_collections[category] = {
            "type": "FeatureCollection",
            "features": unique_features,
        }
        counts[category] = len(unique_features)

    detected_categories = [
        category
        for category in CATEGORY_CONFIG
        if counts.get(category, 0) > 0
    ]

    return {
        "latitude": latitude,
        "longitude": longitude,
        "counts": counts,
        "detected_categories": detected_categories,
        "has_protection": bool(detected_categories),
        "feature_collections": feature_collections,
        "errors": errors,
        "query_scope": {
            "surface": "intersection avec le point exact",
            "ac1_point_line": "recherche dans un rayon indicatif d'environ 12 m",
        },
    }


def compact_feature_properties(feature: dict[str, Any]) -> dict[str, Any]:
    """Retourne les attributs les plus utiles pour l'affichage Streamlit."""
    properties = dict(feature.get("properties") or {})
    preferred_keys = (
        "_display_title",
        "suptype",
        "nomass",
        "typeass",
        "idass",
        "idgen",
        "partition",
        "fichier",
        "_source_endpoint",
    )

    compact: dict[str, Any] = {}

    for key in preferred_keys:
        value = properties.get(key)
        if value not in (None, ""):
            compact[key] = value

    if compact:
        return compact

    return properties

