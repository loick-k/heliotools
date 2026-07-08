from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile

import pandas as pd

import heliostock.borefield_savings as borefield_savings_module
import heliostock.scenarios as scenarios_module
import heliostock.simulation_cache as simulation_cache_module
from heliostock.engine import (
    BtesConfig,
    CollectorConfig,
    HeatPumpConfig,
    MonthlyDemand,
    SimulationConfig,
)
from heliostock.btes_models import PygfunctionBtesModel, create_btes_model, pygfunction_available
from heliostock.app_service import CalculationSelection, HourlyCalculationRequest, ParametricRange, run_hourly_calculation
from heliostock.calculation_snapshot import build_calculation_snapshot, stable_snapshot_hash
from heliostock.dashboard_data_cleaning import group_small_categories, join_values, to_float, to_year
from heliostock.economics import (
    compute_heat_costs,
    compute_solar_thermal_economics,
    solar_capex_eur,
    solar_energy_allocation,
    solar_recharge_value,
)
from heliostock.hourly_engine import HourlyWeather, aggregate_hourly_results_monthly, simulate_hourly
from heliostock.hourly_engine import HourlyResult
from heliostock.geothermal_design import predimension_borefield
from heliostock.inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, ScenarioInputs, SolarInputs
from heliostock.load_profiles import _hourly_demands_from_process_file
from heliostock.postprocess import _hourly_results_to_dataframe, _multiyear_btes_summary
from heliostock.postprocess import (
    btes_efficiency_indicator,
    btes_load_diagnostics_from_dataframe,
    classify_geo_field_mode,
    sign_change_diagnostics,
    surface_insulation_warning,
)
from heliostock.scenarios import (
    ScenarioEconomicsConfig,
    _multiyear_heat_cost,
    borefield_equivalent_savings,
    pac_power_parametric_study,
    run_hourly_scenario,
)
from heliostock.simulation_cache import SimulationCache
from heliostock.ui_formatting import display_dataframe, round_display_df
from heliostock.ui_inputs import (
    DEFAULT_EPW_REGIONS,
    DEFAULT_EPW_STATIONS,
    FixedEconomicsAssumptions,
    FixedGeoAssumptions,
    FixedSolarAssumptions,
)


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


def _return_or_sink_results(results, result_sink=None, store_results=True):
    if result_sink is not None:
        for row in results:
            result_sink(row)
    return results if store_results else []


def test_simulation_cache_reuses_identical_hourly_simulations(monkeypatch):
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
    demands = [MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=100.0)]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=0.0),
        btes=BtesConfig(boreholes=4, depth_m=100.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
    )
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
        calls.append((float(config.collector.area_m2), int(simulation_years)))
        return [
            _fake_hourly_result(
                simulation_year=1,
                hour_index=weather[0].hour_index,
                demand_bt_kwh=100.0,
            )
        ]

    monkeypatch.setattr(simulation_cache_module, "simulate_hourly", fake_simulate_hourly)
    cache = SimulationCache()
    override = _hourly_override(weather, ht_kwh=0.0, bt_kwh=100.0)

    first = cache.simulate(
        weather,
        demands,
        config,
        hourly_demand_override=override,
        simulation_years=25,
        mode="same",
    )
    second = cache.simulate(
        weather,
        demands,
        config,
        hourly_demand_override=override,
        simulation_years=25,
        mode="same",
    )
    cache.simulate(
        weather,
        demands,
        config,
        hourly_demand_override=override,
        simulation_years=1,
        mode="same",
    )

    assert first == second
    assert calls == [(0.0, 25), (0.0, 1)]
    assert cache.summary() == {"hits": 1, "misses": 2, "entries": 2}


def test_hourly_simulation_smoke():
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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
        try:
            create_btes_model(btes)
        except ImportError as exc:
            assert "pygfunction est requis" in str(exc)
            return
        raise AssertionError("create_btes_model ne doit pas revenir silencieusement a un backend alternatif")

    model = create_btes_model(btes)
    assert isinstance(model, PygfunctionBtesModel)


def test_pygfunction_backend_is_used_when_available():
    if not pygfunction_available():
        return

    btes = BtesConfig(boreholes=80, depth_m=100.0, spacing_m=10.0, backend="pygfunction")
    model = create_btes_model(btes)

    assert isinstance(model, PygfunctionBtesModel)
    initial_temp = model.temperature_c()
    model.commit_load(q_net_w_m=-10.0, q_extraction_w_m=0.0, q_injection_w_m=10.0)

    assert model.temperature_c() > initial_temp


def test_hourly_energy_balances():
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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
    if not pygfunction_available():
        return
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


def test_mix_backup_gas_p1_uses_same_inflated_cost_as_reference_gas():
    solar_economics = {
        "p1_eur_mwh": 0.0,
        "p2_eur_mwh": 0.0,
        "p4_eur_mwh": 0.0,
        "capex_eur": 0.0,
        "ademe_aid_eur": 0.0,
        "aid_total_eur": 0.0,
        "net_capex_eur": 0.0,
    }
    heat_costs = compute_heat_costs(
        solar_economics=solar_economics,
        annual_solar_mwh=0.0,
        annual_pac_heat_mwh=0.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=100.0,
        backup_power_kw=100.0,
        reference_heat_mwh=100.0,
        reference_power_kw=100.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=0.82,
        gas_reference_inflation_rate=0.03,
        geothermal_p1_eur_mwh=200.0,
        backup_p1_eur_mwh=70.0,
        backup_p2_eur_kw_year=10.0,
    )
    p1_table = heat_costs["p1_p2_p4"]
    backup_p1 = float(
        p1_table[(p1_table["Generateur"] == "Appoint gaz") & (p1_table["Poste"] == "P1")]["EUR/MWh"].iloc[0]
    )
    backup_p2 = float(
        p1_table[(p1_table["Generateur"] == "Appoint gaz") & (p1_table["Poste"] == "P2")]["EUR/MWh"].iloc[0]
    )
    reference_p1 = float(heat_costs["reference_p1_eur_mwh"])
    reference_p2 = float(heat_costs["reference_p2_eur_mwh"])

    assert backup_p1 == reference_p1
    assert backup_p1 > 70.0 / 0.82
    assert backup_p2 == 10.0
    assert reference_p2 == 10.0


