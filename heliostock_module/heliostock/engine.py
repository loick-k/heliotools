from __future__ import annotations

from dataclasses import dataclass


KWH_PER_J = 1.0 / 3.6e6


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


@dataclass(frozen=True)
class BtesConfig:
    """Simplified equivalent-volume BTES model.

    The model represents the borefield as an equivalent ground volume:
    volume = boreholes * spacing^2 * depth * volume_factor

    The stock energy is expressed relative to undisturbed ground temperature.
    It can be negative down to t_min_c, representing a cooled borefield.
    """

    boreholes: int = 100
    depth_m: float = 100.0
    spacing_m: float = 5.0
    volume_factor: float = 1.0
    volumetric_heat_capacity_j_m3_k: float = 2.4e6
    t_initial_c: float = 12.0
    t_min_c: float = 5.0
    t_max_c: float = 40.0
    monthly_relaxation_tau_months: float = 24.0
    injection_efficiency: float = 0.90
    backend: str = "pygfunction"
    ground_conductivity_w_m_k: float = 2.5
    ground_diffusivity_m2_s: float = 1.0e-6
    borehole_radius_m: float = 0.075
    borehole_buried_depth_m: float = 4.0
    borehole_thermal_resistance_m_k_w: float = 0.10

    @property
    def equivalent_volume_m3(self) -> float:
        return max(
            1.0,
            self.boreholes
            * self.depth_m
            * self.spacing_m
            * self.spacing_m
            * self.volume_factor,
        )

    @property
    def heat_capacity_kwh_k(self) -> float:
        return self.equivalent_volume_m3 * self.volumetric_heat_capacity_j_m3_k * KWH_PER_J

    @property
    def max_energy_kwh(self) -> float:
        return self.heat_capacity_kwh_k * (self.t_max_c - self.t_initial_c)

    @property
    def min_energy_kwh(self) -> float:
        return self.heat_capacity_kwh_k * (self.t_min_c - self.t_initial_c)


@dataclass(frozen=True)
class HeatPumpConfig:
    """Heat pump COP law based on degraded Carnot COP."""

    air_target_bt_c: float = 25.0
    condenser_approach_k: float = 7.0
    evaporator_approach_k: float = 3.0
    carnot_efficiency: float = 0.45
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


def cop_from_btes_temperature(t_btes_c: float, hp: HeatPumpConfig) -> float:
    """COP law for the low-temperature air preheating process.

    COP = eta_PAC * T_cond,K / (T_cond,K - T_evap,K)
    with T_cond ~= T_target_BT + condenser approach and
    T_evap ~= T_btes - evaporator approach.
    """

    t_cond_k = hp.air_target_bt_c + hp.condenser_approach_k + 273.15
    t_evap_k = t_btes_c - hp.evaporator_approach_k + 273.15
    if t_evap_k <= 0:
        return hp.cop_min
    if t_evap_k >= t_cond_k:
        return hp.cop_max
    cop_carnot = t_cond_k / max(1e-6, t_cond_k - t_evap_k)
    cop = hp.carnot_efficiency * cop_carnot
    return max(hp.cop_min, min(hp.cop_max, cop))


def btes_temperature_from_energy(energy_kwh: float, btes: BtesConfig) -> float:
    return btes.t_initial_c + energy_kwh / max(1e-9, btes.heat_capacity_kwh_k)


def clamp_btes_energy(energy_kwh: float, btes: BtesConfig) -> float:
    return max(btes.min_energy_kwh, min(btes.max_energy_kwh, energy_kwh))


def default_industrial_demands_1gwh() -> list[MonthlyDemand]:
    """Default monthly test case demands, in kWh/month.

    The left column of the source case is mapped to HT preheating to 60 C,
    and the right column is mapped to BT preheating to 25 C.
    """

    ht = [39261, 38922, 40944, 36916, 26051, 30145, 26062, 7407, 33897, 38709, 33124, 34773]
    bt = [145565, 141910, 135911, 106353, 58639, 47197, 30948, 10409, 59871, 97891, 107148, 124946]
    return [
        MonthlyDemand(month=m, process_ht_kwh=ht[m - 1], process_bt_kwh=bt[m - 1])
        for m in range(1, 13)
    ]
