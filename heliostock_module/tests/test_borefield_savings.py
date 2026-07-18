import heliostock.borefield_savings as borefield_savings_module
from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, MonthlyDemand, SimulationConfig
from heliostock.hourly_engine import HourlyWeather
from heliostock.postprocess import _hourly_results_to_dataframe
from heliostock.scenarios import borefield_equivalent_savings

from helpers import fake_hourly_result, hourly_override, skip_if_no_pygfunction


def test_borefield_savings_annualizes_multiyear_candidate_heat():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=0,
            month=1,
            day=1,
            hour=12,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=0.0),
        btes=BtesConfig(boreholes=100, depth_m=100.0, spacing_m=10.0, t_initial_c=18.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=100.0),
    )
    savings = borefield_equivalent_savings(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=0.0)],
        config=config,
        reference_final_cop=0.0,
        reference_final_bt_pac_kwh=0.0,
        reference_final_bt_coverage=0.0,
        reference_final_source_limited_hours=0.0,
        hourly_demand_override={0: (0.0, 80.0)},
        simulation_years=3,
        iterations=0,
    )

    assert not bool(savings["found"])
    assert str(savings["message"]) == "Aucune réduction de sondes validée"
    assert abs(float(savings["equivalent_bt_pac_kwh"]) - 80.0) <= 1e-6


def test_borefield_savings_fast_reuses_full_case_and_limits_simulations(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.0)
        for hour in range(2)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=10, depth_m=100.0, spacing_m=8.0, max_extraction_w_m=40.0, max_injection_w_m=40.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=80.0),
    )
    full_results = []
    for year in [1, 2]:
        for item in weather:
            full_results.append(
                fake_hourly_result(
                    simulation_year=year,
                    hour_index=item.hour_index,
                    demand_bt_kwh=100.0,
                    heat_bt_from_pac_kwh=100.0,
                    btes_extracted_by_pac_kwh=75.0,
                    solar_to_btes_kwh=25.0,
                    electricity_compressor_kwh=25.0,
                    q_extraction_w_m=30.0,
                    q_injection_w_m=10.0,
                )
            )
    full_case_df = _hourly_results_to_dataframe(full_results)
    calls = []
    dataframe_calls = []

    def fake_simulate_hourly(weather, demands, config, hourly_demand_override=None, simulation_years=1):
        calls.append(int(config.btes.boreholes))
        results = []
        for year in range(1, int(simulation_years) + 1):
            for item in weather:
                results.append(
                    fake_hourly_result(
                        simulation_year=year,
                        hour_index=item.hour_index,
                        demand_bt_kwh=100.0,
                        heat_bt_from_pac_kwh=100.0,
                        btes_extracted_by_pac_kwh=75.0,
                        solar_to_btes_kwh=25.0,
                        electricity_compressor_kwh=25.0,
                        q_extraction_w_m=30.0,
                        q_injection_w_m=10.0,
                    )
                )
        return results

    def fake_hourly_results_to_dataframe(results):
        dataframe_calls.append(len(results))
        return _hourly_results_to_dataframe(results)

    monkeypatch.setattr(borefield_savings_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(borefield_savings_module, "_hourly_results_to_dataframe", fake_hourly_results_to_dataframe)
    savings = borefield_savings_module.borefield_equivalent_savings(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=200.0)],
        config=config,
        reference_final_cop=4.0,
        reference_final_bt_pac_kwh=200.0,
        reference_final_bt_coverage=1.0,
        reference_final_source_limited_hours=0.0,
        hourly_demand_override=hourly_override(weather, ht_kwh=0.0, bt_kwh=100.0),
        simulation_years=2,
        search_mode="fast",
        full_case_df=full_case_df,
    )

    assert calls
    assert 10 not in calls
    assert int(savings["savings_simulations_count"]) <= 3
    assert len(dataframe_calls) <= 1
