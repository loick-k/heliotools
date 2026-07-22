from heliostock.opportunity_notes.opportunity_model import (
    MONTH_NAMES,
    LoopInputs,
    NeedsInputs,
    SiteInputs,
    SizingInputs,
    compute_opportunity_results,
)


def _measured_needs(daily_l_60c: float = 1000.0) -> NeedsInputs:
    return NeedsInputs(measured_daily_l_60c_by_month={month: daily_l_60c for month in MONTH_NAMES})


def test_no_loop_without_heating_has_no_distribution_pies():
    results = compute_opportunity_results(
        SiteInputs(data_source="Mesure de consommation ECS"),
        _measured_needs(),
        SizingInputs(),
        LoopInputs(method="Aucun bouclage sanitaire"),
    )

    assert results.annual_loop_losses_mwh == 0.0
    assert results.annual_heating_after_boiler_mwh == 0.0


def test_no_loop_can_still_estimate_heating_from_gas_invoices():
    gas_monthly_kwh = {month: 5000.0 for month in MONTH_NAMES}
    results = compute_opportunity_results(
        SiteInputs(data_source="Mesure de consommation ECS"),
        _measured_needs(),
        SizingInputs(),
        LoopInputs(
            method="Aucun bouclage sanitaire",
            include_heating_estimate_without_loop=True,
            gas_monthly_kwh=gas_monthly_kwh,
            boiler_efficiency=0.85,
        ),
    )

    assert results.annual_loop_losses_mwh == 0.0
    assert results.annual_heating_after_boiler_mwh > 0.0
