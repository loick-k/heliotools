from heliostock.opportunity_notes.opportunity_model import (
    MAX_STORAGE_RATIO_L_M2,
    MIN_STORAGE_RATIO_L_M2,
    propose_collectors,
    propose_storage_for_collector_surface,
)


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


def test_storage_is_adapted_when_collector_surface_is_capped() -> None:
    collector_surface_m2 = 35.0

    storage = propose_storage_for_collector_surface(
        target_daily_volume_l_60c=5000.0,
        collector_surface_m2=collector_surface_m2,
        max_tank_count=3,
        target_storage_ratio_l_m2=60.0,
    )

    ratio = storage.total_volume_l / collector_surface_m2
    assert MIN_STORAGE_RATIO_L_M2 <= ratio <= MAX_STORAGE_RATIO_L_M2
    assert storage.total_volume_l < 5000