def test_solar_p2_uses_one_percent_capex_over_total_solar_production():
    surface_m2 = 500.0
    total_solar_mwh = 250.0
    capex = solar_capex_eur(surface_m2)
    economics = compute_solar_thermal_economics(
        surface_m2=surface_m2,
        annual_solar_valued_mwh=100.0,
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_rate=0.03,
        analysis_years=20,
        eta_appoint=0.82,
        auxiliary_electricity_ratio=0.03,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=999.0,
        ademe_eur_mwh_year=63.0,
        other_public_aid_eur=0.0,
        annual_solar_total_mwh=total_solar_mwh,
    )

    assert abs(float(economics["p2_annual_eur"]) - 0.01 * capex) <= 1e-9
    assert abs(float(economics["p2_eur_mwh"]) - (0.01 * capex / total_solar_mwh)) <= 1e-9
    assert abs(float(economics["p1_eur_mwh"]) - 0.03 * 200.0) <= 1e-9


def test_solar_recharge_p2_is_counted_globally_as_geothermal_p2():
    solar_economics = {
        "p1_eur_mwh": 0.0,
        "p2_eur_mwh": 10.0,
        "p4_eur_mwh": 0.0,
        "p2_annual_eur": 3_000.0,
        "annual_solar_total_mwh": 300.0,
        "capex_eur": 0.0,
        "ademe_aid_eur": 0.0,
        "aid_total_eur": 0.0,
        "net_capex_eur": 0.0,
    }
    heat_costs = compute_heat_costs(
        solar_economics=solar_economics,
        annual_solar_mwh=100.0,
        annual_pac_heat_mwh=200.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=0.0,
        backup_power_kw=0.0,
        reference_heat_mwh=300.0,
        reference_power_kw=0.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=0.82,
        gas_reference_inflation_rate=0.0,
        geothermal_p1_eur_mwh=200.0,
    )
    p2_table = heat_costs["p1_p2_p4"]
    solar_p2 = float(
        p2_table[(p2_table["Generateur"] == "Solaire thermique") & (p2_table["Poste"] == "P2")][
            "EUR/MWh"
        ].iloc[0]
    )
    geo_p2 = float(
        p2_table[(p2_table["Generateur"] == "Geothermie PAC") & (p2_table["Poste"] == "P2")][
            "EUR/MWh"
        ].iloc[0]
    )
    trajectory = pd.DataFrame(
        [
            {
                "Annee": 1,
                "Solaire HT (MWh)": 100.0,
                "Chaleur PAC BT (MWh)": 200.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 0.0,
                "E utile totale (MWh)": 300.0,
            },
            {
                "Annee": 2,
                "Solaire HT (MWh)": 100.0,
                "Chaleur PAC BT (MWh)": 200.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 0.0,
                "E utile totale (MWh)": 300.0,
            },
        ]
    )
    multiyear = _multiyear_heat_cost(
        trajectory_df=trajectory,
        heat_costs=heat_costs,
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=0.0,
            eta_appoint_eco=0.82,
            analysis_years=20,
            auxiliary_electricity_ratio_pct=0.0,
            electricity_cost_eur_mwh=200.0,
            maintenance_cost_eur_m2_year=22.0,
            ademe_eur_mwh_year=63.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        capex_net_eur=0.0,
    )

    assert float(heat_costs["solar_p2_total_annual_eur"]) == 3_000.0
    assert float(heat_costs["solar_p2_ht_annual_eur"]) == 1_000.0
    assert float(heat_costs["solar_p2_recharge_annual_eur"]) == 2_000.0
    assert float(heat_costs["geo_p2_with_recharge_annual_eur"]) == 2_000.0
    assert solar_p2 == 10.0
    assert geo_p2 == 10.0
    assert float(heat_costs["mix_p2_eur_mwh"]) == 10.0
    assert float(multiyear["p2_annual_eur"]) == 3_000.0


def test_multiyear_pac_electricity_cost_uses_economics_value():
    trajectory = pd.DataFrame(
        [
            {
                "Annee": 1,
                "Solaire HT (MWh)": 0.0,
                "Chaleur PAC BT (MWh)": 40.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 10.0,
                "E utile totale (MWh)": 40.0,
            },
            {
                "Annee": 2,
                "Solaire HT (MWh)": 0.0,
                "Chaleur PAC BT (MWh)": 40.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 10.0,
                "E utile totale (MWh)": 40.0,
            },
        ]
    )
    costs = _multiyear_heat_cost(
        trajectory_df=trajectory,
        heat_costs={"p1_p2_p4": pd.DataFrame(), "capex_summary": pd.DataFrame()},
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=999.0,
            reference_energy_inflation_pct=0.0,
            eta_appoint_eco=1.0,
            analysis_years=2,
            auxiliary_electricity_ratio_pct=0.0,
            electricity_cost_eur_mwh=123.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=0.0,
        ),
        capex_net_eur=0.0,
    )

    assert float(costs["p1_cumulative_eur"]) == 20.0 * 123.0
    assert float(costs["multiyear_heat_cost_eur_mwh"]) == (20.0 * 123.0) / 80.0


def test_solar_recharge_p2_does_not_penalize_solar_ht_cost():
    base_solar_economics = {
        "p1_eur_mwh": 0.0,
        "p2_eur_mwh": 0.0,
        "p4_eur_mwh": 0.0,
        "p2_annual_eur": 3_000.0,
        "capex_eur": 0.0,
        "ademe_aid_eur": 0.0,
        "aid_total_eur": 0.0,
        "net_capex_eur": 0.0,
    }
    no_recharge = compute_heat_costs(
        solar_economics={**base_solar_economics, "annual_solar_total_mwh": 100.0},
        annual_solar_mwh=100.0,
        annual_pac_heat_mwh=200.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=0.0,
        backup_power_kw=0.0,
        reference_heat_mwh=300.0,
        reference_power_kw=0.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=1.0,
        gas_reference_inflation_rate=0.0,
        geothermal_p1_eur_mwh=200.0,
    )
    with_recharge = compute_heat_costs(
        solar_economics={**base_solar_economics, "annual_solar_total_mwh": 300.0},
        annual_solar_mwh=100.0,
        annual_pac_heat_mwh=200.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=0.0,
        backup_power_kw=0.0,
        reference_heat_mwh=300.0,
        reference_power_kw=0.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=1.0,
        gas_reference_inflation_rate=0.0,
        geothermal_p1_eur_mwh=200.0,
    )

    assert float(no_recharge["solar_p2_ht_annual_eur"]) == 3_000.0
    assert float(no_recharge["solar_p2_recharge_annual_eur"]) == 0.0
    assert float(with_recharge["solar_p2_ht_annual_eur"]) == 1_000.0
    assert float(with_recharge["solar_p2_recharge_annual_eur"]) == 2_000.0
    assert float(with_recharge["geo_p2_with_recharge_annual_eur"]) == 2_000.0


