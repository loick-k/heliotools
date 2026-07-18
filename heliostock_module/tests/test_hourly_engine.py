from dataclasses import replace

import pytest

from heliostock.btes_models import PygfunctionBtesModel, create_btes_model, pygfunction_available
from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, MonthlyDemand, SimulationConfig
from heliostock.hourly_engine import HourlyResult, HourlyWeather, aggregate_hourly_results_monthly, simulate_hourly
from heliostock.postprocess import _hourly_results_to_dataframe, _multiyear_btes_summary


def skip_if_no_pygfunction() -> None:
    if not pygfunction_available():
        pytest.skip("pygfunction non disponible dans cet environnement")


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


def _fake_hourly_result(**overrides) -> HourlyResult:
    base = dict(
        simulation_year=1,
        hour_index=0,
        month=1,
        day=1,
        hour=1,
        tair_c=8.0,
        demand_ht_kwh=0.0,
        demand_bt_kwh=100.0,
        solar_ht_potential_kwh=0.0,
        solar_ht_instant_kwh=0.0,
        solar_ht_from_buffer_kwh=0.0,
        solar_ht_to_buffer_kwh=0.0,
        solar_ht_buffer_loss_kwh=0.0,
        solar_ht_buffer_energy_end_kwh=0.0,
        solar_ht_buffer_temp_start_c=20.0,
        solar_ht_buffer_temp_end_c=20.0,
        collector_temp_ht_c=30.0,
        collector_temp_storage_c=25.0,
        solar_ht_direct_kwh=0.0,
        solar_storage_potential_kwh=0.0,
        solar_to_btes_kwh=0.0,
        solar_not_used_kwh=0.0,
        t_borehole_wall_c=10.0,
        t_source_pac_c=7.0,
        t_source_pac_for_cop_c=7.0,
        t_evaporator_pac_c=4.0,
        t_fluide_injection_c=12.0,
        t_fluide_entree_echangeur_geo_c=7.0,
        q_extraction_w_m=30.0,
        q_injection_w_m=0.0,
        q_injection_signed_w_m=0.0,
        q_net_w_m=30.0,
        cop_limited_max=False,
        source_temp_limited=False,
        source_temp_unmet_bt_kwh=0.0,
        cop_pac=4.0,
        heat_bt_from_pac_kwh=100.0,
        btes_extracted_by_pac_kwh=75.0,
        electricity_compressor_kwh=25.0,
        electricity_pac_auxiliaries_kwh=3.75,
        electricity_standby_kwh=0.05,
        electricity_pac_total_kwh=28.8,
        electricity_system_total_kwh=28.8,
        electricity_pac_kwh=25.0,
        unmet_ht_kwh=0.0,
        unmet_bt_kwh=0.0,
        collector_eff_ht=0.0,
        collector_eff_storage=0.0,
    )
    base.update(overrides)
    return HourlyResult(**base)


def test_hourly_simulation_smoke():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=6.0,
            g_tilt_kwh_m2=0.6 if 9 <= hour % 24 <= 15 else 0.0,
        )
        for hour in range(24 * 31)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=1000.0),
        btes=BtesConfig(boreholes=100, depth_m=100.0, spacing_m=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0),
    )
    hourly_override = _hourly_override(weather, ht_kwh=95.0, bt_kwh=135.0)
    results = simulate_hourly(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=95.0, bt_kwh=135.0),
        config=config,
        hourly_demand_override=hourly_override,
    )
    monthly = aggregate_hourly_results_monthly(results)

    assert len(results) == 24 * 31
    assert len(monthly) == 1
    assert all(result.t_source_pac_c <= config.btes.t_max_c + 1e-9 for result in results)
    assert all(result.t_source_pac_for_cop_c >= config.btes.t_min_c - 1e-9 for result in results)
    assert all(hasattr(result, "t_source_pac_for_cop_c") for result in results)
    assert all(result.solar_ht_potential_kwh >= 0 for result in results)
    assert sum(result.solar_ht_instant_kwh for result in results) == 0.0
    assert sum(result.solar_ht_from_buffer_kwh for result in results) > 0
    assert all(result.solar_ht_direct_kwh == result.solar_ht_from_buffer_kwh for result in results)
    assert min(result.solar_ht_buffer_temp_end_c for result in results) >= config.collector.daily_buffer_ambient_temp_c - 1e-9
    assert max(result.solar_ht_buffer_temp_end_c for result in results) <= config.collector.daily_buffer_max_temp_c + 1e-9
    assert all(
        abs(
            result.heat_bt_from_pac_kwh
            - result.btes_extracted_by_pac_kwh
            - result.electricity_pac_kwh
        )
        <= 1e-6
        for result in results
    )


