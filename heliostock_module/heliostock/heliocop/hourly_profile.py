"""Mode profil horaire HelioCOP pour usages process / industriels.

Ce module ne transpose pas les abaques COSTIC logement collectif à l'industrie.
Il utilise directement un profil thermique 8760 h et teste les couples réels
PAC / stockage du catalogue HelioCOP avec un bilan horaire simplifié.

Le stockage ECS2 est représenté comme un volume agrégé d'eau chaude à la
consigne de stockage. La stratification détaillée et les performances variables
de la PAC restent destinées au futur moteur dynamique.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Iterable

import pandas as pd

from .model import (
    CP_WHLK,
    DEFAULT_MAX_PAC_COUNT,
    DEFAULT_MAX_TANK_COUNT,
    DEFAULT_STORAGE_TEMPERATURE_C,
    MONTH_NAMES,
    STANDARD_TANK_SIZES_L,
    PacOption,
    TankOption,
    pac_options_for_minimum,
)

PROFILE_SHEET_NAME = "besoins_8760h"
PROFILE_REQUIRED_HOURS = 8760
PROFILE_ENERGY_COLUMNS = ("E besoin HT kWh", "E besoin BT kWh")


@dataclass(frozen=True)
class HourlyLoadProfile:
    energy_kwh: tuple[float, ...]
    months: tuple[int, ...]
    days: tuple[int, ...]
    hours: tuple[int, ...]
    source_name: str
    source_sheet: str
    energy_columns: tuple[str, ...]

    @property
    def hour_count(self) -> int:
        return len(self.energy_kwh)

    @property
    def annual_energy_mwh(self) -> float:
        return sum(self.energy_kwh) / 1000.0

    @property
    def peak_hourly_kw(self) -> float:
        # Le pas étant strictement horaire, kWh sur une heure = kW moyen horaire.
        return max(self.energy_kwh, default=0.0)

    @property
    def nonzero_hours(self) -> int:
        return sum(1 for value in self.energy_kwh if value > 1e-9)


@dataclass(frozen=True)
class HourlySimulationResult:
    coverage_fraction: float
    unmet_energy_mwh: float
    unmet_hours: int
    min_soc_fraction: float
    pac_heat_mwh: float
    equivalent_full_load_hours: float
    final_soc_fraction: float
    peak_hourly_kw: float

    @property
    def is_feasible(self) -> bool:
        return self.unmet_energy_mwh <= 1e-8 and self.unmet_hours == 0


@dataclass(frozen=True)
class HourlyTraceRow:
    index: int
    month: int
    day: int
    hour: int
    demand_kwh: float
    pac_heat_kwh: float
    unmet_kwh: float
    storage_soc_fraction: float


@dataclass(frozen=True)
class ProfileSizingOption:
    tank: TankOption
    pac: PacOption
    simulation: HourlySimulationResult

    @property
    def label(self) -> str:
        return (
            f"{self.pac.brand} — {self.pac.unit_count} × {self.pac.model} = "
            f"{self.pac.installed_power_kw:.0f} kW | {self.tank.label}"
        )


def _read_profile_dataframe(source: str | Path | BinaryIO | BytesIO, source_name: str | None = None) -> tuple[pd.DataFrame, str, str]:
    """Lit un fichier Excel/CSV et retourne le DataFrame brut et sa provenance."""
    inferred_name = source_name or getattr(source, "name", None) or (Path(source).name if isinstance(source, (str, Path)) else "profil")
    suffix = Path(str(inferred_name)).suffix.lower()

    if suffix == ".csv":
        frame = pd.read_csv(source)
        return frame, str(inferred_name), "CSV"

    if suffix not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("Format de profil non reconnu. Utiliser un fichier .xlsx ou .csv.")

    excel = pd.ExcelFile(source)
    sheet = PROFILE_SHEET_NAME if PROFILE_SHEET_NAME in excel.sheet_names else excel.sheet_names[0]
    frame = pd.read_excel(excel, sheet_name=sheet)
    return frame, str(inferred_name), sheet


def _find_energy_columns(columns: Iterable[str]) -> tuple[str, ...]:
    names = [str(col).strip() for col in columns]
    exact = tuple(col for col in PROFILE_ENERGY_COLUMNS if col in names)
    if exact:
        return exact
    if "E_total_kWh" in names:
        return ("E_total_kWh",)
    if "E total kWh" in names:
        return ("E total kWh",)

    candidates = [
        col
        for col in names
        if "kwh" in col.lower() and ("besoin" in col.lower() or "energie" in col.lower() or "energy" in col.lower())
    ]
    if candidates:
        return (candidates[0],)

    power_candidates = [col for col in names if "kw" in col.lower() and "kwh" not in col.lower() and "besoin" in col.lower()]
    if power_candidates:
        # Pas strictement horaire : la valeur kW est équivalente au kWh sur l'heure.
        return (power_candidates[0],)
    raise ValueError(
        "Aucune colonne de besoin thermique reconnue. Le format recommandé contient "
        "'E besoin HT kWh' et/ou 'E besoin BT kWh'."
    )


def load_hourly_profile(
    source: str | Path | BinaryIO | BytesIO,
    *,
    source_name: str | None = None,
    required_hours: int = PROFILE_REQUIRED_HOURS,
) -> HourlyLoadProfile:
    """Charge et valide un profil thermique horaire 8760 h.

    Le format HelioStock transmis est reconnu nativement : feuille
    ``besoins_8760h`` et colonnes ``month``, ``day``, ``hour``,
    ``E besoin HT kWh`` et ``E besoin BT kWh``.
    """
    frame, name, sheet = _read_profile_dataframe(source, source_name=source_name)
    frame = frame.copy()
    frame.columns = [str(col).strip() for col in frame.columns]

    if len(frame) != int(required_hours):
        raise ValueError(f"Le profil doit contenir exactement {required_hours} lignes horaires ; {len(frame)} lignes détectées.")

    energy_columns = _find_energy_columns(frame.columns)
    energy = pd.Series(0.0, index=frame.index, dtype=float)
    for column in energy_columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"La colonne '{column}' contient des valeurs non numériques ou vides.")
        if (values < -1e-9).any():
            raise ValueError(f"La colonne '{column}' contient des besoins négatifs.")
        energy = energy + values.clip(lower=0.0)

    def numeric_column(name_: str) -> pd.Series | None:
        if name_ not in frame.columns:
            return None
        values_ = pd.to_numeric(frame[name_], errors="coerce")
        if values_.isna().any():
            return None
        return values_.astype(int)

    months = numeric_column("month")
    days = numeric_column("day")
    hours = numeric_column("hour")

    if months is None or days is None or hours is None:
        calendar = pd.date_range("2025-01-01 00:00:00", periods=required_hours, freq="h")
        months = pd.Series(calendar.month, index=frame.index)
        days = pd.Series(calendar.day, index=frame.index)
        # Format transmis : 1..24 et non 0..23.
        hours = pd.Series(calendar.hour + 1, index=frame.index)

    if not months.between(1, 12).all():
        raise ValueError("La colonne 'month' doit contenir des mois entre 1 et 12.")
    if not days.between(1, 31).all():
        raise ValueError("La colonne 'day' contient des jours invalides.")
    if not (hours.between(0, 23).all() or hours.between(1, 24).all()):
        raise ValueError("La colonne 'hour' doit être codée 0..23 ou 1..24.")

    return HourlyLoadProfile(
        energy_kwh=tuple(float(v) for v in energy.tolist()),
        months=tuple(int(v) for v in months.tolist()),
        days=tuple(int(v) for v in days.tolist()),
        hours=tuple(int(v) for v in hours.tolist()),
        source_name=name,
        source_sheet=sheet,
        energy_columns=tuple(energy_columns),
    )


def tank_pair_options(tank_count: int = DEFAULT_MAX_TANK_COUNT) -> tuple[TankOption, ...]:
    """Toutes les banques ECS2 de ballons identiques."""
    count = max(1, int(tank_count))
    options: list[TankOption] = []
    for unit_volume in STANDARD_TANK_SIZES_L:
        volumes = tuple([int(unit_volume)] * count)
        total = int(unit_volume) * count
        options.append(TankOption(volumes_l=volumes, total_volume_l=total, difference_l=0.0, difference_pct=0.0))
    return tuple(options)


def simulate_hourly_profile(
    profile: HourlyLoadProfile,
    *,
    pac_power_kw: float,
    storage_volume_l: float,
    cold_water_temperatures_c: dict[str, float],
    storage_temperature_c: float = DEFAULT_STORAGE_TEMPERATURE_C,
    initial_soc_fraction: float = 1.0,
    with_trace: bool = False,
) -> tuple[HourlySimulationResult, tuple[HourlyTraceRow, ...]]:
    """Bilan horaire PAC + stockage ECS2 simplifié.

    L'état de stockage est exprimé en litres d'eau chaude équivalents à la
    température de stockage. La demande thermique importée est convertie en
    volume équivalent à partir de la Tef mensuelle HelioCOP. La PAC est supposée
    pouvoir fonctionner à sa puissance thermique nominale à chaque heure et
    recharge le stockage dès qu'une place est disponible.
    """
    pac_kw = max(0.0, float(pac_power_kw))
    capacity_l = max(0.0, float(storage_volume_l))
    if capacity_l <= 0:
        raise ValueError("Le volume de stockage doit être strictement positif.")
    if storage_temperature_c <= 0:
        raise ValueError("La température de stockage doit être strictement positive.")

    state_l = capacity_l * min(1.0, max(0.0, float(initial_soc_fraction)))
    initial_state_l = state_l
    total_demand_kwh = 0.0
    unmet_kwh = 0.0
    unmet_hours = 0
    pac_heat_kwh = 0.0
    min_state_l = state_l
    trace: list[HourlyTraceRow] = []

    for index, (demand_kwh, month, day, hour) in enumerate(
        zip(profile.energy_kwh, profile.months, profile.days, profile.hours)
    ):
        month_name = MONTH_NAMES[max(1, min(12, int(month))) - 1]
        tef = float(cold_water_temperatures_c.get(month_name, 12.0))
        delta_t = float(storage_temperature_c) - tef
        if delta_t <= 0:
            raise ValueError("La température de stockage doit être supérieure à toutes les températures d'eau froide.")

        kwh_per_l = CP_WHLK * delta_t / 1000.0
        demand = max(0.0, float(demand_kwh))
        demand_l = demand / kwh_per_l if kwh_per_l > 0 else 0.0
        max_pac_l = pac_kw / kwh_per_l if kwh_per_l > 0 else 0.0

        # La PAC couvre le besoin courant et recharge le volume libéré dans la
        # limite de sa puissance. Cela reproduit un pilotage simple avec priorité
        # au maintien d'un stock chaud disponible avant le prochain appel.
        pac_l = min(max_pac_l, max(0.0, demand_l + capacity_l - state_l))
        available_l = state_l + pac_l
        served_l = min(demand_l, available_l)
        missing_l = max(0.0, demand_l - served_l)
        state_l = min(capacity_l, max(0.0, available_l - demand_l))

        hour_unmet_kwh = missing_l * kwh_per_l
        hour_pac_kwh = pac_l * kwh_per_l
        total_demand_kwh += demand
        unmet_kwh += hour_unmet_kwh
        pac_heat_kwh += hour_pac_kwh
        if hour_unmet_kwh > 1e-7:
            unmet_hours += 1
        min_state_l = min(min_state_l, state_l)

        if with_trace:
            trace.append(
                HourlyTraceRow(
                    index=index,
                    month=int(month),
                    day=int(day),
                    hour=int(hour),
                    demand_kwh=demand,
                    pac_heat_kwh=hour_pac_kwh,
                    unmet_kwh=hour_unmet_kwh,
                    storage_soc_fraction=state_l / capacity_l,
                )
            )

    served_kwh = max(0.0, total_demand_kwh - unmet_kwh)
    coverage = served_kwh / total_demand_kwh if total_demand_kwh > 0 else 1.0
    result = HourlySimulationResult(
        coverage_fraction=coverage,
        unmet_energy_mwh=unmet_kwh / 1000.0,
        unmet_hours=unmet_hours,
        min_soc_fraction=min_state_l / capacity_l,
        pac_heat_mwh=pac_heat_kwh / 1000.0,
        equivalent_full_load_hours=(pac_heat_kwh / pac_kw if pac_kw > 0 else 0.0),
        final_soc_fraction=state_l / capacity_l,
        peak_hourly_kw=profile.peak_hourly_kw,
    )
    return result, tuple(trace)


def evaluate_profile_configurations(
    profile: HourlyLoadProfile,
    *,
    cold_water_temperatures_c: dict[str, float],
    max_pac_count: int = DEFAULT_MAX_PAC_COUNT,
    tank_count: int = DEFAULT_MAX_TANK_COUNT,
    usage: str = "ECS",
) -> tuple[ProfileSizingOption, ...]:
    """Teste toutes les PAC commerciales et toutes les paires de ballons."""
    pac_options = pac_options_for_minimum(0.0, max_pac_count=max_pac_count, usage=usage)
    tanks = tank_pair_options(tank_count)
    rows: list[ProfileSizingOption] = []
    for pac in pac_options:
        for tank in tanks:
            simulation, _ = simulate_hourly_profile(
                profile,
                pac_power_kw=pac.installed_power_kw,
                storage_volume_l=tank.total_volume_l,
                cold_water_temperatures_c=cold_water_temperatures_c,
                with_trace=False,
            )
            rows.append(ProfileSizingOption(tank=tank, pac=pac, simulation=simulation))
    rows.sort(
        key=lambda item: (
            item.pac.brand,
            item.pac.installed_power_kw,
            item.pac.unit_count,
            item.tank.total_volume_l,
            item.pac.model,
        )
    )
    return tuple(rows)


def minimum_storage_for_each_pac(options: Iterable[ProfileSizingOption]) -> tuple[ProfileSizingOption, ...]:
    """Pour chaque configuration PAC, garde le plus petit stockage assurant 100 %."""
    best: dict[tuple[str, str, int], ProfileSizingOption] = {}
    for option in options:
        if not option.simulation.is_feasible:
            continue
        key = (option.pac.brand, option.pac.model, option.pac.unit_count)
        current = best.get(key)
        if current is None or option.tank.total_volume_l < current.tank.total_volume_l:
            best[key] = option
    return tuple(
        sorted(
            best.values(),
            key=lambda item: (
                item.pac.installed_power_kw,
                item.tank.total_volume_l,
                item.pac.unit_count,
                item.pac.brand,
                item.pac.model,
            ),
        )
    )


def pareto_profile_options(options: Iterable[ProfileSizingOption]) -> tuple[ProfileSizingOption, ...]:
    """Front puissance PAC / volume de stockage parmi les solutions faisables."""
    feasible = [option for option in options if option.simulation.is_feasible]
    front: list[ProfileSizingOption] = []
    for candidate in feasible:
        dominated = False
        for other in feasible:
            if other is candidate:
                continue
            no_more_power = other.pac.installed_power_kw <= candidate.pac.installed_power_kw + 1e-9
            no_more_storage = other.tank.total_volume_l <= candidate.tank.total_volume_l
            strictly_better = (
                other.pac.installed_power_kw < candidate.pac.installed_power_kw - 1e-9
                or other.tank.total_volume_l < candidate.tank.total_volume_l
            )
            if no_more_power and no_more_storage and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(candidate)

    # À puissance/stock identiques, on privilégie moins de machines puis on
    # garde une seule proposition par marque/modèle pour éviter les doublons UI.
    dedup: dict[tuple[float, int, str], ProfileSizingOption] = {}
    for option in sorted(front, key=lambda x: (x.pac.installed_power_kw, x.tank.total_volume_l, x.pac.unit_count, x.pac.brand)):
        key = (option.pac.installed_power_kw, option.tank.total_volume_l, option.pac.brand)
        current = dedup.get(key)
        if current is None or option.pac.unit_count < current.pac.unit_count:
            dedup[key] = option
    return tuple(
        sorted(
            dedup.values(),
            key=lambda item: (item.pac.installed_power_kw, item.tank.total_volume_l, item.pac.unit_count, item.pac.brand),
        )
    )
