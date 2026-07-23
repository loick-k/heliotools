"""Surface and orientation measurement widget for solar opportunity studies."""

from __future__ import annotations

import math
from typing import Any

try:  # pragma: no cover - optional UI dependency in lightweight test environments
    import folium
    from folium.plugins import Draw
    from streamlit_folium import st_folium
except ModuleNotFoundError:  # pragma: no cover
    folium = None
    Draw = None
    st_folium = None

try:  # pragma: no cover - optional UI dependency in lightweight test environments
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover
    st = None

DEFAULT_LATITUDE = 47.2184
DEFAULT_LONGITUDE = -1.5536

GEOPORTAIL_ORTHO_WMTS = (
    "https://data.geopf.fr/wmts?"
    "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&FORMAT=image/jpeg"
    "&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
)
GEOPORTAIL_PLAN_WMTS = (
    "https://data.geopf.fr/wmts?"
    "SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&FORMAT=image/png"
    "&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
)


def _key(prefix: str, name: str) -> str:
    return f"{prefix}_surface_orientation_{name}"


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _project_location(prefix: str) -> tuple[str, float, float]:
    address = str(st.session_state.get(f"{prefix}_project_address_label") or "")
    latitude = _as_float(st.session_state.get(f"{prefix}_project_latitude"), DEFAULT_LATITUDE)
    longitude = _as_float(st.session_state.get(f"{prefix}_project_longitude"), DEFAULT_LONGITUDE)
    return address, latitude, longitude


def _normalise_coordinate(coord: Any) -> list[float] | None:
    if isinstance(coord, dict):
        lat = coord.get("lat")
        lon = coord.get("lng", coord.get("lon"))
        if lat is None or lon is None:
            return None
        return [float(lon), float(lat)]
    if isinstance(coord, (list, tuple)) and len(coord) >= 2:
        lon = float(coord[0])
        lat = float(coord[1])
        # Some Leaflet callbacks may return [lat, lon]. In France, latitude is
        # around 41-51 and longitude around -5/+10, so this is easy to detect.
        if abs(lon) > 20.0 and abs(lat) <= 20.0:
            lon, lat = lat, lon
        return [lon, lat]
    return None


