"""Pré-diagnostic ECS, bouclage sanitaire et prédimensionnement solaire thermique.

Ce module sert de brique métier pour une note d'opportunité :
1. estimation des volumes ECS mensuels à 60 °C ;
2. conversion en besoins utiles mensuels avec température d'eau froide ;
3. estimation des pertes de bouclage sanitaire ;
4. proposition d'un stockage standard ;
5. proposition d'une surface capteurs proche de 60 L/m².

La partie "Hypothèses SOLO 2018" du bouclage reprend les modes, constantes
et formules du bloc bouclage du module SOLO 2018 fourni, sans simplification
en un simple choix bon/moyen/mauvais.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from itertools import combinations_with_replacement
from math import ceil
from typing import Any

from ..collector_library import DEFAULT_COLLECTOR_NAME, get_collector_reference


CP_WHLK = 1.163
CP_EAU_WH_L_K_SOLO = 1.1615

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

MONTH_NAMES: tuple[str, ...] = tuple(month for month, _ in MONTHS)
DAYS_BY_MONTH: dict[str, int] = dict(MONTHS)
SUMMER_MONTHS_FOR_GAS_BASELOAD: tuple[str, ...] = ("Juin", "Juillet", "Août", "Septembre")

SITE_TYPOLOGIES: tuple[str, ...] = (
    "Logement collectif",
    "EHPAD",
    "Hôpital",
    "Camping",
    "Hôtel",
    "Station de lavage",
)

BUILDING_STATES: tuple[str, ...] = ("Bâtiment existant", "Bâtiment neuf")
DATA_SOURCES: tuple[str, ...] = ("Ratio SOCOL", "Mesure de consommation ECS")

LOOP_METHODS: tuple[str, ...] = ("Aucun bouclage sanitaire", "Analyse factures gaz", "Hypothèses SOLO 2018")
SOLO_TYPE_BOUCLAGE_LABELS: tuple[str, ...] = (
    "Sans apport solaire au bouclage",
    "Avec apport solaire indirect au bouclage",
)
SOLO_LOOP_LOSS_MODE_LABELS: tuple[str, ...] = (
    "Pas de pertes de bouclage",
    "Saisie pertes (kWh/j)",
    "Débit et delta T connus",
    "Longueur et isolation connues",
    "Boucle courte bien isolée",
    "Boucle qualité moyenne",
    "Boucle longue mal isolée",
)
SOLO_LOOP_LOSS_MODE_BY_LABEL: dict[str, str] = {
    "Pas de pertes de bouclage": "aucune",
    "Saisie pertes (kWh/j)": "saisie_kwh_j",
    "Débit et delta T connus": "debit_delta",
    "Longueur et isolation connues": "long_kl",
    "Boucle courte bien isolée": "bon",
    "Boucle qualité moyenne": "moyen",
    "Boucle longue mal isolée": "mauvais",
}
SOLO_LOOP_LOSS_LABEL_BY_MODE: dict[str, str] = {v: k for k, v in SOLO_LOOP_LOSS_MODE_BY_LABEL.items()}
SOLO_LOSS_INPUT_MODES: tuple[str, ...] = ("Saisie annuelle", "Saisie mensuelle")

# Alias conservés pour compatibilité avec les versions V13 et précédentes.
SOLO_LOOP_QUALITIES: tuple[str, ...] = ("Bon", "Moyen", "Mauvais")
SOLO_QUALITY_TO_LOSS_MODE_LABEL: dict[str, str] = {
    "Bon": "Boucle courte bien isolée",
    "Moyen": "Boucle qualité moyenne",
    "Mauvais": "Boucle longue mal isolée",
}

# Ratios intégrés d'après les éléments fournis et les valeurs usuelles SOCOL.
# Ils restent volontairement modifiables dans l'interface.
EHPAD_DEFAULT_L_PER_RESIDENT_DAY = 15.0
HOSPITAL_DEFAULT_L_PER_BED_DAY = 25.0
CAMPING_DEFAULT_L_PER_PERSON_NIGHT = 12.0
CAR_WASH_DEFAULT_L_PER_VEHICLE = 80.0

HOTEL_RATIOS_L_PER_ROOM_NIGHT: dict[str, float] = {
    "Eco": 30.0,
    "1 & 2 étoiles": 45.0,
    "3 & 4 étoiles": 60.0,
    "5 étoiles et plus": 80.0,
}

HOUSING_RATIOS_L_PER_DWELLING_DAY: dict[str, float] = {
    "T1": 42.0,
    "T2": 48.0,
    "T3": 63.0,
    "T4": 78.0,
    "T5": 84.0,
    "T6 et +": 90.0,
}

# Coefficients de variation saisonnière SOCOL pour le logement :
# janvier à mai 1,10 ; juin 0,85 ; juillet/août 0,75 ; septembre 0,90 ;
# octobre 1,05 ; novembre/décembre 1,10.
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

# Valeur neutre par défaut avant branchement du profil eau froide SOLO 2018.
DEFAULT_COLD_WATER_TEMPERATURES_C: dict[str, float] = {month: 15.0 for month in MONTH_NAMES}
# Température mensuelle utilisée comme mois.text_c dans la formule SOLO de bouclage.
DEFAULT_LOOP_AMBIENT_TEMPERATURES_C: dict[str, float] = {month: 20.0 for month in MONTH_NAMES}

STANDARD_TANK_SIZES_L: tuple[int, ...] = (
    200,
    250,
    300,
    400,
    500,
    750,
    1000,
    1250,
    1500,
    2000,
    2500,
    3000,
    4000,
    5000,
)

DEFAULT_COLLECTOR_UNIT_AREA_M2 = get_collector_reference(DEFAULT_COLLECTOR_NAME).area_m2
DEFAULT_TARGET_STORAGE_RATIO_L_M2 = 60.0
MIN_STORAGE_RATIO_L_M2 = 50.0
MAX_STORAGE_RATIO_L_M2 = 70.0
DEFAULT_PRODUCTIVITY_KWH_M2_YEAR = 500.0

# Constantes reprises du module SOLO 2018 fourni.
SOLO_LONG1_BOUCLE_BON_M_PAR_UNITE = 6.0
SOLO_LONG1_BOUCLE_MOYEN_M_PAR_UNITE = 9.0
SOLO_LONG1_BOUCLE_MAUVAIS_M_PAR_UNITE = 12.0
SOLO_KL_BOUCLE_BON_W_M_K = 0.2
SOLO_KL_BOUCLE_MOYEN_W_M_K = 0.3
SOLO_KL_BOUCLE_MAUVAIS_W_M_K = 0.4

SOLO_LOOP_DEFAULTS: dict[str, dict[str, float]] = {
    "bon": {"length_m_per_unit": SOLO_LONG1_BOUCLE_BON_M_PAR_UNITE, "kl_w_m_k": SOLO_KL_BOUCLE_BON_W_M_K},
    "moyen": {"length_m_per_unit": SOLO_LONG1_BOUCLE_MOYEN_M_PAR_UNITE, "kl_w_m_k": SOLO_KL_BOUCLE_MOYEN_W_M_K},
    "mauvais": {"length_m_per_unit": SOLO_LONG1_BOUCLE_MAUVAIS_M_PAR_UNITE, "kl_w_m_k": SOLO_KL_BOUCLE_MAUVAIS_W_M_K},
}


@dataclass(frozen=True)
class SiteInputs:
    project_name: str = "Nouveau projet"
    airtable_id: str = ""
    client_name: str = ""
    city: str = ""
    address: str = ""
    latitude: float = 47.2184
    longitude: float = -1.5536
    weather_region: str = "Bretagne"
    weather_station: str = "Rennes"
    typology: str = "Logement collectif"
    building_state: str = "Bâtiment existant"
    data_source: str = "Ratio SOCOL"


@dataclass(frozen=True)
class NeedsInputs:
    ecs_temperature_c: float = 60.0

    # Logement collectif : mode détaillé par typologie de logements.
    housing_counts: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in HOUSING_RATIOS_L_PER_DWELLING_DAY}
    )
    housing_ratios_l_day: dict[str, float] = field(
        default_factory=lambda: dict(HOUSING_RATIOS_L_PER_DWELLING_DAY)
    )

    # EHPAD / hôpital.
    residents_or_beds: int = 0
    liters_per_resident_or_bed_day: float = EHPAD_DEFAULT_L_PER_RESIDENT_DAY

    # Hôtel / camping : occupation mensuelle saisie.
    monthly_occupancy: dict[str, float] = field(default_factory=lambda: {month: 0.0 for month in MONTH_NAMES})
    liters_per_occupied_unit: float = HOTEL_RATIOS_L_PER_ROOM_NIGHT["1 & 2 étoiles"]
    hotel_category: str = "1 & 2 étoiles"

    # Station de lavage : unité de référence métier.
    car_wash_vehicles_per_day: float = 0.0
    car_wash_liters_per_vehicle: float = CAR_WASH_DEFAULT_L_PER_VEHICLE

    # Mesure directe de consommation ECS : valeur journalière mensuelle à 60 °C.
    measured_daily_l_60c_by_month: dict[str, float] = field(
        default_factory=lambda: {month: 0.0 for month in MONTH_NAMES}
    )

    # Modulation mensuelle pour usages réguliers.
    monthly_coefficients: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MONTHLY_COEFFICIENTS))


@dataclass(frozen=True)
class SizingInputs:
    cold_water_mode: str = "Température eau froide manuelle"
    cold_water_temperatures_c: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_COLD_WATER_TEMPERATURES_C))
    collector_name: str = DEFAULT_COLLECTOR_NAME
    collector_unit_area_m2: float = DEFAULT_COLLECTOR_UNIT_AREA_M2
    target_storage_ratio_l_m2: float = DEFAULT_TARGET_STORAGE_RATIO_L_M2
    max_tank_count: int = 3
    productivity_kwh_m2_year: float = DEFAULT_PRODUCTIVITY_KWH_M2_YEAR
    max_collector_surface_m2: float | None = None


@dataclass(frozen=True)
class LoopInputs:
    method: str = "Analyse factures gaz"
    include_heating_estimate_without_loop: bool = False

    # Méthode 1 : analyse factures gaz.
    gas_monthly_kwh: dict[str, float] = field(default_factory=lambda: {month: 0.0 for month in MONTH_NAMES})
    boiler_efficiency: float = 0.85

    # Méthode 2 : bloc bouclage SOLO 2018 repris sans simplification.
    solo_type_bouclage_label: str = "Avec apport solaire indirect au bouclage"
    solo_loss_mode_label: str = "Boucle qualité moyenne"

    # Saisie directe des pertes, selon le bloc SOLO.
    solo_losses_input_mode: str = "Saisie annuelle"
    solo_losses_annual_kwh: float = 0.0
    solo_losses_monthly_kwh_day: dict[str, float] = field(default_factory=lambda: {month: 0.0 for month in MONTH_NAMES})

    # Débit + delta T.
    solo_debit_bouclage_l_h: float = 300.0
    solo_delta_tmax_bouclage_k: float = 5.0

    # Longueur + KL connus.
    solo_long_bouclage_m: float = 120.0
    solo_kl_bouclage_w_m_k: float = 0.3

    # Modes bon/moyen/mauvais.
    solo_long1_boucle_bon_m_per_unit: float = SOLO_LONG1_BOUCLE_BON_M_PAR_UNITE
    solo_long1_boucle_moyen_m_per_unit: float = SOLO_LONG1_BOUCLE_MOYEN_M_PAR_UNITE
    solo_long1_boucle_mauvais_m_per_unit: float = SOLO_LONG1_BOUCLE_MAUVAIS_M_PAR_UNITE
    solo_kl_boucle_bon_w_m_k: float = SOLO_KL_BOUCLE_BON_W_M_K
    solo_kl_boucle_moyen_w_m_k: float = SOLO_KL_BOUCLE_MOYEN_W_M_K
    solo_kl_boucle_mauvais_w_m_k: float = SOLO_KL_BOUCLE_MAUVAIS_W_M_K

    # Paramètres généraux SOLO.
    solo_vecs_unit_ref_l_day: float = 100.0
    solo_tref_bouclage_c: float = 55.0
    solo_tenv_bouclage_c: float = 20.0
    solo_monthly_temperatures_c: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_LOOP_AMBIENT_TEMPERATURES_C)
    )
    solo_active_ratio: float = 1.0

    # Champ hérité V13, conservé pour pouvoir recharger les anciens JSON.
    solo_quality: str = "Moyen"


@dataclass(frozen=True)
class MonthlyNeed:
    month: str
    days: int
    volume_l_60c: float
    average_l_day_60c: float
    cold_water_temperature_c: float
    useful_energy_kwh: float
    useful_energy_mwh: float
    gas_consumption_kwh: float
    gas_baseload_kwh: float
    global_ecs_after_boiler_kwh: float
    heating_after_boiler_kwh: float
    heating_after_boiler_mwh: float
    loop_losses_kwh: float
    loop_losses_mwh: float
    total_ecs_energy_kwh: float
    total_ecs_energy_mwh: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StorageProposal:
    total_volume_l: int
    tank_sizes_l: tuple[int, ...]
    tank_count: int
    target_daily_volume_l: float
    difference_l: float
    difference_percent: float | None

    @property
    def label(self) -> str:
        counts: dict[int, int] = {}
        for size in self.tank_sizes_l:
            counts[size] = counts.get(size, 0) + 1
        parts = [f"{count} × {size} L" for size, count in sorted(counts.items())]
        return " + ".join(parts) + f" = {self.total_volume_l} L"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["label"] = self.label
        return data


@dataclass(frozen=True)
class CollectorProposal:
    collector_count: int
    collector_unit_area_m2: float
    surface_m2: float
    storage_volume_l: int
    storage_ratio_l_m2: float
    target_storage_ratio_l_m2: float
    is_balanced_count: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OpportunityResults:
    monthly_needs: tuple[MonthlyNeed, ...]
    annual_volume_l_60c: float
    average_daily_volume_l_60c: float
    annual_useful_energy_mwh: float
    annual_loop_losses_mwh: float
    annual_total_ecs_energy_mwh: float
    annual_heating_after_boiler_mwh: float
    gas_summer_baseload_daily_kwh: float
    reference_unit_count: float
    solo_reference_volume_l_day_per_unit: float
    storage: StorageProposal
    collectors: CollectorProposal
    estimated_solar_production_mwh_year: float
    default_productivity_kwh_m2_year: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "monthly_needs": [row.as_dict() for row in self.monthly_needs],
            "annual_volume_l_60c": self.annual_volume_l_60c,
            "average_daily_volume_l_60c": self.average_daily_volume_l_60c,
            "annual_useful_energy_mwh": self.annual_useful_energy_mwh,
            "annual_loop_losses_mwh": self.annual_loop_losses_mwh,
            "annual_total_ecs_energy_mwh": self.annual_total_ecs_energy_mwh,
            "annual_heating_after_boiler_mwh": self.annual_heating_after_boiler_mwh,
            "gas_summer_baseload_daily_kwh": self.gas_summer_baseload_daily_kwh,
            "reference_unit_count": self.reference_unit_count,
            "solo_reference_volume_l_day_per_unit": self.solo_reference_volume_l_day_per_unit,
            "storage": self.storage.as_dict(),
            "collectors": self.collectors.as_dict(),
            "estimated_solar_production_mwh_year": self.estimated_solar_production_mwh_year,
            "default_productivity_kwh_m2_year": self.default_productivity_kwh_m2_year,
        }


def _normalise_data_source(value: str) -> str:
    if value in DATA_SOURCES:
        return value
    if value in {"Campagne de mesure ECS", "Factures ou relevés partiels", "Mesure"}:
        return "Mesure de consommation ECS"
    return "Ratio SOCOL"


def _normalise_loop_loss_mode_label(value: str | None, legacy_quality: str | None = None) -> str:
    if value in SOLO_LOOP_LOSS_MODE_LABELS:
        return str(value)
    if legacy_quality in SOLO_QUALITY_TO_LOSS_MODE_LABEL:
        return SOLO_QUALITY_TO_LOSS_MODE_LABEL[str(legacy_quality)]
    if value in SOLO_LOOP_LOSS_LABEL_BY_MODE:
        return SOLO_LOOP_LOSS_LABEL_BY_MODE[str(value)]
    if value in {"Bon", "Moyen", "Mauvais"}:
        return SOLO_QUALITY_TO_LOSS_MODE_LABEL[str(value)]
    return "Boucle qualité moyenne"


def _normalise_type_bouclage_label(value: str | None) -> str:
    if value in SOLO_TYPE_BOUCLAGE_LABELS:
        return str(value)
    if value == "aucun_apport":
        return "Sans apport solaire au bouclage"
    if value == "apport_indirect":
        return "Avec apport solaire indirect au bouclage"
    return "Avec apport solaire indirect au bouclage"


def _validate_typology(typology: str) -> None:
    if typology not in SITE_TYPOLOGIES:
        raise ValueError(f"Typologie non reconnue : {typology}")


def _monthly_volumes_l_60c(site: SiteInputs, needs: NeedsInputs) -> dict[str, float]:
    """Calcule le volume mensuel d'ECS à 60 °C selon la typologie et la source."""

    _validate_typology(site.typology)
    source = _normalise_data_source(site.data_source)
    volumes: dict[str, float] = {}

    if source == "Mesure de consommation ECS":
        for month, days in MONTHS:
            measured_daily_l = max(0.0, needs.measured_daily_l_60c_by_month.get(month, 0.0))
            volumes[month] = measured_daily_l * days
        return volumes

    if site.typology == "Logement collectif":
        base_daily_volume = sum(
            max(0, needs.housing_counts.get(kind, 0)) * max(0.0, needs.housing_ratios_l_day.get(kind, 0.0))
            for kind in HOUSING_RATIOS_L_PER_DWELLING_DAY
        )
        for month, days in MONTHS:
            coefficient = max(0.0, needs.monthly_coefficients.get(month, 1.0))
            volumes[month] = base_daily_volume * days * coefficient
        return volumes

    if site.typology in {"EHPAD", "Hôpital"}:
        base_daily_volume = max(0, needs.residents_or_beds) * max(0.0, needs.liters_per_resident_or_bed_day)
        for month, days in MONTHS:
            coefficient = max(0.0, needs.monthly_coefficients.get(month, 1.0))
            volumes[month] = base_daily_volume * days * coefficient
        return volumes

    if site.typology in {"Camping", "Hôtel"}:
        liters_per_unit = max(0.0, needs.liters_per_occupied_unit)
        for month, _days in MONTHS:
            occupancy = max(0.0, needs.monthly_occupancy.get(month, 0.0))
            volumes[month] = occupancy * liters_per_unit
        return volumes

    if site.typology == "Station de lavage":
        base_daily_volume = max(0.0, needs.car_wash_vehicles_per_day) * max(0.0, needs.car_wash_liters_per_vehicle)
        for month, days in MONTHS:
            volumes[month] = base_daily_volume * days
        return volumes

    raise ValueError(f"Typologie non traitée : {site.typology}")




