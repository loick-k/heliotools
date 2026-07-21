from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import math
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont
import requests


TILE_SIZE = 256
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
REQUEST_TIMEOUT = (5, 15)
USER_AGENT = "HelioTools-Architectural-Constraints/0.1"

CATEGORY_COLORS = {
    "AC1": (192, 38, 211, 180),
    "AC2": (21, 128, 61, 180),
    "AC4": (37, 99, 235, 180),
}


class StaticMapError(RuntimeError):
    """Erreur non bloquante liée au rendu cartographique."""


def _clamp_latitude(latitude: float) -> float:
    return max(min(float(latitude), 85.05112878), -85.05112878)


def _lonlat_to_global_pixel(
    longitude: float,
    latitude: float,
    zoom: int,
) -> tuple[float, float]:
    latitude = _clamp_latitude(latitude)
    scale = TILE_SIZE * (2**zoom)

    x = (float(longitude) + 180.0) / 360.0 * scale
    lat_rad = math.radians(latitude)
    y = (
        1.0
        - math.asinh(math.tan(lat_rad)) / math.pi
    ) / 2.0 * scale

    return x, y


@lru_cache(maxsize=256)
def _download_tile(zoom: int, tile_x: int, tile_y: int) -> bytes | None:
    tile_count = 2**zoom

    if tile_y < 0 or tile_y >= tile_count:
        return None

    wrapped_x = tile_x % tile_count
    url = OSM_TILE_URL.format(z=zoom, x=wrapped_x, y=tile_y)

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


def _load_font(size: int = 16) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _create_background(
    longitude: float,
    latitude: float,
    zoom: int,
    width: int,
    height: int,
) -> tuple[Image.Image, float, float, bool]:
    center_x, center_y = _lonlat_to_global_pixel(
        longitude=longitude,
        latitude=latitude,
        zoom=zoom,
    )
    left = center_x - width / 2
    top = center_y - height / 2

    first_tile_x = math.floor(left / TILE_SIZE)
    last_tile_x = math.floor((left + width - 1) / TILE_SIZE)
    first_tile_y = math.floor(top / TILE_SIZE)
    last_tile_y = math.floor((top + height - 1) / TILE_SIZE)

    canvas = Image.new("RGB", (width, height), (243, 244, 246))
    loaded_any_tile = False

    for tile_x in range(first_tile_x, last_tile_x + 1):
        for tile_y in range(first_tile_y, last_tile_y + 1):
            tile_bytes = _download_tile(zoom, tile_x, tile_y)
            if not tile_bytes:
                continue

            try:
                tile = Image.open(BytesIO(tile_bytes)).convert("RGB")
            except Exception:
                continue

            paste_x = round(tile_x * TILE_SIZE - left)
            paste_y = round(tile_y * TILE_SIZE - top)
            canvas.paste(tile, (paste_x, paste_y))
            loaded_any_tile = True

    if not loaded_any_tile:
        draw = ImageDraw.Draw(canvas)
        for x in range(0, width, 64):
            draw.line([(x, 0), (x, height)], fill=(220, 223, 228), width=1)
        for y in range(0, height, 64):
            draw.line([(0, y), (width, y)], fill=(220, 223, 228), width=1)

        font = _load_font(18)
        message = "Fond OpenStreetMap indisponible - données du projet affichées"
        text_box = draw.textbbox((0, 0), message, font=font)
        text_width = text_box[2] - text_box[0]
        draw.text(
            ((width - text_width) / 2, 24),
            message,
            fill=(70, 70, 70),
            font=font,
        )

    return canvas, left, top, loaded_any_tile


def _viewport_point(
    coordinate: Iterable[float],
    zoom: int,
    left: float,
    top: float,
) -> tuple[float, float] | None:
    values = list(coordinate)

    if len(values) < 2:
        return None

    try:
        longitude = float(values[0])
        latitude = float(values[1])
    except (TypeError, ValueError):
        return None

    global_x, global_y = _lonlat_to_global_pixel(
        longitude=longitude,
        latitude=latitude,
        zoom=zoom,
    )
    return global_x - left, global_y - top


