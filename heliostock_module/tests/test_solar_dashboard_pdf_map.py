import pandas as pd

from heliostock.pdf_report import (
    coordinate_points_for_pdf,
    select_static_map_zoom,
)


def test_coordinate_points_for_pdf_uses_filtered_lat_lon_only():
    df = pd.DataFrame(
        [
            {
                "Application": "A",
                "Ville": "Nantes",
                "Secteur": "Sport",
                "Latitude": 47.2184,
                "Longitude": -1.5536,
            },
            {
                "Application": "B",
                "Ville": "Rennes",
                "Secteur": "Ecole",
                "Latitude": None,
                "Longitude": -1.6778,
            },
        ]
    )

    points = coordinate_points_for_pdf(df)

    assert len(points) == 1
    assert points[0]["Application"] == "A"
    assert points[0]["lat"] == 47.2184
    assert points[0]["lon"] == -1.5536


def test_static_map_zoom_focuses_on_displayed_points():
    close_points = [{"lat": 47.2, "lon": -1.55}, {"lat": 47.25, "lon": -1.50}]
    far_points = [{"lat": 48.4, "lon": -4.5}, {"lat": 46.2, "lon": -1.2}]

    close_zoom = select_static_map_zoom(close_points, width_px=1000, height_px=520, padding_px=70)
    far_zoom = select_static_map_zoom(far_points, width_px=1000, height_px=520, padding_px=70)

    assert close_zoom > far_zoom
