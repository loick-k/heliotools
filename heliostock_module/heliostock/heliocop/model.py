"""Moteur de prédimensionnement HelioCOP.

Le moteur est volontairement simple : il prépare une note d'opportunité.
Le dimensionnement définitif est destiné à être repris par une simulation
dynamique plus détaillée.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor, log
from typing import Iterable

CP_WHLK = 1.163
MONTHS: tuple[tuple[str, int], ...] = (
    ("Janvier", 31),
    ("Février", 28),
    ("Mars", 31),
    ("Avril", 30),
    ("Mai", 31),
    ("Juin", 30),
    ("Juillet", 31),
    ("Août", 31),
    ("Septembre", 30),
    ("Octobre", 31),
    ("Novembre", 30),
    ("Décembre", 31),
)
MONTH_NAMES = tuple(month for month, _ in MONTHS)
DAYS_BY_MONTH = dict(MONTHS)

DEFAULT_MONTHLY_COEFFICIENTS: dict[str, float] = {
    "Janvier": 1.10,
    "Février": 1.10,
    "Mars": 1.10,
    "Avril": 1.10,
    "Mai": 1.10,
    "Juin": 0.85,
    "Juillet": 0.75,
    "Août": 0.75,
    "Septembre": 0.90,
    "Octobre": 1.05,
    "Novembre": 1.10,
    "Décembre": 1.10,
}

HOUSING_STANDARD_EQUIVALENTS: dict[str, dict[str, float]] = {
    "Parc social / public": {
        "T1": 0.6,
        "T2": 0.7,
        "T3": 1.0,
        "T4": 1.4,
        "T5": 1.8,
        "T6 ou plus": 1.9,
    },
    "Parc privé": {
        "T1": 0.6,
        "T2": 0.7,
        "T3": 0.9,
        "T4": 1.1,
        "T5": 1.3,
        "T6 ou plus": 1.4,
    },
}

HOUSING_NEEDS_L_EQ40_DAY: dict[str, dict[str, float]] = {
    "Parc social / public": {
        "T1": 75.0,
        "T2": 80.0,
        "T3": 110.0,
        "T4": 145.0,
        "T5": 190.0,
        "T6 ou plus": 209.0,
    },
    "Parc privé": {
        "T1": 75.0,
        "T2": 80.0,
        "T3": 100.0,
        "T4": 110.0,
        "T5": 140.0,
        "T6 ou plus": 140.0,
    },
}

STANDARD_TANK_SIZES_L: tuple[int, ...] = (1000, 1250, 1500, 2000, 2500, 3000)
DEFAULT_STORAGE_FRACTION = 0.80
DEFAULT_STORAGE_TEMPERATURE_C = 60.0
DEFAULT_COP = 3.2
DEFAULT_AID_EUR_PER_MWH_ENR = 600.0
DEFAULT_COST_UNCERTAINTY = 0.20
DEFAULT_MAX_TANK_COUNT = 2  # Schéma ECS2 : paire de ballons identiques
DEFAULT_MAX_PAC_COUNT = 3

# REX fabricants transmis pour le prédimensionnement de la source solaire.
SOURCE_SURFACE_RATIO_M2_PER_KW_PPAC = {
    # Valeurs de travail HelioCOP issues des REX fabricants transmis.
    # Elles se situent au milieu des plages indicatives du livret SOCOL PAC Solaire ECS2.
    "Moquette solaire": 5.0,
    "PVT": 4.5,
}

# Livret SOCOL PAC Solaire, ECS2, §3.3.5.2 :
# - capteurs non vitrés : 4 à 6 m²/kW PAC
# - PVT : 3 à 6 m²/kW PAC
SOURCE_SURFACE_RATIO_RANGES_M2_PER_KW_PPAC = {
    "Moquette solaire": (4.0, 6.0),
    "PVT": (3.0, 6.0),
}

# Tendance issue du volet "Evaluation cout" du tableur transmis.
REX_FIXED_COST_EUR = 43854.0
REX_POWER_COST_EUR_PER_KW = 2362.0
REX_COLLECTOR_COST_EUR_PER_M2 = 300.0


@dataclass(frozen=True)
class PacCatalogEntry:
    brand: str
    model: str
    nominal_power_kw: float
    usage: str = "ECS"
    extra_usages: tuple[str, ...] = ()
    dynamic_data_available: bool = True
    source_note: str = ""
    xml_filename: str | None = None

    def supports_usage(self, usage: str) -> bool:
        return usage == self.usage or usage in self.extra_usages


PAC_CATALOG: tuple[PacCatalogEntry, ...] = (
    PacCatalogEntry("HelioPAC", "Solerpac SE134A-8", 8.0, extra_usages=("Process",), xml_filename="SolerpacSE134A-8.xml"),
    PacCatalogEntry("HelioPAC", "Solerpac SE513A-10", 10.0, extra_usages=("Process",), xml_filename="SolerpacSE513A-10.xml"),
    PacCatalogEntry("HelioPAC", "Solerpac SE134A-12", 12.0, extra_usages=("Process",), xml_filename="SolerpacSE134A-12.xml"),
    PacCatalogEntry("HelioPAC", "Solerpac SE513A-14", 14.0, extra_usages=("Process",), xml_filename="SolerpacSE513A-14.xml"),
    PacCatalogEntry(
        "HelioPAC",
        "Solerpac P25",
        25.0,
        extra_usages=("Process", "Chauffage"),
        dynamic_data_available=False,
        source_note="Gamme P HelioPAC : chauffage et process industriels. Données XML SoloPAC 1.1 non fournies pour ce modèle.",
        xml_filename=None,
    ),
    PacCatalogEntry(
        "HelioPAC",
        "Solerpac P50 R407C",
        50.0,
        usage="Process",
        extra_usages=("Chauffage", "Bassin"),
        source_note="Gamme P HelioPAC : process industriels, chauffage et maintien en température des bassins. FT1p V3.1 : température chauffage maxi 55 °C.",
        xml_filename="Solerpac 407C.xml",
    ),
    PacCatalogEntry("Giordano", "SolarPump SPC20", 20.0, extra_usages=("Process",), xml_filename="GiordanoSolarPump SPC20.xml"),
    PacCatalogEntry("Giordano", "SolarPump SPC30", 30.0, extra_usages=("Process",), xml_filename="GiordanoSolarPump SPC30.xml"),
    PacCatalogEntry("Giordano", "SolarPump SPC50", 50.0, extra_usages=("Process",), xml_filename="GiordanoSolarPump SPC50.xml"),
)


@dataclass(frozen=True)
class HousingReference:
    actual_dwellings: int
    standard_dwellings_exact: float
    standard_dwellings_costic: int
    daily_need_l_eq40: float


@dataclass(frozen=True)
class MonthlySizingRow:
    month: str
    days: int
    coefficient: float
    cold_water_temperature_c: float
    daily_need_l_eq40: float
    daily_storage_l_eq40: float
    conversion_factor_40_to_60: float
    daily_storage_l_eq60: float
    useful_ecs_energy_mwh: float


@dataclass(frozen=True)
class TankOption:
    volumes_l: tuple[int, ...]
    total_volume_l: int
    difference_l: float
    difference_pct: float | None

    @property
    def label(self) -> str:
        if len(set(self.volumes_l)) == 1:
            return f"{len(self.volumes_l)} × {self.volumes_l[0]:,.0f} L = {self.total_volume_l:,.0f} L".replace(",", " ")
        parts = " + ".join(f"{v:,.0f}".replace(",", " ") for v in self.volumes_l)
        return f"{parts} L = {self.total_volume_l:,.0f} L".replace(",", " ")


@dataclass(frozen=True)
class PacOption:
    brand: str
    model: str
    unit_power_kw: float
    unit_count: int
    installed_power_kw: float
    minimum_power_kw: float
    oversizing_kw: float
    oversizing_pct: float | None
    dynamic_data_available: bool
    xml_filename: str | None = None

    @property
    def label(self) -> str:
        return f"{self.brand} — {self.unit_count} × {self.model} ({self.installed_power_kw:.1f} kW)"


@dataclass(frozen=True)
class EnergyEconomics:
    annual_ecs_need_mwh: float
    cop: float
    pac_heat_mwh: float
    compressor_electricity_mwh: float
    auxiliary_electricity_mwh: float
    pac_electricity_mwh: float
    system_cop_including_aux: float
    renewable_heat_mwh: float
    renewable_share: float
    aid_eur_per_mwh_enr: float
    estimated_aid_eur: float
    capex_mid_eur: float
    capex_low_eur: float
    capex_high_eur: float
    remaining_cost_mid_eur: float


@dataclass(frozen=True)
class HelioCopSizingResult:
    housing: HousingReference
    monthly_rows: tuple[MonthlySizingRow, ...]
    target_storage_l_eq60: float
    lower_tank: TankOption | None
    upper_tank: TankOption | None
    selected_storage_l: int
    pecs_kw: float
    pac_min_kw: float
    pac_options_by_brand: tuple[PacOption, ...]
    selected_pac: PacOption | None
    source_type: str
    source_surface_m2: float
    economics: EnergyEconomics | None

    def as_dict(self) -> dict:
        return asdict(self)


def round_standard_dwellings(value: float) -> int:
    """Arrondi arithmétique utilisé pour l'entrée Ns de l'abaque COSTIC."""
    return max(0, int(floor(max(0.0, value) + 0.5)))


def compute_housing_reference(counts: dict[str, int], park_type: str) -> HousingReference:
    if park_type not in HOUSING_STANDARD_EQUIVALENTS:
        raise ValueError(f"Type de parc inconnu : {park_type}")
    eq = HOUSING_STANDARD_EQUIVALENTS[park_type]
    needs = HOUSING_NEEDS_L_EQ40_DAY[park_type]
    actual = sum(max(0, int(counts.get(kind, 0))) for kind in eq)
    ns_exact = sum(max(0, int(counts.get(kind, 0))) * eq[kind] for kind in eq)
    daily = sum(max(0, int(counts.get(kind, 0))) * needs[kind] for kind in needs)
    return HousingReference(
        actual_dwellings=actual,
        standard_dwellings_exact=float(ns_exact),
        standard_dwellings_costic=round_standard_dwellings(ns_exact),
        daily_need_l_eq40=float(daily),
    )


def build_monthly_sizing_rows(
    *,
    daily_need_l_eq40: float,
    cold_water_temperatures_c: dict[str, float],
    monthly_coefficients: dict[str, float] | None = None,
    storage_fraction: float = DEFAULT_STORAGE_FRACTION,
    storage_temperature_c: float = DEFAULT_STORAGE_TEMPERATURE_C,
) -> tuple[MonthlySizingRow, ...]:
    coeffs = monthly_coefficients or DEFAULT_MONTHLY_COEFFICIENTS
    rows: list[MonthlySizingRow] = []
    for month, days in MONTHS:
        coefficient = max(0.0, float(coeffs.get(month, 1.0)))
        tef = float(cold_water_temperatures_c.get(month, 12.0))
        if tef >= 40.0:
            raise ValueError("La température d'eau froide doit rester inférieure à 40 °C.")
        daily40 = max(0.0, daily_need_l_eq40) * coefficient
        storage40 = daily40 * max(0.0, storage_fraction)
        denominator = storage_temperature_c - tef
        if denominator <= 0:
            raise ValueError("La température de stockage doit être supérieure à la température d'eau froide.")
        factor = (40.0 - tef) / denominator
        storage60 = storage40 * factor
        energy_mwh = daily40 * days * CP_WHLK * (40.0 - tef) / 1_000_000.0
        rows.append(
            MonthlySizingRow(
                month=month,
                days=days,
                coefficient=coefficient,
                cold_water_temperature_c=tef,
                daily_need_l_eq40=daily40,
                daily_storage_l_eq40=storage40,
                conversion_factor_40_to_60=factor,
                daily_storage_l_eq60=storage60,
                useful_ecs_energy_mwh=energy_mwh,
            )
        )
    return tuple(rows)


def weighted_annual_daily_storage_l_eq60(rows: Iterable[MonthlySizingRow]) -> float:
    rows = tuple(rows)
    days = sum(row.days for row in rows)
    if days <= 0:
        return 0.0
    return sum(row.daily_storage_l_eq60 * row.days for row in rows) / days


def _identical_tank_banks(tank_count: int = DEFAULT_MAX_TANK_COUNT) -> tuple[tuple[int, ...], ...]:
    """Configurations de stockage compatibles avec le schéma ECS2.

    Le schéma de référence comporte deux volumes de stockage (zone prioritaire et
    zone de préchauffage). Pour la note d'opportunité, HelioCOP ne propose donc
    que des banques de ballons strictement identiques. La V1 fixe ``tank_count``
    à 2, tout en gardant le paramètre explicite pour faciliter une évolution.
    """
    count = max(1, int(tank_count))
    return tuple(tuple([size] * count) for size in STANDARD_TANK_SIZES_L)


def nearest_tank_options(
    target_volume_l: float,
    max_tank_count: int = DEFAULT_MAX_TANK_COUNT,
) -> tuple[TankOption | None, TankOption | None]:
    """Retourne les paires de ballons identiques encadrant le volume cible.

    ``max_tank_count`` est conservé dans la signature pour compatibilité avec la
    V1 précédente ; il représente désormais le nombre fixe de ballons de la
    banque. Avec la valeur par défaut (2), les seules capacités proposées sont
    2×1000, 2×1250, 2×1500, 2×2000, 2×2500 et 2×3000 L.
    """
    target = max(0.0, float(target_volume_l))
    combos = _identical_tank_banks(max_tank_count)
    totals = {sum(combo): combo for combo in combos}

    lower_total = max((total for total in totals if total <= target), default=None)
    upper_total = min((total for total in totals if total >= target), default=None)

    def make(total: int | None) -> TankOption | None:
        if total is None:
            return None
        diff = float(total - target)
        return TankOption(
            volumes_l=totals[total],
            total_volume_l=total,
            difference_l=diff,
            difference_pct=(diff / target if target > 0 else None),
        )

    return make(lower_total), make(upper_total)


def costic_pecs_kw(standard_dwellings: int, storage_volume_l: float) -> float:
    ns = int(standard_dwellings)
    volume = float(storage_volume_l)
    if ns <= 0 or volume <= 0:
        return 0.0
    a = 14.0 * ns + 495.0
    b = -0.77 + 0.076 * log(ns)
    return a * (volume**b)


def ecs2_dimensioning_power_kw(pecs_kw: float, loop_loss_power_kw: float = 0.0) -> float:
    """Puissance thermique de dimensionnement ECS2 : PECS + PBoucl.

    Adaptation du livret SOCOL PAC Solaire ECS2 (§3.3.5.1).
    """
    return max(0.0, float(pecs_kw)) + max(0.0, float(loop_loss_power_kw))


def costic_pac_min_kw(pecs_kw: float, loop_loss_power_kw: float = 0.0) -> float:
    """Puissance nominale PAC minimale pour le schéma ECS2.

    Le livret SOCOL PAC Solaire adapte la méthode COSTIC 2.3.2 en ajoutant
    directement les pertes de bouclage : PnomPAC = 0,7*PECS + PBoucl.
    Avec PBoucl=0, on retrouve la relation COSTIC générique utilisée auparavant.
    """
    return max(0.0, float(pecs_kw)) * 0.70 + max(0.0, float(loop_loss_power_kw))


def pac_options_for_minimum(
    minimum_power_kw: float,
    *,
    max_pac_count: int = DEFAULT_MAX_PAC_COUNT,
    usage: str = "ECS",
) -> tuple[PacOption, ...]:
    minimum = max(0.0, float(minimum_power_kw))
    candidates: list[PacOption] = []
    for entry in PAC_CATALOG:
        if not entry.supports_usage(usage):
            continue
        for count in range(1, max(1, int(max_pac_count)) + 1):
            installed = entry.nominal_power_kw * count
            if installed + 1e-9 < minimum:
                continue
            oversizing = installed - minimum
            candidates.append(
                PacOption(
                    brand=entry.brand,
                    model=entry.model,
                    unit_power_kw=entry.nominal_power_kw,
                    unit_count=count,
                    installed_power_kw=installed,
                    minimum_power_kw=minimum,
                    oversizing_kw=oversizing,
                    oversizing_pct=(oversizing / minimum if minimum > 0 else None),
                    dynamic_data_available=entry.dynamic_data_available,
                    xml_filename=entry.xml_filename,
                )
            )
    candidates.sort(key=lambda item: (item.installed_power_kw, item.unit_count, item.brand, item.model))
    return tuple(candidates)


def best_pac_option_by_brand(options: Iterable[PacOption]) -> tuple[PacOption, ...]:
    best: dict[str, PacOption] = {}
    for option in options:
        current = best.get(option.brand)
        if current is None or (
            option.installed_power_kw,
            option.unit_count,
            option.unit_power_kw,
        ) < (
            current.installed_power_kw,
            current.unit_count,
            current.unit_power_kw,
        ):
            best[option.brand] = option
    return tuple(best[brand] for brand in sorted(best))


def source_surface_m2(
    pac_power_kw: float,
    source_type: str,
    ratio_m2_per_kw: float | None = None,
) -> float:
    """Surface de source solaire à partir de la puissance PAC installée.

    Les valeurs par défaut (5 m²/kW pour moquette, 4,5 m²/kW pour PVT)
    proviennent des REX fabricants transmis. Elles sont cohérentes avec les
    plages indicatives du livret SOCOL ECS2 : 4-6 m²/kW pour non vitré et
    3-6 m²/kW pour PVT.
    """
    ratio = SOURCE_SURFACE_RATIO_M2_PER_KW_PPAC.get(source_type) if ratio_m2_per_kw is None else float(ratio_m2_per_kw)
    if ratio is None:
        raise ValueError(f"Type de source solaire inconnu : {source_type}")
    return max(0.0, float(pac_power_kw)) * max(0.0, ratio)


def source_surface_range_m2(pac_power_kw: float, source_type: str) -> tuple[float, float]:
    """Plage indicative SOCOL de surface de source en fonction de Ppac."""
    bounds = SOURCE_SURFACE_RATIO_RANGES_M2_PER_KW_PPAC.get(source_type)
    if bounds is None:
        raise ValueError(f"Type de source solaire inconnu : {source_type}")
    power = max(0.0, float(pac_power_kw))
    return power * bounds[0], power * bounds[1]


def compute_energy_economics(
    *,
    annual_ecs_need_mwh: float,
    selected_pac_power_kw: float,
    source_surface_m2_value: float,
    cop: float = DEFAULT_COP,
    auxiliary_electricity_mwh: float = 0.0,
    aid_eur_per_mwh_enr: float = DEFAULT_AID_EUR_PER_MWH_ENR,
    cost_uncertainty: float = DEFAULT_COST_UNCERTAINTY,
) -> EnergyEconomics:
    q_ecs = max(0.0, float(annual_ecs_need_mwh))
    cop_value = max(1.000001, float(cop))
    q_pac = q_ecs
    e_comp = q_pac / cop_value
    e_aux = max(0.0, float(auxiliary_electricity_mwh))
    e_pac = e_comp + e_aux
    system_cop = q_pac / e_pac if e_pac > 0 else 0.0
    q_enr = max(0.0, q_pac - e_pac)
    renewable_share = q_enr / q_pac if q_pac > 0 else 0.0
    aid = q_enr * max(0.0, float(aid_eur_per_mwh_enr))
    capex = (
        REX_FIXED_COST_EUR
        + REX_POWER_COST_EUR_PER_KW * max(0.0, float(selected_pac_power_kw))
        + REX_COLLECTOR_COST_EUR_PER_M2 * max(0.0, float(source_surface_m2_value))
    )
    uncertainty = min(0.9, max(0.0, float(cost_uncertainty)))
    return EnergyEconomics(
        annual_ecs_need_mwh=q_ecs,
        cop=cop_value,
        pac_heat_mwh=q_pac,
        compressor_electricity_mwh=e_comp,
        auxiliary_electricity_mwh=e_aux,
        pac_electricity_mwh=e_pac,
        system_cop_including_aux=system_cop,
        renewable_heat_mwh=q_enr,
        renewable_share=renewable_share,
        aid_eur_per_mwh_enr=float(aid_eur_per_mwh_enr),
        estimated_aid_eur=aid,
        capex_mid_eur=capex,
        capex_low_eur=capex * (1.0 - uncertainty),
        capex_high_eur=capex * (1.0 + uncertainty),
        remaining_cost_mid_eur=max(0.0, capex - aid),
    )