def estimate_reference_unit_count(site: SiteInputs, needs: NeedsInputs) -> float:
    """Estime le nombre d'unités de référence du site.

    Cette valeur sert uniquement au bouclage SOLO pour convertir le besoin
    journalier moyen total en un volume ECS de référence par unité :
    logement, résident/lit, chambre-nuitée ou personne-nuitée selon la
    typologie. Si aucune unité exploitable n'est renseignée, on renvoie 0 et
    le calcul conserve un comportement de repli.
    """

    if site.typology == "Logement collectif":
        return float(sum(max(0, int(needs.housing_counts.get(kind, 0))) for kind in HOUSING_RATIOS_L_PER_DWELLING_DAY))

    if site.typology in {"EHPAD", "Hôpital"}:
        return float(max(0, int(needs.residents_or_beds)))

    if site.typology in {"Camping", "Hôtel"}:
        total_occupancy = sum(max(0.0, float(needs.monthly_occupancy.get(month, 0.0))) for month in MONTH_NAMES)
        return total_occupancy / 365.0 if total_occupancy > 0 else 0.0

    if site.typology == "Station de lavage":
        return max(0.0, float(needs.car_wash_vehicles_per_day))

    return 0.0


def compute_solo_reference_volume_l_day_per_unit(
    average_daily_volume_l_60c: float,
    reference_unit_count: float,
) -> float:
    """Renvoie le volume ECS de référence par unité utilisé par SOLO.

    Formule métier : conso moyenne journalière totale / nombre d'unités.
    En absence d'unité connue, on se replie sur la conso moyenne journalière
    totale pour éviter une division par zéro et garder un calcul non bloquant.
    """

    average = max(0.0, float(average_daily_volume_l_60c))
    units = max(0.0, float(reference_unit_count))
    if average <= 0:
        return 0.0
    if units <= 0:
        return average
    return average / units

