from __future__ import annotations

import calendar
from dataclasses import dataclass

from .btes_models import create_btes_model
from .engine import (
    BtesConfig,
    CollectorConfig,
    HeatPumpConfig,
    MonthlyDemand,
    SimulationConfig,
    collector_efficiency,
    cop_from_btes_temperature,
)

WATER_BUFFER_KWH_PER_L_K = 1.163e-3


@dataclass(frozen=True)
class HourlyWeather:
    hour_index: int
    month: int
    day: int
    hour: int
    tair_c: float
    g_tilt_kwh_m2: float


@dataclass(frozen=True)
class HourlyResult:
    simulation_year: int
    hour_index: int
    month: int
    day: int
    hour: int
    tair_c: float
    demand_ht_kwh: float
    demand_bt_kwh: float
    solar_ht_potential_kwh: float
    solar_ht_instant_kwh: float
    solar_ht_from_buffer_kwh: float
    solar_ht_to_buffer_kwh: float
    solar_ht_buffer_loss_kwh: float
    solar_ht_buffer_energy_end_kwh: float
    solar_ht_buffer_temp_start_c: float
    solar_ht_buffer_temp_end_c: float
    collector_temp_ht_c: float
    collector_temp_storage_c: float
    solar_ht_direct_kwh: float
    solar_storage_potential_kwh: float
    solar_to_btes_kwh: float
    solar_not_used_kwh: float
    btes_temp_start_c: float
    btes_temp_after_charge_c: float
    btes_temp_after_pac_c: float
    btes_temp_end_c: float
    btes_energy_start_kwh: float
    btes_energy_end_kwh: float
    btes_loss_to_ground_kwh: float
    btes_natural_recharge_kwh: float
    cop_pac: float
    heat_bt_from_pac_kwh: float
    btes_extracted_by_pac_kwh: float
    electricity_compressor_kwh: float
    electricity_pac_auxiliaries_kwh: float
    electricity_standby_kwh: float
    electricity_pac_total_kwh: float
    electricity_system_total_kwh: float
    electricity_pac_kwh: float
    unmet_ht_kwh: float
    unmet_bt_kwh: float
    collector_eff_ht: float
    collector_eff_storage: float


def expand_monthly_demands_to_hourly(
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
) -> dict[int, tuple[float, float]]:
    """Spread monthly kWh demands uniformly over EPW hours in each month.

    This keeps V1 usable with the current monthly input table. A later version
    can replace this with imported 8760 h industrial load profiles.
    """

    month_hour_count = {month: 0 for month in range(1, 13)}
    for hour in weather:
        month_hour_count[hour.month] = month_hour_count.get(hour.month, 0) + 1

    demands_by_month = {d.month: d for d in demands}
    hourly: dict[int, tuple[float, float]] = {}
    for month in range(1, 13):
        d = demands_by_month.get(month, MonthlyDemand(month=month, process_ht_kwh=0.0, process_bt_kwh=0.0))
        count = max(1, month_hour_count.get(month, 0))
        hourly[month] = (max(0.0, d.process_ht_kwh) / count, max(0.0, d.process_bt_kwh) / count)
    return hourly


def _daily_buffer_capacity_kwh(collector: CollectorConfig) -> float:
    """Thermal energy stored above ambient in the daily solar tank.

    E_buffer = m_water * Cp_water * (T_tank - T_ambient)
    E_buffer_max = m_water * Cp_water * (T_tank_max - T_ambient)
    """

    volume_l = max(0.0, collector.area_m2) * max(0.0, collector.daily_buffer_l_per_m2)
    delta_t = max(
        0.0,
        collector.daily_buffer_max_temp_c - collector.daily_buffer_ambient_temp_c,
    )
    if delta_t <= 0:
        delta_t = max(0.0, collector.daily_buffer_delta_t_k)
    return volume_l * WATER_BUFFER_KWH_PER_L_K * delta_t


