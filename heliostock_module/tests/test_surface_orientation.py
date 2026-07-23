from heliostock.ui_surface_orientation import compute_surface_orientation_metrics


def test_surface_orientation_metrics_from_polygon_and_line() -> None:
    lon0 = -1.5536
    lat0 = 47.2184
    deg_lat_10m = 10.0 / 111_320.0
    deg_lon_10m = 10.0 / (111_320.0 * 0.68)
    polygon = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon0, lat0],
                    [lon0 + deg_lon_10m, lat0],
                    [lon0 + deg_lon_10m, lat0 + deg_lat_10m],
                    [lon0, lat0 + deg_lat_10m],
                    [lon0, lat0],
                ]
            ],
        },
    }
    south_line = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon0, lat0 + deg_lat_10m], [lon0, lat0]],
        },
    }

    metrics = compute_surface_orientation_metrics([polygon, south_line])

    assert 90.0 <= metrics["surface_m2"] <= 110.0
    assert 45.0 <= metrics["max_collector_surface_m2"] <= 55.0
    assert metrics["orientation_label"] == "Sud"
    assert abs(metrics["orientation_from_south_deg"]) <= 2.0
    assert metrics["orientation_source"] == "ligne tracée"


def test_surface_orientation_without_injection_of_results() -> None:
    metrics = compute_surface_orientation_metrics([])

    assert metrics["surface_m2"] == 0.0
    assert metrics["orientation_label"] == "non déterminée"
    assert metrics["orientation_bearing_deg"] is None
