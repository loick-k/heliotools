"""Cartographies de performances PAC sans extrapolation."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

import numpy as np
from scipy.interpolate import LinearNDInterpolator, RegularGridInterpolator

from ..domain.errors import OutsideHeatPumpMapError, UnknownTemperatureConventionError
from .quality import HeatPumpDataQuality


@dataclass(frozen=True)
class HeatPumpMapPoint:
    T_source_in_C: float
    T_sink_C: float
    P_heat_kW: float
    P_el_kW: float
    COP: float
    provenance: str = ""
    uncertainty_pct: float | None = None

    @property
    def P_evap_kW(self) -> float:
        return self.P_heat_kW - self.P_el_kW


@dataclass(frozen=True)
class HeatPumpEvaluation:
    valid: bool
    P_heat_kW: float
    P_el_kW: float
    COP: float
    P_evap_kW: float
    reason: str = ""
    provenance: str = ""
    uncertainty_pct: float | None = None


class HeatPumpPerformanceMap:
    """Carte 2D locale (source, température côté chaud) sans extrapolation.

    Le deuxième axe conserve explicitement sa convention, par exemple
    ``sink_in`` pour les courbes Heliopac numérisées ou ``sink_out`` pour une
    grille fabricant EN14511 structurée.
    """

    def __init__(
        self,
        points: Iterable[HeatPumpMapPoint],
        *,
        quality: HeatPumpDataQuality,
        sink_temperature_convention: str,
        source_temperature_convention: str = "source_in",
        name: str = "",
    ) -> None:
        self.points = tuple(points)
        if len(self.points) < 3:
            raise ValueError("Une carte dynamique 2D nécessite au moins trois points.")
        if sink_temperature_convention not in {"sink_in", "sink_out"}:
            raise UnknownTemperatureConventionError(
                f"Convention côté chaud inconnue : {sink_temperature_convention!r}."
            )
        if source_temperature_convention != "source_in":
            raise UnknownTemperatureConventionError(
                f"Convention source inconnue : {source_temperature_convention!r}."
            )
        self.quality = quality
        self.sink_temperature_convention = sink_temperature_convention
        self.source_temperature_convention = source_temperature_convention
        self.name = name
        xy = np.array([(p.T_source_in_C, p.T_sink_C) for p in self.points], dtype=float)
        self._xy = xy
        sources = sorted({float(p.T_source_in_C) for p in self.points})
        sinks = sorted({float(p.T_sink_C) for p in self.points})
        point_by_xy = {(float(p.T_source_in_C), float(p.T_sink_C)): p for p in self.points}
        self._regular_grid = len(point_by_xy) == len(sources) * len(sinks) and all((x, y) in point_by_xy for x in sources for y in sinks)
        if self._regular_grid:
            pheat_grid = np.array([[point_by_xy[(x, y)].P_heat_kW for y in sinks] for x in sources], dtype=float)
            pel_grid = np.array([[point_by_xy[(x, y)].P_el_kW for y in sinks] for x in sources], dtype=float)
            self._sources_grid = np.asarray(sources, dtype=float)
            self._sinks_grid = np.asarray(sinks, dtype=float)
            self._pheat_grid = pheat_grid
            self._pel_grid = pel_grid
            self._pheat = RegularGridInterpolator((self._sources_grid, self._sinks_grid), pheat_grid, bounds_error=False, fill_value=np.nan)
            self._pel = RegularGridInterpolator((self._sources_grid, self._sinks_grid), pel_grid, bounds_error=False, fill_value=np.nan)
        else:
            self._sources_grid = None
            self._sinks_grid = None
            self._pheat_grid = None
            self._pel_grid = None
            self._pheat = LinearNDInterpolator(xy, np.array([p.P_heat_kW for p in self.points], dtype=float), fill_value=np.nan)
            self._pel = LinearNDInterpolator(xy, np.array([p.P_el_kW for p in self.points], dtype=float), fill_value=np.nan)
        uncertainties = [p.uncertainty_pct for p in self.points if p.uncertainty_pct is not None]
        self.uncertainty_pct = max(uncertainties) if uncertainties else None
        provenances = sorted({p.provenance for p in self.points if p.provenance})
        self.provenance = " | ".join(provenances)


    @property
    def is_regular_grid(self) -> bool:
        return bool(self._regular_grid)

    def regular_sink_slice(self, *, T_source_in_C: float) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Retourne les vecteurs (T_sink, P_heat, P_el) à T_source fixé.

        Pour une carte rectangulaire, l'interpolation sur l'axe source est
        linéaire et vectorisée. Cette primitive évite des dizaines d'appels à
        ``RegularGridInterpolator`` dans le solveur implicite ``sink_out``.
        Aucune extrapolation n'est réalisée.
        """
        if not self._regular_grid:
            return None
        assert self._sources_grid is not None and self._sinks_grid is not None
        assert self._pheat_grid is not None and self._pel_grid is not None
        x = float(T_source_in_C)
        xs = self._sources_grid
        if x < xs[0] - 1e-12 or x > xs[-1] + 1e-12:
            return None
        if x <= xs[0] + 1e-12:
            return self._sinks_grid, self._pheat_grid[0].copy(), self._pel_grid[0].copy()
        if x >= xs[-1] - 1e-12:
            return self._sinks_grid, self._pheat_grid[-1].copy(), self._pel_grid[-1].copy()
        i = int(np.searchsorted(xs, x, side="right") - 1)
        i = max(0, min(i, len(xs) - 2))
        f = (x - xs[i]) / max(1e-12, xs[i + 1] - xs[i])
        pheat = self._pheat_grid[i] + f * (self._pheat_grid[i + 1] - self._pheat_grid[i])
        pel = self._pel_grid[i] + f * (self._pel_grid[i + 1] - self._pel_grid[i])
        return self._sinks_grid, pheat, pel

    @property
    def source_bounds_C(self) -> tuple[float, float]:
        return float(self._xy[:, 0].min()), float(self._xy[:, 0].max())

    @property
    def sink_bounds_C(self) -> tuple[float, float]:
        return float(self._xy[:, 1].min()), float(self._xy[:, 1].max())

    def evaluate(self, *, T_source_in_C: float, T_sink_C: float, raise_on_invalid: bool = False) -> HeatPumpEvaluation:
        source = float(T_source_in_C)
        sink = float(T_sink_C)
        if self._regular_grid:
            p_heat = float(self._pheat((source, sink)))
            p_el = float(self._pel((source, sink)))
        else:
            p_heat = float(self._pheat(source, sink))
            p_el = float(self._pel(source, sink))
        if not (isfinite(p_heat) and isfinite(p_el) and p_heat > 0 and p_el > 0):
            if raise_on_invalid:
                raise OutsideHeatPumpMapError(
                    f"Point ({source:.2f} °C source, {sink:.2f} °C chaud) hors carte {self.name or 'PAC'}."
                )
            return HeatPumpEvaluation(False, 0.0, 0.0, 0.0, 0.0, reason="OUTSIDE_HP_MAP", provenance=self.provenance)
        cop = p_heat / p_el
        return HeatPumpEvaluation(
            True,
            P_heat_kW=p_heat,
            P_el_kW=p_el,
            COP=cop,
            P_evap_kW=p_heat - p_el,
            provenance=self.provenance,
            uncertainty_pct=self.uncertainty_pct,
        )
