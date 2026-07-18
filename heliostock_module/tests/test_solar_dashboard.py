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
    assert b"Projet A" in pdf
    assert b"Projet B" not in pdf


def test_solar_dashboard_text_has_no_common_mojibake_sequences():
    source = (MODULE_ROOT / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")
    forbidden = ["\u00f0", "\u00c3", "\u00c2", "\u00ef\u00b8", "\u00e2\u201a\u00ac"]
    assert not any(token in source for token in forbidden)