def test_four_economic_scenarios_have_simple_expected_multiyear_costs():
    economics = ScenarioEconomicsConfig(
        reference_energy_cost_eur_mwh=90.0,
        reference_energy_inflation_pct=0.0,
        eta_appoint_eco=1.0,
        analysis_years=2,
        auxiliary_electricity_ratio_pct=0.0,
        electricity_cost_eur_mwh=100.0,
        maintenance_cost_eur_m2_year=0.0,
        ademe_eur_mwh_year=0.0,
        other_public_aid_eur=0.0,
        backup_p2_eur_kw_year=0.0,
    )
    heat_costs = {"p1_p2_p4": pd.DataFrame(), "capex_summary": pd.DataFrame()}

    def trajectory(*, solar: float, pac_heat: float, pac_electricity: float, backup: float) -> pd.DataFrame:
        useful = solar + pac_heat + backup
        return pd.DataFrame(
            [
                {
                    "Annee": year,
                    "Solaire HT (MWh)": solar,
                    "Chaleur PAC BT (MWh)": pac_heat,
                    "Appoint gaz total (MWh)": backup,
                    "Electricite PAC (MWh)": pac_electricity,
                    "E utile totale (MWh)": useful,
                }
                for year in [1, 2]
            ]
        )

    costs_by_scenario = {
        "Reference 100 % gaz": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=0.0, pac_heat=0.0, pac_electricity=0.0, backup=100.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
            reference=True,
        ),
        "Geothermie seule": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=0.0, pac_heat=80.0, pac_electricity=20.0, backup=20.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
        ),
        "Geothermie + solaire meme sondes": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=20.0, pac_heat=60.0, pac_electricity=15.0, backup=20.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
        ),
        "Geothermie + solaire sondes reduites": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=20.0, pac_heat=60.0, pac_electricity=14.0, backup=20.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
        ),
    }

    assert set(costs_by_scenario) == {
        "Reference 100 % gaz",
        "Geothermie seule",
        "Geothermie + solaire meme sondes",
        "Geothermie + solaire sondes reduites",
    }
    assert float(costs_by_scenario["Reference 100 % gaz"]["multiyear_heat_cost_eur_mwh"]) == 90.0
    assert float(costs_by_scenario["Geothermie seule"]["multiyear_heat_cost_eur_mwh"]) == 38.0
    assert float(costs_by_scenario["Geothermie + solaire meme sondes"]["multiyear_heat_cost_eur_mwh"]) == 33.0
    assert float(costs_by_scenario["Geothermie + solaire sondes reduites"]["multiyear_heat_cost_eur_mwh"]) == 32.0
    assert float(costs_by_scenario["Geothermie + solaire sondes reduites"]["pac_electricity_cumulative_mwh"]) == 28.0
    assert float(costs_by_scenario["Geothermie + solaire meme sondes"]["backup_gas_cumulative_mwh"]) == 40.0


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


def test_round_display_df_keeps_one_decimal_for_cop_columns():
    df = pd.DataFrame(
        {
            "COP PAC moyen": [5.94],
            "CAPEX net (EUR)": [1234.56],
        }
    )
    rounded = round_display_df(df)

    assert float(rounded["COP PAC moyen"].iloc[0]) == 5.9
    assert int(rounded["CAPEX net (EUR)"].iloc[0]) == 1235


def test_display_dataframe_normalizes_mixed_object_columns():
    df = pd.DataFrame(
        {
            "Progression (%)": [None, 15, 35.0],
            "Message": ["start", 2, None],
            "Economie sondes trouvee": [True, False, True],
            "_private": [object(), object(), object()],
        }
    )

    display_df = display_dataframe(df)

    assert "_private" not in display_df
    assert pd.api.types.is_numeric_dtype(display_df["Progression (%)"])
    assert pd.api.types.is_string_dtype(display_df["Message"])
    assert pd.api.types.is_bool_dtype(display_df["Economie sondes trouvee"])


def test_fixed_ui_assumptions_keep_expected_defaults():
    solar = FixedSolarAssumptions()
    geo = FixedGeoAssumptions()
    economics = FixedEconomicsAssumptions()

    assert "Bretagne" in DEFAULT_EPW_REGIONS
    assert "Pays de la Loire" in DEFAULT_EPW_REGIONS
    assert "Rennes - St Jacques" in DEFAULT_EPW_REGIONS["Bretagne"]
    assert "Nantes Atlantique" in DEFAULT_EPW_REGIONS["Pays de la Loire"]
    assert "Pays de la Loire - Nantes Atlantique" in DEFAULT_EPW_STATIONS
    assert solar.daily_buffer_l_per_m2 == 60.0
    assert solar.daily_buffer_tank_count == 1
    assert solar.daily_buffer_insulation_thickness_cm == 10.0
    assert solar.daily_buffer_insulation_lambda_w_m_k == 0.035
    assert geo.spacing_m == 10.0
    assert geo.carnot_efficiency == 0.54
    assert geo.t_min_c == -3.0
    assert geo.gmi_t_min_c == -3.0
    assert geo.gmi_t_max_c == 40.0
    assert geo.probe_power_ratio_w_m == 40.0
    assert geo.max_extraction_kwh_per_m_year == 60.0
    assert geo.safety_factor == 1.20
    assert geo.reduced_borefield_safety_factor == 1.10
    assert economics.analysis_years == 20
    assert economics.ademe_eur_mwh_year == 63.0