def _build_base_monthly_needs(
    site: SiteInputs,
    needs: NeedsInputs,
    sizing: SizingInputs,
) -> tuple[MonthlyNeed, ...]:
    monthly_volumes = _monthly_volumes_l_60c(site, needs)
    ecs_temperature_c = max(0.0, float(needs.ecs_temperature_c or 60.0))
    rows: list[MonthlyNeed] = []
    for month, days in MONTHS:
        volume_l = monthly_volumes[month]
        t_ef = sizing.cold_water_temperatures_c.get(month, 15.0)
        delta_t = max(0.0, ecs_temperature_c - t_ef)
        useful_energy_kwh = volume_l * CP_WHLK * delta_t / 1000.0
        rows.append(
            MonthlyNeed(
                month=month,
                days=days,
                volume_l_60c=volume_l,
                average_l_day_60c=volume_l / days if days else 0.0,
                cold_water_temperature_c=t_ef,
                useful_energy_kwh=useful_energy_kwh,
                useful_energy_mwh=useful_energy_kwh / 1000.0,
                gas_consumption_kwh=0.0,
                gas_baseload_kwh=0.0,
                global_ecs_after_boiler_kwh=0.0,
                heating_after_boiler_kwh=0.0,
                heating_after_boiler_mwh=0.0,
                loop_losses_kwh=0.0,
                loop_losses_mwh=0.0,
                total_ecs_energy_kwh=useful_energy_kwh,
                total_ecs_energy_mwh=useful_energy_kwh / 1000.0,
            )
        )
    return tuple(rows)