def _normalise_coordinates(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value and all(not isinstance(item, (list, tuple, dict)) for item in value):
        return _normalise_coordinate(value)
    if isinstance(value, dict):
        return _normalise_coordinate(value)
    if isinstance(value, (list, tuple)):
        normalised = [_normalise_coordinates(item) for item in value]
        return [item for item in normalised if item is not None]
    return None


def _normalise_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        return None
    if feature.get("type") in {"LineString", "Polygon", "Rectangle"}:
        geometry = feature
    else:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if not isinstance(geometry, dict):
        return None
    geometry_type = geometry.get("type")
    if geometry_type not in {"LineString", "Polygon", "Rectangle"}:
        return None
    coordinates = _normalise_coordinates(geometry.get("coordinates") or geometry.get("latlngs") or [])
    if not coordinates:
        return None
    normalised_geometry = {"type": "Polygon" if geometry_type == "Rectangle" else geometry_type, "coordinates": coordinates}
    if normalised_geometry["type"] == "Polygon" and coordinates and coordinates and isinstance(coordinates[0][0], (float, int)):
        normalised_geometry["coordinates"] = [coordinates]
    return {"type": "Feature", "properties": feature.get("properties") or {}, "geometry": normalised_geometry}


def _drawings_from_map_state(map_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(map_state, dict):
        return []
    raw_drawings = map_state.get("all_drawings") or map_state.get("drawings") or map_state.get("features") or []
    if not isinstance(raw_drawings, list):
        raw_drawings = []
    drawings = [_normalise_feature(feature) for feature in raw_drawings if isinstance(feature, dict)]
    drawings = [feature for feature in drawings if feature is not None]
    if drawings:
        return drawings
    last = map_state.get("last_active_drawing")
    if isinstance(last, dict):
        normalised = _normalise_feature(last)
        return [normalised] if normalised is not None else []
    return []


def _xy_meters(coords_lon_lat: list[list[float]]) -> list[tuple[float, float]]:
    if not coords_lon_lat:
        return []
    mean_lat_rad = math.radians(sum(float(coord[1]) for coord in coords_lon_lat) / len(coords_lon_lat))
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(mean_lat_rad)
    lon0 = float(coords_lon_lat[0][0])
    lat0 = float(coords_lon_lat[0][1])
    return [
        ((float(lon) - lon0) * meters_per_deg_lon, (float(lat) - lat0) * meters_per_deg_lat)
        for lon, lat in coords_lon_lat
    ]


def _polygon_area_m2(coords_lon_lat: list[list[float]]) -> float:
    if len(coords_lon_lat) < 3:
        return 0.0
    coords = list(coords_lon_lat)
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    xy = _xy_meters(coords)
    area = 0.0
    for index in range(len(xy) - 1):
        x1, y1 = xy[index]
        x2, y2 = xy[index + 1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _polygon_centroid_lat_lon(coords_lon_lat: list[list[float]]) -> tuple[float, float] | None:
    if len(coords_lon_lat) < 3:
        return None
    coords = coords_lon_lat[:-1] if coords_lon_lat[0] == coords_lon_lat[-1] else coords_lon_lat
    if not coords:
        return None
    lon = sum(float(coord[0]) for coord in coords) / len(coords)
    lat = sum(float(coord[1]) for coord in coords) / len(coords)
    return lat, lon


def _drawings_center_lat_lon(drawings: list[dict[str, Any]]) -> tuple[float, float] | None:
    coords: list[list[float]] = []
    for feature in drawings:
        coords.extend(_feature_coordinates(feature))
    if not coords:
        return None
    lon = sum(float(coord[0]) for coord in coords) / len(coords)
    lat = sum(float(coord[1]) for coord in coords) / len(coords)
    return lat, lon


def _bearing_deg_from_north(point_a: list[float], point_b: list[float]) -> float:
    lon1 = math.radians(float(point_a[0]))
    lat1 = math.radians(float(point_a[1]))
    lon2 = math.radians(float(point_b[0]))
    lat2 = math.radians(float(point_b[1]))
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _orientation_from_south_deg(bearing_deg: float) -> float:
    return ((bearing_deg - 180.0 + 540.0) % 360.0) - 180.0


def _orientation_label(delta_south_deg: float) -> str:
    if -22.5 <= delta_south_deg <= 22.5:
        return "Sud"
    if 22.5 < delta_south_deg <= 67.5:
        return "Sud-Ouest"
    if -67.5 <= delta_south_deg < -22.5:
        return "Sud-Est"
    if 67.5 < delta_south_deg <= 112.5:
        return "Ouest"
    if -112.5 <= delta_south_deg < -67.5:
        return "Est"
    if 112.5 < delta_south_deg <= 157.5:
        return "Nord-Ouest"
    if -157.5 <= delta_south_deg < -112.5:
        return "Nord-Est"
    return "Nord"


def _longest_polygon_edge(coords_lon_lat: list[list[float]]) -> tuple[list[float], list[float]] | None:
    if len(coords_lon_lat) < 2:
        return None
    coords = list(coords_lon_lat)
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    xy = _xy_meters(coords)
    best_index = 0
    best_distance = -1.0
    for index in range(len(xy) - 1):
        x1, y1 = xy[index]
        x2, y2 = xy[index + 1]
        distance = math.hypot(x2 - x1, y2 - y1)
        if distance > best_distance:
            best_distance = distance
            best_index = index
    return coords[best_index], coords[best_index + 1]


def _feature_coordinates(feature: dict[str, Any]) -> list[list[float]]:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    geometry_type = geometry.get("type")
    if geometry_type in {"Polygon", "Rectangle"} and coordinates:
        return coordinates[0] if isinstance(coordinates[0], list) else []
    if geometry_type == "LineString":
        return coordinates if isinstance(coordinates, list) else []
    return []


def compute_surface_orientation_metrics(drawings: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute planimetric area and orientation from drawn GeoJSON features."""
    surface_m2 = 0.0
    orientation_points: tuple[list[float], list[float]] | None = None
    orientation_source = ""

    polygons = [feature for feature in drawings if (feature.get("geometry") or {}).get("type") in {"Polygon", "Rectangle"}]
    lines = [feature for feature in drawings if (feature.get("geometry") or {}).get("type") == "LineString"]

    if polygons:
        polygon_coords = _feature_coordinates(polygons[-1])
        surface_m2 = _polygon_area_m2(polygon_coords)
        orientation_points = _longest_polygon_edge(polygon_coords)
        orientation_source = "bord principal de l'emprise"

    if lines:
        line_coords = _feature_coordinates(lines[-1])
        if len(line_coords) >= 2:
            orientation_points = (line_coords[0], line_coords[-1])
            orientation_source = "ligne tracée"

    metrics: dict[str, Any] = {
        "surface_m2": surface_m2,
        "orientation_bearing_deg": None,
        "orientation_from_south_deg": None,
        "orientation_label": "non déterminée",
        "orientation_source": orientation_source or "non déterminée",
        "drawings_count": len(drawings),
    }
    if orientation_points is not None:
        bearing = _bearing_deg_from_north(orientation_points[0], orientation_points[1])
        delta = _orientation_from_south_deg(bearing)
        metrics.update(
            {
                "orientation_bearing_deg": bearing,
                "orientation_from_south_deg": delta,
                "orientation_label": _orientation_label(delta),
            }
        )
    return metrics


def _measurement_map(
    *,
    latitude: float,
    longitude: float,
    address: str,
    drawings: list[dict[str, Any]],
    map_center: tuple[float, float] | None = None,
    map_zoom: int = 20,
) -> folium.Map:
    center = map_center or (latitude, longitude)
    map_object = folium.Map(
        location=[center[0], center[1]],
        zoom_start=map_zoom,
        max_zoom=22,
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer(
        tiles=GEOPORTAIL_ORTHO_WMTS,
        attr="Géoplateforme / IGN",
        name="Géoportail - orthophotos",
        overlay=False,
        control=True,
        show=True,
        max_zoom=22,
        max_native_zoom=19,
    ).add_to(map_object)
    folium.TileLayer(
        tiles=GEOPORTAIL_PLAN_WMTS,
        attr="Géoplateforme / IGN",
        name="Géoportail - plan IGN",
        overlay=False,
        control=True,
        show=False,
        max_zoom=22,
        max_native_zoom=19,
    ).add_to(map_object)
    folium.TileLayer(
        "OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
        control=True,
        show=False,
        max_zoom=22,
        max_native_zoom=19,
    ).add_to(map_object)
    folium.Marker(
        [latitude, longitude],
        tooltip=address or "Projet",
        popup=folium.Popup(f"<b>{address or 'Projet'}</b><br>{latitude:.6f}, {longitude:.6f}", max_width=280),
        icon=folium.Icon(color="red", icon="crosshairs"),
    ).add_to(map_object)
    if drawings:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": drawings},
            name="Mesures sauvegardées",
            style_function=lambda _feature: {"color": "#22B2A6", "weight": 3, "fillOpacity": 0.18},
        ).add_to(map_object)
        for feature in drawings:
            geometry_type = (feature.get("geometry") or {}).get("type")
            if geometry_type not in {"Polygon", "Rectangle"}:
                continue
            coords = _feature_coordinates(feature)
            area_m2 = _polygon_area_m2(coords)
            centroid = _polygon_centroid_lat_lon(coords)
            if centroid is None or area_m2 <= 0:
                continue
            folium.Marker(
                centroid,
                icon=folium.DivIcon(
                    html=(
                        "<div style='background:#ffffff; border:1px solid #22B2A6; border-radius:4px; "
                        "padding:2px 6px; font-size:12px; font-weight:600; color:#0f172a; "
                        "box-shadow:0 1px 4px rgba(15,23,42,0.25); white-space:nowrap;'>"
                        f"{area_m2:.1f} m²</div>"
                    )
                ),
            ).add_to(map_object)
    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polyline": {"shapeOptions": {"color": "#486DAC", "weight": 4}},
            "polygon": {"allowIntersection": False, "showArea": True, "shapeOptions": {"color": "#22B2A6", "weight": 3}},
            "rectangle": {"shapeOptions": {"color": "#22B2A6", "weight": 3}},
            "circle": False,
            "circlemarker": False,
            "marker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(map_object)
    folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def _viewport_from_map_state(map_state: Any) -> tuple[tuple[float, float] | None, int | None]:
    if not isinstance(map_state, dict):
        return None, None
    center_raw = map_state.get("center")
    center: tuple[float, float] | None = None
    if isinstance(center_raw, dict) and center_raw.get("lat") is not None and center_raw.get("lng") is not None:
        center = (float(center_raw["lat"]), float(center_raw["lng"]))
    elif isinstance(center_raw, (list, tuple)) and len(center_raw) >= 2:
        center = (float(center_raw[0]), float(center_raw[1]))
    zoom_raw = map_state.get("zoom")
    zoom: int | None = None
    if isinstance(zoom_raw, (float, int)):
        zoom = max(1, min(22, int(zoom_raw)))
    return center, zoom


def current_surface_orientation_payload(state_prefix: str = "helionop") -> dict[str, Any]:
    if st is None:
        return {"drawings": [], "metrics": {}}
    return {
        "drawings": st.session_state.get(_key(state_prefix, "drawings"), []),
        "metrics": st.session_state.get(_key(state_prefix, "metrics"), {}),
        "map_center": st.session_state.get(_key(state_prefix, "map_center")),
        "map_zoom": st.session_state.get(_key(state_prefix, "map_zoom")),
    }


def restore_surface_orientation_state(payload: dict[str, Any], *, project_id: str, state_prefix: str = "helionop") -> None:
    if st is None:
        return
    if st.session_state.get(_key(state_prefix, "payload_project_id")) == project_id:
        return
    st.session_state[_key(state_prefix, "payload_project_id")] = project_id
    saved = payload.get("surface_orientation")
    if not isinstance(saved, dict):
        return
    drawings = saved.get("drawings")
    metrics = saved.get("metrics")
    map_center = saved.get("map_center")
    map_zoom = saved.get("map_zoom")
    st.session_state[_key(state_prefix, "drawings")] = drawings if isinstance(drawings, list) else []
    st.session_state[_key(state_prefix, "metrics")] = metrics if isinstance(metrics, dict) else {}
    if isinstance(map_center, (list, tuple)) and len(map_center) >= 2:
        st.session_state[_key(state_prefix, "map_center")] = (float(map_center[0]), float(map_center[1]))
    if isinstance(map_zoom, int):
        st.session_state[_key(state_prefix, "map_zoom")] = max(1, min(22, map_zoom))


def render_surface_orientation_measurement(state_prefix: str = "helionop") -> dict[str, Any]:
    if st is None:
        return {"drawings": [], "metrics": {}}
    st.subheader("Mesure de surface et d'orientation")
    st.caption(
        "Trace un polygone ou un rectangle pour mesurer une surface, puis trace une ligne dans le sens de l'orientation "
        "de la toiture ou de la zone au sol. L'orientation est exprimée par rapport au sud : 0° = sud, -90° = est, +90° = ouest."
    )
    if folium is None or Draw is None or st_folium is None:
        st.error("Le module de cartographie folium / streamlit-folium n'est pas disponible dans cet environnement.")
        return current_surface_orientation_payload(state_prefix)
    address, latitude, longitude = _project_location(state_prefix)
    drawings_key = _key(state_prefix, "drawings")
    metrics_key = _key(state_prefix, "metrics")
    center_key = _key(state_prefix, "map_center")
    zoom_key = _key(state_prefix, "map_zoom")
    drawings = st.session_state.get(drawings_key)
    if not isinstance(drawings, list):
        drawings = []
        st.session_state[drawings_key] = drawings
    saved_center = st.session_state.get(center_key)
    if not (isinstance(saved_center, (list, tuple)) and len(saved_center) >= 2):
        saved_center = _drawings_center_lat_lon(drawings) or (latitude, longitude)
    saved_zoom = st.session_state.get(zoom_key, 20)
    if not isinstance(saved_zoom, int):
        saved_zoom = 20

    map_state = st_folium(
        _measurement_map(
            latitude=latitude,
            longitude=longitude,
            address=address,
            drawings=drawings,
            map_center=(float(saved_center[0]), float(saved_center[1])),
            map_zoom=saved_zoom,
        ),
        height=560,
        width="stretch",
        returned_objects=["all_drawings", "last_active_drawing", "center", "zoom"],
        key=_key(state_prefix, "map"),
    )
    session_map_state = st.session_state.get(_key(state_prefix, "map"))
    new_drawings = _drawings_from_map_state(map_state) or _drawings_from_map_state(session_map_state)
    viewport_center, viewport_zoom = _viewport_from_map_state(map_state)
    if viewport_center is not None:
        st.session_state[center_key] = viewport_center
    if viewport_zoom is not None:
        st.session_state[zoom_key] = viewport_zoom
    if new_drawings != drawings:
        drawings = new_drawings
        st.session_state[drawings_key] = drawings
        st.session_state[metrics_key] = compute_surface_orientation_metrics(drawings)
        measured_center = _drawings_center_lat_lon(drawings)
        if measured_center is not None:
            st.session_state[center_key] = measured_center

    if st.button("Effacer les mesures", key=_key(state_prefix, "clear"), width="content"):
        st.session_state[drawings_key] = []
        st.session_state[metrics_key] = {}
        st.session_state.pop(center_key, None)
        st.session_state.pop(zoom_key, None)
        st.rerun()

    metrics = st.session_state.get(metrics_key)
    if not isinstance(metrics, dict) or (drawings and not metrics):
        metrics = compute_surface_orientation_metrics(drawings)
        st.session_state[metrics_key] = metrics

    surface_m2 = metrics.get("surface_m2")
    delta_south = metrics.get("orientation_from_south_deg")
    label = str(metrics.get("orientation_label") or "non déterminée")
    source = str(metrics.get("orientation_source") or "non déterminée")

    if isinstance(surface_m2, (float, int)) and surface_m2 > 0:
        st.success(f"Surface dessinée : {surface_m2:.1f} m²")

    col1, col2, col3 = st.columns(3)
    col1.metric("Surface mesurée", f"{surface_m2:.1f} m²" if isinstance(surface_m2, (float, int)) and surface_m2 > 0 else "n.d.")
    col2.metric("Orientation solaire", label)
    col3.metric("Écart au sud", f"{delta_south:+.0f}°" if isinstance(delta_south, (float, int)) else "n.d.")
    st.caption("Convention orientation / sud : 0° = plein sud, valeur négative = vers l'est, valeur positive = vers l'ouest.")

    if not drawings:
        st.info("Dessine au moins un polygone pour obtenir une surface. Ajoute une ligne pour définir clairement l'orientation.")
    elif source != "ligne tracée":
        st.warning(
            "Orientation estimée depuis le bord le plus long du polygone. Pour une toiture, trace une ligne dans le sens "
            "de l'orientation retenue afin d'éviter une mauvaise interprétation."
        )
    elif isinstance(delta_south, (float, int)) and abs(delta_south) <= 45:
        st.success("Orientation favorable pour du solaire thermique : l'écart au sud reste limité.")
    elif isinstance(delta_south, (float, int)) and abs(delta_south) <= 90:
        st.warning("Orientation exploitable mais dégradée : l'écart au sud peut réduire la productivité solaire.")
    else:
        st.error("Orientation défavorable : une analyse plus fine est nécessaire avant de retenir cette zone.")

    st.caption(
        "Mesure indicative : la surface est planimétrique et n'intègre pas la pente réelle du toit. "
        "Le module ne remplace pas une vérification de masque solaire, structure et accès maintenance."
    )
    return current_surface_orientation_payload(state_prefix)
