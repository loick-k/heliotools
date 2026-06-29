from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass

from .engine import BtesConfig, btes_temperature_from_energy, clamp_btes_energy


@dataclass(frozen=True)
class BtesThermalState:
    energy_kwh: float
    temp_c: float


class EquivalentCapacityBtesModel:
    """Current V1 equivalent-capacity BTES model."""

    name = "equivalent_capacity"

    def __init__(self, config: BtesConfig, initial_energy_kwh: float = 0.0):
        self.config = config
        self.energy_kwh = clamp_btes_energy(initial_energy_kwh, config)
        self._pending_net_extraction_kwh = 0.0

    def temperature_c(self) -> float:
        return btes_temperature_from_energy(self.energy_kwh, self.config)

    def capacity_remaining_kwh(self) -> float:
        return max(0.0, self.config.max_energy_kwh - self.energy_kwh)

    def field_available_kwh(self) -> float:
        return max(0.0, self.energy_kwh - self.config.min_energy_kwh)

    def add_heat(self, heat_kwh: float) -> float:
        accepted = min(max(0.0, heat_kwh), self.capacity_remaining_kwh())
        self.energy_kwh = clamp_btes_energy(self.energy_kwh + accepted, self.config)
        self._pending_net_extraction_kwh -= accepted
        return accepted

    def extract_heat(self, heat_kwh: float) -> float:
        extracted = min(max(0.0, heat_kwh), self.field_available_kwh())
        self.energy_kwh = clamp_btes_energy(self.energy_kwh - extracted, self.config)
        self._pending_net_extraction_kwh += extracted
        return extracted

    def relax_to_ground(self) -> tuple[float, float]:
        relaxation = _hourly_relaxation_to_ground(self.energy_kwh, self.config)
        self.energy_kwh = clamp_btes_energy(self.energy_kwh - relaxation, self.config)
        self._pending_net_extraction_kwh = 0.0
        return max(0.0, relaxation), max(0.0, -relaxation)

    def state(self) -> BtesThermalState:
        return BtesThermalState(energy_kwh=self.energy_kwh, temp_c=self.temperature_c())


class PygfunctionBtesModel(EquivalentCapacityBtesModel):
    """Optional pygfunction-backed BTES temperature model.

    The equivalent-capacity energy state is kept for dispatch limits. The
    source temperature used by the PAC is updated from pygfunction load
    aggregation using the net hourly field load:
    extraction from ground positive, solar injection negative.
    """

    name = "pygfunction"

    def __init__(
        self,
        config: BtesConfig,
        initial_energy_kwh: float = 0.0,
        simulation_hours: int = 8760,
    ):
        if importlib.util.find_spec("pygfunction") is None:
            raise ImportError("pygfunction n'est pas installe.")
        super().__init__(config, initial_energy_kwh=initial_energy_kwh)
        self._gfunction_ready = False
        self._hour_index = 0
        self._pyg_temp_c = btes_temperature_from_energy(self.energy_kwh, config)
        self._load_agg = None
        self._simulation_hours = max(1, int(simulation_hours))
        self._prepare_gfunction()

    def _prepare_gfunction(self) -> None:
        try:
            import pygfunction as gt

            n_boreholes = max(1, int(self.config.boreholes))
            n_side = max(1, int(math.ceil(math.sqrt(n_boreholes))))
            dt = 3600.0
            tmax = float(self._simulation_hours) * dt
            load_agg = gt.load_aggregation.ClaessonJaved(dt, tmax)
            time_req = load_agg.get_times_for_simulation()
            borefield = gt.boreholes.rectangle_field(
                N_1=n_side,
                N_2=n_side,
                B_1=max(0.1, self.config.spacing_m),
                B_2=max(0.1, self.config.spacing_m),
                H=max(1.0, self.config.depth_m),
                D=max(0.0, self.config.borehole_buried_depth_m),
                r_b=max(1e-3, self.config.borehole_radius_m),
            )[:n_boreholes]
            gfunc = gt.gfunction.gFunction(
                borefield,
                alpha=max(1e-9, self.config.ground_diffusivity_m2_s),
                time=time_req,
                options={"nSegments": 4, "disp": False},
            )
            load_agg.initialize(gfunc.gFunc / (2.0 * math.pi * max(1e-9, self.config.ground_conductivity_w_m_k)))
            self._load_agg = load_agg
            self._total_borehole_length_m = max(1e-9, n_boreholes * max(1.0, self.config.depth_m))
            self._gfunction_ready = True
        except Exception:
            self._gfunction_ready = False

    @property
    def is_ready(self) -> bool:
        return self._gfunction_ready and self._load_agg is not None

    def temperature_c(self) -> float:
        if not self.is_ready:
            return super().temperature_c()
        return max(self.config.t_min_c, min(self.config.t_max_c, self._pyg_temp_c))

    def relax_to_ground(self) -> tuple[float, float]:
        relaxation = _hourly_relaxation_to_ground(self.energy_kwh, self.config)
        self.energy_kwh = clamp_btes_energy(self.energy_kwh - relaxation, self.config)
        if self.is_ready:
            self._hour_index += 1
            time_s = self._hour_index * 3600.0
            net_load_w = self._pending_net_extraction_kwh * 1000.0
            q_b_w_m = net_load_w / self._total_borehole_length_m
            self._load_agg.next_time_step(time_s)
            self._load_agg.set_current_load(q_b_w_m)
            delta_t_b = float(self._load_agg.temporal_superposition())
            borehole_wall_temp_c = self.config.t_initial_c - delta_t_b
            self._pyg_temp_c = borehole_wall_temp_c - q_b_w_m * self.config.borehole_thermal_resistance_m_k_w
        self._pending_net_extraction_kwh = 0.0
        return max(0.0, relaxation), max(0.0, -relaxation)


def _hourly_relaxation_to_ground(energy_kwh: float, btes: BtesConfig) -> float:
    tau_hours = max(1e-6, btes.monthly_relaxation_tau_months * 30.4375 * 24.0)
    fraction = 1.0 - math.exp(-1.0 / tau_hours)
    return energy_kwh * fraction


def create_btes_model(
    config: BtesConfig,
    initial_energy_kwh: float = 0.0,
    simulation_hours: int = 8760,
):
    backend = str(config.backend or "pygfunction").lower()
    if backend == "pygfunction":
        model = PygfunctionBtesModel(
            config,
            initial_energy_kwh=initial_energy_kwh,
            simulation_hours=simulation_hours,
        )
        if model.is_ready:
            return model
        raise RuntimeError("pygfunction n'a pas pu initialiser le champ de sondes.")
    return EquivalentCapacityBtesModel(config, initial_energy_kwh=initial_energy_kwh)


def pygfunction_available() -> bool:
    return importlib.util.find_spec("pygfunction") is not None