def _gas_summer_baseload(loop: LoopInputs) -> tuple[float, str | None]:
    """Renvoie le talon gaz journalier estival et le mois qui le porte.

    Le talon est recherché entre juin et septembre en kWh PCI/PCS facturés
    par jour. On conserve le mois associé pour estimer les pertes de
    bouclage à partir du besoin utile de ce mois représentatif.
    """

    candidates: list[tuple[float, str]] = []
    for month in SUMMER_MONTHS_FOR_GAS_BASELOAD:
        gas_kwh = max(0.0, loop.gas_monthly_kwh.get(month, 0.0))
        days = DAYS_BY_MONTH[month]
        if gas_kwh > 0 and days > 0:
            candidates.append((gas_kwh / days, month))
    return min(candidates, key=lambda item: item[0]) if candidates else (0.0, None)


def _gas_summer_baseload_daily_kwh(loop: LoopInputs) -> float:
    return _gas_summer_baseload(loop)[0]


def _solo_loop_mode(loop: LoopInputs) -> str:
    label = _normalise_loop_loss_mode_label(loop.solo_loss_mode_label, loop.solo_quality)
    return SOLO_LOOP_LOSS_MODE_BY_LABEL[label]


def _solo_loop_text_min_c(loop: LoopInputs) -> float:
    vals = [float(loop.solo_monthly_temperatures_c.get(month, 20.0)) for month in MONTH_NAMES]
    return min(vals) if vals else 20.0


