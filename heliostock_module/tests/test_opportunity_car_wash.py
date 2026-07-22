from heliostock.opportunity_notes.opportunity_model import (
    MONTH_NAMES,
    NeedsInputs,
    SiteInputs,
    SizingInputs,
    compute_opportunity_results,
    estimate_reference_unit_count,
)


def test_car_wash_reference_unit_is_vehicles_per_day():
    needs = NeedsInputs(
        car_wash_vehicles_per_day=25.0,
        measured_daily_l_60c_by_month={month: 2500.0 for month in MONTH_NAMES},
    )
    site = SiteInputs(typology="Station de lavage", data_source="Mesure de consommation ECS")

    assert estimate_reference_unit_count(site, needs) == 25.0

    results = compute_opportunity_results(site, needs, SizingInputs())

    assert results.reference_unit_count == 25.0
    assert results.average_daily_volume_l_60c == 2500.0
    assert results.solo_reference_volume_l_day_per_unit == 100.0
