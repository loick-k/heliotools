from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .data import location_from_label, weather_for_city

MONTHS_FR = [
    "Janvier",
    "Février",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Août",
    "Septembre",
    "Octobre",
    "Novembre",
    "Décembre",
]

MONTH_CODES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

REGIMES = {
    "Bas (65°C/45°C)": 55.0,
    "Moyen (75°C/55°C)": 65.0,
    "Haut (85°C/65°C)": 75.0,
    "Très haut (95°C/75°C)": 85.0,
}

AID_FORFAITS = {
    "Nord": 63.0,
    "Sud": 56.0,
    "Méditerranée": 50.0,
}

CALCULATION_MODES = {
    "excel_v5_3": "Excel v5.3 - reproduction stricte",
    "presentation": "Méthode présentation - rendement réseau et 200 m/MW",
}

DEFAULT_MONTHLY_NEEDS_MWH = [
    1890.0,
    1463.0,
    1495.0,
    1162.0,
    758.0,
    375.0,
    339.0,
    339.0,
    353.0,
    671.0,
    1378.0,
    1790.0,
]

# Cells H19:H30 in workbook NO_STH_RCU_v5.3. They are constants, not formulas.
# They adjust the monthly irradiation profile for the seasonal efficiency of a
# high-performance glazed flat-plate collector. The annual productivity is
# calculated separately with the parametric equation below.
FPC_SEASONAL_CORRECTION_V53 = np.array(
    [
        0.22164752319180825,
        0.31480409782585017,
        0.38238716898163555,
        0.4197183768526124,
        0.4198204980062965,
        0.4319178843118203,
        0.4281466542448268,
        0.44161368385858546,
        0.4397232709068444,
        0.3906251470370936,
        0.2893862164629595,
        0.22542681948107146,
    ],
    dtype=float,
)

ECS_SEASONAL_COEFFICIENTS = np.array(
    [1.10, 1.10, 1.10, 1.10, 1.10, 0.85, 0.75, 0.75, 0.90, 1.05, 1.10, 1.10],
    dtype=float,
)


@dataclass(frozen=True)
class CalculationInputs:
    location_label: str
    zone: str
    regime_label: str
    mean_network_temperature_c: float
    base_load_fraction: float
    monthly_needs_mwh: list[float]
    other_aid_eur: float = 0.0
    electricity_price_eur_mwh: float = 245.1
    project_lifetime_years: int = 30
    discount_rate_override: float | None = None
    calculation_mode: str = "excel_v5_3"
    network_operates_summer: bool = True
    summer_excess_enr: bool = False
    land_identified: bool = True