def test_borefield_predesign_uses_prudent_max_of_power_and_annual_extraction():
    predesign = predimension_borefield(
        pac_power_kw=100.0,
        cop=5.0,
        heat_pac_mwh_year=500.0,
        power_ratio_w_per_m=40.0,
        max_extraction_kwh_per_m_year=60.0,
        unit_depth_m=100.0,
        safety_factor=1.20,
    )
    length_power = predesign.ground_power_kw * 1000.0 / 40.0 * 1.20
    length_energy = predesign.ground_heat_mwh_year * 1000.0 / 60.0 * 1.20

    assert predesign.energy_ratio_kwh_per_m_year == 60.0
    assert predesign.required_length_m >= length_power
    assert predesign.required_length_m >= length_energy


def test_hourly_8760_process_profile_maps_generic_ht_and_bt_columns():
    with tempfile.TemporaryDirectory() as tmp:
        workbook = Path(tmp) / "besoin_horaire.xlsx"
        pd.DataFrame(
            {
                "Date heure": pd.date_range("2001-01-01", periods=24, freq="h"),
                "E besoin BT kWh": [2.0] * 24,
                "E besoin HT kWh": [1.0] * 24,
            }
        ).to_excel(workbook, index=False)
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

        override, monthly, profile, info = _hourly_demands_from_process_file(workbook, weather)

        assert info["format"] == "hourly_8760"
        assert override[0] == (1.0, 2.0)
        assert float(profile["demand_ht_kwh"].sum()) == 24.0
        assert float(profile["demand_bt_kwh"].sum()) == 48.0
        assert monthly[0].process_ht_kwh == 24.0
        assert monthly[0].process_bt_kwh == 48.0


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

    reduced_df = _hourly_results_to_dataframe(
        [
            _fake_hourly_result(
                simulation_year=year,
                hour_index=item.hour_index,
                month=item.month,
                day=item.day,
                hour=item.hour,
                demand_ht_kwh=10.0,
                demand_bt_kwh=20.0,
                heat_bt_from_pac_kwh=18.0,
                btes_extracted_by_pac_kwh=13.5,
                electricity_compressor_kwh=4.5,
            )
            for year in range(1, 3)
            for item in weather
        ]
    )

    def fake_borefield_equivalent_savings(**kwargs):
        return {
            "found": True,
            "equivalent_length_m": 500.0,
            "equivalent_boreholes": 5,
            "saved_length_m": 500.0,
            "saved_fraction": 0.5,
            "equivalent_cop": 4.0,
            "equivalent_bt_pac_kwh": 36.0,
            "_equivalent_hourly_df": reduced_df,
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

    assert sorted(calls) == [(0.0, 10), (500.0, 10)]
    assert "_equivalent_hourly_df" not in result.savings
    assert result.economic_borefield_length_m == 500.0


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
    request = HourlyCalculationRequest(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=100.0, bt_kwh=100.0),
        hourly_demand_override=_hourly_override(weather, ht_kwh=100.0, bt_kwh=100.0),
        solar=SolarInputs(
            area_m2=100.0,
            eta0=0.8,
            a1_w_m2_k=3.0,
            a2_w_m2_k2=0.02,
            process_ht_target_c=60.0,
            system_efficiency=0.9,
            daily_buffer_charge_factor_ht=1.0,
            daily_buffer_l_per_m2=60.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            daily_buffer_loss_pct_per_day=2.0,
            solar_preheat_target_ht_c=60.0,
            solar_buffer_hx_approach_k=5.0,
            solar_buffer_collector_approach_k=10.0,
        ),
        btes=BtesInputs(
            boreholes=20,
            depth_m=100.0,
            spacing_m=10.0,
            t_initial_c=12.0,
            t_min_c=5.0,
            t_max_c=40.0,
        ),
        heat_pump=HeatPumpInputs(
            air_target_bt_c=25.0,
            condenser_approach_k=2.0,
            evaporator_approach_k=3.0,
            carnot_efficiency=0.54,
            cop_min=2.0,
            cop_max=8.0,
            pac_power_fraction_pct=100.0,
            peak_bt_power_kw=0.0,
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
        pac_power_fraction_pct=100.0,
        use_probe_predesign=True,
        probe_power_ratio_w_m=60.0,
        probe_energy_ratio_kwh_m=70.0,
        probe_unit_depth_m=100.0,
        calculation_selection=CalculationSelection(),
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
    if not pygfunction_available():
        return
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
    request = HourlyCalculationRequest(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        solar=SolarInputs(
            area_m2=100.0,
            eta0=0.8,
            a1_w_m2_k=3.5,
            a2_w_m2_k2=0.015,
            process_ht_target_c=60.0,
            system_efficiency=0.9,
            daily_buffer_charge_factor_ht=1.0,
            daily_buffer_l_per_m2=50.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            daily_buffer_loss_pct_per_day=2.0,
            solar_preheat_target_ht_c=60.0,
            solar_buffer_hx_approach_k=5.0,
            solar_buffer_collector_approach_k=10.0,
        ),
        btes=BtesInputs(boreholes=8, depth_m=80.0, spacing_m=8.0, t_initial_c=12.0, t_min_c=5.0, t_max_c=40.0),
        heat_pump=HeatPumpInputs(
            air_target_bt_c=25.0,
            condenser_approach_k=2.0,
            evaporator_approach_k=3.0,
            carnot_efficiency=0.54,
            cop_min=2.0,
            cop_max=8.0,
            pac_power_fraction_pct=100.0,
            peak_bt_power_kw=0.0,
        ),
        economics=EconomicsInputs(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=3.0,
            eta_appoint_eco=0.82,
            analysis_years=25,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=200.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        pac_power_fraction_pct=100.0,
        use_probe_predesign=False,
        probe_power_ratio_w_m=40.0,
        probe_energy_ratio_kwh_m=60.0,
        probe_unit_depth_m=100.0,
        calculation_selection=CalculationSelection(
            quick_preview=True,
            run_multiyear=True,
            technical_simulation_years=2,
            run_reduced_borefield=False,
            savings_search_mode="none",
        ),
        pac_parametric=ParametricRange(False, 50.0, 100.0, 50.0),
        solar_parametric=ParametricRange(False, 0.0, 100.0, 100.0),
    )

    result = run_hourly_calculation(request)

    assert result.scenario.simulation_years_total == 2
    assert result.scenario.simulation_year_displayed == 2
    assert not result.scenario.savings["found"]
    assert result.parametric_pac_df.empty
    assert result.parametric_surface_df.empty
    assert not any("previsualisation rapide" in warning for warning in result.warnings)


def test_legacy_dimensioning_profile_is_ignored_by_final_calculation():
    if not pygfunction_available():
        return
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
    request = HourlyCalculationRequest(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=10.0, bt_kwh=20.0),
        hourly_demand_override=_hourly_override(weather, ht_kwh=10.0, bt_kwh=20.0),
        solar=SolarInputs(
            area_m2=100.0,
            eta0=0.8,
            a1_w_m2_k=3.5,
            a2_w_m2_k2=0.015,
            process_ht_target_c=60.0,
            system_efficiency=0.9,
            daily_buffer_charge_factor_ht=1.0,
            daily_buffer_l_per_m2=50.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            daily_buffer_loss_pct_per_day=2.0,
            solar_preheat_target_ht_c=60.0,
            solar_buffer_hx_approach_k=5.0,
            solar_buffer_collector_approach_k=10.0,
        ),
        btes=BtesInputs(boreholes=8, depth_m=80.0, spacing_m=8.0, t_initial_c=12.0, t_min_c=5.0, t_max_c=40.0),
        heat_pump=HeatPumpInputs(
            air_target_bt_c=25.0,
            condenser_approach_k=2.0,
            evaporator_approach_k=3.0,
            carnot_efficiency=0.54,
            cop_min=2.0,
            cop_max=8.0,
            pac_power_fraction_pct=100.0,
            peak_bt_power_kw=0.0,
        ),
        economics=EconomicsInputs(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=3.0,
            eta_appoint_eco=0.82,
            analysis_years=2,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=200.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        pac_power_fraction_pct=100.0,
        use_probe_predesign=False,
        probe_power_ratio_w_m=40.0,
        probe_energy_ratio_kwh_m=60.0,
        probe_unit_depth_m=100.0,
        calculation_selection=CalculationSelection(
            calculation_profile="dimensionnement_25_ans",
            technical_simulation_years=2,
            run_reduced_borefield=False,
            savings_search_mode="none",
        ),
        pac_parametric=ParametricRange(False, 50.0, 100.0, 50.0),
        solar_parametric=ParametricRange(False, 0.0, 100.0, 100.0),
    )

    result = run_hourly_calculation(request)

    assert result.scenario.simulation_years_total == 2
    assert result.scenario.simulation_year_displayed == 2
    assert result.scenario.no_solar_hourly_df.empty is False
    assert not result.scenario.savings["found"]
    assert result.parametric_pac_df.empty
    assert result.parametric_surface_df.empty


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


def test_scenario_inputs_build_configs():
    inputs = ScenarioInputs(
        solar=SolarInputs(
            area_m2=750.0,
            eta0=0.8,
            a1_w_m2_k=3.0,
            a2_w_m2_k2=0.02,
            process_ht_target_c=60.0,
            system_efficiency=0.9,
            daily_buffer_charge_factor_ht=1.0,
            daily_buffer_l_per_m2=50.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            daily_buffer_loss_pct_per_day=2.0,
            solar_preheat_target_ht_c=60.0,
            solar_buffer_hx_approach_k=5.0,
            solar_buffer_collector_approach_k=10.0,
        ),
        btes=BtesInputs(
            boreholes=42,
            depth_m=120.0,
            spacing_m=5.0,
            t_initial_c=12.0,
            t_min_c=5.0,
            t_max_c=40.0,
            backend="pygfunction",
        ),
        heat_pump=HeatPumpInputs(
            air_target_bt_c=25.0,
            condenser_approach_k=2.0,
            evaporator_approach_k=3.0,
            carnot_efficiency=0.54,
            cop_min=2.0,
            cop_max=8.0,
            pac_power_fraction_pct=80.0,
            peak_bt_power_kw=500.0,
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
    )

    config = inputs.to_simulation_config()
    economics = inputs.to_economics_config()

    assert inputs.validate() == []
    assert config.collector.area_m2 == 750.0
    assert config.collector.daily_buffer_delta_t_k == 60.0
    assert config.btes.boreholes == 42
    assert config.btes.backend == "pygfunction"
    assert config.heat_pump.max_thermal_power_kw == 400.0
    assert economics.analysis_years == 20


def _small_economic_scenario():
    if not pygfunction_available():
        return None
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=hour // 24 + 1,
            hour=hour % 24 + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.8 if 8 <= hour % 24 <= 16 else 0.0,
        )
        for hour in range(24 * 5)
    ]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=900.0),
        btes=BtesConfig(boreholes=50, depth_m=100.0, spacing_m=5.0, t_initial_c=12.0, t_min_c=5.0, t_max_c=40.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0, max_thermal_power_kw=120.0),
    )
    hourly_override = _hourly_override(weather, ht_kwh=160.0, bt_kwh=96.0)
    return run_hourly_scenario(
        weather=weather,
        demands=_demand_aggregate(1, weather, ht_kwh=160.0, bt_kwh=96.0),
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


def test_economic_comparison_geo_only_forces_solar_area_to_zero():
    result = _small_economic_scenario()
    if result is None:
        return
    row = result.economic_comparison_df[result.economic_comparison_df["Scenario"] == "Geothermie seule"].iloc[0]

    assert float(row["Surface solaire (m2)"]) == 0.0


def test_same_borefield_scenario_keeps_geo_only_length():
    result = _small_economic_scenario()
    if result is None:
        return
    table = result.economic_comparison_df.set_index("Scenario")

    assert (
        float(table.loc["Geothermie + solaire meme sondes", "Lineaire sondes (ml)"])
        == float(table.loc["Geothermie seule", "Lineaire sondes (ml)"])
    )
    assert float(table.loc["Geothermie + solaire meme sondes", "Lineaire sondes economise (ml)"]) == 0.0


def test_borefield_savings_annualizes_multiyear_candidate_heat():
    if not pygfunction_available():
        return
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
                _fake_hourly_result(
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
                    _fake_hourly_result(
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
        hourly_demand_override=_hourly_override(weather, ht_kwh=0.0, bt_kwh=100.0),
        simulation_years=2,
        search_mode="fast",
        full_case_df=full_case_df,
    )

    assert calls
    assert 10 not in calls
    assert int(savings["savings_simulations_count"]) <= 3
    assert len(dataframe_calls) <= 1


def test_reduced_borefield_has_no_p2_savings_per_meter():
    result = _small_economic_scenario()
    if result is None:
        return

    assert float(result.recharge_value["p2_borefield_savings_eur_an"]) == 0.0


def test_recharge_annual_gain_has_no_borefield_p2_term():
    allocation = solar_energy_allocation(
        solar_ht_mwh=10.0,
        solar_btes_mwh=30.0,
        solar_net_capex_eur=100_000.0,
        solar_p2_annual_eur=4_000.0,
        solar_p4_annual_eur=5_000.0,
    )
    value = solar_recharge_value(
        allocation=allocation,
        saved_borefield_length_m=100.0,
        borefield_unit_cost_eur_m=100.0,
        electricity_savings_mwh=5.0,
        average_electricity_cost_eur_mwh=200.0,
        analysis_years=20,
    )

    expected = 100.0 * 100.0 / 20.0 + 5.0 * 200.0
    assert float(value["annual_recharge_gain_eur_an"]) == expected
    assert float(value["p2_borefield_savings_eur_an"]) == 0.0


def test_recharge_annual_gain_can_use_net_borefield_capex_savings():
    allocation = solar_energy_allocation(
        solar_ht_mwh=10.0,
        solar_btes_mwh=30.0,
        solar_net_capex_eur=100_000.0,
        solar_p2_annual_eur=4_000.0,
        solar_p4_annual_eur=5_000.0,
    )
    value = solar_recharge_value(
        allocation=allocation,
        saved_borefield_length_m=100.0,
        borefield_unit_cost_eur_m=100.0,
        saved_borefield_net_capex_eur=3_500.0,
        electricity_savings_mwh=5.0,
        average_electricity_cost_eur_mwh=200.0,
        analysis_years=20,
    )

    expected = 3_500.0 / 20.0 + 5.0 * 200.0
    assert float(value["saved_borefield_capex_eur"]) == 10_000.0
    assert float(value["saved_borefield_net_capex_eur"]) == 3_500.0
    assert float(value["annual_recharge_gain_eur_an"]) == expected
    assert float(value["p2_borefield_savings_eur_an"]) == 0.0


def test_solar_energy_allocation_prorata_sums_to_one():
    allocation = solar_energy_allocation(
        solar_ht_mwh=25.0,
        solar_btes_mwh=75.0,
        solar_net_capex_eur=100_000.0,
        solar_p2_annual_eur=4_000.0,
        solar_p4_annual_eur=5_000.0,
    )

    assert abs(float(allocation["part_ht"]) + float(allocation["part_recharge"]) - 1.0) <= 1e-12
    assert float(allocation["capex_solar_ht_eur"]) == 25_000.0
    assert float(allocation["capex_solar_recharge_eur"]) == 75_000.0


def test_import_package_minimal():
    import heliostock

    assert heliostock.__all__ == []
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock.streamlit_module import render_heliostock_hourly

    assert callable(render_heliostock_hourly)


def test_heliotools_portal_password_hashing_helpers():
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock import ui_portal

    password_hash = ui_portal._hash_password("motdepasse-solide")
    assert password_hash != "motdepasse-solide"
    assert ui_portal._verify_password("motdepasse-solide", password_hash)
    assert not ui_portal._verify_password("mauvais", password_hash)
    assert ui_portal._safe_project_slug("Projet test / 01") == "Projet_test_01"
    try:
        ui_portal._validate_password("court")
    except ValueError:
        pass
    else:
        raise AssertionError("password length validation should fail")


def test_no_nested_project_folder():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "heliostock_module" / "heliostock_module").exists()


def test_default_technical_years_is_25():
    selection = CalculationSelection()
    assert selection.calculation_profile == "calcul_final"
    assert selection.technical_simulation_years == 25
    assert selection.custom_display_year == 25
    assert selection.savings_search_mode == "fast"
    assert selection.run_reduced_borefield is True


def test_technical_years_not_economic_years():
    import inspect

    app_source = inspect.getsource(run_hourly_calculation)
    scenario_source = inspect.getsource(run_hourly_scenario)
    assert "technical_simulation_years=int(technical_simulation_years)" in app_source
    assert "technical_simulation_years or 25" in scenario_source
    assert "technical_simulation_years or economics.analysis_years" not in scenario_source


def test_found_false_when_no_real_savings():
    result = borefield_savings_module._base_return(
        found=True,
        base_length_m=1000.0,
        boreholes=10,
        equivalent_cop=4.0,
        equivalent_bt_pac_kwh=1000.0,
        final_metrics={"depth_m": 100.0, "final_cop": 4.0},
        estimated_length_m=1000.0,
        simulations_count=0,
    )

    assert result["found"] is False
    assert float(result["saved_length_m"]) == 0.0
    assert float(result["saved_fraction"]) == 0.0
    assert result["message"] == "Aucune réduction de sondes validée"


def test_no_pygfunction_parallel():
    root = Path(__file__).resolve().parent / "heliostock"
    simulation_files = [
        "app_service.py",
        "borefield_savings.py",
        "btes_models.py",
        "hourly_engine.py",
        "scenarios.py",
        "simulation_cache.py",
    ]
    source = "\n".join((root / name).read_text(encoding="utf-8") for name in simulation_files)
    assert "ThreadPoolExecutor" not in source
    assert "ProcessPoolExecutor" not in source


def test_btes_efficiency_indicator():
    assert btes_efficiency_indicator(800.0, 1000.0) == 0.8
    assert btes_efficiency_indicator(800.0, 0.0) is None


def test_sign_change_diagnostics():
    diagnostics = sign_change_diagnostics([10.0, 8.0, -4.0, -3.0, 2.0, 0.0, -1.0])
    assert diagnostics["sign_changes"] == 3
    assert diagnostics["extraction_to_injection_changes"] == 2
    assert diagnostics["injection_to_extraction_changes"] == 1
    assert diagnostics["extraction_sequences"] == 2
    assert diagnostics["injection_sequences"] == 2


def test_geo_field_mode_classification():
    assert classify_geo_field_mode(0.05) == "GSHP_dominant"
    assert classify_geo_field_mode(0.25) == "solar_recharged_borefield"
    assert classify_geo_field_mode(0.75) == "BTES_like"


def test_surface_insulation_warning():
    message = surface_insulation_warning(
        depth_m=30.0,
        spacing_m=5.0,
        injected_kwh=1000.0,
        extracted_kwh=2000.0,
        surface_insulation_considered=False,
    )
    assert "HelioStock ne les modélise pas explicitement" in message
    assert (
        surface_insulation_warning(
            depth_m=30.0,
            spacing_m=5.0,
            injected_kwh=1000.0,
            extracted_kwh=2000.0,
            surface_insulation_considered=True,
        )
        == ""
    )


def test_load_aggregation_mode_default():
    config = BtesConfig()
    assert config.load_aggregation_mode == "pygfunction_default"
    assert config.surface_insulation_considered is False


def test_no_energy_creation_in_btes_metrics():
    df = pd.DataFrame(
        {
            "q_net_W_m": [20.0, -10.0, 0.0],
            "btes_extracted_by_pac_kwh": [20.0, 0.0, 0.0],
            "solar_to_btes_kwh": [0.0, 10.0, 0.0],
        }
    )
    diagnostics = btes_load_diagnostics_from_dataframe(
        df,
        simulation_years=1,
        depth_m=100.0,
        spacing_m=8.0,
        surface_insulation_considered=False,
    )

    assert diagnostics["extracted_ground_kwh"] == 20.0
    assert diagnostics["injected_btes_kwh"] == 10.0
    assert diagnostics["ratio_injection_extraction"] == 0.5
    assert diagnostics["eta_btes"] == 2.0


def test_run_hourly_scenario_builds_btes_diagnostics_without_multiyear_dataframe(monkeypatch):
    weather = [
        HourlyWeather(hour_index=hour, month=1, day=1, hour=hour + 1, tair_c=8.0, g_tilt_kwh_m2=0.0)
        for hour in range(2)
    ]

    def fake_simulate_hourly(weather, demands, config, hourly_demand_override=None, simulation_years=1):
        results = []
        for year in range(1, int(simulation_years) + 1):
            for item in weather:
                results.append(
                    _fake_hourly_result(
                        simulation_year=year,
                        hour_index=item.hour_index,
                        demand_ht_kwh=0.0,
                        demand_bt_kwh=20.0,
                        heat_bt_from_pac_kwh=20.0,
                        btes_extracted_by_pac_kwh=15.0,
                        solar_to_btes_kwh=5.0,
                        electricity_compressor_kwh=5.0,
                        electricity_pac_total_kwh=6.0,
                        q_net_w_m=10.0 if item.hour_index == 0 else -5.0,
                    )
                )
        return results

    monkeypatch.setattr(scenarios_module, "simulate_hourly", fake_simulate_hourly)
    result = scenarios_module.run_hourly_scenario(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=40.0)],
        config=SimulationConfig(
            collector=CollectorConfig(area_m2=100.0),
            btes=BtesConfig(boreholes=10, depth_m=100.0, spacing_m=6.0),
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
        hourly_demand_override=_hourly_override(weather, ht_kwh=0.0, bt_kwh=20.0),
        run_multiyear=True,
        technical_simulation_years=2,
        run_geo_only=False,
        run_reduced_borefield=False,
    )

    assert result.btes_diagnostics["hours_total"] == 4
    assert result.btes_diagnostics["sign_changes"] >= 1
    assert float(result.btes_diagnostics["injected_btes_kwh"]) > 0.0


