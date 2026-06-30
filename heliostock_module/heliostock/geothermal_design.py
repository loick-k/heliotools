from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BorefieldPreDesign:
    pac_power_kw: float
    cop: float
    heat_pac_mwh_year: float
    ground_power_kw: float
    ground_heat_mwh_year: float
    power_ratio_w_per_m: float
    energy_ratio_kwh_per_m_year: float
    required_length_m: float
    unit_depth_m: float
    boreholes: int
    effective_length_m: float
    safety_factor: float


def predimension_borefield(
    *,
    pac_power_kw: float,
    cop: float,
    heat_pac_mwh_year: float,
    power_ratio_w_per_m: float = 40.0,
    energy_ratio_kwh_per_m_year: float = 60.0,
    max_extraction_kwh_per_m_year: float | None = None,
    unit_depth_m: float = 100.0,
    safety_factor: float = 1.20,
) -> BorefieldPreDesign:
    """Pre-size geothermal probes from heat pump power and COP.

    This mirrors the opportunity-matrix logic:
    - ground_power = pac_power * (COP - 1) / COP
    - ground_heat = annual_PAC_heat * (COP - 1) / COP
    - required_length = max(ground_power / W_per_m, ground_heat / kWh_per_m.year)

    Power is converted from kW to W and annual heat from MWh to kWh before
    applying the ratios. Required length is rounded up to the next 10 m.
    """

    safe_power = max(0.0, float(pac_power_kw))
    safe_cop = max(1.01, float(cop))
    safe_heat = max(0.0, float(heat_pac_mwh_year))
    safe_power_ratio = max(1e-9, float(power_ratio_w_per_m))
    extraction_ratio = (
        energy_ratio_kwh_per_m_year
        if max_extraction_kwh_per_m_year is None
        else max_extraction_kwh_per_m_year
    )
    safe_energy_ratio = max(1e-9, float(extraction_ratio))
    safe_depth = max(1.0, float(unit_depth_m))
    safe_safety_factor = max(1.0, float(safety_factor))

    ground_fraction = max(0.0, (safe_cop - 1.0) / safe_cop)
    ground_power_kw = safe_power * ground_fraction
    ground_heat_mwh = safe_heat * ground_fraction
    length_power_m = ground_power_kw * 1000.0 / safe_power_ratio
    length_energy_m = ground_heat_mwh * 1000.0 / safe_energy_ratio
    required_length_m = math.ceil(max(length_power_m, length_energy_m) * safe_safety_factor / 10.0) * 10.0
    boreholes = max(1, math.ceil(required_length_m / safe_depth))
    effective_length_m = boreholes * safe_depth

    return BorefieldPreDesign(
        pac_power_kw=safe_power,
        cop=safe_cop,
        heat_pac_mwh_year=safe_heat,
        ground_power_kw=ground_power_kw,
        ground_heat_mwh_year=ground_heat_mwh,
        power_ratio_w_per_m=safe_power_ratio,
        energy_ratio_kwh_per_m_year=safe_energy_ratio,
        required_length_m=required_length_m,
        unit_depth_m=safe_depth,
        boreholes=boreholes,
        effective_length_m=effective_length_m,
        safety_factor=safe_safety_factor,
    )
