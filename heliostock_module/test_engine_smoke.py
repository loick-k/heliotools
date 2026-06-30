from dataclasses import replace
from pathlib import Path
import tempfile

import pandas as pd

from heliostock.engine import (
    BtesConfig,
    CollectorConfig,
    HeatPumpConfig,
    MonthlyDemand,
    SimulationConfig,
)
from heliostock.btes_models import PygfunctionBtesModel, create_btes_model, pygfunction_available
from heliostock.app_service import CalculationSelection, HourlyCalculationRequest, ParametricRange, run_hourly_calculation
from heliostock.economics import (
    compute_heat_costs,
    compute_solar_thermal_economics,
    solar_capex_eur,
    solar_energy_allocation,
    solar_recharge_value,
)
from heliostock.hourly_engine import HourlyWeather, aggregate_hourly_results_monthly, simulate_hourly
from heliostock.geothermal_design import predimension_borefield
from heliostock.inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, ScenarioInputs, SolarInputs
from heliostock.load_profiles import _hourly_demands_from_process_file
from heliostock.postprocess import _hourly_results_to_dataframe, _multiyear_btes_summary
from heliostock.scenarios import (
    ScenarioEconomicsConfig,
    _multiyear_heat_cost,
    borefield_equivalent_savings,
    pac_power_parametric_study,
    run_hourly_scenario,
)
from heliostock.ui_formatting import round_display_df
from heliostock.ui_inputs import (
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
    assert sum(result.solar_ht_direct_kwh for result in results) > 0
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


def test_multiyear_simulation_keeps_btes_thermal_memory():
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
        btes=BtesConfig(boreholes=10, depth_m=100.0, spacing_m=10.0),
        heat_pump=HeatPumpConfig(air_target_bt_c=25.0, max_thermal_power_kw=80.0),
    )
    results = simulate_hourly(
        weather=weather,
        demands=[MonthlyDemand(month=1, process_ht_kwh=7_000.0, process_bt_kwh=14_000.0)],
        config=config,
        hourly_demand_override=_hourly_override(weather, ht_kwh=42.0, bt_kwh=84.0),
        simulation_years=3,
    )
    df = _hourly_results_to_dataframe(results)
    summary = _multiyear_btes_summary(df, t_min_c=config.btes.t_min_c)

    assert len(results) == len(weather) * 3
    assert sorted(df["simulation_year"].unique().tolist()) == [1, 2, 3]
    assert len(summary) == 3
    assert summary["T source PAC fin (C)"].iloc[-1] < summary["T source PAC fin (C)"].iloc[0]


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
        assert abs(result.demand_ht_kwh - result.solar_ht_direct_kwh - result.unmet_ht_kwh) <= 1e-6
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
    assert sum(result.solar_ht_direct_kwh for result in results) == 0.0
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


def test_fixed_ui_assumptions_keep_expected_defaults():
    solar = FixedSolarAssumptions()
    geo = FixedGeoAssumptions()
    economics = FixedEconomicsAssumptions()

    assert list(DEFAULT_EPW_STATIONS.keys())[0] == "Nantes"
    assert solar.daily_buffer_l_per_m2 == 60.0
    assert geo.spacing_m == 10.0
    assert geo.carnot_efficiency == 0.54
    assert geo.max_extraction_kwh_per_m_year == 70.0
    assert economics.analysis_years == 20
    assert economics.ademe_eur_mwh_year == 63.0


def test_borefield_predesign_uses_prudent_max_of_power_and_annual_extraction():
    predesign = predimension_borefield(
        pac_power_kw=100.0,
        cop=5.0,
        heat_pac_mwh_year=500.0,
        power_ratio_w_per_m=60.0,
        max_extraction_kwh_per_m_year=70.0,
        unit_depth_m=100.0,
    )
    length_power = predesign.ground_power_kw * 1000.0 / 60.0
    length_energy = predesign.ground_heat_mwh_year * 1000.0 / 70.0

    assert predesign.energy_ratio_kwh_per_m_year == 70.0
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
    assert len(result.multiyear_btes_df) == len(result.no_solar_multiyear_btes_df)
    assert not result.no_solar_multiyear_btes_df.empty
    assert not result.annual_df.empty
    assert not result.hourly_by_month_df.empty
    assert result.total_ht_kwh > 0.0
    assert result.total_bt_kwh > 0.0
    assert result.solar_direct_ht_economic_mwh == result.total_preheat_ht_kwh / 1000.0
    assert "combined_heat_cost_eur_mwh" in result.heat_costs
    assert "annual_solar_direct_ht_mwh" in result.solar_economics


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
    assert any("Mix ENR" in column for column in df.columns)


def test_scenario_inputs_build_configs():
    inputs = ScenarioInputs(
        solar=SolarInputs(
            area_m2=750.0,
            eta0=0.8,
            a1_w_m2_k=3.0,
            a2_w_m2_k2=0.02,
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
        reference_cop=0.0,
        reference_bt_pac_kwh=0.0,
        hourly_demand_override={0: (0.0, 80.0)},
        simulation_years=3,
        iterations=0,
    )

    assert bool(savings["found"])
    assert abs(float(savings["equivalent_bt_pac_kwh"]) - 80.0) <= 1e-6


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