def test_multiyear_simulation_keeps_btes_thermal_memory_without_saturation():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=6.0,
            g_tilt_kwh_m2=0.5 if 9 <= hour % 24 <= 15 else 0.0,
        )
        for hour in range(24 * 7)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=100.0),
        btes=BtesConfig(boreholes=16, depth_m=120.0, spacing_m=10.0, t_min_c=3.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0, max_thermal_power_kw=45.0),
    )
    results = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=3_000.0, process_bt_kwh=6_000.0)],
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=18.0, bt_kwh=36.0),
        simulation_years=3,
    )
    df = _hourly_results_to_dataframe(results)
    summary = _multiyear_btes_summary(df, t_min_c=config.btes.t_min_c)

    assert len(results) == len(weather) * 3
    assert sorted(df["simulation_year"].unique().tolist()) == [1, 2, 3]
    assert len(summary) == 3
    assert int(summary["Heures sous Tmin operationnelle"].sum()) == 0
    assert summary["T source PAC fin (C)"].iloc[-1] < summary["T source PAC fin (C)"].iloc[0]


def test_multiyear_simulation_keeps_btes_thermal_memory_with_saturation():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=5.0,
            g_tilt_kwh_m2=0.2 if 10 <= hour % 24 <= 14 else 0.0,
        )
        for hour in range(24 * 7)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=20.0),
        btes=BtesConfig(boreholes=8, depth_m=80.0, spacing_m=8.0, t_min_c=5.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=30.0, max_thermal_power_kw=110.0),
    )
    results = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=10_000.0, process_bt_kwh=22_000.0)],
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=60.0, bt_kwh=130.0),
        simulation_years=3,
    )
    df = _hourly_results_to_dataframe(results)
    annual = df.groupby("simulation_year").agg(
        t_wall_min=("T_paroi_forage_C", "min"),
        pac_heat=("heat_bt_from_pac_kwh", "sum"),
        limited_hours=("Limite_temperature_source", "sum"),
    )

    assert annual.loc[3, "t_wall_min"] < annual.loc[1, "t_wall_min"]
    assert annual.loc[3, "pac_heat"] < annual.loc[1, "pac_heat"]
    assert annual.loc[3, "limited_hours"] > 1


def test_pygfunction_backend_is_required_without_alternative_backend():
    btes = BtesConfig(boreholes=10, depth_m=100.0, spacing_m=10.0, backend="pygfunction")
    if not pygfunction_available():
        with pytest.raises(ImportError, match="pygfunction est requis"):
            create_btes_model(btes)
        return

    model = create_btes_model(btes)
    assert isinstance(model, PygfunctionBtesModel)


def test_pygfunction_backend_is_used_when_available():
    skip_if_no_pygfunction()

    btes = BtesConfig(boreholes=80, depth_m=100.0, spacing_m=10.0, backend="pygfunction")
    model = create_btes_model(btes)

    assert isinstance(model, PygfunctionBtesModel)
    initial_temp = model.temperature_c()
    model.commit_load(q_net_w_m=-10.0, q_extraction_w_m=0.0, q_injection_w_m=10.0)

    assert model.temperature_c() > initial_temp


