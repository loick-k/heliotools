import pytest

from heliostock.btes_models import pygfunction_available
from heliostock.engine import MonthlyDemand
from heliostock.hourly_engine import HourlyResult, HourlyWeather


def hourly_override(weather: list[HourlyWeather], *, ht_kwh: float, bt_kwh: float) -> dict[int, tuple[float, float]]:
    return {hour.hour_index: (ht_kwh, bt_kwh) for hour in weather}


def demand_aggregate(month: int, weather: list[HourlyWeather], *, ht_kwh: float, bt_kwh: float) -> list[MonthlyDemand]:
    return [
        MonthlyDemand(
            month=month,
            process_ht_kwh=ht_kwh * len(weather),
            process_bt_kwh=bt_kwh * len(weather),
        )
    ]


def skip_if_no_pygfunction() -> None:
    if not pygfunction_available():
        pytest.skip("pygfunction non disponible dans cet environnement")


def fake_hourly_result(**overrides) -> HourlyResult:
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


def return_or_sink_results(results, result_sink=None, store_results=True):
    if result_sink is not None:
        for row in results:
            result_sink(row)
    return results if store_results else []