def test_airtable_token_is_not_project_saveable():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    saveable_block = source.split("SAVEABLE_WIDGET_KEYS = [", 1)[1].split("]", 1)[0]
    assert '"airtable_api_key"' not in saveable_block
    assert '"dashboard_google_api_key"' not in saveable_block
    assert '"airtable_base_id"' in saveable_block
    assert '"airtable_table_id"' in saveable_block


def test_project_result_pickle_is_limited_to_local_sidecar():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    assert "RESULT_SIDECAR_SUFFIX" in source
    assert "def _assert_local_project_path" in source
    assert "_assert_local_project_path(path)" in source
    assert "_assert_local_project_path(path: Path)" in source
    assert "pickle.load(handle)" in source
    assert "resolved.name.endswith(RESULT_SIDECAR_SUFFIX)" in source


def test_admin_creation_is_blocked_when_project_data_already_exists():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    assert "def _has_existing_project_data" in source
    assert "if _has_existing_project_data() or _backup_users_configured():" in source
    assert "création libre d'un nouvel administrateur est bloquée" in source
    assert "HELIOSTOCK_ADMIN_EMAIL" in source
    assert "HELIOSTOCK_ADMIN_PASSWORD" in source
    assert "path.resolve() != users_path" in source


def test_users_are_restored_from_configured_backup_path():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    assert 'DEFAULT_BACKUP_USERS_PATH = "seed_data/users.json"' in source
    assert 'GITHUB_BACKUP_USERS_PATH' in source
    assert 'GITHUB_BACKUP_REPO' in source
    assert 'GITHUB_BACKUP_BRANCH' in source
    assert 'GITHUB_BACKUP_TOKEN' in source
    assert "def _restore_users_from_backup" in source
    assert "_github_read_json_list(_backup_users_path_setting())" in source
    assert "return _restore_users_from_backup()" in source
    assert "_write_users_file(_resolve_backup_users_path(), users)" in source
    assert "_github_write_json_list(" in source