def _draw_point(
    draw: ImageDraw.ImageDraw,
    coordinate: Iterable[float],
    color: tuple[int, int, int, int],
    zoom: int,
    left: float,
    top: float,
) -> None:
    point = _viewport_point(coordinate, zoom, left, top)
    if point is None:
        return

    x, y = point
    radius = 6
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=color,
        outline=(255, 255, 255, 255),
        width=2,
    )


def _draw_line(
    draw: ImageDraw.ImageDraw,
    coordinates: list,
    color: tuple[int, int, int, int],
    zoom: int,
    left: float,
    top: float,
    width: int = 4,
) -> None:
    points = [
        point
        for coordinate in coordinates
        if (point := _viewport_point(coordinate, zoom, left, top)) is not None
    ]

    if len(points) >= 2:
        draw.line(points, fill=color, width=width, joint="curve")


def _draw_polygon(
    overlay: Image.Image,
    rings: list,
    color: tuple[int, int, int, int],
    zoom: int,
    left: float,
    top: float,
) -> None:
    draw = ImageDraw.Draw(overlay, "RGBA")

    if not rings:
        return

    exterior = [
        point
        for coordinate in rings[0]
        if (point := _viewport_point(coordinate, zoom, left, top)) is not None
    ]

    if len(exterior) >= 3:
        fill_color = (color[0], color[1], color[2], 55)
        outline_color = (color[0], color[1], color[2], 230)
        draw.polygon(exterior, fill=fill_color)
        draw.line(exterior + [exterior[0]], fill=outline_color, width=4)

    # Les anneaux intérieurs sont matérialisés par leur contour.
    for interior_ring in rings[1:]:
        interior = [
            point
            for coordinate in interior_ring
            if (point := _viewport_point(coordinate, zoom, left, top)) is not None
        ]
        if len(interior) >= 3:
            draw.line(
                interior + [interior[0]],
                fill=(color[0], color[1], color[2], 220),
                width=2,
            )


def _draw_geometry(
    overlay: Image.Image,
    geometry: dict[str, Any] | None,
    color: tuple[int, int, int, int],
    zoom: int,
    left: float,
    top: float,
) -> None:
    if not isinstance(geometry, dict):
        return

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    draw = ImageDraw.Draw(overlay, "RGBA")

    if geometry_type == "Point" and isinstance(coordinates, list):
        _draw_point(draw, coordinates, color, zoom, left, top)

    elif geometry_type == "MultiPoint" and isinstance(coordinates, list):
        for point in coordinates:
            _draw_point(draw, point, color, zoom, left, top)

    elif geometry_type == "LineString" and isinstance(coordinates, list):
        _draw_line(draw, coordinates, color, zoom, left, top)

    elif geometry_type == "MultiLineString" and isinstance(coordinates, list):
        for line in coordinates:
            _draw_line(draw, line, color, zoom, left, top)

    elif geometry_type == "Polygon" and isinstance(coordinates, list):
        _draw_polygon(overlay, coordinates, color, zoom, left, top)

    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            _draw_polygon(overlay, polygon, color, zoom, left, top)

    elif geometry_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        if isinstance(geometries, list):
            for child_geometry in geometries:
                _draw_geometry(
                    overlay,
                    child_geometry,
                    color,
                    zoom,
                    left,
                    top,
                )


def _draw_project_marker(
    overlay: Image.Image,
    latitude: float,
    longitude: float,
    zoom: int,
    left: float,
    top: float,
) -> None:
    point = _viewport_point(
        [longitude, latitude],
        zoom=zoom,
        left=left,
        top=top,
    )
    if point is None:
        return

    x, y = point
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Halo pour rester visible sur tous les fonds.
    draw.ellipse(
        [x - 13, y - 13, x + 13, y + 13],
        fill=(255, 255, 255, 210),
    )
    draw.ellipse(
        [x - 9, y - 9, x + 9, y + 9],
        fill=(220, 38, 38, 255),
        outline=(127, 29, 29, 255),
        width=2,
    )
    draw.line([(x - 13, y), (x + 13, y)], fill=(127, 29, 29, 255), width=2)
    draw.line([(x, y - 13), (x, y + 13)], fill=(127, 29, 29, 255), width=2)


