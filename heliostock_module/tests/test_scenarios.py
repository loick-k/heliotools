import heliostock.scenarios as scenarios_module
from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, SimulationConfig
from heliostock.hourly_engine import HourlyWeather
from heliostock.postprocess import _hourly_results_to_dataframe
from heliostock.scenarios import ScenarioEconomicsConfig, run_hourly_scenario

from helpers import (
    demand_aggregate as _demand_aggregate,
    fake_hourly_result as _fake_hourly_result,
    hourly_override as _hourly_override,
    return_or_sink_results as _return_or_sink_results,
)


def test_run_hourly_scenario_returns_summaries_and_economics():
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.7 if 8 <= hour % 24 <= 16 else 0.0,
        )
        for hour in range(24 * 3)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=60, depth_m=100.0, spacing_m=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0, max_thermal_power_kw=80.0),
    )
    hourly_override = _hourly_override(weather, ht_kwh=125.0, bt_kwh=80.0)
    result = run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=125.0, bt_kwh=80.0),
        config=config,
        economics=ScenarioEconomicsConfig(
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
        hourly_demand_override=hourly_override,
    )

    assert len(result.hourly_df) == 24 * 3
    assert len(result.no_solar_hourly_df) == 24 * 3
    assert set(result.hourly_df["simulation_year"].unique()) == {25}
    assert set(result.no_solar_hourly_df["simulation_year"].unique()) == {25}
    assert int(result.no_solar_hourly_df["simulation_year_displayed"].iloc[0]) == 25
    assert len(result.multiyear_btes_df) == len(result.no_solar_multiyear_btes_df)
    assert not result.no_solar_multiyear_btes_df.empty
    assert not result.annual_df.empty
    assert not result.hourly_by_month_df.empty
    assert result.total_ht_kwh > 0.0
    assert result.total_bt_kwh > 0.0
    assert result.solar_ht_from_buffer_economic_mwh == result.total_preheat_ht_kwh / 1000.0
    assert "combined_heat_cost_eur_mwh" in result.heat_costs
    assert "annual_solar_ht_from_buffer_mwh" in result.solar_economics
    assert "annual_solar_direct_ht_mwh" in result.solar_economics


def test_multiyear_scenario_reuses_projection_instead_of_one_year_runs(monkeypatch):
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
    calls = []
    progress_messages = []
    dataframe_lengths = []

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
        calls.append((float(config.collector.area_m2), int(simulation_years)))
        results = []
        for year in range(1, int(simulation_years) + 1):
            for item in weather:
                ht_kwh, bt_kwh = (hourly_demand_override or {}).get(item.hour_index, (10.0, 20.0))
                results.append(
                    _fake_hourly_result(
                        simulation_year=year,
                        hour_index=item.hour_index,
                        month=item.month,
                        day=item.day,
                        hour=item.hour,
                        tair_c=item.tair_c,
                        demand_ht_kwh=ht_kwh,
                        demand_bt_kwh=bt_kwh,
                        heat_bt_from_pac_kwh=bt_kwh,
                        btes_extracted_by_pac_kwh=bt_kwh * 0.75,
                        electricity_compressor_kwh=bt_kwh * 0.25,
                        electricity_pac_total_kwh=bt_kwh * 0.30,
                        electricity_system_total_kwh=bt_kwh * 0.30,
                        electricity_pac_kwh=bt_kwh * 0.25,
                    )
                )
        return _return_or_sink_results(results, result_sink=result_sink, store_results=store_results)

    def counted_hourly_results_to_dataframe(results):
        dataframe_lengths.append(len(results))
        return _hourly_results_to_dataframe(results)

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(scenarios_module, "_hourly_results_to_dataframe", counted_hourly_results_to_dataframe)
    result = scenarios_module.run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=SimulationConfig(
            collector=CollectorConfig(area_m2=500.0),
            btes=BtesConfig(boreholes=20, depth_m=100.0, spacing_m=6.0),
            heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
        ),
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=2.0,
            eta_appoint_eco=0.9,
            analysis_years=25,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=180.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        run_multiyear=True,
        technical_simulation_years=25,
        run_geo_only=True,
        run_reduced_borefield=False,
        progress=lambda value, text: progress_messages.append(text),
    )

    assert calls == [(500.0, 25), (0.0, 25)]
    assert "Simulation solaire 25 ans - demarrage" in progress_messages
    assert "Simulation sans solaire 25 ans - demarrage" in progress_messages
    assert "Nettoyage memoire" in progress_messages
    assert set(result.hourly_df["simulation_year"].unique()) == {25}
    assert set(result.no_solar_hourly_df["simulation_year"].unique()) == {25}
    assert dataframe_lengths == [len(weather), len(weather)]


