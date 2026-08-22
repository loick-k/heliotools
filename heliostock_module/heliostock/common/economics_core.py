"""Briques économiques partagées entre les modules HelioTools.

Ce module ne porte pas un modèle métier complet. Il centralise les conventions
communes utilisées par HelioEco, HelioNOP, HelioDyn et HelioCOP pour éviter des
formules divergentes sur les grandeurs P1/P2/P4 et la référence gaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ..gas_reference import includes_gas_boiler_fixed_costs


DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH = 75.0
DEFAULT_REFERENCE_EFFICIENCY = 0.82
DEFAULT_REFERENCE_INFLATION = 0.03
DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR = 10.0
DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW = 200.0


def safe_divide(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    """Division robuste pour les indicateurs économiques."""

    if denominator <= 0:
        return default
    value = numerator / denominator
    return value if isfinite(value) else default


def average_escalation_factor(rate: float, years: int) -> float:
    """Facteur moyen d'un coût qui évolue de `rate` par an.

    Exemple : avec 3 %/an sur 20 ans, ce facteur vaut environ 1,34. Appliqué
    au prix initial du gaz puis divisé par le rendement, il donne le coût moyen
    utile de référence sur la période.
    """

    years = max(1, int(years))
    rate = float(rate)
    if abs(rate) < 1e-12:
        return 1.0
    return ((1.0 + rate) ** years - 1.0) / (years * rate)


def reference_gas_p1_eur_mwh(
    *,
    reference_energy_cost_eur_mwh: float,
    reference_efficiency: float,
    reference_inflation_rate: float,
    analysis_years: int,
) -> float:
    """Coût P1 gaz utile moyen, hors coûts fixes chaudière."""

    eta_ref = max(1e-6, float(reference_efficiency))
    return (
        max(0.0, float(reference_energy_cost_eur_mwh))
        / eta_ref
        * average_escalation_factor(float(reference_inflation_rate), int(analysis_years))
    )


@dataclass(frozen=True)
class GasBoilerFixedCosts:
    investment_eur: float
    p2_annual_eur: float
    p2_eur_mwh: float
    p4_eur_mwh: float


def gas_boiler_fixed_costs(
    *,
    gas_reference_context: str | None,
    boiler_power_kw: float,
    annual_heat_mwh: float,
    analysis_years: int,
    boiler_p2_eur_kw_year: float = DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR,
    boiler_capex_eur_kw: float = DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW,
) -> GasBoilerFixedCosts:
    """Coûts fixes chaudière gaz à ajouter seulement en contexte renouvellement."""

    if not includes_gas_boiler_fixed_costs(gas_reference_context):
        return GasBoilerFixedCosts(0.0, 0.0, 0.0, 0.0)

    power_kw = max(0.0, float(boiler_power_kw))
    years = max(1, int(analysis_years))
    annual_heat = max(0.0, float(annual_heat_mwh))
    investment = power_kw * max(0.0, float(boiler_capex_eur_kw))
    p2_annual = power_kw * max(0.0, float(boiler_p2_eur_kw_year))
    return GasBoilerFixedCosts(
        investment_eur=investment,
        p2_annual_eur=p2_annual,
        p2_eur_mwh=safe_divide(p2_annual, annual_heat),
        p4_eur_mwh=safe_divide(investment, annual_heat * years),
    )


def p4_eur_mwh(*, net_investment_eur: float, annual_heat_mwh: float, analysis_years: int) -> float:
    """Convention P4 simplifiée : CAPEX net / chaleur utile sur la durée."""

    return safe_divide(
        max(0.0, float(net_investment_eur)),
        max(0.0, float(annual_heat_mwh)) * max(1, int(analysis_years)),
    )
