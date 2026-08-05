from datetime import date

from heliostock.common.formatting import format_mwh_from_kwh, owner_slug, safe_slug
from heliostock.common.project_context import project_context_to_payload
from heliostock.common.project_identity import ProjectIdentity
from heliostock.common.project_store import JsonProjectStore
from heliostock.economics_core import compute_heat_costs
from heliostock.project_store import JsonProjectStore as LegacyJsonProjectStore
from heliostock.solar_thermal_core import _daily_buffer_volume_l


def test_common_formatting_helpers_are_stable():
    assert format_mwh_from_kwh(1234, 1) == "1.2 MWh"
    assert safe_slug("Projet école solaire") == "projet-ecole-solaire"
    assert owner_slug("USER@Example.COM") == "user-example.com"


def test_business_core_facades_expose_existing_functions():
    assert callable(compute_heat_costs)
    assert callable(_daily_buffer_volume_l)


def test_legacy_project_store_import_points_to_common_store():
    assert LegacyJsonProjectStore is JsonProjectStore


def test_project_store_uses_explicit_artifact_directories(tmp_path):
    store = JsonProjectStore("heliostock", app_label="HelioStock", root_dir=tmp_path)
    path = store.save_project(
        payload={"name": "Demo"},
        owner_email="alice@example.com",
        project_name="Demo",
        project_id="aaaaaaaa-0000-0000-0000-000000000000",
    )

    input_path = store.project_input_path(path, "besoins_horaires.xlsx")
    result_path = store.project_result_path(path, "latest_result.json")

    assert input_path.parent.name == "inputs"
    assert result_path.parent.name == "results"
    assert input_path.parent.parent == result_path.parent.parent
    assert input_path.parent.parent == path.with_suffix("")


def test_project_context_payload_normalizes_shared_fields():
    context = project_context_to_payload(
        ProjectIdentity(
            project_name="Projet test",
            client_name="Client",
            airtable_id="rec123",
            analyst="Analyste",
            project_date=date(2026, 7, 26),
            typology="Industrie",
            region="Bretagne",
            department="35 - Ille-et-Vilaine",
            city="Rennes",
            address="1 rue Exemple, Rennes",
            latitude=48.1173,
            longitude=-1.6778,
            weather_region="Bretagne",
            weather_station="Rennes",
        ),
        app_key="heliostock",
        app_label="HelioStock",
        geographic_scope="Bretagne et Pays de la Loire",
        weather_source="EPW / TMYx",
    )

    assert context["schema_version"] == 1
    assert context["project_name"] == "Projet test"
    assert context["project_date"] == "2026-07-26"
    assert context["latitude"] == 48.1173
    assert context["weather"] == {"source": "EPW / TMYx", "region": "Bretagne", "station": "Rennes"}


def test_project_context_payload_preserves_app_specific_scope_and_weather_source():
    context = project_context_to_payload(
        {"project_name": "Réseau test", "client": "Collectivité", "weather_station": "PVGIS 44"},
        app_key="heliorc",
        app_label="HelioRC",
        geographic_scope="France",
        weather_source="PVGIS",
        extra={"needs_mode": "ratio"},
    )

    assert context["client_name"] == "Collectivité"
    assert context["geographic_scope"] == "France"
    assert context["weather"]["source"] == "PVGIS"
    assert context["extra"] == {"needs_mode": "ratio"}