def _solo_calc_kg_bouclage_w_k(monthly_row: MonthlyNeed, loop: LoopInputs, text_min_annuel_c: float) -> float:
    """Reprise de _calc_kg_bouclage_w_k du module SOLO 2018 fourni."""

    mode = _solo_loop_mode(loop)
    if mode == "aucune" or mode == "saisie_kwh_j":
        return 0.0

    if mode in ("bon", "moyen", "mauvais"):
        if monthly_row.average_l_day_60c <= 0:
            return 0.0
        nb_unites_estime = monthly_row.average_l_day_60c / max(1e-6, loop.solo_vecs_unit_ref_l_day)
        if mode == "bon":
            long1 = loop.solo_long1_boucle_bon_m_per_unit
            kl = loop.solo_kl_boucle_bon_w_m_k
        elif mode == "moyen":
            long1 = loop.solo_long1_boucle_moyen_m_per_unit
            kl = loop.solo_kl_boucle_moyen_w_m_k
        else:
            long1 = loop.solo_long1_boucle_mauvais_m_per_unit
            kl = loop.solo_kl_boucle_mauvais_w_m_k
        long_boucle = nb_unites_estime * long1
        return max(0.0, long_boucle * kl)

    if mode == "long_kl":
        return max(0.0, loop.solo_long_bouclage_m * loop.solo_kl_bouclage_w_m_k)

    # mode == "debit_delta"
    text_boucle_min = 0.5 * (text_min_annuel_c + loop.solo_tenv_bouclage_c)
    p_perte_boucle_max_w = (
        loop.solo_debit_bouclage_l_h
        * loop.solo_delta_tmax_bouclage_k
        * CP_EAU_WH_L_K_SOLO
    )
    denom = max(1e-6, loop.solo_tref_bouclage_c - text_boucle_min)
    return max(0.0, p_perte_boucle_max_w / denom)


def _solo_loop_loss_kwh(monthly_row: MonthlyNeed, loop: LoopInputs, text_min_annuel_c: float) -> float:
    """Reprise de pertes_bouclage_kwh_j du module SOLO 2018 fourni, puis cumul mensuel."""

    mode = _solo_loop_mode(loop)
    if mode == "saisie_kwh_j":
        if loop.solo_losses_input_mode == "Saisie mensuelle":
            loss_kwh_day = max(0.0, loop.solo_losses_monthly_kwh_day.get(monthly_row.month, 0.0))
        else:
            loss_kwh_day = max(0.0, loop.solo_losses_annual_kwh) / 365.0
        return loss_kwh_day * monthly_row.days

    kg_boucle = _solo_calc_kg_bouclage_w_k(monthly_row, loop, text_min_annuel_c)
    if kg_boucle <= 0:
        return 0.0
    month_text_c = float(loop.solo_monthly_temperatures_c.get(monthly_row.month, 20.0))
    text_boucle = 0.5 * (loop.solo_tenv_bouclage_c + month_text_c)
    p_perte_boucle_w = kg_boucle * max(0.0, loop.solo_tref_bouclage_c - text_boucle)
    e_perte_boucle_kwh_j = 24.0 * p_perte_boucle_w / 1000.0
    return max(0.0, e_perte_boucle_kwh_j * max(0.0, loop.solo_active_ratio) * monthly_row.days)


