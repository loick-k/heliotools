from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, SimulationConfig
from heliostock.hourly_engine import HourlyWeather
from heliostock.scenarios import ScenarioEconomicsConfig, run_hourly_scenario

from helpers import demand_aggregate, hourly_override, skip_if_no_pygfunction


def _small_economic_scenario():
    skip_if_no_pygfunction()
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
    hourly_demand_override = hourly_override(weather, ht_kwh=160.0, bt_kwh=96.0)
    return run_hourly_scenario(
        weather=weather,
        demands=demand_aggregate(1, weather, ht_kwh=160.0, bt_kwh=96.0),
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
        hourly_demand_override=hourly_demand_override,
    )


def test_economic_comparison_geo_only_forces_solar_area_to_zero():
    result = _small_economic_scenario()
    row = result.economic_comparison_df[result.economic_comparison_df["Scenario"] == "Geothermie seule"].iloc[0]

    assert float(row["Surface solaire (m2)"]) == 0.0


def test_same_borefield_scenario_keeps_geo_only_length():
    result = _small_economic_scenario()
    table = result.economic_comparison_df.set_index("Scenario")

    assert (
        float(table.loc["Geothermie + solaire meme sondes", "Lineaire sondes (ml)"])
        == float(table.loc["Geothermie seule", "Lineaire sondes (ml)"])
    )
    assert float(table.loc["Geothermie + solaire meme sondes", "Lineaire sondes economise (ml)"]) == 0.0


def test_reduced_borefield_has_no_p2_savings_per_meter():
    result = _small_economic_scenario()

    assert float(result.recharge_value["p2_borefield_savings_eur_an"]) == 0.0
