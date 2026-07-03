from dataclasses import replace

from heliostock.engine import CollectorConfig
from heliostock.hourly_engine import (
    WATER_BUFFER_KWH_PER_L_K,
    _hourly_buffer_loss,
    _solo2018_cr_stock_wh_l_k_day,
    _solo2018_tank_surface_m2,
)


def _collector(**overrides) -> CollectorConfig:
    return replace(
        CollectorConfig(
            area_m2=100.0,
            daily_buffer_l_per_m2=10.0,
            daily_buffer_ambient_temp_c=20.0,
            daily_buffer_max_temp_c=80.0,
            daily_buffer_tank_count=1,
            daily_buffer_insulation_thickness_cm=10.0,
            daily_buffer_insulation_lambda_w_m_k=0.035,
        ),
        **overrides,
    )


def test_solo2018_tank_surface_order_of_magnitude() -> None:
    surface_m2 = _solo2018_tank_surface_m2(1.0)

    assert surface_m2 > 0.0
    assert 4.0 <= surface_m2 <= 8.0


def test_solo2018_cr_stock_uses_litres_not_cubic_metres() -> None:
    cr_stock = _solo2018_cr_stock_wh_l_k_day(_collector())

    assert cr_stock > 0.0
    assert 0.02 <= cr_stock <= 0.10


def test_hourly_buffer_loss_with_solo2018_cr() -> None:
    collector = _collector()
    volume_l = collector.area_m2 * collector.daily_buffer_l_per_m2
    buffer_energy_kwh = volume_l * WATER_BUFFER_KWH_PER_L_K * 40.0

    loss_kwh = _hourly_buffer_loss(buffer_energy_kwh, collector)

    assert loss_kwh > 0.0
    assert loss_kwh < buffer_energy_kwh


def test_hourly_buffer_loss_safety_cases() -> None:
    collector = _collector()

    assert _hourly_buffer_loss(0.0, collector) == 0.0
    assert _hourly_buffer_loss(10.0, _collector(area_m2=0.0)) == 0.0
    assert _solo2018_cr_stock_wh_l_k_day(_collector(daily_buffer_insulation_lambda_w_m_k=0.0)) == 0.0
    assert _hourly_buffer_loss(10.0, _collector(daily_buffer_insulation_lambda_w_m_k=0.0)) == 0.0
    assert _solo2018_cr_stock_wh_l_k_day(_collector(daily_buffer_insulation_thickness_cm=0.0)) == 0.0
    assert _hourly_buffer_loss(10.0, _collector(daily_buffer_insulation_thickness_cm=0.0)) == 0.0


def test_solo2018_losses_follow_physical_trends() -> None:
    base = _collector()
    volume_l = base.area_m2 * base.daily_buffer_l_per_m2
    base_energy_kwh = volume_l * WATER_BUFFER_KWH_PER_L_K * 40.0

    colder_energy_kwh = volume_l * WATER_BUFFER_KWH_PER_L_K * 20.0
    assert _hourly_buffer_loss(base_energy_kwh, base) > _hourly_buffer_loss(colder_energy_kwh, base)

    larger_volume = _collector(area_m2=200.0)
    larger_volume_l = larger_volume.area_m2 * larger_volume.daily_buffer_l_per_m2
    larger_energy_kwh = larger_volume_l * WATER_BUFFER_KWH_PER_L_K * 40.0
    assert _hourly_buffer_loss(larger_energy_kwh, larger_volume) > _hourly_buffer_loss(base_energy_kwh, base)

    more_tanks = _collector(daily_buffer_tank_count=2)
    assert _hourly_buffer_loss(base_energy_kwh, more_tanks) > _hourly_buffer_loss(base_energy_kwh, base)

    higher_lambda = _collector(daily_buffer_insulation_lambda_w_m_k=0.070)
    assert _hourly_buffer_loss(base_energy_kwh, higher_lambda) > _hourly_buffer_loss(base_energy_kwh, base)

    thicker_insulation = _collector(daily_buffer_insulation_thickness_cm=20.0)
    assert _hourly_buffer_loss(base_energy_kwh, thicker_insulation) < _hourly_buffer_loss(base_energy_kwh, base)

    larger_unit = _collector(area_m2=200.0)
    assert _solo2018_cr_stock_wh_l_k_day(larger_unit) < _solo2018_cr_stock_wh_l_k_day(base)