def build_monthly_needs(
    site: SiteInputs,
    needs: NeedsInputs,
    sizing: SizingInputs,
    loop: LoopInputs | None = None,
) -> tuple[MonthlyNeed, ...]:
    """Construit le tableau mensuel volume ECS, besoin utile et bouclage sanitaire."""

    loop = loop or LoopInputs()
    base_rows = _build_base_monthly_needs(site, needs, sizing)

    # Pour les modes SOLO bon/moyen/mauvais, le champ historique
    # vecs_unite_ref_l_j ne doit pas être une saisie utilisateur dans l'onglet
    # bouclage. Il est déduit automatiquement du besoin ECS estimé :
    # conso moyenne journalière totale / nombre d'unités du site.
    annual_volume_l_60c = sum(row.volume_l_60c for row in base_rows)
    average_daily_volume_l_60c = annual_volume_l_60c / 365.0 if annual_volume_l_60c > 0 else 0.0
    reference_unit_count = estimate_reference_unit_count(site, needs)
    solo_reference_volume_l_day_per_unit = compute_solo_reference_volume_l_day_per_unit(
        average_daily_volume_l_60c,
        reference_unit_count,
    )
    if solo_reference_volume_l_day_per_unit > 0:
        loop = replace(loop, solo_vecs_unit_ref_l_day=solo_reference_volume_l_day_per_unit)

    rows: list[MonthlyNeed] = []
    gas_baseload_daily_kwh, gas_baseload_month = _gas_summer_baseload(loop)
    boiler_efficiency = min(1.0, max(0.0, loop.boiler_efficiency))
    text_min_annuel_c = _solo_loop_text_min_c(loop)

    # Méthode factures gaz : le talon est une valeur journalière d'été.
    # Après rendement chaudière, on retranche le besoin utile journalier du mois
    # qui porte le talon pour obtenir une perte de bouclage journalière constante.
    # Cette perte journalière est ensuite multipliée par le nombre exact de jours
    # de chaque mois. Le besoin utile, lui, reste mensuel et varie avec les
    # coefficients de modulation et la température d'eau froide.
    useful_daily_kwh_at_gas_baseload = 0.0
    if gas_baseload_month is not None:
        talon_row = next((base for base in base_rows if base.month == gas_baseload_month), None)
        if talon_row is not None and talon_row.days > 0:
            useful_daily_kwh_at_gas_baseload = talon_row.useful_energy_kwh / talon_row.days
    loop_losses_daily_kwh_from_gas = max(
        0.0,
        gas_baseload_daily_kwh * boiler_efficiency - useful_daily_kwh_at_gas_baseload,
    )

    for row in base_rows:
        gas_consumption_kwh = 0.0
        gas_baseload_kwh = 0.0
        global_after_boiler_kwh = 0.0
        heating_after_boiler_kwh = 0.0
        if loop.method == "Analyse factures gaz":
            gas_consumption_kwh = max(0.0, loop.gas_monthly_kwh.get(row.month, 0.0))
            gas_baseload_kwh = gas_baseload_daily_kwh * row.days
            global_after_boiler_kwh = gas_baseload_kwh * boiler_efficiency
            heating_after_boiler_kwh = max(0.0, gas_consumption_kwh - gas_baseload_kwh) * boiler_efficiency
            loop_losses_kwh = loop_losses_daily_kwh_from_gas * row.days
        elif loop.method == "Aucun bouclage sanitaire":
            gas_consumption_kwh = max(0.0, loop.gas_monthly_kwh.get(row.month, 0.0))
            if loop.include_heating_estimate_without_loop:
                global_after_boiler_kwh = gas_consumption_kwh * boiler_efficiency
                heating_after_boiler_kwh = max(0.0, global_after_boiler_kwh - row.useful_energy_kwh)
            loop_losses_kwh = 0.0
        elif loop.method == "Hypothèses SOLO 2018":
            loop_losses_kwh = _solo_loop_loss_kwh(row, loop, text_min_annuel_c)
        else:
            loop_losses_kwh = 0.0

        total_ecs_kwh = row.useful_energy_kwh + loop_losses_kwh
        rows.append(
            MonthlyNeed(
                month=row.month,
                days=row.days,
                volume_l_60c=row.volume_l_60c,
                average_l_day_60c=row.average_l_day_60c,
                cold_water_temperature_c=row.cold_water_temperature_c,
                useful_energy_kwh=row.useful_energy_kwh,
                useful_energy_mwh=row.useful_energy_mwh,
                gas_consumption_kwh=gas_consumption_kwh,
                gas_baseload_kwh=gas_baseload_kwh,
                global_ecs_after_boiler_kwh=global_after_boiler_kwh,
                heating_after_boiler_kwh=heating_after_boiler_kwh,
                heating_after_boiler_mwh=heating_after_boiler_kwh / 1000.0,
                loop_losses_kwh=loop_losses_kwh,
                loop_losses_mwh=loop_losses_kwh / 1000.0,
                total_ecs_energy_kwh=total_ecs_kwh,
                total_ecs_energy_mwh=total_ecs_kwh / 1000.0,
            )
        )
    return tuple(rows)


def _all_tank_combinations(max_tank_count: int) -> tuple[tuple[int, ...], ...]:
    combos: list[tuple[int, ...]] = []
    max_count = max(1, max_tank_count)
    for count in range(1, max_count + 1):
        combos.extend(combinations_with_replacement(STANDARD_TANK_SIZES_L, count))
    return tuple(combos)


def propose_storage(average_daily_volume_l_60c: float, max_tank_count: int = 3) -> StorageProposal:
    """Propose un stockage standard proche du volume journalier moyen.

    La sélection privilégie les ballons identiques, par exemple 2 × 1000 L,
    plutôt qu'une combinaison hétérogène, car c'est plus simple à concevoir,
    équilibrer et expliquer dans une note d'opportunité.
    """

    target = max(0.0, average_daily_volume_l_60c)
    combos = _all_tank_combinations(max_tank_count)
    if not combos:
        raise ValueError("Aucune combinaison de stockage disponible.")

    def is_homogeneous(combo: tuple[int, ...]) -> bool:
        return len(set(combo)) == 1

    def score(combo: tuple[int, ...]) -> tuple[int, float, int, int]:
        total = sum(combo)
        return (0 if is_homogeneous(combo) else 1, abs(total - target), len(combo), total)

    best = min(combos, key=score)
    total = sum(best)
    diff = total - target
    diff_percent = (diff / target) if target > 0 else None
    return StorageProposal(
        total_volume_l=total,
        tank_sizes_l=best,
        tank_count=len(best),
        target_daily_volume_l=target,
        difference_l=diff,
        difference_percent=diff_percent,
    )


