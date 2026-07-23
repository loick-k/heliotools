from heliostock.opportunity_notes.opportunity_model import propose_collectors


def test_collector_surface_is_capped_by_measured_available_surface() -> None:
    collectors = propose_collectors(
        storage_volume_l=5000,
        collector_unit_area_m2=2.5,
        target_storage_ratio_l_m2=60.0,
        max_collector_surface_m2=37.0,
    )

    assert collectors.surface_m2 <= 37.0
    assert collectors.collector_count == 14


def test_collector_cap_can_return_zero_when_no_full_collector_fits() -> None:
    collectors = propose_collectors(
        storage_volume_l=500,
        collector_unit_area_m2=2.5,
        target_storage_ratio_l_m2=60.0,
        max_collector_surface_m2=2.0,
    )

    assert collectors.collector_count == 0
    assert collectors.surface_m2 == 0.0

