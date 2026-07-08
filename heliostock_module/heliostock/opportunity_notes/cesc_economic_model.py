"""Modèle économique CESC issu de l'onglet 'Simulateur eco CESC'.

Ce module reprend les formules de l'Excel Atlansun v5, sans dépendance à Excel.
Il est volontairement isolé de Streamlit pour rester testable et réutilisable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any


ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY: dict[str, float] = {
    "CESC": 1260.0,
    "SSC bâtiment existant": 2120.0,
    "SSC bâtiment neuf": 1120.0,
}

TYPOLOGY_LABELS: tuple[str, ...] = tuple(ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY)


def get_ademe_aid_eur_per_mwh_year(typologie: str) -> float:
    """Renvoie le forfait Fonds Chaleur ADEME associé à la typologie choisie."""

    try:
        return ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY[typologie]
    except KeyError as exc:
        allowed = ", ".join(TYPOLOGY_LABELS)
        raise ValueError(f"Typologie non reconnue : {typologie}. Valeurs possibles : {allowed}.") from exc


@dataclass(frozen=True)
class CescEconomicInputs:
    """Hypothèses d'entrée du modèle économique CESC.

    Les valeurs par défaut reproduisent l'onglet Excel analysé :
    - surface = 13 capteurs * 2,6 m² = 33,8 m²
    - productivité = 562 kWh/m².an
    - coût énergie de référence = 75 €/MWh
    - inflation énergie = 3 %/an
    - durée = 20 ans
    - coût travaux = 1 563 €HT/m²
    - typologie = CESC, avec forfait ADEME 1 260 €/MWh.an
    - eta_appoint = 0,82
    """

    typologie: str = "CESC"
    surface_m2: float = 13 * 2.6
    productivity_kwh_m2_year: float = 562.0
    reference_energy_cost_eur_mwh: float = 75.0
    reference_energy_inflation_rate: float = 0.03
    years: int = 20
    works_cost_eur_m2: float = 1563.0

    # Rendement global de l'appoint utilisé dans l'Excel : cellule B32.
    eta_appoint: float = 0.82

    # P1' : coût d'électricité auxiliaire.
    auxiliary_electricity_ratio: float = 0.03
    electricity_cost_eur_mwh: float = 200.0

    # P2 : suivi et maintenance.
    maintenance_cost_eur_m2_year: float = 22.0

    # P4 : FAE / études / frais assimilés.
    fae_cost_eur: float = 4929.0
    fae_aid_rate: float = 0.70

    # Aide ADEME Fonds Chaleur : le forfait est déterminé automatiquement
    # par la typologie, sauf si une valeur explicite est passée.
    ademe_aid_eur_per_mwh_year: float | None = None
    ademe_aid_max_rate_on_works: float = 0.65


def _annuity_average_factor(rate: float, years: int) -> float:
    """Facteur moyen sur la période pour un coût qui augmente de `rate` par an.

    Formule Excel d'origine : ((1+MAX(rate,0.001))^years-1)/(years*MAX(rate,0.001))
    Ici, on traite explicitement le cas rate = 0 pour éviter le plancher artificiel à 0,1 %.
    """

    if years <= 0:
        raise ValueError("La durée d'analyse doit être strictement positive.")
    if rate == 0:
        return 1.0
    return ((1.0 + rate) ** years - 1.0) / (years * rate)


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    value = numerator / denominator
    if not isfinite(value):
        return None
    return value


@dataclass(frozen=True)
class CostLine:
    category: str
    label: str
    total_cost_eur: float | None = None
    ademe_aid_eur: float | None = None
    net_cost_eur: float | None = None
    cost_eur_mwh_year: float | None = None


@dataclass(frozen=True)
class CescEconomicResults:
    annual_production_mwh: float
    average_reference_energy_cost_eur_mwh: float
    investment_cost_eur: float
    ademe_aid_eur_per_mwh_year_used: float
    works_aid_uncapped_eur: float
    works_aid_cap_eur: float
    aid_total_eur: float
    aid_rate: float | None
    net_investment_eur: float
    annual_savings_eur: float
    raw_payback_years: float | None
    solar_heat_cost_eur_mwh: float
    heat_cost_p1_eur_mwh: float | None
    heat_cost_p2_eur_mwh: float | None
    heat_cost_p4_eur_mwh: float | None
    savings_over_period_eur: float
    cost_lines: tuple[CostLine, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cost_lines"] = [asdict(line) for line in self.cost_lines]
        return data


def compute_cesc_economic_model(inputs: CescEconomicInputs) -> CescEconomicResults:
    """Calcule les indicateurs économiques CESC.

    Les formules suivent l'onglet Excel, avec une correction volontaire :
    si le taux d'inflation est nul, le coût moyen reste égal au coût initial
    au lieu d'appliquer le plancher Excel de 0,1 %.
    """

    if inputs.surface_m2 < 0:
        raise ValueError("La surface de capteurs ne peut pas être négative.")
    if inputs.productivity_kwh_m2_year < 0:
        raise ValueError("La productivité ne peut pas être négative.")
    if inputs.eta_appoint <= 0:
        raise ValueError("Le rendement appoint doit être strictement positif.")

    annual_production_mwh = inputs.surface_m2 * inputs.productivity_kwh_m2_year / 1000.0

    average_reference_energy_cost_eur_mwh = (
        inputs.reference_energy_cost_eur_mwh
        / inputs.eta_appoint
        * _annuity_average_factor(inputs.reference_energy_inflation_rate, inputs.years)
    )

    p1_auxiliary_electricity_eur = (
        inputs.auxiliary_electricity_ratio
        * annual_production_mwh
        * inputs.electricity_cost_eur_mwh
    )
    p1_auxiliary_electricity_eur_mwh = _safe_divide(
        p1_auxiliary_electricity_eur, annual_production_mwh
    )

    p2_maintenance_eur = inputs.maintenance_cost_eur_m2_year * inputs.surface_m2
    p2_maintenance_eur_mwh = _safe_divide(p2_maintenance_eur, annual_production_mwh)

    fae_cost_eur = inputs.fae_cost_eur
    fae_aid_eur = fae_cost_eur * inputs.fae_aid_rate
    fae_net_cost_eur = fae_cost_eur - fae_aid_eur

    works_cost_eur = inputs.surface_m2 * inputs.works_cost_eur_m2
    aid_eur_per_mwh_year = (
        inputs.ademe_aid_eur_per_mwh_year
        if inputs.ademe_aid_eur_per_mwh_year is not None
        else get_ademe_aid_eur_per_mwh_year(inputs.typologie)
    )
    works_aid_uncapped_eur = annual_production_mwh * aid_eur_per_mwh_year
    works_aid_cap_eur = inputs.ademe_aid_max_rate_on_works * works_cost_eur
    works_aid_eur = min(works_aid_uncapped_eur, works_aid_cap_eur)
    works_net_cost_eur = works_cost_eur - works_aid_eur

    investment_cost_eur = fae_cost_eur + works_cost_eur
    aid_total_eur = fae_aid_eur + works_aid_eur
    net_investment_eur = investment_cost_eur - aid_total_eur
    aid_rate = _safe_divide(aid_total_eur, investment_cost_eur)

    p4_investment_eur_mwh = _safe_divide(
        net_investment_eur, annual_production_mwh * inputs.years
    )
    solar_heat_cost_eur_mwh = sum(
        value or 0.0
        for value in (
            p1_auxiliary_electricity_eur_mwh,
            p2_maintenance_eur_mwh,
            p4_investment_eur_mwh,
        )
    )

    operating_costs_eur_mwh = (p1_auxiliary_electricity_eur_mwh or 0.0) + (
        p2_maintenance_eur_mwh or 0.0
    )
    annual_savings_eur = annual_production_mwh * (
        average_reference_energy_cost_eur_mwh - operating_costs_eur_mwh
    )

    raw_payback_years = None
    if annual_savings_eur > 0:
        raw_payback_years = net_investment_eur / annual_savings_eur

    savings_over_period_eur = annual_savings_eur * inputs.years - net_investment_eur

    cost_lines = (
        CostLine(
            category="P1' - Coût de l'énergie",
            label="Coût élec.",
            total_cost_eur=p1_auxiliary_electricity_eur,
            cost_eur_mwh_year=p1_auxiliary_electricity_eur_mwh,
        ),
        CostLine(
            category="P2 - Entretien et maintenance",
            label="Suivi et maintenance",
            total_cost_eur=p2_maintenance_eur,
            cost_eur_mwh_year=p2_maintenance_eur_mwh,
        ),
        CostLine(
            category="P4 - Investissement initial",
            label="FAE",
            total_cost_eur=fae_cost_eur,
            ademe_aid_eur=fae_aid_eur,
            net_cost_eur=fae_net_cost_eur,
            cost_eur_mwh_year=p4_investment_eur_mwh,
        ),
        CostLine(
            category="P4 - Investissement initial",
            label=f"Travaux - {inputs.typologie}",
            total_cost_eur=works_cost_eur,
            ademe_aid_eur=works_aid_eur,
            net_cost_eur=works_net_cost_eur,
        ),
        CostLine(
            category="P4 - Investissement initial",
            label="Total",
            total_cost_eur=investment_cost_eur,
            ademe_aid_eur=aid_total_eur,
            net_cost_eur=net_investment_eur,
        ),
    )

    return CescEconomicResults(
        annual_production_mwh=annual_production_mwh,
        average_reference_energy_cost_eur_mwh=average_reference_energy_cost_eur_mwh,
        investment_cost_eur=investment_cost_eur,
        ademe_aid_eur_per_mwh_year_used=aid_eur_per_mwh_year,
        works_aid_uncapped_eur=works_aid_uncapped_eur,
        works_aid_cap_eur=works_aid_cap_eur,
        aid_total_eur=aid_total_eur,
        aid_rate=aid_rate,
        net_investment_eur=net_investment_eur,
        annual_savings_eur=annual_savings_eur,
        raw_payback_years=raw_payback_years,
        solar_heat_cost_eur_mwh=solar_heat_cost_eur_mwh,
        heat_cost_p1_eur_mwh=p1_auxiliary_electricity_eur_mwh,
        heat_cost_p2_eur_mwh=p2_maintenance_eur_mwh,
        heat_cost_p4_eur_mwh=p4_investment_eur_mwh,
        savings_over_period_eur=savings_over_period_eur,
        cost_lines=cost_lines,
    )



def build_yearly_cashflow_projection(
    inputs: CescEconomicInputs,
    results: CescEconomicResults,
) -> tuple[dict[str, float | int], ...]:
    """Construit une projection annuelle du flux cumulé.

    Deux approches sont calculées :
    - une courbe lissée, basée sur l'économie annuelle moyenne du modèle ;
    - une courbe annuelle, basée sur le coût de l'énergie de référence qui augmente
      chaque année avec le taux d'inflation saisi.

    La formule annuelle utilise la même convention que la formule moyenne de
    l'Excel : année 1 = coût de référence initial / rendement appoint, puis
    augmentation de `(1 + inflation)^(année - 1)`.
    """

    if inputs.years <= 0:
        raise ValueError("La durée d'analyse doit être strictement positive.")
    if inputs.eta_appoint <= 0:
        raise ValueError("Le rendement appoint doit être strictement positif.")

    operating_costs_eur_mwh = (results.heat_cost_p1_eur_mwh or 0.0) + (
        results.heat_cost_p2_eur_mwh or 0.0
    )
    initial_reference_cost_eur_mwh = (
        inputs.reference_energy_cost_eur_mwh / inputs.eta_appoint
    )

    rows: list[dict[str, float | int]] = []
    cumulative_inflated = -results.net_investment_eur

    for year in range(0, inputs.years + 1):
        if year == 0:
            reference_cost_year_eur_mwh = 0.0
            annual_savings_inflated_eur = 0.0
        else:
            reference_cost_year_eur_mwh = initial_reference_cost_eur_mwh * (
                (1.0 + inputs.reference_energy_inflation_rate) ** (year - 1)
            )
            annual_savings_inflated_eur = results.annual_production_mwh * (
                reference_cost_year_eur_mwh - operating_costs_eur_mwh
            )
            cumulative_inflated += annual_savings_inflated_eur

        rows.append(
            {
                "Année": year,
                "Coût référence annuel (€/MWh)": reference_cost_year_eur_mwh,
                "Économie annuelle moyenne (€)": results.annual_savings_eur
                if year > 0
                else 0.0,
                "Économie annuelle inflation (€)": annual_savings_inflated_eur,
                "Flux cumulé moyen (€)": -results.net_investment_eur
                + results.annual_savings_eur * year,
                "Flux cumulé inflation annuelle (€)": cumulative_inflated,
            }
        )

    return tuple(rows)


def build_inputs_from_installation(
    *,
    surface_m2: float,
    typologie: str | None = None,
    productivity_kwh_m2_year: float | None = None,
    reference_energy_cost_eur_mwh: float | None = None,
    years: int | None = None,
    eta_appoint: float | None = None,
) -> CescEconomicInputs:
    """Petit adaptateur pour Heliopilot.

    Il permet d'injecter les données déjà connues d'une installation tout en gardant
    les valeurs par défaut de l'Excel pour les hypothèses non renseignées.
    """

    defaults = CescEconomicInputs()
    return CescEconomicInputs(
        typologie=typologie if typologie is not None else defaults.typologie,
        surface_m2=surface_m2,
        productivity_kwh_m2_year=productivity_kwh_m2_year
        if productivity_kwh_m2_year is not None
        else defaults.productivity_kwh_m2_year,
        reference_energy_cost_eur_mwh=reference_energy_cost_eur_mwh
        if reference_energy_cost_eur_mwh is not None
        else defaults.reference_energy_cost_eur_mwh,
        years=years if years is not None else defaults.years,
        eta_appoint=eta_appoint if eta_appoint is not None else defaults.eta_appoint,
    )
