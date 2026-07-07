from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonthlyDemand:
    """Monthly process heat demands, already calculated upstream.

    Physical preheating logic expected upstream:
    Q_air = m_dot * Cp_air * max(0, T_target - T_air_ext)

    The Streamlit interface now requires an imported 8760 h profile. Monthly
    values remain only as an internal aggregate format shared by legacy helpers.
    """

    month: int
    process_ht_kwh: float
    process_bt_kwh: float


@dataclass(frozen=True)
class CollectorConfig:
    """Solar thermal collector and hydraulic assumptions."""

    area_m2: float = 1000.0
    eta0: float = 0.75
    a1_w_m2_k: float = 3.5
    a2_w_m2_k2: float = 0.015
    system_efficiency: float = 0.90
    daily_buffer_charge_factor_ht: float = 1.0
    btes_injection_margin_k: float = 5.0
    min_collector_temp_storage_c: float = 25.0
    max_collector_temp_storage_c: float = 45.0
    daily_buffer_l_per_m2: float = 50.0
    daily_buffer_delta_t_k: float = 30.0
    daily_buffer_ambient_temp_c: float = 20.0
    solar_preheat_target_ht_c: float = 60.0
    solar_buffer_hx_approach_k: float = 5.0
    solar_buffer_collector_approach_k: float = 10.0
    daily_buffer_min_temp_c: float = 20.0
    daily_buffer_max_temp_c: float = 80.0
    daily_buffer_loss_fraction_per_day: float = 0.02
    daily_buffer_tank_count: int = 1
    daily_buffer_insulation_thickness_cm: float = 10.0
    daily_buffer_insulation_lambda_w_m_k: float = 0.035


@dataclass(frozen=True)
class BtesConfig:
    """Expert borefield assumptions for the pygfunction backend."""

    boreholes: int = 100
    depth_m: float = 100.0
    spacing_m: float = 5.0
    t_initial_c: float = 12.0
    t_min_c: float = 5.0
    t_max_c: float = 40.0
    gmi_t_min_c: float = -3.0
    gmi_t_max_c: float = 40.0
    gmi_check_enabled: bool = True
    injection_efficiency: float = 0.90
    backend: str = "pygfunction"
    ground_conductivity_w_m_k: float = 2.5
    ground_diffusivity_m2_s: float = 1.0e-6
    borehole_radius_m: float = 0.075
    borehole_buried_depth_m: float = 4.0
    borehole_thermal_resistance_m_k_w: float = 0.10
    max_extraction_w_m: float = 40.0
    max_injection_w_m: float = 40.0
    load_aggregation_mode: str = "pygfunction_default"
    surface_insulation_considered: bool = False


@dataclass(frozen=True)
class HeatPumpConfig:
    """Heat pump COP law based on degraded Carnot COP."""

    air_target_bt_c: float = 25.0
    condenser_approach_k: float = 2.0
    evaporator_approach_k: float = 3.0
    carnot_efficiency: float = 0.54
    cop_min: float = 2.0
    cop_max: float = 8.0
    max_thermal_power_kw: float | None = None
    aux_pac_ratio: float = 0.15
    standby_power_kw: float = 0.05


@dataclass(frozen=True)
class SimulationConfig:
    collector: CollectorConfig
    btes: BtesConfig
    heat_pump: HeatPumpConfig
    process_ht_target_c: float = 60.0
    process_bt_target_c: float = 25.0


def collector_efficiency(
    *,
    eta0: float,
    a1_w_m2_k: float,
    a2_w_m2_k2: float,
    t_mean_collector_c: float,
    t_air_c: float,
    reference_irradiance_w_m2: float,
) -> float:
    """Steady collector efficiency, EN12975-style.

    eta = eta0 - a1*(T_mean - T_air)/G - a2*(T_mean - T_air)^2/G
    """

    g = max(0.0, reference_irradiance_w_m2)
    if g <= 0.0:
        return 0.0
    dt = max(0.0, t_mean_collector_c - t_air_c)
    eta = eta0 - a1_w_m2_k * dt / g - a2_w_m2_k2 * dt * dt / g
    return max(0.0, min(eta, eta0))


def cop_from_source_temperature(t_source_pac_c: float, hp: HeatPumpConfig) -> float:
    """COP law for the low-temperature air preheating process.

    COP = eta_PAC * T_cond,K / (T_cond,K - T_evap,K)
    with T_cond ~= T_target_BT + condenser approach and
    T_evap ~= T_source_PAC - evaporator approach.
    """

    t_cond_k = hp.air_target_bt_c + hp.condenser_approach_k + 273.15
    t_evap_k = t_source_pac_c - hp.evaporator_approach_k + 273.15
    if t_evap_k <= 0:
        return hp.cop_min
    if t_evap_k >= t_cond_k:
        return hp.cop_max
    cop_carnot = t_cond_k / max(1e-6, t_cond_k - t_evap_k)
    cop = hp.carnot_efficiency * cop_carnot
    return max(hp.cop_min, min(hp.cop_max, cop))