def test_login_events_are_recorded_without_secret_values():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    assert "LOGIN_EVENTS_FILE" in source
    assert 'DEFAULT_BACKUP_LOGIN_EVENTS_PATH = "seed_data/login_events.json"' in source
    assert "def _append_login_event" in source
    assert '"email": _email_normalise(email)' in source
    assert '"success": bool(success)' in source
    assert '"role": str(role or "")' in source
    assert "_github_write_json_list(" in source


def test_solar_dashboard_is_admin_only_and_airtable_inputs_are_hidden():
    portal_source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    dashboard_source = (Path(__file__).resolve().parent / "heliostock" / "solar_thermal_dashboard.py").read_text(encoding="utf-8")

    assert 'app_options = ["HelioStock"]' in portal_source
    assert 'if is_admin_authenticated():' in portal_source
    assert 'app_options.append("Dashboard solaire thermique")' in portal_source
    assert '"Personal Access Token Airtable"' not in dashboard_source
    assert 'st.sidebar.text_input("Base ID"' not in dashboard_source
    assert 'st.sidebar.text_input("Table ID' not in dashboard_source
    assert '_dashboard_secret("AIRTABLE_TOKEN")' in dashboard_source


def test_opportunity_notes_app_is_admin_only_and_callable():
    portal_source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    demo_source = (Path(__file__).resolve().parent / "demo_app.py").read_text(encoding="utf-8")
    app_source = (
        Path(__file__).resolve().parent
        / "heliostock"
        / "opportunity_notes"
        / "streamlit_opportunity_app.py"
    ).read_text(encoding="utf-8")

    assert "Note d'opportunité solaire thermique" in portal_source
    assert "Note d'opportunité solaire thermique" in demo_source
    assert "from heliostock.opportunity_notes import render_opportunity_notes_app" in demo_source
    assert "def render_opportunity_notes_app() -> None:" in app_source
    assert "st.set_page_config" not in app_source
    assert 'PROJECTS_DIR = Path.home() / ".heliotools" / "opportunity_notes" / "projects"' in app_source