def propose_storage_for_collector_surface(
    target_daily_volume_l_60c: float,
    collector_surface_m2: float,
    max_tank_count: int = 3,
    target_storage_ratio_l_m2: float = DEFAULT_TARGET_STORAGE_RATIO_L_M2,
) -> StorageProposal:
    """Propose un stockage compatible avec une surface capteurs contrainte.

    Quand l'emprise disponible plafonne la surface solaire, le volume de stockage
    est recalé pour rester dans la plage standard 50 à 70 L/m².
    """

    surface = max(0.0, float(collector_surface_m2))
    if surface <= 0:
        return propose_storage(target_daily_volume_l_60c, max_tank_count)

    min_volume_l = surface * MIN_STORAGE_RATIO_L_M2
    max_volume_l = surface * MAX_STORAGE_RATIO_L_M2
    target_ratio_volume_l = surface * max(
        MIN_STORAGE_RATIO_L_M2,
        min(MAX_STORAGE_RATIO_L_M2, float(target_storage_ratio_l_m2)),
    )
    target_daily_volume_l = max(0.0, float(target_daily_volume_l_60c))
    target = min(target_daily_volume_l, target_ratio_volume_l) if target_daily_volume_l > 0 else target_ratio_volume_l

    combos = _all_tank_combinations(max_tank_count)
    if not combos:
        raise ValueError("Aucune combinaison de stockage disponible.")

    def is_homogeneous(combo: tuple[int, ...]) -> bool:
        return len(set(combo)) == 1

    valid_combos = [combo for combo in combos if min_volume_l <= sum(combo) <= max_volume_l]
    candidate_pool = valid_combos or combos

    def score(combo: tuple[int, ...]) -> tuple[int, float, float, int, int]:
        total = sum(combo)
        if total < min_volume_l:
            bound_gap = min_volume_l - total
        elif total > max_volume_l:
            bound_gap = total - max_volume_l
        else:
            bound_gap = 0.0
        return (0 if bound_gap == 0 else 1, bound_gap, abs(total - target), 0 if is_homogeneous(combo) else 1, len(combo))

    best = min(candidate_pool, key=score)
    total = sum(best)
    diff = total - target_daily_volume_l
    diff_percent = (diff / target_daily_volume_l) if target_daily_volume_l > 0 else None
    return StorageProposal(
        total_volume_l=total,
        tank_sizes_l=best,
        tank_count=len(best),
        target_daily_volume_l=target_daily_volume_l,
        difference_l=diff,
        difference_percent=diff_percent,
    )


def _is_balanced_collector_count(count: int) -> bool:
    return count > 0 and (count % 2 == 0 or count % 3 == 0)