def _daily_buffer_heat_capacity_kwh_k(collector: CollectorConfig) -> float:
    volume_l = max(0.0, collector.area_m2) * max(0.0, collector.daily_buffer_l_per_m2)
    return volume_l * WATER_BUFFER_KWH_PER_L_K


def _daily_buffer_temperature_c(buffer_energy_kwh: float, collector: CollectorConfig) -> float:
    heat_capacity = _daily_buffer_heat_capacity_kwh_k(collector)
    if heat_capacity <= 1e-9:
        return collector.daily_buffer_ambient_temp_c
    return collector.daily_buffer_ambient_temp_c + max(0.0, buffer_energy_kwh) / heat_capacity


def _hourly_buffer_loss(buffer_energy_kwh: float, collector: CollectorConfig) -> float:
    daily_loss = max(0.0, min(1.0, collector.daily_buffer_loss_fraction_per_day))
    hourly_fraction = 1.0 - (1.0 - daily_loss) ** (1.0 / 24.0)
    return buffer_energy_kwh * hourly_fraction


def _solar_yield_hour_kwh(
    weather: HourlyWeather,
    collector: CollectorConfig,
    t_mean_collector_c: float,
) -> tuple[float, float]:
    # EPW gives irradiation over the hour in kWh/m2. For a one-hour timestep,
    # kWh/m2 is numerically equal to average kW/m2. Multiplying by 1000 gives
    # the average irradiance G in W/m2 used by the EN12975 efficiency law.
    reference_irradiance = max(0.0, weather.g_tilt_kwh_m2 * 1000.0)
    if reference_irradiance <= 0.0 or weather.g_tilt_kwh_m2 <= 0.0:
        return 0.0, 0.0
    eta = collector_efficiency(
        eta0=collector.eta0,
        a1_w_m2_k=collector.a1_w_m2_k,
        a2_w_m2_k2=collector.a2_w_m2_k2,
        t_mean_collector_c=t_mean_collector_c,
        t_air_c=weather.tair_c,
        reference_irradiance_w_m2=reference_irradiance,
    )
    q = (
        weather.g_tilt_kwh_m2
        * max(0.0, collector.area_m2)
        * eta
        * max(0.0, min(1.0, collector.system_efficiency))
    )
    return max(0.0, q), eta