def test_projects_are_scoped_to_owner_for_non_admin_users():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_portal.py").read_text(encoding="utf-8")
    assert '"owner_email": _current_user_email()' in source
    assert "def _can_access_project" in source
    assert "if is_admin_authenticated():" in source
    assert "owner_email == _current_user_email()" in source
    assert "and _can_access_project(path)" in source
    assert "def _owned_project_slug" in source
    assert "_owned_project_slug(str(payload['name']))" in source
    assert "Tu n'as pas accès à ce projet." in source


def test_app_gate_accepts_non_admin_authenticated_users():
    source = (Path(__file__).resolve().parent / "demo_app.py").read_text(encoding="utf-8")
    assert "getattr(ui_portal, \"is_user_authenticated\", None)" in source
    assert "if not _is_user_authenticated():" in source
    assert "if not is_admin_authenticated():" not in source


def test_calculation_snapshot_hash_is_stable_and_sensitive():
    base_kwargs = dict(
        weather_region="Bretagne",
        weather_station="Rennes",
        weather_tilt_deg=35.0,
        weather_azimuth_deg_south=0.0,
        weather_albedo=0.2,
        demand_file_name="besoins.xlsx",
        demand_file_hash="abc",
        hourly_profile_df=pd.DataFrame({"hour_index": [0], "demand_ht_kwh": [1.0], "demand_bt_kwh": [2.0]}),
        process_bt_target_c=25.0,
        process_ht_target_c=60.0,
        solar=SolarInputs(
            area_m2=100.0,
            eta0=0.8,
            a1_w_m2_k=3.0,
            a2_w_m2_k2=0.01,
            process_ht_target_c=60.0,
            system_efficiency=0.9,
            daily_buffer_charge_factor_ht=1.0,
            daily_buffer_l_per_m2=60.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            daily_buffer_loss_pct_per_day=0.0,
            solar_preheat_target_ht_c=60.0,
            solar_buffer_hx_approach_k=5.0,
            solar_buffer_collector_approach_k=5.0,
        ),
        btes=BtesInputs(boreholes=10, depth_m=100.0, spacing_m=6.0, t_initial_c=12.0, t_min_c=-3.0, t_max_c=40.0),
        heat_pump=HeatPumpInputs(
            air_target_bt_c=25.0,
            condenser_approach_k=2.0,
            evaporator_approach_k=3.0,
            carnot_efficiency=0.54,
            cop_min=1.0,
            cop_max=8.0,
            pac_power_fraction_pct=100.0,
            peak_bt_power_kw=100.0,
        ),
        economics=EconomicsInputs(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=2.0,
            eta_appoint_eco=0.9,
            analysis_years=25,
            auxiliary_electricity_ratio_pct=3.0,
            electricity_cost_eur_mwh=180.0,
            maintenance_cost_eur_m2_year=1.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        pac_power_fraction_pct=100.0,
        use_probe_predesign=True,
        probe_power_ratio_w_m=40.0,
        probe_energy_ratio_kwh_m=60.0,
        probe_unit_depth_m=100.0,
        calculation_selection=CalculationSelection(technical_simulation_years=25),
        pac_parametric=ParametricRange(False, 0.0, 0.0, 1.0),
        solar_parametric=ParametricRange(False, 0.0, 0.0, 1.0),
    )
    snapshot = build_calculation_snapshot(**base_kwargs)
    assert stable_snapshot_hash(snapshot) == stable_snapshot_hash(build_calculation_snapshot(**base_kwargs))

    changed = dict(base_kwargs)
    changed["weather_station"] = "Brest"
    assert stable_snapshot_hash(snapshot) != stable_snapshot_hash(build_calculation_snapshot(**changed))


def test_dashboard_data_cleaning_helpers_are_testable():
    assert to_float("5 000,5 L") == 5000.5
    assert to_year("mise en service 2024") == 2024
    assert join_values(["A", "B"]) == "A, B"
    grouped = group_small_categories(
        pd.DataFrame({"Categorie": ["A", "B", "C"], "Valeur": [95, 3, 2]}),
        "Categorie",
        "Valeur",
        seuil_pct=4.0,
    )
    assert "Autres" in set(grouped["Categorie"])


def test_ui_results_uses_single_active_section_instead_of_tabs():
    source = (Path(__file__).resolve().parent / "heliostock" / "ui_results.py").read_text(encoding="utf-8")
    assert "st.tabs(" not in source
    assert "st.radio(" in source
