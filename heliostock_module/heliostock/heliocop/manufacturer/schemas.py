from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping

from .hp_map import HeatPumpMapPoint, HeatPumpPerformanceMap
from .quality import HeatPumpDataQuality


@dataclass(frozen=True)
class HeatPumpProduct:
    manufacturer: str
    model: str
    nominal_power_kw: float
    data_quality: HeatPumpDataQuality
    rated_points: tuple[HeatPumpMapPoint, ...] = ()
    performance_map: HeatPumpPerformanceMap | None = None
    refrigerant: str = ""
    source_temperature_min_C: float | None = None
    source_temperature_max_C: float | None = None
    sink_temperature_max_C: float | None = None
    sink_outlet_temperature_max_C: float | None = None
    source_flow_m3h: float | None = None
    sink_flow_m3h: float | None = None
    source_pump_kW: float | None = None
    sink_pump_kW: float | None = None
    provenance: str = ""
    notes: str = ""

    @property
    def id(self) -> str:
        return f"{self.manufacturer}::{self.model}"

    @property
    def dynamic_available(self) -> bool:
        return self.data_quality.dynamic_allowed and self.performance_map is not None

    @property
    def predim_available(self) -> bool:
        return self.data_quality.predim_allowed and bool(self.rated_points or self.performance_map)


@dataclass(frozen=True)
class WISCCollectorProduct:
    manufacturer: str
    model: str
    certification: str
    unit_area_m2: float
    coefficients: Mapping[str, float]
    Kd: float
    KT: Mapping[int, float]
    KL: Mapping[int, float]
    collector_type: str = ""
    provenance: str = ""
    standard_version: str = ""
    equation_schema: str = ""
    schema_verified: bool = False

    @property
    def id(self) -> str:
        return f"{self.manufacturer}::{self.model}"