def simulate_hourly(
    weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    config: SimulationConfig,
    initial_btes_energy_kwh: float = 0.0,
    hourly_demand_override: dict[int, tuple[float, float]] | None = None,
    simulation_years: int = 1,
) -> list[HourlyResult]:
    """Run simplified hourly solar + BTES + heat pump dispatch."""

    hourly_demands = expand_monthly_demands_to_hourly(weather, demands)
    btes = config.btes
    collector = config.collector
    hp = config.heat_pump
    years = max(1, int(simulation_years))
    btes_model = create_btes_model(
        btes,
        initial_energy_kwh=initial_btes_energy_kwh,
        simulation_hours=len(weather) * years,
    )
    buffer_capacity = _daily_buffer_capacity_kwh(collector)
    buffer_energy = 0.0
    results: list[HourlyResult] = []

    total_hours = len(weather) * years
    for absolute_position in range(total_hours):
        w = weather[absolute_position % len(weather)]
        year_index = absolute_position // len(weather) + 1
        absolute_hour_index = absolute_position
        if hourly_demand_override is not None:
            demand_ht, demand_bt = hourly_demand_override.get(w.hour_index, (0.0, 0.0))
        else:
            demand_ht, demand_bt = hourly_demands.get(w.month, (0.0, 0.0))
        state_start = btes_model.state()
        temp_start = state_start.temp_c
        energy_start = state_start.energy_kwh
        buffer_temp_start = _daily_buffer_temperature_c(buffer_energy, collector)

        collector_temp_ht = max(
            collector.daily_buffer_ambient_temp_c + collector.solar_buffer_collector_approach_k,
            buffer_temp_start + collector.solar_buffer_collector_approach_k,
        )
        solar_ht_potential, eta_ht = _solar_yield_hour_kwh(w, collector, collector_temp_ht)
        buffer_capacity_remaining = max(0.0, buffer_capacity - buffer_energy)
        ht_surplus_to_buffer_available = (
            solar_ht_potential
            * max(0.0, min(1.0, collector.daily_buffer_charge_factor_ht))
        )
        solar_ht_to_buffer = min(ht_surplus_to_buffer_available, buffer_capacity_remaining)
        buffer_energy += solar_ht_to_buffer
        buffer_loss = min(buffer_energy, _hourly_buffer_loss(buffer_energy, collector))
        buffer_energy -= buffer_loss

        buffer_temp_after_charge = _daily_buffer_temperature_c(buffer_energy, collector)
        solar_preheat_out_c = min(
            config.process_ht_target_c,
            collector.solar_preheat_target_ht_c,
            max(w.tair_c, buffer_temp_after_charge - collector.solar_buffer_hx_approach_k),
        )
        full_ht_lift_k = max(0.0, config.process_ht_target_c - w.tair_c)
        solar_preheat_lift_k = max(0.0, solar_preheat_out_c - w.tair_c)
        solar_preheat_fraction = (
            min(1.0, solar_preheat_lift_k / full_ht_lift_k)
            if full_ht_lift_k > 1e-9
            else 0.0
        )
        solar_ht_eligible_from_buffer = demand_ht * solar_preheat_fraction
        solar_ht_from_buffer = min(solar_ht_eligible_from_buffer, buffer_energy)
        buffer_energy -= solar_ht_from_buffer
        solar_ht_instant = 0.0
        solar_ht_direct = solar_ht_from_buffer

        buffer_was_saturated_by_solar = (
            solar_ht_potential > 0.0
            and buffer_capacity_remaining <= ht_surplus_to_buffer_available + 1e-9
        )
        if solar_ht_potential > 0.0 and buffer_was_saturated_by_solar:
            resource_used_fraction = min(1.0, solar_ht_to_buffer / solar_ht_potential)
        elif solar_ht_potential > 0.0:
            # The BTES is not allowed to receive solar heat until the daily
            # solar tank has reached its Tmax charging limit. Any resource not
            # charged because of charge_factor is therefore not redirected to
            # the BTES in this simplified dispatch.
            resource_used_fraction = 1.0
        else:
            resource_used_fraction = 0.0
        remaining_resource_fraction = max(0.0, 1.0 - resource_used_fraction)

        t_storage_collector = min(
            collector.max_collector_temp_storage_c,
            max(collector.min_collector_temp_storage_c, temp_start + collector.btes_injection_margin_k),
        )
        solar_storage_gross, eta_storage = _solar_yield_hour_kwh(w, collector, t_storage_collector)
        solar_storage_potential = solar_storage_gross * remaining_resource_fraction

        solar_to_btes = min(
            solar_storage_potential * max(0.0, min(1.0, btes.injection_efficiency)),
            btes_model.capacity_remaining_kwh(),
        )
        solar_to_btes = btes_model.add_heat(solar_to_btes)
        solar_not_used = max(0.0, solar_storage_potential - solar_to_btes)
        temp_after_charge = btes_model.temperature_c()

        cop = cop_from_btes_temperature(temp_after_charge, hp)
        if demand_bt > 0 and cop > 1.0:
            field_fraction = 1.0 - 1.0 / cop
            field_available = btes_model.field_available_kwh()
            pac_power_limit = demand_bt
            if hp.max_thermal_power_kw is not None and hp.max_thermal_power_kw > 0.0:
                pac_power_limit = min(pac_power_limit, hp.max_thermal_power_kw)
            heat_bt_from_pac = min(pac_power_limit, field_available / max(1e-9, field_fraction))
            electricity_compressor = heat_bt_from_pac / cop
            btes_extracted = heat_bt_from_pac - electricity_compressor
        else:
            heat_bt_from_pac = 0.0
            electricity_compressor = 0.0
            btes_extracted = 0.0

        # Conservative pre-design allowance for PAC/geothermal pumps and
        # controls. Solar and BTES injection pumps are intentionally excluded.
        electricity_pac_auxiliaries = electricity_compressor * max(0.0, hp.aux_pac_ratio)
        electricity_standby = max(0.0, hp.standby_power_kw)
        electricity_pac_total = electricity_compressor + electricity_pac_auxiliaries + electricity_standby
        electricity_system_total = electricity_pac_total

        btes_extracted = btes_model.extract_heat(btes_extracted)
        temp_after_pac = btes_model.temperature_c()

        btes_loss_to_ground, btes_natural_recharge = btes_model.relax_to_ground()
        final_state = btes_model.state()
        temp_end = final_state.temp_c

        results.append(
            HourlyResult(
                simulation_year=year_index,
                hour_index=absolute_hour_index,
                month=w.month,
                day=w.day,
                hour=w.hour,
                tair_c=w.tair_c,
                demand_ht_kwh=demand_ht,
                demand_bt_kwh=demand_bt,
                solar_ht_potential_kwh=solar_ht_potential,
                solar_ht_instant_kwh=solar_ht_instant,
                solar_ht_from_buffer_kwh=solar_ht_from_buffer,
                solar_ht_to_buffer_kwh=solar_ht_to_buffer,
                solar_ht_buffer_loss_kwh=buffer_loss,
                solar_ht_buffer_energy_end_kwh=buffer_energy,
                solar_ht_buffer_temp_start_c=buffer_temp_start,
                solar_ht_buffer_temp_end_c=_daily_buffer_temperature_c(buffer_energy, collector),
                collector_temp_ht_c=collector_temp_ht,
                collector_temp_storage_c=t_storage_collector,
                solar_ht_direct_kwh=solar_ht_direct,
                solar_storage_potential_kwh=solar_storage_potential,
                solar_to_btes_kwh=solar_to_btes,
                solar_not_used_kwh=solar_not_used,
                btes_temp_start_c=temp_start,
                btes_temp_after_charge_c=temp_after_charge,
                btes_temp_after_pac_c=temp_after_pac,
                btes_temp_end_c=temp_end,
                btes_energy_start_kwh=energy_start,
                btes_energy_end_kwh=final_state.energy_kwh,
                btes_loss_to_ground_kwh=btes_loss_to_ground,
                btes_natural_recharge_kwh=btes_natural_recharge,
                cop_pac=cop,
                heat_bt_from_pac_kwh=heat_bt_from_pac,
                btes_extracted_by_pac_kwh=btes_extracted,
                electricity_compressor_kwh=electricity_compressor,
                electricity_pac_auxiliaries_kwh=electricity_pac_auxiliaries,
                electricity_standby_kwh=electricity_standby,
                electricity_pac_total_kwh=electricity_pac_total,
                electricity_system_total_kwh=electricity_system_total,
                electricity_pac_kwh=electricity_compressor,
                unmet_ht_kwh=max(0.0, demand_ht - solar_ht_direct),
                unmet_bt_kwh=max(0.0, demand_bt - heat_bt_from_pac),
                collector_eff_ht=eta_ht,
                collector_eff_storage=eta_storage,
            )
        )

    return results


