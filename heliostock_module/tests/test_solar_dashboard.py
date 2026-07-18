import importlib
import sys
import types
from pathlib import Path

import pandas as pd


MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))


def test_dashboard_parallelism_is_limited_to_geocoding_io():
    source = (MODULE_ROOT / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")
    assert "GEOCODING_MAX_WORKERS = 6" in source
    assert "ThreadPoolExecutor(max_workers=GEOCODING_MAX_WORKERS)" in source
    assert "pygfunction calls remain sequential" in source
    assert "simulate_hourly" not in source
    assert "create_btes_model" not in source


def test_solar_dashboard_overview_pdf_uses_filtered_values(monkeypatch):
    fake_folium = types.ModuleType("folium")
    fake_folium.Map = object
    fake_folium.Marker = object
    fake_folium.Popup = object
    fake_folium.Icon = object
    fake_folium_plugins = types.ModuleType("folium.plugins")
    fake_folium_plugins.MarkerCluster = object
    fake_px = types.ModuleType("plotly.express")
    fake_plotly = types.ModuleType("plotly")
    fake_plotly.express = fake_px
    fake_pyairtable = types.ModuleType("pyairtable")
    fake_pyairtable.Api = object
    fake_streamlit_folium = types.ModuleType("streamlit_folium")
    fake_streamlit_folium.st_folium = lambda *args, **kwargs: None
    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.cache_data = lambda *args, **kwargs: (lambda fn: fn)
    fake_streamlit.secrets = {}
    fake_streamlit.sidebar = types.SimpleNamespace()
    fake_streamlit.column_config = types.SimpleNamespace(LinkColumn=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "folium", fake_folium)
    monkeypatch.setitem(sys.modules, "folium.plugins", fake_folium_plugins)
    monkeypatch.setitem(sys.modules, "plotly", fake_plotly)
    monkeypatch.setitem(sys.modules, "plotly.express", fake_px)
    monkeypatch.setitem(sys.modules, "pyairtable", fake_pyairtable)
    monkeypatch.setitem(sys.modules, "streamlit_folium", fake_streamlit_folium)
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    solar_dashboard_module = importlib.import_module("heliostock.solar_thermal_dashboard")

    df = pd.DataFrame(
        [
            {
                "Application": "Projet A",
                "Ville": "Nantes",
                "Département": "44",
                "Secteur": "Santé",
                "Type d'installation": "ECS",
                "Etat": "En service",
                "Année de mise en service": 2024,
                "Superficie (m²)": 100.0,
                "Production annuelle (MWh)": 80.0,
                "Aide ADEME (€)": 1000.0,
            },
            {
                "Application": "Projet B",
                "Ville": "Rennes",
                "Département": "35",
                "Secteur": "Logement",
                "Type d'installation": "ECS",
                "Etat": "Projet",
                "Année de mise en service": 2025,
                "Superficie (m²)": 900.0,
                "Production annuelle (MWh)": 700.0,
                "Aide ADEME (€)": 9000.0,
            },
        ]
    )
    filtered = df[df["Département"] == "44"]
    filters = solar_dashboard_module._active_filters_summary(
        departements=["44"],
        secteurs=[],
        types=[],
        etats=["En service"],
        annees=(2024, 2024),
    )

    metrics = dict(solar_dashboard_module._filtered_summary_metrics(filtered))
    pdf = solar_dashboard_module._overview_pdf_bytes(df_f=filtered, filters=filters)

    assert pdf.startswith(b"%PDF-1.3") or pdf.startswith(b"%PDF-1.4")
    assert metrics["Installations"] == "1"
    assert metrics["Superficie totale"] == "100 m²"
    assert metrics["Production annuelle totale"] == "80 MWh"
    assert len(pdf) > 8000
    assert b"Surface" in pdf
    assert b"Aper" not in pdf
    assert b"Projet B" not in pdf


def test_solar_dashboard_overview_pdf_tolerates_missing_cumulative_column(monkeypatch):
    fake_folium = types.ModuleType("folium")
    fake_folium.Map = object
    fake_folium.Marker = object
    fake_folium.Popup = object
    fake_folium.Icon = object
    fake_folium_plugins = types.ModuleType("folium.plugins")
    fake_folium_plugins.MarkerCluster = object
    fake_px = types.ModuleType("plotly.express")
    fake_plotly = types.ModuleType("plotly")
    fake_plotly.express = fake_px
    fake_pyairtable = types.ModuleType("pyairtable")
    fake_pyairtable.Api = object
    fake_streamlit_folium = types.ModuleType("streamlit_folium")
    fake_streamlit_folium.st_folium = lambda *args, **kwargs: None
    fake_streamlit = types.ModuleType("streamlit")
    fake_streamlit.cache_data = lambda *args, **kwargs: (lambda fn: fn)
    fake_streamlit.secrets = {}
    fake_streamlit.sidebar = types.SimpleNamespace()
    fake_streamlit.column_config = types.SimpleNamespace(LinkColumn=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "folium", fake_folium)
    monkeypatch.setitem(sys.modules, "folium.plugins", fake_folium_plugins)
    monkeypatch.setitem(sys.modules, "plotly", fake_plotly)
    monkeypatch.setitem(sys.modules, "plotly.express", fake_px)
    monkeypatch.setitem(sys.modules, "pyairtable", fake_pyairtable)
    monkeypatch.setitem(sys.modules, "streamlit_folium", fake_streamlit_folium)
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    solar_dashboard_module = importlib.import_module("heliostock.solar_thermal_dashboard")

    broken_table = pd.DataFrame({"Année de mise en service": [2024], "Nombre": [1]})

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas as pdf_canvas
    from io import BytesIO

    buffer = BytesIO()
    width, height = landscape(A4)
    canvas = pdf_canvas.Canvas(buffer, pagesize=(width, height))

    solar_dashboard_module._draw_line_chart(
        canvas,
        broken_table,
        x=34,
        y=92,
        width=360,
        height=175,
        title="Évolution cumulée du nombre d'installations",
        x_col="Année de mise en service",
        y_col="Cumulé",
    )
    canvas.save()
    assert buffer.getvalue().startswith(b"%PDF")


def test_solar_dashboard_text_has_no_common_mojibake_sequences():
    source = (MODULE_ROOT / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")
    forbidden = ["\u00f0", "\u00c3", "\u00c2", "\u00ef\u00b8", "\u00e2\u201a\u00ac"]
    assert not any(token in source for token in forbidden)


def test_geocoder_apps_script_is_linked_and_versioned():
    source = (MODULE_ROOT / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")
    script = (MODULE_ROOT / "scripts" / "geocoder_airtable.gs").read_text(encoding="utf-8")

    assert "GEOCODER_APPS_SCRIPT_URL" in source
    assert "1jDiVia7tT3dOoWIMxlypC2BxXWAAXz48x-pCneMn_w0730BT8fUVdxdZ" in source
    assert "st.link_button(" in source
    assert "scripts/geocoder_airtable.gs" in source
    assert "function geocodeInstallationsAirtable()" in script
    assert "Maps.newGeocoder().setRegion('fr')" in script
    assert "Latitude" in script
    assert "Longitude" in script


def test_satellite_map_adds_city_labels_overlay():
    source = (MODULE_ROOT / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")

    assert 'fond_choisi == "Satellite (vue aérienne)"' in source
    assert "Esri.WorldTransportation" in source
    assert "Esri.WorldBoundariesAndPlaces" in source
    assert 'name="Noms des villes"' in source
    assert "folium.LayerControl" in source


def test_map_uses_individual_points_and_labels_instead_of_clusters():
    source = (MODULE_ROOT / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")

    assert "MarkerCluster" not in source
    assert "folium.CircleMarker(" in source
    assert "folium.DivIcon(" in source
    assert "def _map_short_label" in source