def _draw_legend(
    image: Image.Image,
    detected_categories: list[str],
    address: str,
    latitude: float,
    longitude: float,
    tiles_loaded: bool,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    font = _load_font(15)
    small_font = _load_font(13)

    categories = detected_categories or []
    row_count = 2 + len(categories)
    box_height = 42 + row_count * 24
    box_width = min(470, image.width - 24)

    x0 = 12
    y0 = image.height - box_height - 12
    x1 = x0 + box_width
    y1 = image.height - 12

    draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=10,
        fill=(255, 255, 255, 230),
        outline=(90, 90, 90, 150),
        width=1,
    )

    title = address or "Emplacement du projet solaire thermique"
    if len(title) > 58:
        title = title[:55] + "..."

    draw.text((x0 + 12, y0 + 9), title, fill=(25, 25, 25, 255), font=font)
    draw.text(
        (x0 + 12, y0 + 31),
        f"{latitude:.6f}, {longitude:.6f}",
        fill=(70, 70, 70, 255),
        font=small_font,
    )

    current_y = y0 + 57
    if categories:
        labels = {
            "AC1": "AC1 - monuments historiques et abords",
            "AC2": "AC2 - sites classés ou inscrits",
            "AC4": "AC4 - sites patrimoniaux remarquables",
        }
        for category in categories:
            color = CATEGORY_COLORS.get(category, (90, 90, 90, 180))
            draw.rectangle(
                [x0 + 12, current_y + 3, x0 + 28, current_y + 19],
                fill=color,
            )
            draw.text(
                (x0 + 36, current_y),
                labels.get(category, category),
                fill=(30, 30, 30, 255),
                font=small_font,
            )
            current_y += 24
    else:
        draw.text(
            (x0 + 12, current_y),
            "Aucune protection affichée au droit du point",
            fill=(30, 110, 55, 255),
            font=small_font,
        )
        current_y += 24

    source_text = (
        "Fond : OpenStreetMap"
        if tiles_loaded
        else "Fond cartographique indisponible"
    )
    draw.text(
        (x0 + 12, current_y),
        source_text,
        fill=(90, 90, 90, 255),
        font=small_font,
    )


def render_static_map(
    latitude: float,
    longitude: float,
    result: dict[str, Any] | None,
    address: str = "",
    zoom: int = 17,
    width: int = 900,
    height: int = 560,
) -> Image.Image:
    """
    Génère une carte PNG côté Python.

    Aucun JavaScript, iframe, Leaflet ou composant Streamlit externe n'est
    nécessaire dans le navigateur.
    """
    if not (-90 <= float(latitude) <= 90):
        raise ValueError("Latitude invalide.")
    if not (-180 <= float(longitude) <= 180):
        raise ValueError("Longitude invalide.")

    zoom = min(max(int(zoom), 1), 19)
    width = min(max(int(width), 400), 1600)
    height = min(max(int(height), 300), 1000)

    base, left, top, tiles_loaded = _create_background(
        longitude=float(longitude),
        latitude=float(latitude),
        zoom=zoom,
        width=width,
        height=height,
    )

    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    detected_categories: list[str] = []

    if isinstance(result, dict):
        collections = result.get("feature_collections") or {}

        for category in ("AC1", "AC2", "AC4"):
            collection = collections.get(category) or {}
            features = collection.get("features") or []

            if features:
                detected_categories.append(category)

            color = CATEGORY_COLORS.get(category, (90, 90, 90, 180))

            for feature in features:
                if not isinstance(feature, dict):
                    continue

                _draw_geometry(
                    overlay=overlay,
                    geometry=feature.get("geometry"),
                    color=color,
                    zoom=zoom,
                    left=left,
                    top=top,
                )

    _draw_project_marker(
        overlay=overlay,
        latitude=float(latitude),
        longitude=float(longitude),
        zoom=zoom,
        left=left,
        top=top,
    )

    rendered = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    _draw_legend(
        image=rendered,
        detected_categories=detected_categories,
        address=address,
        latitude=float(latitude),
        longitude=float(longitude),
        tiles_loaded=tiles_loaded,
    )

    return rendered