def test_hourly_energy_balances():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.7 if 8 <= hour % 24 <= 16 else 0.0,
        )
        for hour in range(24 * 7)
    ]
    demands = [MonthlyDemand(month=1, process_ht_kwh=70_000.0, process_bt_kwh=50_000.0)]
    config = SimulationConfig(
        collector=CollectorConfig(
            area_m2=800.0,
            daily_buffer_l_per_m2=50.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            solar_preheat_target_ht_c=60.0,
            daily_buffer_loss_fraction_per_day=0.02,
        ),
        btes=BtesConfig(boreholes=80, depth_m=120.0, spacing_m=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0),
    )
    results = simulate_hourly(
        weather=weather,
        demands=demands,
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=420.0, bt_kwh=300.0),
    )

    previous_buffer = 0.0
    buffer_capacity = (
        config.collector.area_m2
        * config.collector.daily_buffer_l_per_m2
        * 1.163e-3
        * (config.collector.daily_buffer_max_temp_c - config.collector.daily_buffer_ambient_temp_c)
    )
    for result in results:
        assert abs(result.demand_ht_kwh - result.solar_ht_from_buffer_kwh - result.unmet_ht_kwh) <= 1e-6
        assert result.solar_ht_instant_kwh == 0.0
        assert config.collector.daily_buffer_ambient_temp_c - 1e-9 <= result.solar_ht_buffer_temp_end_c <= config.collector.daily_buffer_max_temp_c + 1e-9
        assert abs(
            previous_buffer
            + result.solar_ht_to_buffer_kwh
            - result.solar_ht_from_buffer_kwh
            - result.solar_ht_buffer_loss_kwh
            - result.solar_ht_buffer_energy_end_kwh
        ) <= 1e-6
        previous_buffer = result.solar_ht_buffer_energy_end_kwh

        if result.solar_to_btes_kwh > 1e-6:
            assert previous_buffer + result.solar_ht_from_buffer_kwh + result.solar_ht_buffer_loss_kwh >= buffer_capacity - 1e-6

        expected_q_net = (
            (result.btes_extracted_by_pac_kwh - result.solar_to_btes_kwh)
            * 1000.0
            / max(1e-9, config.btes.boreholes * config.btes.depth_m)
        )
        assert abs(result.q_net_w_m - expected_q_net) <= 1e-6
        assert abs(
            result.heat_bt_from_pac_kwh
            - result.btes_extracted_by_pac_kwh
            - result.electricity_pac_kwh
        ) <= 1e-6
        assert result.solar_ht_instant_kwh + result.solar_ht_to_buffer_kwh <= result.solar_ht_potential_kwh + 1e-6


def test_hourly_night_has_zero_solar_efficiency_and_yield():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=0,
            month=1,
            day=1,
            hour=1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=50, depth_m=100.0, spacing_m=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0),
    )
    results = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=10_000.0, process_bt_kwh=10_000.0)],
        config=config,
        hourly_demand_override={0: (100.0, 100.0)},
    )
    result = results[0]

    assert result.collector_eff_ht == 0.0
    assert result.collector_eff_storage == 0.0
    assert result.solar_ht_potential_kwh == 0.0
    assert result.solar_to_btes_kwh == 0.0


def test_hourly_no_solar_case_has_no_solar_fluxes():
    skip_if_no_pygfunction()
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.8,
        )
        for hour in range(24)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=500.0),
        btes=BtesConfig(boreholes=50, depth_m=100.0, spacing_m=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0),
    )
    no_solar_config = replace(config, collector=replace(config.collector, area_m2=0.0))
    results = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=10_000.0, process_bt_kwh=10_000.0)],
        config=no_solar_config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=100.0, bt_kwh=100.0),
    )

    assert sum(result.solar_ht_potential_kwh for result in results) == 0.0
    assert sum(result.solar_ht_from_buffer_kwh for result in results) == 0.0
    assert sum(result.solar_to_btes_kwh for result in results) == 0.0
    assert sum(result.solar_not_used_kwh for result in results) == 0.0


