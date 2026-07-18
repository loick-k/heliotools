import heliostock.borefield_savings as borefield_savings_module
import heliostock.scenario_compact as scenario_compact_module
import heliostock.scenarios as scenarios_module
from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, SimulationConfig
from heliostock.hourly_engine import HourlyWeather
from heliostock.postprocess import _hourly_results_to_dataframe
from heliostock.scenarios import pac_power_parametric_study

from helpers import (
    demand_aggregate as _demand_aggregate,
    fake_hourly_result as _fake_hourly_result,
    hourly_override as _hourly_override,
    return_or_sink_results as _return_or_sink_results,
)


def test_pac_power_parametric_study_runs_without_streamlit():
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
        for hour in range(24)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=20, depth_m=100.0, spacing_m=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0, max_thermal_power_kw=50.0),
    )
    df = pac_power_parametric_study(
        pac_power_fractions_pct=[50.0, 100.0],
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=100.0, bt_kwh=100.0),
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=100.0, bt_kwh=100.0),
        peak_bt_power_kw=100.0,
        use_probe_predesign=False,
        probe_power_ratio_w_m=60.0,
        probe_energy_ratio_kwh_m=115.0,
        probe_unit_depth_m=100.0,
        full_borefield_length_m=2_000.0,
        reference_gas_power_kw=200.0,
        reference_heat_mwh=4.8,
        analysis_years=20,
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_pct=3.0,
        eta_appoint_eco=0.82,
        backup_p2_eur_kw_year=10.0,
        auxiliary_electricity_ratio_pct=3.0,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=22.0,
        ademe_eur_mwh_year=63.0,
        other_public_aid_eur=0.0,
    )

    assert len(df) == 2
    assert "P PAC (% Pmax BT)" in df.columns
    assert "Couverture PAC BT (%)" in df.columns
    assert "Coût chaleur géothermie + appoint gaz (EUR/MWh)" in df.columns
    assert not any("Mix ENR" in column for column in df.columns)


def test_solar_parametric_study_uses_direct_summaries_without_full_dataframe(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.4)
        for hour in range(2)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=20, depth_m=100.0, spacing_m=5.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=80.0),
    )
    dataframe_calls = []

    def fake_simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=None,
        simulation_years=1,
        result_sink=None,
        store_results=True,
        **kwargs,
    ):
        results = []
        for year in range(1, int(simulation_years) + 1):
            for item in weather:
                results.append(
                    _fake_hourly_result(
                        simulation_year=year,
                        hour_index=item.hour_index,
                        month=item.month,
                        day=item.day,
                        hour=item.hour,
                        tair_c=item.tair_c,
                        demand_ht_kwh=10.0,
                        demand_bt_kwh=20.0,
                        solar_ht_direct_kwh=float(config.collector.area_m2) / 100.0,
                        solar_ht_from_buffer_kwh=float(config.collector.area_m2) / 100.0,
                        solar_to_btes_kwh=float(config.collector.area_m2) / 200.0,
                        heat_bt_from_pac_kwh=20.0,
                        btes_extracted_by_pac_kwh=15.0,
                        electricity_compressor_kwh=5.0,
                        electricity_pac_total_kwh=6.0,
                        electricity_system_total_kwh=6.0,
                        q_extraction_w_m=20.0,
                        q_injection_w_m=5.0,
                    )
                )
        return _return_or_sink_results(results, result_sink=result_sink, store_results=store_results)

    def counted_hourly_results_to_dataframe(results):
        dataframe_calls.append(len(results))
        return _hourly_results_to_dataframe(results)

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(scenarios_module, "_hourly_results_to_dataframe", counted_hourly_results_to_dataframe)
    df = scenarios_module.solar_surface_parametric_study(
        surfaces_m2=[250.0, 500.0],
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        no_solar_cop=4.0,
        no_solar_total_pac_kwh=40.0,
        no_solar_bt_coverage=1.0,
        no_solar_source_limited_hours=0.0,
        pac_nominal_power_kw=80.0,
        full_borefield_length_m=2_000.0,
        reference_gas_power_kw=30.0,
        reference_heat_mwh=0.06,
        analysis_years=2,
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_pct=3.0,
        eta_appoint_eco=0.82,
        backup_p2_eur_kw_year=10.0,
        auxiliary_electricity_ratio_pct=3.0,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=22.0,
        ademe_eur_mwh_year=63.0,
        other_public_aid_eur=0.0,
        savings_search_mode="none",
    )

    assert len(df) == 2
    assert dataframe_calls == []
    assert "Coût chaleur même linéaire (EUR/MWh)" in df.columns


