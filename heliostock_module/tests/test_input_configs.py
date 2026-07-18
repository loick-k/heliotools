from heliostock.inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, ScenarioInputs, SolarInputs


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
