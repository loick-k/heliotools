from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "heliostock" / "opportunity_notes" / "streamlit_opportunity_app.py"


def test_economics_defaults_to_predesign_recommendation():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'economic_default.get("use_predesign_for_economics", True)' in source
    assert "economic_surface = recommended_economic_surface" in source
    assert "economic_productivity = recommended_economic_productivity" in source
    assert 'economic_default.get("surface_m2", recommended_economic_surface)' in source
