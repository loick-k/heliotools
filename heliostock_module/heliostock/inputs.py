from __future__ import annotations

from dataclasses import dataclass

from .engine import BtesConfig, CollectorConfig, HeatPumpConfig, SimulationConfig
from .scenarios import ScenarioEconomicsConfig


@dataclass(frozen=True)
class SolarInputs:
    area_m2: float
    eta0: float
    a1_w_m2_k: float
    a2_w_m2_k2: float
    process_ht_target_c: float
    system_efficiency: float
    daily_buffer_charge_factor_ht: float
    daily_buffer_l_per_m2: float
    daily_buffer_ambient_temp_c: float
    daily_buffer_max_temp_c: float
    daily_buffer_loss_pct_per_day: float
    solar_preheat_target_ht_c: float
    solar_buffer_hx_approach_k: float
    solar_buffer_collector_approach_k: float

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if self.area_m2 <= 0.0:
            warnings.append("La surface solaire doit etre strictement positive.")
        if not 0.0 <= self.eta0 <= 1.0:
            warnings.append("eta0 doit etre compris entre 0 et 1.")
        if not 0.0 <= self.system_efficiency <= 1.0:
            warnings.append("Le rendement hydraulique global doit etre compris entre 0 et 1.")
        if self.daily_buffer_max_temp_c <= self.daily_buffer_ambient_temp_c:
            warnings.append("Tmax ballon doit etre superieure a la temperature ambiante du ballon.")
        return warnings

    def to_collector_config(self) -> CollectorConfig:
        return CollectorConfig(
            area_m2=self.area_m2,
            eta0=self.eta0,
            a1_w_m2_k=self.a1_w_m2_k,
            a2_w_m2_k2=self.a2_w_m2_k2,
            system_efficiency=self.system_efficiency,
            daily_buffer_charge_factor_ht=self.daily_buffer_charge_factor_ht,
            daily_buffer_l_per_m2=self.daily_buffer_l_per_m2,
            daily_buffer_ambient_temp_c=self.daily_buffer_ambient_temp_c,
            solar_preheat_target_ht_c=self.solar_preheat_target_ht_c,
            solar_buffer_hx_approach_k=self.solar_buffer_hx_approach_k,
            solar_buffer_collector_approach_k=self.solar_buffer_collector_approach_k,
            daily_buffer_min_temp_c=self.daily_buffer_ambient_temp_c,
            daily_buffer_max_temp_c=self.daily_buffer_max_temp_c,
            daily_buffer_delta_t_k=max(0.0, self.daily_buffer_max_temp_c - self.daily_buffer_ambient_temp_c),
            daily_buffer_loss_fraction_per_day=self.daily_buffer_loss_pct_per_day / 100.0,
        )


@dataclass(frozen=True)
class BtesInputs:
    boreholes: int
    depth_m: float
    spacing_m: float
    t_initial_c: float
    t_min_c: float
    t_max_c: float
    gmi_t_min_c: float = -3.0
    gmi_t_max_c: float = 40.0
    gmi_check_enabled: bool = True
    ground_conductivity_w_m_k: float = 2.5
    ground_diffusivity_m2_s: float = 1.0e-6
    borehole_radius_m: float = 0.075
    borehole_buried_depth_m: float = 4.0
    borehole_thermal_resistance_m_k_w: float = 0.10
    max_extraction_w_m: float = 40.0
    max_injection_w_m: float = 40.0
    backend: str = "pygfunction"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if self.boreholes <= 0:
            warnings.append("Le nombre de sondes doit etre strictement positif.")
        if self.depth_m <= 0.0:
            warnings.append("La profondeur des sondes doit etre strictement positive.")
        if self.spacing_m <= 0.0:
            warnings.append("L'espacement moyen des sondes doit etre strictement positif.")
        if self.t_max_c <= self.t_min_c:
            warnings.append("Tmax injection doit etre superieure a la Tmin source PAC operationnelle.")
        if not self.t_min_c <= self.t_initial_c <= self.t_max_c:
            warnings.append("Tsol initiale devrait etre comprise entre Tmin et Tmax champ.")
        return warnings

    def to_btes_config(self) -> BtesConfig:
        return BtesConfig(
            boreholes=int(self.boreholes),
            depth_m=self.depth_m,
            spacing_m=self.spacing_m,
            t_initial_c=self.t_initial_c,
            t_min_c=self.t_min_c,
            t_max_c=self.t_max_c,
            gmi_t_min_c=self.gmi_t_min_c,
            gmi_t_max_c=self.gmi_t_max_c,
            gmi_check_enabled=self.gmi_check_enabled,
            backend=self.backend,
            ground_conductivity_w_m_k=self.ground_conductivity_w_m_k,
            ground_diffusivity_m2_s=self.ground_diffusivity_m2_s,
            borehole_radius_m=self.borehole_radius_m,
            borehole_buried_depth_m=self.borehole_buried_depth_m,
            borehole_thermal_resistance_m_k_w=self.borehole_thermal_resistance_m_k_w,
            max_extraction_w_m=self.max_extraction_w_m,
            max_injection_w_m=self.max_injection_w_m,
        )