@dataclass(frozen=True)
class CalculationResults:
    annual_need_mwh: float
    summer_need_share: float
    minimum_monthly_need_mwh: float
    annual_horizontal_irradiation_kwh_m2: float
    annual_solar_production_mwh: float
    solar_fraction: float
    productivity_kwh_m2_year: float
    collector_area_m2: float
    storage_volume_m3: float
    land_area_ha: float
    recommended_connection_distance_m: float
    capex_eur: float
    unit_capex_eur_m2: float
    ademe_aid_eur: float
    other_aid_eur: float
    remaining_cost_eur: float
    aid_rate: float
    p1_eur_mwh: float
    opex_eur_mwh: float
    capital_recovery_eur_mwh: float
    lcoh_aided_eur_mwh: float
    discount_rate: float
    panel_count_15m2: int
    latitude: float
    longitude: float
    city: str
    department: str
    scope_status: str
    opportunity_status: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_monthly_array(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.shape != (12,):
        raise ValueError("Les besoins mensuels doivent contenir exactement 12 valeurs.")
    if not np.all(np.isfinite(array)):
        raise ValueError("Les besoins mensuels contiennent une valeur non numérique.")
    if np.any(array < 0):
        raise ValueError("Les besoins mensuels ne peuvent pas être négatifs.")
    if float(array.sum()) <= 0:
        raise ValueError("La consommation annuelle doit être strictement positive.")
    return array


def estimate_monthly_needs(
    *,
    location_label: str,
    annual_heating_mwh: float,
    annual_ecs_mwh: float,
    network_efficiency: float,
    calculation_mode: str = "excel_v5_3",
) -> pd.DataFrame:
    """Estimate monthly district-heating needs from annual subscriber loads.

    ``excel_v5_3`` reproduces the workbook formula for constant losses:
    losses = (heating + ECS) * (1 - efficiency).

    ``presentation`` follows the interpretation used in the ADEME example:
    network input = subscriber needs / efficiency.
    """
    if annual_heating_mwh < 0 or annual_ecs_mwh < 0:
        raise ValueError("Les besoins annuels ne peuvent pas être négatifs.")
    if not 0 < network_efficiency <= 1:
        raise ValueError("Le rendement réseau doit être compris entre 0 et 1.")
    if calculation_mode not in CALCULATION_MODES:
        raise ValueError(f"Mode de calcul inconnu : {calculation_mode}")

    location = location_from_label(location_label)
    city = str(location["city"])
    weather = weather_for_city(city)
    ambient = weather["ambient_temp_c"].to_numpy(dtype=float)

    summer_reference = float(np.min(ambient[5:8]))  # June-August
    heating_degree_proxy = np.maximum(summer_reference - ambient, 0.0)
    if float(heating_degree_proxy.sum()) <= 0:
        heating_profile = np.full(12, 1 / 12, dtype=float)
    else:
        heating_profile = heating_degree_proxy / heating_degree_proxy.sum()

    heating = annual_heating_mwh * heating_profile
    ecs = annual_ecs_mwh / 12.0 * ECS_SEASONAL_COEFFICIENTS
    subscriber_total = annual_heating_mwh + annual_ecs_mwh
    if calculation_mode == "excel_v5_3":
        annual_losses = subscriber_total * (1.0 - network_efficiency)
    else:
        annual_losses = subscriber_total / network_efficiency - subscriber_total
    losses = np.full(12, annual_losses / 12.0, dtype=float)
    total = heating + ecs + losses

    return pd.DataFrame(
        {
            "Mois": MONTHS_FR,
            "Température extérieure moyenne (°C)": ambient,
            "Chauffage (MWh)": heating,
            "ECS (MWh)": ecs,
            "Pertes réseau (MWh)": losses,
            "Besoins RCU (MWh)": total,
        }
    )


def _unit_capex(surface_m2: float) -> float:
    if surface_m2 <= 100:
        return 1500.0
    if surface_m2 <= 1000:
        return 1500.0 - 0.5556 * (surface_m2 - 100.0)
    if surface_m2 <= 1500:
        return 1000.0 - 0.35 * (surface_m2 - 1000.0)
    return -159.1 * math.log(surface_m2) + 1990.2


def _capital_recovery_factor(rate: float, years: int) -> float:
    if years <= 0:
        raise ValueError("La durée de vie doit être strictement positive.")
    if rate == 0:
        return 1.0 / years
    growth = (1.0 + rate) ** years
    return rate * growth / (growth - 1.0)


def _ademe_aid(
    *,
    surface_m2: float,
    annual_production_mwh: float,
    capex_eur: float,
    aid_forfait_eur_mwh: float,
    other_aid_eur: float,
) -> float:
    if surface_m2 <= 0 or annual_production_mwh <= 0 or capex_eur <= 0:
        return 0.0
    transition = min(1.0, math.exp((1500.0 - surface_m2) / 1500.0))
    unit_cost = _unit_capex(surface_m2)
    indicative_aid = (
        min(surface_m2, 1500.0)
        * annual_production_mwh
        / surface_m2
        * aid_forfait_eur_mwh
        * 20.0
        * transition
        + (max(surface_m2, 1500.0) - 1500.0 * transition)
        * unit_cost
        * 0.5
    )
    cap_65_percent = (0.65 - other_aid_eur / capex_eur) * capex_eur
    return min(indicative_aid, cap_65_percent)


def calculate_opportunity(inputs: CalculationInputs) -> tuple[CalculationResults, pd.DataFrame]:
    if inputs.zone not in AID_FORFAITS:
        raise ValueError(f"Zone géographique inconnue : {inputs.zone}")
    if inputs.calculation_mode not in CALCULATION_MODES:
        raise ValueError(f"Mode de calcul inconnu : {inputs.calculation_mode}")
    if not 0 < inputs.base_load_fraction <= 1:
        raise ValueError("Le taux de dimensionnement au talon doit être compris entre 0 et 100 %.")
    if inputs.other_aid_eur < 0:
        raise ValueError("Les autres aides ne peuvent pas être négatives.")
    if inputs.electricity_price_eur_mwh < 0:
        raise ValueError("Le prix de l'électricité ne peut pas être négatif.")

    needs = _as_monthly_array(inputs.monthly_needs_mwh)
    location = location_from_label(inputs.location_label)
    city = str(location["city"])
    weather = weather_for_city(city)

    h_opt = weather["h_opt_kwh_m2"].to_numpy(dtype=float)
    h_horizontal = weather["h_horizontal_kwh_m2"].to_numpy(dtype=float)
    corrected_irradiation = h_opt * FPC_SEASONAL_CORRECTION_V53
    max_corrected = float(np.max(corrected_irradiation))
    if max_corrected <= 0:
        raise ValueError("Le profil d'irradiation corrigée est invalide.")
    solar_profile = corrected_irradiation / max_corrected

    annual_need = float(needs.sum())
    summer_need_share = float(needs[4:9].sum() / annual_need)
    minimum_need = float(np.min(needs))
    monthly_solar = inputs.base_load_fraction * minimum_need * solar_profile
    annual_solar = float(monthly_solar.sum())
    annual_horizontal = float(h_horizontal.sum())

    productivity = (
        0.4818 * annual_horizontal
        - 503.1 * summer_need_share
        + 1.1244 * summer_need_share * annual_horizontal
        - 199.6
    ) * (1.0 + 0.014 * (55.0 - inputs.mean_network_temperature_c))
    if productivity <= 0:
        raise ValueError(
            "La productivité calculée est négative ou nulle. Les hypothèses sont hors du domaine du modèle."
        )

    collector_area = annual_solar / (productivity / 1000.0)
    solar_fraction = annual_solar / annual_need
    storage = math.floor((0.2 * collector_area) / 10.0) * 10.0
    land_area = collector_area * 2.5 / 10000.0
    unit_capex = _unit_capex(collector_area)
    capex = collector_area * unit_capex

    if inputs.calculation_mode == "excel_v5_3":
        connection_distance = math.floor(0.3 * capex / 10000.0) * 10.0
    else:
        # Presentation: 200 m/MW and an order-of-magnitude peak power of 1 kW/m².
        connection_distance = math.floor((0.2 * collector_area) / 10.0) * 10.0

    ademe_aid = _ademe_aid(
        surface_m2=collector_area,
        annual_production_mwh=annual_solar,
        capex_eur=capex,
        aid_forfait_eur_mwh=AID_FORFAITS[inputs.zone],
        other_aid_eur=inputs.other_aid_eur,
    )
    # The workbook formula can become negative when other aids exceed 65 %.
    # The application avoids presenting a negative public grant.
    ademe_aid = max(0.0, ademe_aid)
    remaining_cost = capex - ademe_aid - inputs.other_aid_eur
    remaining_cost = max(0.0, remaining_cost)
    aid_rate = (ademe_aid + inputs.other_aid_eur) / capex if capex > 0 else 0.0

    discount_rate = (
        inputs.discount_rate_override
        if inputs.discount_rate_override is not None
        else (0.05 if collector_area < 500.0 else 0.06)
    )
    p1 = 0.015 * inputs.electricity_price_eur_mwh
    opex = 0.01 * capex / annual_solar
    capital_recovery = (
        _capital_recovery_factor(discount_rate, inputs.project_lifetime_years)
        * remaining_cost
        / annual_solar
    )
    lcoh = p1 + opex + capital_recovery

    warnings: list[str] = []
    if not inputs.network_operates_summer:
        warnings.append("Le réseau ne fonctionne pas en été : condition rédhibitoire dans le cadre de l'outil.")
    if inputs.summer_excess_enr:
        warnings.append("Une autre EnR&R est excédentaire en été : le talon solaire doit être adapté.")
    if not inputs.land_identified:
        warnings.append("Aucun foncier n'est identifié à ce stade.")
    if inputs.mean_network_temperature_c > 65:
        warnings.append("Régime élevé : un abaissement des températures du réseau est à étudier.")
    if collector_area < 100:
        warnings.append("Surface inférieure à 100 m² : hors du cadre de calibration de l'outil.")
    if solar_fraction < 0.10 or solar_fraction > 0.30:
        warnings.append("Fraction solaire hors de la plage de calibration indicative de 10 à 30 %.")
    if collector_area < 150:
        warnings.append("Surface inférieure au premier seuil d'opportunité de 150 à 250 m².")
    if collector_area > 1500:
        warnings.append("Au-delà de 1 500 m², l'aide ADEME affichée est seulement indicative.")
    if inputs.calculation_mode == "excel_v5_3":
        warnings.append("Mode compatibilité Excel v5.3 : pertes réseau et distance de raccordement reproduisent les formules du classeur.")

    scope_ok = 100 <= collector_area and 0.10 <= solar_fraction <= 0.30
    if scope_ok:
        scope_status = "Dans le cadre de calibration"
    else:
        scope_status = "Hors cadre ou à confirmer"

    hard_stop = (not inputs.network_operates_summer) or inputs.summer_excess_enr
    if hard_stop:
        opportunity_status = "Conditions préalables non réunies"
    elif solar_fraction >= 0.10 and collector_area >= 250:
        opportunity_status = "Opportunité favorable à approfondir"
    elif solar_fraction >= 0.05 and collector_area >= 150:
        opportunity_status = "Opportunité intermédiaire à qualifier"
    else:
        opportunity_status = "Opportunité faible avec les hypothèses actuelles"

    monthly = pd.DataFrame(
        {
            "Mois": MONTHS_FR,
            "Besoins RCU (MWh)": needs,
            "Irradiation inclinée (kWh/m²)": h_opt,
            "Coefficient FPC v5.3": FPC_SEASONAL_CORRECTION_V53,
            "Irradiation corrigée": corrected_irradiation,
            "Profil solaire normalisé": solar_profile,
            "Production solaire (MWh)": monthly_solar,
            "Taux de couverture mensuel": np.divide(
                monthly_solar,
                needs,
                out=np.zeros_like(monthly_solar),
                where=needs > 0,
            ),
        }
    )

    results = CalculationResults(
        annual_need_mwh=annual_need,
        summer_need_share=summer_need_share,
        minimum_monthly_need_mwh=minimum_need,
        annual_horizontal_irradiation_kwh_m2=annual_horizontal,
        annual_solar_production_mwh=annual_solar,
        solar_fraction=solar_fraction,
        productivity_kwh_m2_year=float(productivity),
        collector_area_m2=float(collector_area),
        storage_volume_m3=float(storage),
        land_area_ha=float(land_area),
        recommended_connection_distance_m=float(connection_distance),
        capex_eur=float(capex),
        unit_capex_eur_m2=float(unit_capex),
        ademe_aid_eur=float(ademe_aid),
        other_aid_eur=float(inputs.other_aid_eur),
        remaining_cost_eur=float(remaining_cost),
        aid_rate=float(aid_rate),
        p1_eur_mwh=float(p1),
        opex_eur_mwh=float(opex),
        capital_recovery_eur_mwh=float(capital_recovery),
        lcoh_aided_eur_mwh=float(lcoh),
        discount_rate=float(discount_rate),
        panel_count_15m2=int(math.floor(collector_area / 15.0)),
        latitude=float(location["latitude"]),
        longitude=float(location["longitude"]),
        city=city,
        department=str(location["department"]),
        scope_status=scope_status,
        opportunity_status=opportunity_status,
        warnings=warnings,
    )
    return results, monthly
