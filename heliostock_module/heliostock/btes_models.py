from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass

from .engine import BtesConfig


@dataclass(frozen=True)
class BtesThermalState:
    t_borehole_wall_c: float
    t_source_pac_c: float
    q_net_w_m: float


class PygfunctionExpertBtesModel:
    """Expert borefield model driven by pygfunction load aggregation.

    Load convention:
    - extraction from ground by the heat pump is positive;
    - solar injection into ground is negative;
    - loads passed to pygfunction are linear loads in W/m.

    Coupling is explicit hourly in this V1: the PAC COP is computed from the
    borehole wall temperature at the beginning of the hour, then the net hourly
    load is committed to pygfunction at the end of the hour.
    """

    name = "pygfunction"

    def __init__(
        self,
        config: BtesConfig,
        simulation_hours: int = 8760,
    ):
        if importlib.util.find_spec("pygfunction") is None:
            raise ImportError(
                "pygfunction est requis pour HelioStock en mode expert. "
                "Installez-le avec pip install pygfunction."
            )
        self.config = config
        self._hour_index = 0
        self._simulation_hours = max(1, int(simulation_hours))
        self._t_borehole_wall_c = float(config.t_initial_c)
        self._t_source_pac_c = float(config.t_initial_c)
        self._last_q_net_w_m = 0.0
        self._last_q_extraction_w_m = 0.0
        self._last_q_injection_w_m = 0.0
        self._load_agg = None
        self._total_borehole_length_m = max(
            1e-9,
            float(config.boreholes) * max(1.0, float(config.depth_m)),
        )
        self._prepare_gfunction()

    @property
    def total_borehole_length_m(self) -> float:
        return self._total_borehole_length_m

    def _prepare_gfunction(self) -> None:
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
        load_agg.initialize(
            gfunc.gFunc
            / (2.0 * math.pi * max(1e-9, self.config.ground_conductivity_w_m_k))
        )
        self._load_agg = load_agg

    def borehole_wall_temperature_c(self) -> float:
        return self._t_borehole_wall_c

    def source_pac_temperature_c(self) -> float:
        return self._t_source_pac_c

    def source_temperature_for_extraction(self, q_extraction_w_m: float) -> float:
        q_extraction = max(0.0, float(q_extraction_w_m))
        return self._t_borehole_wall_c - q_extraction * self.config.borehole_thermal_resistance_m_k_w

    def injection_fluid_temperature_c(self, q_injection_w_m: float) -> float:
        q_injection = max(0.0, float(q_injection_w_m))
        return self._t_borehole_wall_c + q_injection * self.config.borehole_thermal_resistance_m_k_w

    def commit_load(self, *, q_net_w_m: float, q_extraction_w_m: float, q_injection_w_m: float) -> None:
        assert self._load_agg is not None
        self._hour_index += 1
        time_s = self._hour_index * 3600.0
        self._last_q_net_w_m = float(q_net_w_m)
        self._last_q_extraction_w_m = max(0.0, float(q_extraction_w_m))
        self._last_q_injection_w_m = max(0.0, float(q_injection_w_m))
        self._load_agg.next_time_step(time_s)
        self._load_agg.set_current_load(self._last_q_net_w_m)
        delta_t_b = float(self._load_agg.temporal_superposition())
        self._t_borehole_wall_c = self.config.t_initial_c - delta_t_b
        self._t_source_pac_c = self.source_temperature_for_extraction(self._last_q_extraction_w_m)

    def temperature_c(self) -> float:
        return self.source_pac_temperature_c()

    def state(self) -> BtesThermalState:
        return BtesThermalState(
            t_borehole_wall_c=self.borehole_wall_temperature_c(),
            t_source_pac_c=self.source_pac_temperature_c(),
            q_net_w_m=self._last_q_net_w_m,
        )


# Compatibility alias for old imports of the expert model.
PygfunctionBtesModel = PygfunctionExpertBtesModel


def create_btes_model(
    config: BtesConfig,
    simulation_hours: int = 8760,
) -> PygfunctionExpertBtesModel:
    backend = str(config.backend or "pygfunction").lower()
    if backend != "pygfunction":
        raise ValueError("HelioStock utilise uniquement le backend expert pygfunction.")
    return PygfunctionExpertBtesModel(
        config,
        simulation_hours=simulation_hours,
    )


def pygfunction_available() -> bool:
    return importlib.util.find_spec("pygfunction") is not None
