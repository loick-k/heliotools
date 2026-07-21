from unittest.mock import patch

from heliostock.architectural_patrimony_service import analyse_patrimoine, compact_feature_properties


def test_architectural_analysis_detects_heritage_categories():
    def fake_query(endpoint, category, geometry):
        if endpoint == "assiette-sup-s" and category in {"AC1", "AC4"}:
            return {
                "type": "FeatureCollection",
                "totalFeatures": 1,
                "features": [
                    {
                        "type": "Feature",
                        "id": f"{category}.1",
                        "geometry": {"type": "Polygon", "coordinates": []},
                        "properties": {"suptype": category, "nomass": f"Protection {category}"},
                    }
                ],
            }
        return {"type": "FeatureCollection", "totalFeatures": 0, "features": []}

    with patch("heliostock.architectural_patrimony_service._query_gpu", side_effect=fake_query):
        result = analyse_patrimoine(47.2184, -1.5536)

    assert result["has_protection"] is True
    assert result["counts"]["AC1"] == 1
    assert result["counts"]["AC2"] == 0
    assert result["counts"]["AC4"] == 1
    assert result["detected_categories"] == ["AC1", "AC4"]


def test_architectural_compact_feature_properties_keeps_useful_fields():
    feature = {
        "properties": {
            "_display_title": "Abords de l'église",
            "suptype": "AC1",
            "nomass": "Abords de l'église",
            "irrelevant": "value",
        }
    }

    compact = compact_feature_properties(feature)

    assert compact["suptype"] == "AC1"
    assert compact["nomass"] == "Abords de l'église"
    assert "irrelevant" not in compact

