from pathlib import Path

from heliostock.inputs import SolarInputs


def test_solar_inputs_do_not_reactivate_legacy_daily_buffer_loss_fraction():
    solar = SolarInputs(
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
        daily_buffer_loss_pct_per_day=25.0,
        solar_preheat_target_ht_c=60.0,
        solar_buffer_hx_approach_k=5.0,
        solar_buffer_collector_approach_k=10.0,
    )

    collector = solar.to_collector_config()

    assert collector.daily_buffer_loss_fraction_per_day == 0.0
    assert collector.daily_buffer_insulation_thickness_cm == 10.0
    assert collector.daily_buffer_insulation_lambda_w_m_k == 0.035


def test_solar_ht_direct_is_only_a_legacy_alias_name():
    source = (Path(__file__).resolve().parents[1] / "heliostock" / "hourly_engine.py").read_text(encoding="utf-8")
    assert "solar_ht_direct_legacy_alias = solar_ht_from_buffer" in source
    assert "solar_ht_direct = solar_ht_from_buffer" not in source
