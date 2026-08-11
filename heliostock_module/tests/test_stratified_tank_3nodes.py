import inspect

import pytest

from heliostock.hourly_engine import simulate_hourly
from heliostock.models.stratified_tank_3nodes import J_PER_KWH, StratifiedTank3Nodes


def test_energy_conservation_without_losses():
    tank = StratifiedTank3Nodes(
        volume_m3=1.0,
        t_init_c=20.0,
        ua_total_w_per_k=0.0,
        t_amb_c=20.0,
        g_interlayer_w_per_k=0.0,
        t_min_useful_c=20.0,
    )
    initial = tank.stored_energy_j(20.0)
    result = tank.step(
        q_solar_j=10.0 * J_PER_KWH,
        q_load_j=4.0 * J_PER_KWH,
        dt_s=3600.0,
        t_cold_c=20.0,
        t_supply_target_c=60.0,
        reference_temp_c=20.0,
    )
    final = tank.stored_energy_j(20.0)
    assert result["losses_j"] == pytest.approx(0.0)
    assert initial + result["solar_to_tank_j"] - result["load_from_tank_j"] - final == pytest.approx(
        0.0,
        abs=1e-6,
    )


def test_losses_cool_nodes_toward_ambient():
    tank = StratifiedTank3Nodes(volume_m3=1.0, t_init_c=60.0, ua_total_w_per_k=10.0, t_amb_c=20.0)
    before = tank.state()
    losses = tank.apply_losses(3600.0, 20.0)
    after = tank.state()
    assert losses > 0.0
    assert after.t_top_c < before.t_top_c
    assert after.t_middle_c < before.t_middle_c
    assert after.t_bottom_c < before.t_bottom_c


def test_stratification_mixes_inverted_layers():
    tank = StratifiedTank3Nodes(volume_m3=1.0, t_init_c=20.0, ua_total_w_per_k=0.0, t_amb_c=20.0)
    tank.temperatures_c = [70.0, 50.0, 40.0]
    before = tank.stored_energy_j(0.0)
    tank.enforce_stratification()
    after = tank.stored_energy_j(0.0)
    state = tank.state()
    assert state.t_top_c + 1e-9 >= state.t_middle_c >= state.t_bottom_c - 1e-9
    assert after == pytest.approx(before)


def test_interlayer_exchange_is_capped_at_equalization():
    tank = StratifiedTank3Nodes(
        volume_m3=0.03,
        t_init_c=20.0,
        ua_total_w_per_k=0.0,
        t_amb_c=20.0,
        fractions_volume=(1 / 3, 1 / 3, 1 / 3),
        g_interlayer_w_per_k=10_000.0,
    )
    tank.temperatures_c = [20.0, 80.0, 80.0]
    before = tank.stored_energy_j(0.0)
    tank.apply_interlayer_exchange(3600.0)
    after = tank.stored_energy_j(0.0)

    assert after == pytest.approx(before)
    assert tank.temperatures_c[0] <= tank.temperatures_c[1] + 1e-9


def test_solar_charge_uses_variable_inlet_node():
    tank = StratifiedTank3Nodes(
        volume_m3=1.0,
        t_init_c=30.0,
        ua_total_w_per_k=0.0,
        t_amb_c=20.0,
        g_interlayer_w_per_k=0.0,
        mode_charge_solaire="variable_inlet",
    )
    tank.temperatures_c = [25.0, 40.0, 55.0]
    tank.charge_from_solar(1.0 * J_PER_KWH, t_inlet_c=45.0)
    assert tank.state().t_middle_c > 40.0


def test_draw_off_pushes_cold_water_into_bottom():
    tank = StratifiedTank3Nodes(
        volume_m3=1.0,
        t_init_c=20.0,
        ua_total_w_per_k=0.0,
        t_amb_c=20.0,
        g_interlayer_w_per_k=0.0,
        t_min_useful_c=20.0,
    )
    tank.temperatures_c = [35.0, 50.0, 65.0]
    before = tank.stored_energy_j(0.0)
    delivered, unmet = tank.discharge_to_load(
        q_load_j=3.0 * J_PER_KWH,
        t_cold_c=20.0,
        t_supply_target_c=60.0,
        dt_s=300.0,
    )
    after = tank.stored_energy_j(0.0)
    state = tank.state()

    assert delivered > 0.0
    assert unmet == pytest.approx(0.0)
    assert state.t_bottom_c < 35.0
    assert before - after == pytest.approx(delivered)


def test_hourly_engine_collector_coupling_uses_bottom_temperature():
    source = inspect.getsource(simulate_hourly)
    assert "tank_state_start.t_bottom_c + collector.solar_buffer_collector_approach_k" in source
    assert "_solar_yield_with_collector_mean_temperature" in source