def propose_collectors(
    storage_volume_l: int,
    collector_unit_area_m2: float = DEFAULT_COLLECTOR_UNIT_AREA_M2,
    target_storage_ratio_l_m2: float = DEFAULT_TARGET_STORAGE_RATIO_L_M2,
    max_collector_surface_m2: float | None = None,
) -> CollectorProposal:
    """Propose une seule surface capteurs, centrée au plus près de 60 L/m²."""

    if collector_unit_area_m2 <= 0:
        raise ValueError("La surface unitaire capteur doit être strictement positive.")
    if storage_volume_l <= 0:
        raise ValueError("Le volume de stockage doit être strictement positif.")

    min_count = max(1, int(storage_volume_l / MAX_STORAGE_RATIO_L_M2 / collector_unit_area_m2) - 2)
    max_count = max(min_count + 1, ceil(storage_volume_l / MIN_STORAGE_RATIO_L_M2 / collector_unit_area_m2) + 4)
    if max_collector_surface_m2 is not None and max_collector_surface_m2 > 0:
        capped_count = int(max_collector_surface_m2 // collector_unit_area_m2)
        if capped_count < 1:
            return CollectorProposal(
                collector_count=0,
                collector_unit_area_m2=collector_unit_area_m2,
                surface_m2=0.0,
                storage_volume_l=storage_volume_l,
                storage_ratio_l_m2=float("inf"),
                target_storage_ratio_l_m2=target_storage_ratio_l_m2,
                is_balanced_count=False,
            )
        max_count = min(max_count, capped_count)
        min_count = min(min_count, max_count)

    candidates: list[CollectorProposal] = []
    for count in range(min_count, max_count + 1):
        surface = count * collector_unit_area_m2
        ratio = storage_volume_l / surface
        candidates.append(
            CollectorProposal(
                collector_count=count,
                collector_unit_area_m2=collector_unit_area_m2,
                surface_m2=surface,
                storage_volume_l=storage_volume_l,
                storage_ratio_l_m2=ratio,
                target_storage_ratio_l_m2=target_storage_ratio_l_m2,
                is_balanced_count=_is_balanced_collector_count(count),
            )
        )

    constrained = [
        candidate
        for candidate in candidates
        if MIN_STORAGE_RATIO_L_M2 <= candidate.storage_ratio_l_m2 <= MAX_STORAGE_RATIO_L_M2
    ] or candidates

    balanced = [candidate for candidate in constrained if candidate.is_balanced_count]
    candidate_pool = balanced or constrained

    def score(candidate: CollectorProposal) -> tuple[float, int, float]:
        return (
            abs(candidate.storage_ratio_l_m2 - target_storage_ratio_l_m2),
            0 if candidate.is_balanced_count else 1,
            candidate.surface_m2,
        )

    return min(candidate_pool, key=score)


def compute_opportunity_results(
    site: SiteInputs,
    needs: NeedsInputs,
    sizing: SizingInputs,
    loop: LoopInputs | None = None,
) -> OpportunityResults:
    loop = loop or LoopInputs()
    monthly = build_monthly_needs(site, needs, sizing, loop)
    annual_volume_l_equivalent_60c = sum(
        row.useful_energy_kwh * 1000.0 / (CP_WHLK * max(1e-6, 60.0 - float(row.cold_water_temperature_c)))
        for row in monthly
    )
    average_daily_l = annual_volume_l_equivalent_60c / 365.0
    annual_useful_energy_mwh = sum(row.useful_energy_mwh for row in monthly)
    annual_loop_losses_mwh = sum(row.loop_losses_mwh for row in monthly)
    annual_total_ecs_energy_mwh = sum(row.total_ecs_energy_mwh for row in monthly)
    annual_heating_after_boiler_mwh = sum(row.heating_after_boiler_mwh for row in monthly)
    reference_unit_count = estimate_reference_unit_count(site, needs)
    solo_reference_volume_l_day_per_unit = compute_solo_reference_volume_l_day_per_unit(
        average_daily_l,
        reference_unit_count,
    )
    storage = propose_storage(average_daily_l, sizing.max_tank_count)
    collectors = propose_collectors(
        storage.total_volume_l,
        sizing.collector_unit_area_m2,
        sizing.target_storage_ratio_l_m2,
        sizing.max_collector_surface_m2,
    )
    if (
        sizing.max_collector_surface_m2 is not None
        and sizing.max_collector_surface_m2 > 0
        and collectors.surface_m2 > 0
        and collectors.storage_ratio_l_m2 > MAX_STORAGE_RATIO_L_M2
    ):
        storage = propose_storage_for_collector_surface(
            average_daily_l,
            collectors.surface_m2,
            sizing.max_tank_count,
            sizing.target_storage_ratio_l_m2,
        )
        collectors = propose_collectors(
            storage.total_volume_l,
            sizing.collector_unit_area_m2,
            sizing.target_storage_ratio_l_m2,
            sizing.max_collector_surface_m2,
        )
    estimated_production = collectors.surface_m2 * sizing.productivity_kwh_m2_year / 1000.0
    return OpportunityResults(
        monthly_needs=monthly,
        annual_volume_l_60c=annual_volume_l_equivalent_60c,
        average_daily_volume_l_60c=average_daily_l,
        annual_useful_energy_mwh=annual_useful_energy_mwh,
        annual_loop_losses_mwh=annual_loop_losses_mwh,
        annual_total_ecs_energy_mwh=annual_total_ecs_energy_mwh,
        annual_heating_after_boiler_mwh=annual_heating_after_boiler_mwh,
        gas_summer_baseload_daily_kwh=_gas_summer_baseload_daily_kwh(loop),
        reference_unit_count=reference_unit_count,
        solo_reference_volume_l_day_per_unit=solo_reference_volume_l_day_per_unit,
        storage=storage,
        collectors=collectors,
        estimated_solar_production_mwh_year=estimated_production,
        default_productivity_kwh_m2_year=sizing.productivity_kwh_m2_year,
    )


def dict_to_site_inputs(data: dict[str, Any] | None) -> SiteInputs:
    defaults = asdict(SiteInputs())
    if data:
        data = dict(data)
        data["data_source"] = _normalise_data_source(str(data.get("data_source", defaults["data_source"])))
        defaults.update(data)
    allowed = {f.name for f in fields(SiteInputs)}
    return SiteInputs(**{k: v for k, v in defaults.items() if k in allowed})


def dict_to_needs_inputs(data: dict[str, Any] | None) -> NeedsInputs:
    defaults = asdict(NeedsInputs())
    if data:
        defaults.update(data)
    allowed = {f.name for f in fields(NeedsInputs)}
    return NeedsInputs(**{k: v for k, v in defaults.items() if k in allowed})


def dict_to_sizing_inputs(data: dict[str, Any] | None) -> SizingInputs:
    defaults = asdict(SizingInputs())
    if data:
        defaults.update(data)
    allowed = {f.name for f in fields(SizingInputs)}
    return SizingInputs(**{k: v for k, v in defaults.items() if k in allowed})


def dict_to_loop_inputs(data: dict[str, Any] | None) -> LoopInputs:
    defaults = asdict(LoopInputs())
    if data:
        data = dict(data)
        # Migration V13 -> V14.
        if "solo_ambient_temperatures_c" in data and "solo_monthly_temperatures_c" not in data:
            data["solo_monthly_temperatures_c"] = data.pop("solo_ambient_temperatures_c")
        if "solo_loss_mode_label" not in data:
            data["solo_loss_mode_label"] = _normalise_loop_loss_mode_label(None, data.get("solo_quality"))
        defaults.update(data)
    if defaults.get("method") not in LOOP_METHODS:
        defaults["method"] = "Analyse factures gaz"
    defaults["solo_type_bouclage_label"] = _normalise_type_bouclage_label(defaults.get("solo_type_bouclage_label"))
    defaults["solo_loss_mode_label"] = _normalise_loop_loss_mode_label(
        defaults.get("solo_loss_mode_label"), defaults.get("solo_quality")
    )
    if defaults.get("solo_losses_input_mode") not in SOLO_LOSS_INPUT_MODES:
        defaults["solo_losses_input_mode"] = "Saisie annuelle"
    allowed = {f.name for f in fields(LoopInputs)}
    return LoopInputs(**{k: v for k, v in defaults.items() if k in allowed})