def aggregate_hourly_results_monthly(results: list[HourlyResult]) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for month in range(1, 13):
        month_results = [r for r in results if r.month == month]
        if not month_results:
            continue
        rows.append(
            {
                "month": month,
                "Mois": calendar.month_abbr[month],
                "Mois graphique": f"{month:02d} {calendar.month_abbr[month]}",
                "Heures": len(month_results),
                "Besoin HT (kWh)": sum(r.demand_ht_kwh for r in month_results),
                "Besoin BT (kWh)": sum(r.demand_bt_kwh for r in month_results),
                "Potentiel solaire HT (kWh)": sum(r.solar_ht_potential_kwh for r in month_results),
                "Solaire HT instantane (kWh)": sum(r.solar_ht_instant_kwh for r in month_results),
                "Solaire HT via ballon (kWh)": sum(r.solar_ht_from_buffer_kwh for r in month_results),
                "Solaire HT charge ballon (kWh)": sum(r.solar_ht_to_buffer_kwh for r in month_results),
                "Pertes ballon HT (kWh)": sum(r.solar_ht_buffer_loss_kwh for r in month_results),
                "Stock ballon HT fin (kWh)": month_results[-1].solar_ht_buffer_energy_end_kwh,
                "T stockage solaire debut (C)": month_results[0].solar_ht_buffer_temp_start_c,
                "T stockage solaire fin (C)": month_results[-1].solar_ht_buffer_temp_end_c,
                "T stockage solaire moyenne (C)": sum(r.solar_ht_buffer_temp_end_c for r in month_results) / len(month_results),
                "T capteur HT moyenne (C)": sum(r.collector_temp_ht_c for r in month_results) / len(month_results),
                "T capteur stockage moyenne (C)": sum(r.collector_temp_storage_c for r in month_results) / len(month_results),
                "Prechauffage HT solaire (kWh)": sum(r.solar_ht_direct_kwh for r in month_results),
                "Potentiel solaire stockage (kWh)": sum(r.solar_storage_potential_kwh for r in month_results),
                "Solaire injecte BTES (kWh)": sum(r.solar_to_btes_kwh for r in month_results),
                "Solaire non valorise (kWh)": sum(r.solar_not_used_kwh for r in month_results),
                "Chaleur extraite champ PAC (kWh)": sum(r.btes_extracted_by_pac_kwh for r in month_results),
                "BT couvert PAC (kWh)": sum(r.heat_bt_from_pac_kwh for r in month_results),
                "Electricite compresseur PAC (kWh)": sum(r.electricity_compressor_kwh for r in month_results),
                "Forfait pompes + auxiliaires PAC (kWh)": sum(r.electricity_pac_auxiliaries_kwh for r in month_results),
                "Veille/regulation PAC (kWh)": sum(r.electricity_standby_kwh for r in month_results),
                "Electricite totale PAC (kWh)": sum(r.electricity_pac_total_kwh for r in month_results),
                "Electricite totale systeme (kWh)": sum(r.electricity_system_total_kwh for r in month_results),
                "Appoint HT (kWh)": sum(r.unmet_ht_kwh for r in month_results),
                "Appoint BT (kWh)": sum(r.unmet_bt_kwh for r in month_results),
                "Pertes champ vers sol (kWh)": sum(r.btes_loss_to_ground_kwh for r in month_results),
                "Recharge naturelle depuis sol (kWh)": sum(r.btes_natural_recharge_kwh for r in month_results),
                "T champ debut (C)": month_results[0].btes_temp_start_c,
                "T champ fin (C)": month_results[-1].btes_temp_end_c,
                "COP machine": (
                    sum(r.heat_bt_from_pac_kwh for r in month_results)
                    / max(1e-9, sum(r.electricity_compressor_kwh for r in month_results))
                ),
                "SPF PAC complet": (
                    sum(r.heat_bt_from_pac_kwh for r in month_results)
                    / max(1e-9, sum(r.electricity_pac_total_kwh for r in month_results))
                ),
                "Taux couverture solaire HT (%)": (
                    sum(r.solar_ht_direct_kwh for r in month_results)
                    / max(1e-9, sum(r.demand_ht_kwh for r in month_results))
                    * 100.0
                ),
            }
        )
    return rows