def test_run_hourly_scenario_reuses_reduced_borefield_dataframe(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.0)
        for hour in range(2)
    ]
    calls = []

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
        calls.append((float(config.collector.area_m2), int(config.btes.boreholes)))
        return [
            _fake_hourly_result(
                simulation_year=year,
                hour_index=item.hour_index,
                month=item.month,
                day=item.day,
                hour=item.hour,
                demand_ht_kwh=10.0,
                demand_bt_kwh=20.0,
                heat_bt_from_pac_kwh=20.0,
                btes_extracted_by_pac_kwh=15.0,
                electricity_compressor_kwh=5.0,
            )
            for year in range(1, int(simulation_years) + 1)
            for item in weather
        ]

    def fake_borefield_equivalent_savings(**kwargs):
        assert kwargs["include_hourly_df"] is False
        return {
            "found": True,
            "simulated": True,
            "equivalent_length_m": 500.0,
            "equivalent_boreholes": 5,
            "saved_length_m": 500.0,
            "saved_fraction": 0.5,
            "equivalent_cop": 4.0,
            "equivalent_bt_pac_kwh": 36.0,
        }

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(scenarios_module, "borefield_equivalent_savings", fake_borefield_equivalent_savings)
    result = scenarios_module.run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=SimulationConfig(
            collector=CollectorConfig(area_m2=500.0),
            btes=BtesConfig(boreholes=10, depth_m=100.0, spacing_m=6.0),
            heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
        ),
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=2.0,
            eta_appoint_eco=0.9,
            analysis_years=2,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=180.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        run_multiyear=True,
        technical_simulation_years=2,
        run_geo_only=True,
        run_reduced_borefield=True,
    )

    assert sorted(calls) == [(0.0, 10), (500.0, 5), (500.0, 10)]
    assert "_equivalent_hourly_df" not in result.savings
    assert result.economic_borefield_length_m == 500.0


def test_run_hourly_scenario_displays_unvalidated_reduced_candidate(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.0)
        for hour in range(2)
    ]

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
        return [
            _fake_hourly_result(
                simulation_year=year,
                hour_index=item.hour_index,
                month=item.month,
                day=item.day,
                hour=item.hour,
                demand_ht_kwh=10.0,
                demand_bt_kwh=20.0,
                heat_bt_from_pac_kwh=20.0,
                btes_extracted_by_pac_kwh=15.0,
                electricity_compressor_kwh=5.0,
            )
            for year in range(1, int(simulation_years) + 1)
            for item in weather
        ]

    def fake_borefield_equivalent_savings(**kwargs):
        assert kwargs["include_hourly_df"] is False
        return {
            "found": False,
            "simulated": True,
            "validated": False,
            "candidate_length_m": 500.0,
            "candidate_boreholes": 5,
            "candidate_saved_length_m": 500.0,
            "equivalent_length_m": 1000.0,
            "equivalent_boreholes": 10,
            "saved_length_m": 0.0,
            "saved_fraction": 0.0,
            "equivalent_cop": 4.0,
            "equivalent_bt_pac_kwh": 32.0,
            "message": "Aucune réduction de sondes validée",
        }

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(scenarios_module, "borefield_equivalent_savings", fake_borefield_equivalent_savings)

    result = scenarios_module.run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=SimulationConfig(
            collector=CollectorConfig(area_m2=500.0),
            btes=BtesConfig(boreholes=10, depth_m=100.0, spacing_m=6.0),
            heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
        ),
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=2.0,
            eta_appoint_eco=0.9,
            analysis_years=2,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=180.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        run_multiyear=True,
        technical_simulation_years=2,
        run_geo_only=True,
        run_reduced_borefield=True,
    )

    reduced_row = result.economic_comparison_df[
        result.economic_comparison_df["Scenario"] == "Geothermie + solaire sondes reduites"
    ].iloc[0]
    assert result.savings["found"] is False
    assert result.savings["simulated"] is True
    assert "_candidate_hourly_df" not in result.savings
    assert float(reduced_row["Lineaire sondes (ml)"]) == 500.0
    assert float(reduced_row["Lineaire sondes economise (ml)"]) == 0.0
    assert result.economic_borefield_length_m == 1000.0


