import pandas as pd

from heliostock.app_service import CalculationSelection, ParametricRange
from heliostock.calculation_snapshot import build_calculation_snapshot, stable_snapshot_hash
from heliostock.inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, SolarInputs


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
        demand_scope="ht_bt",
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

    changed_scope = dict(base_kwargs)
    changed_scope["demand_scope"] = "bt_only"
    assert stable_snapshot_hash(snapshot) != stable_snapshot_hash(build_calculation_snapshot(**changed_scope))
