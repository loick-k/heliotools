"""Solveur dynamique ECS1 : WISC -> PAC -> ballon de préchauffage -> appoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import pandas as pd

from ...models.stratified_tank_3nodes import J_PER_KWH, StratifiedTank3Nodes
from ..hourly_profile import HourlyLoadProfile
from ..manufacturer.schemas import HeatPumpProduct, WISCCollectorProduct
from .source_coupling import SourceCouplingResult, solve_wisc_heat_pump_equilibrium
from .weather import DynamicWeather8760
from .wisc_qdt import WISCQuasiDynamicModel


SensorNode = Literal["bottom", "middle", "top"]


@dataclass(frozen=True)
class ECS1DynamicConfig:
    collector_area_m2: float
    hp_count: int
    tank_volume_l: float
    service_temperature_c: float = 55.0
    cold_water_temperature_c: float = 12.0
    tank_initial_temperature_c: float = 35.0
    tank_preheat_setpoint_c: float = 45.0
    tank_hysteresis_k: float = 3.0
    tank_max_temperature_c: float = 60.0
    tank_ambient_temperature_c: float = 20.0
    tank_ua_w_per_k: float = 4.0
    interlayer_w_per_k: float = 2.0
    control_sensor_node: SensorNode = "middle"
    charge_return_node: SensorNode = "middle"
    preferred_start_hour: int = 0
    preferred_end_hour: int = 24
    min_cop_to_run: float = 0.0
    substeps_per_hour: int = 6
    source_flow_m3h_per_hp: float | None = None
    sink_flow_m3h_per_hp: float | None = None
    source_pump_kw_per_hp: float = 0.0
    sink_pump_kw_per_hp: float = 0.0
    backup_efficiency: float = 1.0
    clamp_sink_below_map: bool = True
    clamp_sink_above_map: bool = False


@dataclass(frozen=True)
class ECS1DynamicSummary:
    demand_mwh: float
    preheat_from_tank_mwh: float
    hp_heat_mwh: float
    hp_electric_mwh: float
    hp_evap_mwh: float
    collector_mwh: float
    collector_solar_mwh: float
    collector_atmospheric_ir_mwh: float
    backup_mwh: float
    source_pump_mwh: float
    sink_pump_mwh: float
    tank_losses_mwh: float
    spf_hp: float
    spf_system: float
    mean_cop_running: float
    hp_runtime_h: float
    service_rate_pct: float
    source_temp_min_c: float | None
    source_temp_mean_c: float | None
    source_temp_max_c: float | None
    hours_source_insufficient: int
    hours_outside_hp_map: int
    hours_sink_outside_hp_map: int
    hours_sink_clamped_low: int
    hours_sink_clamped_high: int
    hours_source_above_hp_map: int
    final_tank_top_c: float
    final_tank_middle_c: float
    final_tank_bottom_c: float


@dataclass(frozen=True)
class ECS1DynamicResult:
    summary: ECS1DynamicSummary
    hourly: pd.DataFrame


def _node_temp(tank: StratifiedTank3Nodes, node: SensorNode) -> float:
    return tank.temperatures_c[{"bottom": 0, "middle": 1, "top": 2}[node]]


def _add_stratified_charge(tank: StratifiedTank3Nodes, energy_j: float) -> float:
    """Charge prioritairement la partie haute, puis milieu, puis bas."""
    remaining = max(0.0, float(energy_j))
    accepted = 0.0
    for node in ("top", "middle", "bottom"):
        if remaining <= 1e-6:
            break
        q = tank.add_energy_to_node(node, remaining)
        accepted += q
        remaining -= q
    tank.enforce_stratification()
    return accepted


def _is_preferred_hour(hour_value: int, start: int, end: int) -> bool:
    # Profils HelioTools peuvent coder 1..24 ou 0..23.
    h = int(hour_value)
    if 1 <= h <= 24:
        h -= 1
    h %= 24
    start %= 24
    end = 24 if end == 24 else end % 24
    if start == 0 and end == 24:
        return True
    if start < end:
        return start <= h < end
    return h >= start or h < end


def simulate_ecs1_dynamic(
    *,
    profile: HourlyLoadProfile,
    weather: DynamicWeather8760,
    heat_pump: HeatPumpProduct,
    collector: WISCCollectorProduct,
    config: ECS1DynamicConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ECS1DynamicResult:
    if profile.hour_count != 8760:
        raise ValueError("ECS1 dynamique V1 requiert un profil 8760 h.")
    weather.validate()
    if not heat_pump.dynamic_available or heat_pump.performance_map is None:
        raise ValueError(f"MISSING_HP_MAP — {heat_pump.manufacturer} {heat_pump.model}")
    if config.service_temperature_c <= config.cold_water_temperature_c:
        raise ValueError("La température de service doit dépasser la température d'eau froide.")
    if config.tank_volume_l <= 0 or config.collector_area_m2 <= 0:
        raise ValueError("Surface capteur et volume de ballon doivent être positifs.")
    if config.hp_count <= 0:
        raise ValueError("Le nombre de PAC doit être positif.")
    source_flow = config.source_flow_m3h_per_hp or heat_pump.source_flow_m3h
    sink_flow = config.sink_flow_m3h_per_hp or heat_pump.sink_flow_m3h
    if source_flow is None or source_flow <= 0:
        raise ValueError("MISSING_SOURCE_FLOW — débit source fabricant requis pour le dynamique.")
    if sink_flow is None or sink_flow <= 0:
        raise ValueError("MISSING_SINK_FLOW — débit chauffage fabricant requis pour le dynamique.")

    tank = StratifiedTank3Nodes(
        volume_m3=config.tank_volume_l / 1000.0,
        t_init_c=config.tank_initial_temperature_c,
        ua_total_w_per_k=config.tank_ua_w_per_k,
        t_amb_c=config.tank_ambient_temperature_c,
        g_interlayer_w_per_k=config.interlayer_w_per_k,
        t_max_c=config.tank_max_temperature_c,
        t_min_useful_c=-20.0,  # ECS1 valorise tout préchauffage au-dessus de Tef.
        dt_internal_s=600.0,
    )
    collector_model = WISCQuasiDynamicModel(collector)
    n_sub = max(1, int(config.substeps_per_hour))
    dt_s = 3600.0 / n_sub
    previous_collector_mean_c: float | None = None
    previous_source_in_c: float | None = None
    hp_on_latch = False

    totals = {
        "demand": 0.0, "preheat": 0.0, "hp_heat": 0.0, "hp_el": 0.0,
        "hp_evap": 0.0, "collector": 0.0, "collector_solar": 0.0,
        "collector_other": 0.0, "backup": 0.0, "source_pump": 0.0, "sink_pump": 0.0,
        "tank_losses": 0.0, "runtime_h": 0.0,
    }
    source_temps: list[float] = []
    cop_weighted = 0.0
    diagnostic_hours = {
        "SOURCE_INSUFFICIENT": set(),
        "OUTSIDE_HP_MAP": set(),
        "SINK_OUTSIDE_HP_MAP": set(),
        "SINK_CLAMPED_LOW": set(),
        "SINK_CLAMPED_HIGH": set(),
        "SOURCE_EQUILIBRIUM_ABOVE_HP_MAP": set(),
    }
    rows: list[dict] = []

    for i in range(8760):
        demand_hour = max(0.0, float(profile.energy_kwh[i]))
        w = weather.hours[i]
        hour_acc = {
            "preheat": 0.0, "backup": 0.0, "hp_heat": 0.0, "hp_el": 0.0,
            "hp_evap": 0.0, "collector": 0.0, "collector_solar": 0.0,
            "collector_other": 0.0, "runtime_h": 0.0, "losses": 0.0,
        }
        t_source_values: list[float] = []
        cop_values: list[tuple[float, float]] = []
        last_reason = "OFF"
        last_sink_in = _node_temp(tank, config.charge_return_node)
        last_sink_lookup = last_sink_in
        last_sink_map_status = "IN_MAP"
        last_sink_out = last_sink_in
        last_source_out = None
        last_collector_mean = previous_collector_mean_c
        for _sub in range(n_sub):
            # 1) Soutirage : le ballon préchauffe le débit sanitaire, l'appoint aval complète.
            q_demand_j = demand_hour / n_sub * J_PER_KWH
            delivered_j, unmet_j = tank.discharge_to_load(
                q_demand_j,
                t_cold_c=config.cold_water_temperature_c,
                t_supply_target_c=config.service_temperature_c,
                dt_s=dt_s,
            )
            hour_acc["preheat"] += delivered_j / J_PER_KWH
            hour_acc["backup"] += unmet_j / J_PER_KWH / max(1e-9, config.backup_efficiency)

            # 2) Régulation de préchauffage ECS1.
            sensor_t = _node_temp(tank, config.control_sensor_node)
            if hp_on_latch:
                if sensor_t >= config.tank_preheat_setpoint_c:
                    hp_on_latch = False
            elif sensor_t <= config.tank_preheat_setpoint_c - config.tank_hysteresis_k:
                hp_on_latch = True
            preferred = _is_preferred_hour(profile.hours[i], config.preferred_start_hour, config.preferred_end_hour)
            should_run = hp_on_latch and preferred

            if should_run:
                sink_in = _node_temp(tank, config.charge_return_node)
                last_sink_in = sink_in
                hp_map = heat_pump.performance_map
                assert hp_map is not None

                # Pour une carte indexée sur T retour (sink_in), on peut
                # verrouiller directement la valeur de lookup avant le
                # couplage. Pour une carte indexée sur T sortie (sink_out),
                # le solveur résout implicitement Tsortie = Tretour + Q/(m.cp)
                # à chaque température source candidate.
                sink_lookup = sink_in
                sink_map_status = "IN_MAP"
                sink_blocked = False
                if hp_map.sink_temperature_convention == "sink_in":
                    sink_lo, sink_hi = hp_map.sink_bounds_C
                    if sink_in < sink_lo - 1e-9:
                        if config.clamp_sink_below_map:
                            sink_lookup = sink_lo
                            sink_map_status = "SINK_CLAMPED_LOW"
                            diagnostic_hours["SINK_CLAMPED_LOW"].add(i)
                        else:
                            sink_blocked = True
                    elif sink_in > sink_hi + 1e-9:
                        if config.clamp_sink_above_map:
                            sink_lookup = sink_hi
                            sink_map_status = "SINK_CLAMPED_HIGH"
                            diagnostic_hours["SINK_CLAMPED_HIGH"].add(i)
                        else:
                            sink_blocked = True

                last_sink_lookup = sink_lookup
                last_sink_map_status = sink_map_status
                if sink_blocked:
                    last_reason = "SINK_OUTSIDE_HP_MAP"
                    diagnostic_hours["SINK_OUTSIDE_HP_MAP"].add(i)
                    previous_collector_mean_c = None
                else:
                    coupling = solve_wisc_heat_pump_equilibrium(
                        weather=w,
                        collector_model=collector_model,
                        collector_area_m2=config.collector_area_m2,
                        heat_pump=heat_pump,
                        hp_count=config.hp_count,
                        sink_in_c=sink_in,
                        sink_map_lookup_c=(sink_lookup if hp_map.sink_temperature_convention == "sink_in" else None),
                        sink_map_status=sink_map_status,
                        clamp_sink_below_map=bool(config.clamp_sink_below_map),
                        clamp_sink_above_map=bool(config.clamp_sink_above_map),
                        source_flow_m3h_per_hp=float(source_flow),
                        sink_flow_m3h_per_hp=float(sink_flow),
                        previous_collector_mean_c=previous_collector_mean_c,
                        previous_source_in_c=previous_source_in_c,
                        dt_s=dt_s,
                    )
                    last_reason = coupling.reason
                    if coupling.valid:
                        last_sink_lookup = coupling.sink_map_lookup_c
                        last_sink_map_status = coupling.sink_map_status
                        last_sink_out = coupling.sink_out_c
                        if coupling.sink_map_status in diagnostic_hours:
                            diagnostic_hours[coupling.sink_map_status].add(i)
                    if coupling.valid and coupling.cop >= config.min_cop_to_run:
                        # Charge maximale sur le sous-pas, limitée par l'énergie acceptée par le ballon.
                        q_possible_j = coupling.p_heat_kw * 1000.0 * dt_s
                        accepted_j = _add_stratified_charge(tank, q_possible_j)
                        runtime_fraction = accepted_j / q_possible_j if q_possible_j > 1e-9 else 0.0
                        runtime_fraction = max(0.0, min(1.0, runtime_fraction))
                        runtime_h = runtime_fraction * dt_s / 3600.0
                        hour_acc["runtime_h"] += runtime_h
                        hour_acc["hp_heat"] += coupling.p_heat_kw * runtime_h
                        hour_acc["hp_el"] += coupling.p_el_kw * runtime_h
                        hour_acc["hp_evap"] += coupling.p_evap_kw * runtime_h
                        hour_acc["collector"] += coupling.p_collector_kw * runtime_h
                        hour_acc["collector_solar"] += coupling.q_solar_kw * runtime_h
                        hour_acc["collector_other"] += coupling.q_atmospheric_and_ir_kw * runtime_h
                        if config.source_pump_kw_per_hp > 0:
                            hour_acc.setdefault("source_pump", 0.0)
                            hour_acc["source_pump"] += config.source_pump_kw_per_hp * config.hp_count * runtime_h
                        if config.sink_pump_kw_per_hp > 0:
                            hour_acc.setdefault("sink_pump", 0.0)
                            hour_acc["sink_pump"] += config.sink_pump_kw_per_hp * config.hp_count * runtime_h
                        if runtime_fraction > 1e-9:
                            previous_collector_mean_c = coupling.t_collector_mean_c
                            previous_source_in_c = coupling.t_source_in_c
                            last_collector_mean = coupling.t_collector_mean_c
                            last_source_out = coupling.t_source_out_c
                            last_sink_out = coupling.sink_out_c
                            t_source_values.append(coupling.t_source_in_c)
                            cop_values.append((coupling.cop, runtime_h))
                    elif coupling.valid:
                        last_reason = "COP_BELOW_MINIMUM"
                    else:
                        if coupling.reason in diagnostic_hours:
                            diagnostic_hours[coupling.reason].add(i)
                        previous_collector_mean_c = None
                        previous_source_in_c = None
            else:
                # Le capteur n'est pas suivi thermiquement à l'arrêt dans cette V1 ;
                # on réinitialise le terme capacitif au prochain démarrage plutôt
                # que de réutiliser une température moyenne vieille de plusieurs heures.
                previous_collector_mean_c = None
                previous_source_in_c = None

            # 3) Échanges passifs du ballon pendant le sous-pas.
            tank.apply_interlayer_exchange(dt_s)
            loss_j = tank.apply_losses(dt_s, t_amb_c=config.tank_ambient_temperature_c)
            tank.enforce_stratification()
            hour_acc["losses"] += loss_j / J_PER_KWH

        state = tank.state()
        totals["demand"] += demand_hour
        for key in ("preheat", "backup", "hp_heat", "hp_el", "hp_evap", "collector", "collector_solar", "collector_other", "runtime_h", "losses"):
            totals["tank_losses" if key == "losses" else key] += hour_acc[key]
        source_pump_hour = hour_acc.get("source_pump", 0.0)
        sink_pump_hour = hour_acc.get("sink_pump", 0.0)
        totals["source_pump"] += source_pump_hour
        totals["sink_pump"] += sink_pump_hour
        if cop_values:
            for cop, runtime in cop_values:
                cop_weighted += cop * runtime
        source_temps.extend(t_source_values)
        rows.append({
            "hour_index": i,
            "month": profile.months[i],
            "day": profile.days[i],
            "hour": profile.hours[i],
            "T_amb_C": w.t_amb_c,
            "wind_ms": w.wind_ms,
            "RH_pct": w.rh_pct,
            "G_POA_Wm2": w.g_poa_wm2,
            "E_demand_kWh": demand_hour,
            "E_preheat_from_tank_kWh": hour_acc["preheat"],
            "E_backup_kWh": hour_acc["backup"],
            "HP_runtime_h": hour_acc["runtime_h"],
            "E_HP_heat_kWh": hour_acc["hp_heat"],
            "E_HP_el_kWh": hour_acc["hp_el"],
            "E_HP_evap_kWh": hour_acc["hp_evap"],
            "E_collector_kWh": hour_acc["collector"],
            "E_collector_solar_kWh": hour_acc["collector_solar"],
            "E_collector_atmospheric_IR_kWh": hour_acc["collector_other"],
            "E_source_pump_kWh": source_pump_hour,
            "E_sink_pump_kWh": sink_pump_hour,
            "COP_hour": (hour_acc["hp_heat"] / hour_acc["hp_el"]) if hour_acc["hp_el"] > 1e-9 else None,
            "T_source_in_C": (sum(t_source_values) / len(t_source_values)) if t_source_values else None,
            "T_source_out_C": last_source_out,
            "T_collector_mean_C": last_collector_mean,
            "T_sink_in_C": last_sink_in,
            "T_sink_lookup_C": last_sink_lookup,
            "sink_map_status": last_sink_map_status,
            "T_sink_out_C": last_sink_out,
            "T_tank_top_C": state.t_top_c,
            "T_tank_middle_C": state.t_middle_c,
            "T_tank_bottom_C": state.t_bottom_c,
            "tank_losses_kWh": hour_acc["losses"],
            "dynamic_status": last_reason,
        })
        if progress_callback is not None and ((i + 1) % 168 == 0 or i == 8759):
            progress_callback(i + 1, 8760)

    hp_el = totals["hp_el"]
    runtime = totals["runtime_h"]
    useful = totals["demand"]
    total_electric = hp_el + totals["source_pump"] + totals["sink_pump"] + totals["backup"]
    service_rate = 100.0 if useful <= 1e-9 else 100.0 * min(1.0, (totals["preheat"] + totals["backup"] * config.backup_efficiency) / useful)
    state = tank.state()
    summary = ECS1DynamicSummary(
        demand_mwh=totals["demand"] / 1000.0,
        preheat_from_tank_mwh=totals["preheat"] / 1000.0,
        hp_heat_mwh=totals["hp_heat"] / 1000.0,
        hp_electric_mwh=hp_el / 1000.0,
        hp_evap_mwh=totals["hp_evap"] / 1000.0,
        collector_mwh=totals["collector"] / 1000.0,
        collector_solar_mwh=totals["collector_solar"] / 1000.0,
        collector_atmospheric_ir_mwh=totals["collector_other"] / 1000.0,
        backup_mwh=totals["backup"] / 1000.0,
        source_pump_mwh=totals["source_pump"] / 1000.0,
        sink_pump_mwh=totals["sink_pump"] / 1000.0,
        tank_losses_mwh=totals["tank_losses"] / 1000.0,
        spf_hp=(totals["hp_heat"] / hp_el) if hp_el > 1e-9 else 0.0,
        spf_system=(useful / total_electric) if total_electric > 1e-9 else 0.0,
        mean_cop_running=(cop_weighted / runtime) if runtime > 1e-9 else 0.0,
        hp_runtime_h=runtime,
        service_rate_pct=service_rate,
        source_temp_min_c=min(source_temps) if source_temps else None,
        source_temp_mean_c=(sum(source_temps) / len(source_temps)) if source_temps else None,
        source_temp_max_c=max(source_temps) if source_temps else None,
        hours_source_insufficient=len(diagnostic_hours["SOURCE_INSUFFICIENT"]),
        hours_outside_hp_map=len(diagnostic_hours["OUTSIDE_HP_MAP"]),
        hours_sink_outside_hp_map=len(diagnostic_hours["SINK_OUTSIDE_HP_MAP"]),
        hours_sink_clamped_low=len(diagnostic_hours["SINK_CLAMPED_LOW"]),
        hours_sink_clamped_high=len(diagnostic_hours["SINK_CLAMPED_HIGH"]),
        hours_source_above_hp_map=len(diagnostic_hours["SOURCE_EQUILIBRIUM_ABOVE_HP_MAP"]),
        final_tank_top_c=state.t_top_c,
        final_tank_middle_c=state.t_middle_c,
        final_tank_bottom_c=state.t_bottom_c,
    )
    return ECS1DynamicResult(summary=summary, hourly=pd.DataFrame(rows))