@dataclass(frozen=True)
class HeatPumpInputs:
    air_target_bt_c: float
    condenser_approach_k: float
    evaporator_approach_k: float
    carnot_efficiency: float
    cop_min: float
    cop_max: float
    pac_power_fraction_pct: float
    peak_bt_power_kw: float
    aux_pac_ratio: float = 0.15
    standby_power_kw: float = 0.05

    @property
    def pac_nominal_power_kw(self) -> float:
        return max(0.0, self.peak_bt_power_kw) * max(0.0, self.pac_power_fraction_pct) / 100.0

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if self.cop_max < self.cop_min:
            warnings.append("COP max doit etre superieur ou egal au COP min.")
        if not 0.0 < self.carnot_efficiency <= 1.0:
            warnings.append("Le rendement Carnot PAC devrait etre compris entre 0 et 1.")
        if self.pac_power_fraction_pct <= 0.0:
            warnings.append("La puissance PAC retenue doit etre strictement positive.")
        return warnings

    def to_heat_pump_config(self) -> HeatPumpConfig:
        return HeatPumpConfig(
            air_target_bt_c=self.air_target_bt_c,
            condenser_approach_k=self.condenser_approach_k,
            evaporator_approach_k=self.evaporator_approach_k,
            carnot_efficiency=self.carnot_efficiency,
            cop_min=self.cop_min,
            cop_max=self.cop_max,
            max_thermal_power_kw=self.pac_nominal_power_kw,
            aux_pac_ratio=self.aux_pac_ratio,
            standby_power_kw=self.standby_power_kw,
        )


@dataclass(frozen=True)
class EconomicsInputs:
    reference_energy_cost_eur_mwh: float
    reference_energy_inflation_pct: float
    eta_appoint_eco: float
    analysis_years: int
    auxiliary_electricity_ratio_pct: float
    electricity_cost_eur_mwh: float
    maintenance_cost_eur_m2_year: float
    ademe_eur_mwh_year: float
    other_public_aid_eur: float
    backup_p2_eur_kw_year: float

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if self.analysis_years <= 0:
            warnings.append("La duree d'analyse economique doit etre strictement positive.")
        if self.eta_appoint_eco <= 0.0:
            warnings.append("Le rendement d'appoint gaz doit etre strictement positif.")
        return warnings

    def to_scenario_economics_config(self) -> ScenarioEconomicsConfig:
        return ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=self.reference_energy_cost_eur_mwh,
            reference_energy_inflation_pct=self.reference_energy_inflation_pct,
            eta_appoint_eco=self.eta_appoint_eco,
            analysis_years=int(self.analysis_years),
            auxiliary_electricity_ratio_pct=self.auxiliary_electricity_ratio_pct,
            electricity_cost_eur_mwh=self.electricity_cost_eur_mwh,
            maintenance_cost_eur_m2_year=self.maintenance_cost_eur_m2_year,
            ademe_eur_mwh_year=self.ademe_eur_mwh_year,
            other_public_aid_eur=self.other_public_aid_eur,
            backup_p2_eur_kw_year=self.backup_p2_eur_kw_year,
        )


@dataclass(frozen=True)
class ScenarioInputs:
    solar: SolarInputs
    btes: BtesInputs
    heat_pump: HeatPumpInputs
    economics: EconomicsInputs

    @property
    def pac_nominal_power_kw(self) -> float:
        return self.heat_pump.pac_nominal_power_kw

    def validate(self) -> list[str]:
        return [
            *self.solar.validate(),
            *self.btes.validate(),
            *self.heat_pump.validate(),
            *self.economics.validate(),
        ]

    def to_simulation_config(self) -> SimulationConfig:
        return SimulationConfig(
            collector=self.solar.to_collector_config(),
            btes=self.btes.to_btes_config(),
            heat_pump=self.heat_pump.to_heat_pump_config(),
            process_ht_target_c=self.solar.process_ht_target_c,
            process_bt_target_c=self.heat_pump.air_target_bt_c,
        )

    def to_economics_config(self) -> ScenarioEconomicsConfig:
        return self.economics.to_scenario_economics_config()
