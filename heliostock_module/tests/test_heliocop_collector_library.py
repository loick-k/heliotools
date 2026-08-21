from heliostock.heliocop.solopac_reference import (
    available_pvt_references,
    collector_reference_for_pac_brand,
    round_collector_surface,
)


def test_heliocop_uses_shared_collector_catalog_for_pvt_references():
    refs = available_pvt_references()

    assert len(refs) >= 2
    assert {ref.brand for ref in refs} == {"Dualsun"}
    assert all(ref.unit_area_m2 > 0.0 for ref in refs)


def test_heliocop_brand_reference_still_rounds_source_surface():
    reference = collector_reference_for_pac_brand("Heliopac", "Moquette solaire")

    assert reference is not None
    rounded = round_collector_surface(25.0, reference)

    assert rounded.collector_count >= 1
    assert rounded.installed_surface_m2 >= 25.0