def test_run_hourly_scenario_does_not_crash_when_borefield_savings_fails(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.0)
        for hour in range(2)
    ]

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
        results = [
            _fake_hourly_result(
                simulation_year=year,
                hour_index=item.hour_index,
                month=item.month,
                day=item.day,
                hour=item.hour,
                demand_ht_kwh=10.0,
                demand_bt_kwh=20.0,
                heat_bt_from_pac_kwh=20.0,
                btes_extracted_by_pac_kwh=15.0,
                electricity_compressor_kwh=5.0,
            )
            for year in range(1, int(simulation_years) + 1)
            for item in weather
        ]
        if result_sink is not None:
            for result in results:
                result_sink(result)
            return [] if not store_results else results
        return results

    def fake_borefield_equivalent_savings(**kwargs):
        assert kwargs["include_hourly_df"] is True
        raise RuntimeError("pygfunction expert search failed")

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    monkeypatch.setattr(scenarios_module, "borefield_equivalent_savings", fake_borefield_equivalent_savings)

    result = scenarios_module.run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        config=SimulationConfig(
            collector=CollectorConfig(area_m2=500.0),
            btes=BtesConfig(boreholes=10, depth_m=100.0, spacing_m=6.0),
            heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
        ),
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=2.0,
            eta_appoint_eco=0.9,
            analysis_years=2,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=180.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        run_multiyear=True,
        technical_simulation_years=2,
        run_geo_only=True,
        run_reduced_borefield=True,
        savings_search_mode="expert",
    )

    assert result.savings["found"] is False
    assert "non determinee" in str(result.savings["message"])
    assert result.economic_borefield_length_m == 1000.0


def test_scenario_p1_uses_total_pac_electricity_and_spf_is_below_machine_cop():
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
        collector=CollectorConfig(area_m2=0.0),
        btes=BtesConfig(boreholes=100, depth_m=100.0, spacing_m=10.0, t_initial_c=18.0),
        heat_pump=HeatPumpConfig(
            max_thermal_power_kw=100.0,
            aux_pac_ratio=0.15,
            standby_power_kw=0.05,
        ),
    )
    result = run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=0.0, bt_kwh=100.0),
        config=config,
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=3.0,
            eta_appoint_eco=0.82,
            analysis_years=20,
            auxiliary_electricity_ratio_pct=0.0,
            electricity_cost_eur_mwh=200.0,
            maintenance_cost_eur_m2_year=22.0,
            ademe_eur_mwh_year=63.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        hourly_demand_override=_hourly_override(weather, ht_kwh=0.0, bt_kwh=100.0),
    )
    p1_table = result.heat_costs["p1_p2_p4"]
    geo_p1 = float(
        p1_table[(p1_table["Generateur"] == "Geothermie PAC") & (p1_table["Poste"] == "P1")]["EUR/MWh"].iloc[0]
    )
    expected_p1 = (result.total_elec_kwh / 1000.0 * 200.0) / (result.total_pac_kwh / 1000.0)

    assert result.total_elec_kwh > result.total_compressor_kwh
    assert abs(geo_p1 - expected_p1) <= 1e-9
    assert result.mean_cop >= result.spf_pac_total
    assert not any("solar_pump" in column.lower() for column in result.hourly_df.columns)
    assert not any("injection_pump" in column.lower() for column in result.hourly_df.columns)