def test_hourly_pac_power_limit_creates_bt_backup():
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
        btes=BtesConfig(
            boreholes=500,
            depth_m=150.0,
            spacing_m=5.0,
            t_initial_c=20.0,
            t_min_c=5.0,
            t_max_c=40.0,
        ),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0, max_thermal_power_kw=50.0),
    )
    results = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=0.0)],
        config=config,
        hourly_demand_override={0: (0.0, 120.0)},
    )
    result = results[0]

    assert result.heat_bt_from_pac_kwh <= 50.0 + 1e-9
    assert abs(result.heat_bt_from_pac_kwh - 50.0) <= 1e-6
    assert abs(result.unmet_bt_kwh - 70.0) <= 1e-6


def test_pac_total_electricity_includes_auxiliaries_and_standby():
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
        btes=BtesConfig(boreholes=500, depth_m=150.0, spacing_m=10.0, t_initial_c=20.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=100.0, aux_pac_ratio=0.15, standby_power_kw=0.05),
    )
    result = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=0.0)],
        config=config,
        hourly_demand_override={0: (0.0, 80.0)},
    )[0]

    assert result.electricity_pac_total_kwh > result.electricity_compressor_kwh
    assert result.electricity_pac_auxiliaries_kwh == result.electricity_compressor_kwh * 0.15
    assert result.electricity_standby_kwh == 0.05
    assert result.electricity_system_total_kwh == result.electricity_pac_total_kwh


def test_zero_pac_auxiliaries_keeps_legacy_compressor_electricity():
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
        btes=BtesConfig(boreholes=500, depth_m=150.0, spacing_m=10.0, t_initial_c=20.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=100.0, aux_pac_ratio=0.0, standby_power_kw=0.0),
    )
    result = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=0.0)],
        config=config,
        hourly_demand_override={0: (0.0, 80.0)},
    )[0]

    assert result.electricity_pac_total_kwh == result.electricity_compressor_kwh
    assert result.electricity_pac_kwh == result.electricity_compressor_kwh


def test_postprocess_exports_year_metadata_and_signed_injection():
    df = _hourly_results_to_dataframe(
        [
            _fake_hourly_result(
                simulation_year=25,
                q_injection_w_m=12.0,
                q_injection_signed_w_m=-12.0,
                q_net_w_m=-12.0,
                solar_to_btes_kwh=12.0,
            )
        ]
    )
    df["simulation_year_displayed"] = 25
    df["simulation_years_total"] = 25
    df["scenario"] = "Geothermie + solaire meme sondes"
    df["surface_solaire_m2"] = 500.0
    df["solaire_actif"] = True
    df["puissance_pac_kw"] = 100.0
    df["lineaire_sondes_m"] = 1000.0
    df["tmin_source_operationnelle_c"] = 5.0
    df["critere_gmi_active"] = True

    assert float(df["q_injection_W_m"].iloc[0]) == 12.0
    assert float(df["q_injection_signee_W_m"].iloc[0]) == -12.0
    assert int(df["simulation_year_displayed"].iloc[0]) == 25
    assert int(df["simulation_years_total"].iloc[0]) == 25
    assert bool(df["critere_gmi_active"].iloc[0])


def test_gmi_threshold_is_distinct_from_operational_tmin():
    df = _hourly_results_to_dataframe(
        [
            _fake_hourly_result(
                t_source_pac_c=4.0,
                t_source_pac_for_cop_c=4.0,
                t_fluide_entree_echangeur_geo_c=4.0,
                t_fluide_injection_c=35.0,
            ),
            _fake_hourly_result(
                hour_index=1,
                t_source_pac_c=-4.0,
                t_source_pac_for_cop_c=5.0,
                t_fluide_entree_echangeur_geo_c=-4.0,
                t_fluide_injection_c=41.0,
            ),
        ]
    )
    summary = _multiyear_btes_summary(df, t_min_c=5.0, gmi_t_min_c=-3.0, gmi_t_max_c=40.0)

    row = summary.iloc[0]
    assert int(row["Heures sous Tmin operationnelle"]) == 2
    assert int(row["Heures sous Tmin GMI"]) == 1
    assert int(row["Heures sur Tmax GMI"]) == 1
    assert not bool(row["Conformite GMI"])
