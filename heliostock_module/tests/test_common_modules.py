from heliostock.common.formatting import format_mwh_from_kwh, owner_slug, safe_slug
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
