import pytest

from heliostock.app_service import CalculationSelection, HourlyCalculationRequest, ParametricRange, run_hourly_calculation
from heliostock.btes_models import pygfunction_available
from heliostock.engine import MonthlyDemand
from heliostock.hourly_engine import HourlyWeather
from heliostock.inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, SolarInputs


def _hourly_override(weather: list[HourlyWeather], *, ht_kwh: float, bt_kwh: float) -> dict[int, tuple[float, float]]:
    return {hour.hour_index: (ht_kwh, bt_kwh) for hour in weather}


def _demand_aggregate(month: int, weather: list[HourlyWeather], *, ht_kwh: float, bt_kwh: float) -> list[MonthlyDemand]:
    return [
        MonthlyDemand(
            month=month,
            process_ht_kwh=ht_kwh * len(weather),
            process_bt_kwh=bt_kwh * len(weather),
        )
    ]


def skip_if_no_pygfunction() -> None:
    if not pygfunction_available():
        pytest.skip("pygfunction non disponible dans cet environnement")


def _solar_inputs(*, area_m2: float = 100.0, daily_buffer_l_per_m2: float = 60.0) -> SolarInputs:
    return SolarInputs(
        area_m2=area_m2,
        eta0=0.8,
        a1_w_m2_k=3.0,
        a2_w_m2_k2=0.02,
        process_ht_target_c=60.0,
        system_efficiency=0.9,
        daily_buffer_charge_factor_ht=1.0,
        daily_buffer_l_per_m2=daily_buffer_l_per_m2,
        daily_buffer_ambient_temp_c=20.0,
        daily_buffer_max_temp_c=80.0,
        daily_buffer_loss_pct_per_day=2.0,
        solar_preheat_target_ht_c=60.0,
        solar_buffer_hx_approach_k=5.0,
        solar_buffer_collector_approach_k=10.0,
    )


def _btes_inputs() -> BtesInputs:
    return BtesInputs(
        boreholes=8,
        depth_m=80.0,
        spacing_m=8.0,
        t_initial_c=12.0,
        t_min_c=5.0,
        t_max_c=40.0,
    )


def _heat_pump_inputs() -> HeatPumpInputs:
    return HeatPumpInputs(
        air_target_bt_c=25.0,
        condenser_approach_k=2.0,
        evaporator_approach_k=3.0,
        carnot_efficiency=0.54,
        cop_min=2.0,
        cop_max=8.0,
        pac_power_fraction_pct=100.0,
        peak_bt_power_kw=0.0,
    )


def _economics_inputs(*, analysis_years: int = 20, maintenance_cost_eur_m2_year: float = 0.0) -> EconomicsInputs:
    return EconomicsInputs(
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_pct=3.0,
        eta_appoint_eco=0.82,
        analysis_years=analysis_years,
        auxiliary_electricity_ratio_pct=3.0,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=maintenance_cost_eur_m2_year,
        ademe_eur_mwh_year=0.0,
        other_public_aid_eur=0.0,
        backup_p2_eur_kw_year=10.0,
    )


def _request(
    *,
    weather: list[HourlyWeather],
    ht_kwh: float,
    bt_kwh: float,
    solar: SolarInputs | None = None,
    btes: BtesInputs | None = None,
    economics: EconomicsInputs | None = None,
    selection: CalculationSelection | None = None,
    use_probe_predesign: bool = False,
    probe_power_ratio_w_m: float = 40.0,
    probe_energy_ratio_kwh_m: float = 60.0,
    pac_parametric: ParametricRange | None = None,
    solar_parametric: ParametricRange | None = None,
) -> HourlyCalculationRequest:
    return HourlyCalculationRequest(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=ht_kwh, bt_kwh=bt_kwh),
        hourly_demand_override=_hourly_override(weather, ht_kwh=ht_kwh, bt_kwh=bt_kwh),
        solar=solar or _solar_inputs(),
        btes=btes or _btes_inputs(),
        heat_pump=_heat_pump_inputs(),
        economics=economics or _economics_inputs(),
        pac_power_fraction_pct=100.0,
        use_probe_predesign=use_probe_predesign,
        probe_power_ratio_w_m=probe_power_ratio_w_m,
        probe_energy_ratio_kwh_m=probe_energy_ratio_kwh_m,
        probe_unit_depth_m=100.0,
        calculation_selection=selection or CalculationSelection(),
        pac_parametric=pac_parametric or ParametricRange(False, 50.0, 100.0, 50.0),
        solar_parametric=solar_parametric or ParametricRange(False, 0.0, 100.0, 100.0),
    )


