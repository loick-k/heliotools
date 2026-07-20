from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET

import requests


WFS_URL = "https://mapsref.brgm.fr/wxs/geothermie/gmi_total"
REQUEST_TIMEOUT = (8, 45)
USER_AGENT = "HelioTools-GMI/0.1"


class GMIServiceError(RuntimeError):
    """Erreur lisible liée au service cartographique GMI du BRGM."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def _get(params: dict[str, object]) -> requests.Response:
    try:
        response = requests.get(
            WFS_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise GMIServiceError("Le service BRGM n'a pas répondu dans le délai prévu.") from exc
    except requests.RequestException as exc:
        raise GMIServiceError(f"Connexion au service BRGM impossible : {exc}") from exc
    if not response.content:
        raise GMIServiceError("Le service BRGM a renvoyé une réponse vide.")
    return response


def _parse_xml(content: bytes, context: str) -> ET.Element:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise GMIServiceError(f"La réponse XML du BRGM est illisible ({context}).") from exc
    if "exception" in _normalize(_local_name(root.tag)):
        detail = " ".join((element.text or "").strip() for element in root.iter() if (element.text or "").strip())
        raise GMIServiceError(f"Le service BRGM a renvoyé une erreur OGC : {detail[:700] or 'détail indisponible'}")
    return root


def _guess_exchanger_type(searchable: str) -> str | None:
    if any(token in searchable for token in ("sonde", "echangeur ferme", "ferme")):
        return "ferme"
    if any(token in searchable for token in ("nappe", "echangeur ouvert", "ouvert")):
        return "ouvert"
    return None


def _guess_depth_max(searchable: str) -> int | None:
    ranges = re.findall(r"(?:10\s*(?:a|à|jusqu a|to|-)\s*)?(50|100|200)\s*m", searchable)
    if ranges:
        return int(ranges[-1])
    compact = re.findall(r"(?:^|\D)(50|100|200)(?:m|\D|$)", searchable)
    return int(compact[-1]) if compact else None


def discover_gmi_layers() -> list[dict[str, object]]:
    response = _get({"SERVICE": "WFS", "REQUEST": "GetCapabilities", "ACCEPTVERSIONS": "2.0.0,1.1.0,1.0.0"})
    root = _parse_xml(response.content, "GetCapabilities")
    layers: list[dict[str, object]] = []
    for feature_type in root.iter():
        if _local_name(feature_type.tag) != "FeatureType":
            continue
        name = ""
        title = ""
        for child in feature_type:
            child_name = _local_name(child.tag)
            if child_name == "Name":
                name = (child.text or "").strip()
            elif child_name == "Title":
                title = (child.text or "").strip()
        searchable = _normalize(f"{name} {title}")
        if not name or "gmi" not in searchable:
            continue
        layers.append(
            {
                "name": name,
                "title": title or name,
                "exchanger_type_detected": _guess_exchanger_type(searchable) or "inconnu",
                "depth_max_m_detected": _guess_depth_max(searchable),
            }
        )
    if not layers:
        raise GMIServiceError("Aucune couche GMI n'a été trouvée dans le GetCapabilities du BRGM.")
    return layers


def select_layer(layers: list[dict[str, object]], exchanger_type: str, depth_max_m: int) -> dict[str, object]:
    if exchanger_type not in {"ferme", "ouvert"}:
        raise ValueError("Le type d'échangeur doit être 'ferme' ou 'ouvert'.")
    if depth_max_m not in {50, 100, 200}:
        raise ValueError("La profondeur maximale doit être 50, 100 ou 200 m.")
    exact_matches = [
        layer
        for layer in layers
        if layer.get("exchanger_type_detected") == exchanger_type
        and layer.get("depth_max_m_detected") == depth_max_m
    ]
    if exact_matches:
        return sorted(exact_matches, key=lambda layer: len(str(layer.get("name", ""))))[0]
    available = "\n".join(f"- {layer['title']} ({layer['name']})" for layer in layers)
    raise GMIServiceError(
        "HelioStock n'a pas identifié automatiquement la couche BRGM correspondant à "
        f"{exchanger_type} / 10 à {depth_max_m} m.\n\nCouches détectées :\n{available}"
    )


def _extract_scalar_properties(root: ET.Element) -> list[dict[str, str]]:
    features: list[dict[str, str]] = []
    for member in root.iter():
        if _local_name(member.tag) not in {"member", "featureMember"}:
            continue
        feature = next(iter(member), None)
        if feature is None:
            continue
        properties: dict[str, str] = {}
        for child in feature:
            if len(child) != 0:
                continue
            value = (child.text or "").strip()
            if value:
                properties[_local_name(child.tag)] = value
        if properties:
            features.append(properties)
    return features


def _zone_from_properties(features: list[dict[str, str]]) -> str:
    detected: set[str] = set()
    numeric_mapping = {"1": "vert", "1.0": "vert", "2": "orange", "2.0": "orange", "3": "rouge", "3.0": "rouge"}
    likely_keys = ("zone", "classe", "classif", "couleur", "reglement", "niveau", "categorie", "code")
    for properties in features:
        for key, raw_value in properties.items():
            key_norm = _normalize(key)
            value_norm = _normalize(raw_value)
            if "rouge" in value_norm:
                detected.add("rouge")
            elif "orange" in value_norm:
                detected.add("orange")
            elif re.search(r"\bvert(?:e)?\b", value_norm):
                detected.add("vert")
            elif any(token in key_norm for token in likely_keys):
                mapped = numeric_mapping.get(value_norm)
                if mapped:
                    detected.add(mapped)
    for zone in ("rouge", "orange", "vert"):
        if zone in detected:
            return zone
    return "inconnu"


def check_gmi_zoning(latitude: float, longitude: float, layer_name: str, layer_title: str = "") -> dict[str, object]:
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude invalide.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude invalide.")
    if not layer_name:
        raise ValueError("Nom de couche WFS manquant.")
    delta = 0.00002
    bbox = (
        f"{latitude - delta:.7f},"
        f"{longitude - delta:.7f},"
        f"{latitude + delta:.7f},"
        f"{longitude + delta:.7f},"
        "urn:ogc:def:crs:EPSG::4326"
    )
    response = _get(
        {
            "SERVICE": "WFS",
            "REQUEST": "GetFeature",
            "VERSION": "2.0.0",
            "TYPENAMES": layer_name,
            "STARTINDEX": 0,
            "COUNT": 10,
            "SRSNAME": "urn:ogc:def:crs:EPSG::4326",
            "BBOX": bbox,
        }
    )
    root = _parse_xml(response.content, "GetFeature")
    features = _extract_scalar_properties(root)
    return {
        "zone": _zone_from_properties(features) if features else "aucune_donnee",
        "layer_name": layer_name,
        "layer_title": layer_title or layer_name,
        "feature_count": len(features),
    }