def test_solar_parametric_reuses_matching_main_scenario(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.4)
        for hour in range(2)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=20, depth_m=100.0, spacing_m=5.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=80.0),
    )
    calls = []

    def make_results(surface_m2: float, simulation_years: int):
        rows = []
        for year in range(1, int(simulation_years) + 1):
            for item in weather:
                rows.append(
                    _fake_hourly_result(
                        simulation_year=year,
                        hour_index=item.hour_index,
                        month=item.month,
                        day=item.day,
                        hour=item.hour,
                        tair_c=item.tair_c,
                        demand_ht_kwh=10.0,
                        demand_bt_kwh=20.0,
                        solar_ht_direct_kwh=float(surface_m2) / 100.0,
                        solar_ht_from_buffer_kwh=float(surface_m2) / 100.0,
                        solar_to_btes_kwh=float(surface_m2) / 200.0,
                        heat_bt_from_pac_kwh=20.0,
                        btes_extracted_by_pac_kwh=15.0,
                        electricity_compressor_kwh=5.0,
                        electricity_pac_total_kwh=6.0,
                        electricity_system_total_kwh=6.0,
                        q_extraction_w_m=20.0,
                        q_injection_w_m=5.0,
                    )
                )
        return rows

    reference_results = make_results(500.0, 2)
    reference_metrics = scenarios_module._hourly_metrics_from_results(reference_results, annualization_years=2)
    reference_full = scenarios_module._final_year_screening_metrics_from_results(
        reference_results,
        t_min_c=config.btes.t_min_c,
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        demand_bt_kwh=40.0,
    )
    reference_full["mean_cop"] = reference_metrics["mean_cop"]
    reference_full["mean_bt_pac_kwh"] = reference_metrics["pac_heat_mwh"] * 1000.0
    reference_trajectory = scenarios_module._annual_metrics_trajectory_from_results(
        reference_results,
        analysis_years=2,
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        gmi_check_enabled=config.btes.gmi_check_enabled,
        pac_power_kw=80.0,
    )

    def fake_simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=None,
        simulation_years=1,
        result_sink=None,
        store_results=True,
        **kwargs,
    ):
        calls.append(float(config.collector.area_m2))
        return _return_or_sink_results(
            make_results(float(config.collector.area_m2), int(simulation_years)),
            result_sink=result_sink,
            store_results=store_results,
        )

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(scenario_compact_module, "simulate_hourly", fake_simulate_hourly)
    df = scenarios_module.solar_surface_parametric_study(
        surfaces_m2=[250.0, 500.0],
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        no_solar_cop=4.0,
        no_solar_total_pac_kwh=40.0,
        no_solar_bt_coverage=1.0,
        no_solar_source_limited_hours=0.0,
        pac_nominal_power_kw=80.0,
        full_borefield_length_m=2_000.0,
        reference_gas_power_kw=30.0,
        reference_heat_mwh=0.06,
        analysis_years=2,
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_pct=3.0,
        eta_appoint_eco=0.82,
        backup_p2_eur_kw_year=10.0,
        auxiliary_electricity_ratio_pct=3.0,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=22.0,
        ademe_eur_mwh_year=63.0,
        other_public_aid_eur=0.0,
        savings_search_mode="none",
        full_case_reference={
            "surface_m2": 500.0,
            "boreholes": 20,
            "depth_m": 100.0,
            "simulation_years": 2,
            "metrics": reference_metrics,
            "full_case_metrics": reference_full,
            "trajectory_df": reference_trajectory,
        },
    )

    assert calls == [250.0]
    assert df["Scenario principal reutilise"].tolist() == [False, True]


