"""Screening énergétique 8760 h V2.

Ce solveur reste un outil de prédimensionnement capacité/stockage. Il ne calcule
ni la température de source ni le COP horaire. Contrairement au legacy, l'état
de stockage est exprimé en kWh à référence fixe et une condition de cyclicité
annuelle est contrôlée.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from ..hourly_profile import HourlyLoadProfile
from ..model import CP_WHLK


@dataclass(frozen=True)
class ScreeningTraceRow:
    index: int
    demand_kWh: float
    pac_heat_kWh: float
    unmet_kWh: float
    storage_energy_kWh: float
    storage_soc_fraction: float


@dataclass(frozen=True)
class ScreeningResultV2:
    coverage_fraction: float
    unmet_energy_mwh: float
    unmet_hours: int
    min_soc_fraction: float
    final_soc_fraction: float
    cyclic_deviation_fraction: float
    cyclic_ok: bool
    pac_heat_mwh: float
    equivalent_full_load_hours: float
    storage_capacity_kWh: float
    peak_hourly_kw: float

    @property
    def is_feasible(self) -> bool:
        return self.unmet_energy_mwh <= 1e-8 and self.unmet_hours == 0 and self.cyclic_ok


def storage_capacity_kwh(
    storage_volume_l: float,
    *,
    storage_temperature_c: float = 60.0,
    reference_temperature_c: float = 10.0,
) -> float:
    delta_t = float(storage_temperature_c) - float(reference_temperature_c)
    if storage_volume_l <= 0 or delta_t <= 0:
        raise ValueError("Volume > 0 et température de stockage > température de référence requis.")
    return float(storage_volume_l) * CP_WHLK * delta_t / 1000.0


def simulate_screening_v2(
    profile: HourlyLoadProfile,
    *,
    pac_power_kw: float,
    storage_volume_l: float,
    storage_temperature_c: float = 60.0,
    reference_temperature_c: float = 10.0,
    initial_soc_fraction: float = 1.0,
    cyclic_tolerance_fraction: float = 1e-4,
    with_trace: bool = False,
) -> tuple[ScreeningResultV2, tuple[ScreeningTraceRow, ...]]:
    pac_kw = max(0.0, float(pac_power_kw))
    capacity = storage_capacity_kwh(
        storage_volume_l,
        storage_temperature_c=storage_temperature_c,
        reference_temperature_c=reference_temperature_c,
    )
    initial_fraction = min(1.0, max(0.0, float(initial_soc_fraction)))
    state = capacity * initial_fraction
    initial_state = state
    total_demand = 0.0
    unmet = 0.0
    unmet_hours = 0
    pac_heat = 0.0
    min_state = state
    trace: list[ScreeningTraceRow] = []

    for idx, demand_raw in enumerate(profile.energy_kwh):
        demand = max(0.0, float(demand_raw))
        # PAC et stockage peuvent servir simultanément le besoin sur le pas horaire.
        max_pac = pac_kw  # kW * 1 h = kWh
        pac_energy = min(max_pac, max(0.0, demand + capacity - state))
        available = state + pac_energy
        served = min(demand, available)
        missing = max(0.0, demand - served)
        state = min(capacity, max(0.0, available - demand))

        total_demand += demand
        unmet += missing
        pac_heat += pac_energy
        if missing > 1e-7:
            unmet_hours += 1
        min_state = min(min_state, state)
        if with_trace:
            trace.append(
                ScreeningTraceRow(
                    index=idx,
                    demand_kWh=demand,
                    pac_heat_kWh=pac_energy,
                    unmet_kWh=missing,
                    storage_energy_kWh=state,
                    storage_soc_fraction=state / capacity,
                )
            )

    served = max(0.0, total_demand - unmet)
    coverage = served / total_demand if total_demand > 0 else 1.0
    final_fraction = state / capacity
    deviation = abs(state - initial_state) / capacity
    cyclic_ok = deviation <= max(0.0, float(cyclic_tolerance_fraction))
    result = ScreeningResultV2(
        coverage_fraction=coverage,
        unmet_energy_mwh=unmet / 1000.0,
        unmet_hours=unmet_hours,
        min_soc_fraction=min_state / capacity,
        final_soc_fraction=final_fraction,
        cyclic_deviation_fraction=deviation,
        cyclic_ok=cyclic_ok,
        pac_heat_mwh=pac_heat / 1000.0,
        equivalent_full_load_hours=pac_heat / pac_kw if pac_kw > 0 else 0.0,
        storage_capacity_kWh=capacity,
        peak_hourly_kw=profile.peak_hourly_kw,
    )
    return result, tuple(trace)


@dataclass(frozen=True)
class ScreeningConfigurationV2:
    """Couple produit PAC / nombre de machines / volume de stockage."""

    manufacturer: str
    model: str
    unit_power_kw: float
    unit_count: int
    storage_volume_l: float
    data_quality: str
    result: ScreeningResultV2

    @property
    def installed_power_kw(self) -> float:
        return self.unit_power_kw * self.unit_count

    @property
    def label(self) -> str:
        return (
            f"{self.manufacturer} — {self.unit_count} × {self.model} "
            f"({self.installed_power_kw:g} kW) + {self.storage_volume_l:g} L"
        )


def evaluate_screening_configurations_v2(
    profile: HourlyLoadProfile,
    *,
    heat_pumps: Iterable[object],
    storage_volumes_l: Iterable[float],
    max_pac_count: int = 6,
    storage_temperature_c: float = 60.0,
    reference_temperature_c: float = 10.0,
) -> tuple[ScreeningConfigurationV2, ...]:
    """Balaye automatiquement les produits PAC et volumes de stockage.

    Le screening V2 utilise ici la puissance commerciale nominale comme niveau
    de puissance constant. Les points fabricant servent à qualifier le produit
    et sa traçabilité, mais le COP/source ne sont pas encore sollicités dans ce
    prédimensionnement capacité/stockage.
    """
    rows: list[ScreeningConfigurationV2] = []
    storages = sorted({float(v) for v in storage_volumes_l if float(v) > 0})
    for hp in heat_pumps:
        unit_kw = float(getattr(hp, "nominal_power_kw", 0.0) or 0.0)
        if unit_kw <= 0:
            continue
        manufacturer = str(getattr(hp, "manufacturer", ""))
        model = str(getattr(hp, "model", ""))
        quality_obj = getattr(hp, "data_quality", "")
        quality = str(getattr(quality_obj, "value", quality_obj))
        for count in range(1, max(1, int(max_pac_count)) + 1):
            installed_kw = unit_kw * count
            for storage_l in storages:
                result, _ = simulate_screening_v2(
                    profile,
                    pac_power_kw=installed_kw,
                    storage_volume_l=storage_l,
                    storage_temperature_c=storage_temperature_c,
                    reference_temperature_c=reference_temperature_c,
                    with_trace=False,
                )
                rows.append(
                    ScreeningConfigurationV2(
                        manufacturer=manufacturer,
                        model=model,
                        unit_power_kw=unit_kw,
                        unit_count=count,
                        storage_volume_l=storage_l,
                        data_quality=quality,
                        result=result,
                    )
                )
    return tuple(
        sorted(
            rows,
            key=lambda o: (
                o.installed_power_kw,
                o.storage_volume_l,
                o.unit_count,
                o.manufacturer.lower(),
                o.model.lower(),
            ),
        )
    )


def minimum_storage_for_each_pac_v2(
    options: Iterable[ScreeningConfigurationV2],
) -> tuple[ScreeningConfigurationV2, ...]:
    """Garde, pour chaque modèle/nombre de PAC, le plus petit stockage faisable."""
    best: dict[tuple[str, str, int], ScreeningConfigurationV2] = {}
    for option in options:
        if not option.result.is_feasible:
            continue
        key = (option.manufacturer, option.model, option.unit_count)
        current = best.get(key)
        if current is None or option.storage_volume_l < current.storage_volume_l:
            best[key] = option
    return tuple(
        sorted(
            best.values(),
            key=lambda o: (o.installed_power_kw, o.storage_volume_l, o.unit_count, o.manufacturer, o.model),
        )
    )


def pareto_screening_options_v2(
    options: Iterable[ScreeningConfigurationV2],
) -> tuple[ScreeningConfigurationV2, ...]:
    """Front de Pareto puissance PAC / stockage parmi les solutions faisables."""
    feasible = [o for o in options if o.result.is_feasible]
    front: list[ScreeningConfigurationV2] = []
    for candidate in feasible:
        dominated = False
        for other in feasible:
            if other is candidate:
                continue
            no_more_power = other.installed_power_kw <= candidate.installed_power_kw + 1e-9
            no_more_storage = other.storage_volume_l <= candidate.storage_volume_l + 1e-9
            strictly_better = (
                other.installed_power_kw < candidate.installed_power_kw - 1e-9
                or other.storage_volume_l < candidate.storage_volume_l - 1e-9
            )
            if no_more_power and no_more_storage and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(candidate)

    # À puissance/stock identiques, conserver toutes les marques/modèles :
    # l'utilisateur veut justement comparer les configurations constructeur.
    return tuple(
        sorted(
            front,
            key=lambda o: (o.installed_power_kw, o.storage_volume_l, o.unit_count, o.manufacturer, o.model),
        )
    )