def test_app_service_runs_calculation_without_streamlit():
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.6 if 8 <= hour % 24 <= 16 else 0.0,
        )
        for hour in range(24)
    ]
    request = _request(
        weather=weather,
        ht_kwh=100.0,
        bt_kwh=100.0,
        solar=_solar_inputs(area_m2=100.0, daily_buffer_l_per_m2=60.0),
        btes=BtesInputs(
            boreholes=20,
            depth_m=100.0,
            spacing_m=10.0,
            t_initial_c=12.0,
            t_min_c=5.0,
            t_max_c=40.0,
        ),
        economics=EconomicsInputs(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=3.0,
            eta_appoint_eco=0.82,
            analysis_years=20,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=200.0,
            maintenance_cost_eur_m2_year=22.0,
            ademe_eur_mwh_year=63.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        use_probe_predesign=True,
        probe_power_ratio_w_m=60.0,
        probe_energy_ratio_kwh_m=70.0,
        pac_parametric=ParametricRange(False, 50.0, 100.0, 10.0),
        solar_parametric=ParametricRange(False, 0.0, 500.0, 100.0),
    )

    result = run_hourly_calculation(request)

    assert len(result.scenario.hourly_df) == 24
    assert result.peak_bt_power_kw > 0.0
    assert result.pac_nominal_power_kw > 0.0
    assert result.parametric_pac_df.empty
    assert result.parametric_surface_df.empty
    assert str(result.performance_log_df["Progression (%)"].dtype) == "Float64"
    assert result.performance_log_df["Progression (%)"].dropna().map(type).eq(float).all()
    assert "Duree pygfunction (s)" in result.performance_log_df
    assert "Duree dataframe (s)" in result.performance_log_df
    assert "Heures simulees" in result.performance_log_df
    assert "Simulations lancees" in result.performance_log_df
    assert (result.performance_log_df["Etape"] == "simulate:pygfunction").any()
    assert (result.performance_log_df["Etape"] == "postprocess:dataframe").any()


def test_legacy_quick_preview_flag_is_ignored_by_final_calculation():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=1,
            hour=hour + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
        for hour in range(4)
    ]
    request = _request(
        weather=weather,
        ht_kwh=10.0,
        bt_kwh=20.0,
        solar=_solar_inputs(daily_buffer_l_per_m2=50.0),
        economics=_economics_inputs(analysis_years=25),
        selection=CalculationSelection(
            quick_preview=True,
            run_multiyear=True,
            technical_simulation_years=2,
            run_reduced_borefield=False,
            savings_search_mode="none",
        ),
    )

    result = run_hourly_calculation(request)

    assert result.scenario.simulation_years_total == 2
    assert result.scenario.simulation_year_displayed == 2
    assert not result.scenario.savings["found"]
    assert result.parametric_pac_df.empty
    assert result.parametric_surface_df.empty
    assert not any("previsualisation rapide" in warning for warning in result.warnings)


def test_legacy_dimensioning_profile_is_ignored_by_final_calculation():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=1,
            hour=hour + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
        for hour in range(2)
    ]
    request = _request(
        weather=weather,
        ht_kwh=10.0,
        bt_kwh=20.0,
        solar=_solar_inputs(daily_buffer_l_per_m2=50.0),
        economics=_economics_inputs(analysis_years=2),
        selection=CalculationSelection(
            calculation_profile="dimensionnement_25_ans",
            technical_simulation_years=2,
            run_reduced_borefield=False,
            savings_search_mode="none",
        ),
    )

    result = run_hourly_calculation(request)

    assert result.scenario.simulation_years_total == 2
    assert result.scenario.simulation_year_displayed == 2
    assert result.scenario.no_solar_hourly_df.empty is False
    assert not result.scenario.savings["found"]
    assert result.parametric_pac_df.empty
    assert result.parametric_surface_df.empty