def test_solar_parametric_fast_savings_reuses_full_case_metrics(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.4)
        for hour in range(2)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=20, depth_m=100.0, spacing_m=5.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=80.0),
    )

    def make_results(surface_m2: float, simulation_years: int):
        rows = []
        for year in range(1, int(simulation_years) + 1):
            for item in weather:
                rows.append(
                    _fake_hourly_result(
                        simulation_year=year,
                        hour_index=item.hour_index,
                        month=item.month,
                        day=item.day,
                        hour=item.hour,
                        tair_c=item.tair_c,
                        demand_ht_kwh=10.0,
                        demand_bt_kwh=20.0,
                        solar_ht_direct_kwh=float(surface_m2) / 100.0,
                        solar_ht_from_buffer_kwh=float(surface_m2) / 100.0,
                        solar_to_btes_kwh=float(surface_m2) / 200.0,
                        heat_bt_from_pac_kwh=20.0,
                        btes_extracted_by_pac_kwh=15.0,
                        electricity_compressor_kwh=5.0,
                        electricity_pac_total_kwh=6.0,
                        electricity_system_total_kwh=6.0,
                        q_extraction_w_m=20.0,
                        q_injection_w_m=5.0,
                    )
                )
        return rows

    reference_results = make_results(500.0, 2)
    reference_metrics = scenarios_module._hourly_metrics_from_results(reference_results, annualization_years=2)
    reference_full = scenarios_module._final_year_screening_metrics_from_results(
        reference_results,
        t_min_c=config.btes.t_min_c,
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        demand_bt_kwh=40.0,
    )
    reference_full["mean_cop"] = reference_metrics["mean_cop"]
    reference_full["mean_bt_pac_kwh"] = reference_metrics["pac_heat_mwh"] * 1000.0
    reference_trajectory = scenarios_module._annual_metrics_trajectory_from_results(
        reference_results,
        analysis_years=2,
        gmi_t_min_c=config.btes.gmi_t_min_c,
        gmi_t_max_c=config.btes.gmi_t_max_c,
        gmi_check_enabled=config.btes.gmi_check_enabled,
        pac_power_kw=80.0,
    )

    savings_calls = []

    def fake_savings_simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=None,
        simulation_years=1,
        result_sink=None,
        store_results=True,
        **kwargs,
    ):
        savings_calls.append(int(config.btes.boreholes))
        if int(config.btes.boreholes) == 20:
            raise AssertionError("Le cas champ complet reutilise ne doit pas relancer pygfunction.")
        return _return_or_sink_results(
            make_results(float(config.collector.area_m2), int(simulation_years)),
            result_sink=result_sink,
            store_results=store_results,
        )

    def fail_main_simulate_hourly(*args, **kwargs):
        raise AssertionError("Le scenario principal reutilise ne doit pas relancer pygfunction.")

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fail_main_simulate_hourly)
    monkeypatch.setattr(borefield_savings_module, "simulate_hourly", fake_savings_simulate_hourly)

    df = scenarios_module.solar_surface_parametric_study(
        surfaces_m2=[500.0],
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        no_solar_cop=4.0,
        no_solar_total_pac_kwh=40.0,
        no_solar_bt_coverage=1.0,
        no_solar_source_limited_hours=0.0,
        pac_nominal_power_kw=80.0,
        full_borefield_length_m=2_000.0,
        reference_gas_power_kw=30.0,
        reference_heat_mwh=0.06,
        analysis_years=2,
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_pct=3.0,
        eta_appoint_eco=0.82,
        backup_p2_eur_kw_year=10.0,
        auxiliary_electricity_ratio_pct=3.0,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=22.0,
        ademe_eur_mwh_year=63.0,
        other_public_aid_eur=0.0,
        savings_search_mode="fast",
        full_case_reference={
            "surface_m2": 500.0,
            "boreholes": 20,
            "depth_m": 100.0,
            "simulation_years": 2,
            "metrics": reference_metrics,
            "full_case_metrics": reference_full,
            "trajectory_df": reference_trajectory,
        },
    )

    assert df["Scenario principal reutilise"].tolist() == [True]
    assert 20 not in savings_calls
