"""Modèle énergétique mensuel et économique P1/P2/P4 de HelioCOP.

Le modèle reste un modèle de note d'opportunité : les COP mensuels à 60 °C
sont des valeurs de référence fournies pour le prédimensionnement. Ils sont
appliqués aux besoins thermiques adressés mois par mois.

La décomposition économique reprend la logique HelioEco :
- P1 : énergie électrique achetée pour produire la chaleur PAC ;
- P2 : suivi / maintenance annuel ;
- P4 : investissement net aidé ramené à la chaleur produite sur la durée
  d'analyse.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Mapping

from .solopac_results import SoloPacResults

from ..gas_reference import GAS_REFERENCE_EXISTING_BOILER, includes_gas_boiler_fixed_costs
from .model import (
    DEFAULT_AID_EUR_PER_MWH_ENR,
    DEFAULT_COST_UNCERTAINTY,
    MONTH_NAMES,
    REX_COLLECTOR_COST_EUR_PER_M2,
    REX_FIXED_COST_EUR,
    REX_POWER_COST_EUR_PER_KW,
)


DEFAULT_MONTHLY_COP_60C: dict[str, float] = {
    "Janvier": 2.53236,
    "Février": 2.89346,
    "Mars": 3.17380,
    "Avril": 3.30696,
    "Mai": 3.15356,
    "Juin": 3.45954,
    "Juillet": 3.68322,
    "Août": 3.68457,
    "Septembre": 3.42448,
    "Octobre": 3.09132,
    "Novembre": 3.07363,
    "Décembre": 2.94027,
}

DEFAULT_ELECTRICITY_COST_EUR_MWH = 200.0
DEFAULT_MAINTENANCE_ANNUAL_EUR = 2000.0
DEFAULT_ANALYSIS_YEARS = 20
DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH = 75.0
DEFAULT_REFERENCE_EFFICIENCY = 0.82
DEFAULT_REFERENCE_INFLATION = 0.03
DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR = 10.0
DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW = 200.0


@dataclass(frozen=True)
class MonthlyPacEnergyRow:
    month: str
    heat_mwh: float
    cop_machine: float
    compressor_electricity_mwh: float
    auxiliary_electricity_mwh: float
    total_electricity_mwh: float
    system_cop: float
    renewable_heat_mwh: float


@dataclass(frozen=True)
class PacEconomicResults:
    monthly_rows: tuple[MonthlyPacEnergyRow, ...]
    annual_heat_mwh: float
    seasonal_cop_machine: float
    compressor_electricity_mwh: float
    auxiliary_electricity_mwh: float
    total_electricity_mwh: float
    system_cop_including_aux: float
    renewable_heat_mwh: float
    renewable_share: float
    aid_eur_per_mwh_enr: float
    estimated_aid_eur: float
    capex_mid_eur: float
    capex_low_eur: float
    capex_high_eur: float
    net_investment_eur: float
    net_investment_low_eur: float
    net_investment_high_eur: float
    p1_annual_eur: float
    p1_eur_mwh: float
    p2_annual_eur: float
    p2_eur_mwh: float
    p4_eur_mwh: float
    p4_low_eur_mwh: float
    p4_high_eur_mwh: float
    heat_cost_eur_mwh: float
    heat_cost_low_eur_mwh: float
    heat_cost_high_eur_mwh: float
    average_reference_heat_cost_eur_mwh: float
    reference_heat_p1_eur_mwh: float
    reference_heat_p2_eur_mwh: float
    reference_heat_p4_eur_mwh: float
    reference_boiler_investment_eur: float
    pac_scenario_boiler_investment_eur: float
    pac_scenario_boiler_p2_annual_eur: float
    pac_scenario_gross_investment_eur: float
    pac_scenario_net_investment_eur: float
    reference_scenario_gross_investment_eur: float
    reference_scenario_net_investment_eur: float
    incremental_net_investment_eur: float
    annual_savings_eur: float
    raw_payback_years: float | None
    analysis_years: int
    p1_electricity_annual_eur: float = 0.0
    p1_gas_annual_eur: float = 0.0
    gas_backup_heat_mwh: float = 0.0
    gas_backup_fuel_mwh: float = 0.0

    @property
    def annual_ecs_need_mwh(self) -> float:
        return self.annual_heat_mwh

    @property
    def pac_heat_mwh(self) -> float:
        return self.annual_heat_mwh

    @property
    def pac_electricity_mwh(self) -> float:
        return self.total_electricity_mwh

    @property
    def cop(self) -> float:
        return self.seasonal_cop_machine

    @property
    def remaining_cost_mid_eur(self) -> float:
        return self.net_investment_eur

    def as_dict(self) -> dict:
        return asdict(self)


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    value = numerator / denominator
    return value if isfinite(value) else 0.0


def _average_escalation_factor(rate: float, years: int) -> float:
    years = max(1, int(years))
    rate = float(rate)
    if abs(rate) < 1e-12:
        return 1.0
    return ((1.0 + rate) ** years - 1.0) / (years * rate)


def normalize_monthly_heat(monthly_heat_mwh: Mapping[str, float] | None, annual_heat_mwh: float | None = None) -> dict[str, float]:
    """Retourne douze besoins mensuels ordonnés.

    Si aucun profil mensuel n'est fourni mais qu'une énergie annuelle existe,
    elle est répartie uniformément. Cette voie sert uniquement de repli pour
    préserver la compatibilité avec des appels anciens du moteur.
    """

    if monthly_heat_mwh:
        return {month: max(0.0, float(monthly_heat_mwh.get(month, 0.0))) for month in MONTH_NAMES}
    annual = max(0.0, float(annual_heat_mwh or 0.0))
    return {month: annual / 12.0 for month in MONTH_NAMES}


def build_monthly_pac_energy(
    monthly_heat_mwh: Mapping[str, float],
    *,
    monthly_cop: Mapping[str, float] | None = None,
    auxiliary_electricity_mwh: float = 0.0,
) -> tuple[MonthlyPacEnergyRow, ...]:
    """Applique les COP mensuels au besoin thermique adressé de chaque mois."""

    heat = normalize_monthly_heat(monthly_heat_mwh)
    cops = monthly_cop or DEFAULT_MONTHLY_COP_60C
    annual_heat = sum(heat.values())
    annual_aux = max(0.0, float(auxiliary_electricity_mwh))
    rows: list[MonthlyPacEnergyRow] = []
    for month in MONTH_NAMES:
        q = heat[month]
        cop = max(1.000001, float(cops.get(month, DEFAULT_MONTHLY_COP_60C[month])))
        e_comp = q / cop
        e_aux = annual_aux * q / annual_heat if annual_heat > 0 else 0.0
        e_total = e_comp + e_aux
        system_cop = _safe_divide(q, e_total)
        q_enr = max(0.0, q - e_total)
        rows.append(
            MonthlyPacEnergyRow(
                month=month,
                heat_mwh=q,
                cop_machine=cop,
                compressor_electricity_mwh=e_comp,
                auxiliary_electricity_mwh=e_aux,
                total_electricity_mwh=e_total,
                system_cop=system_cop,
                renewable_heat_mwh=q_enr,
            )
        )
    return tuple(rows)


def compute_pac_heat_cost_model(
    *,
    monthly_heat_mwh: Mapping[str, float],
    selected_pac_power_kw: float,
    source_surface_m2: float,
    monthly_cop: Mapping[str, float] | None = None,
    auxiliary_electricity_mwh: float = 0.0,
    electricity_cost_eur_mwh: float = DEFAULT_ELECTRICITY_COST_EUR_MWH,
    maintenance_annual_eur: float = DEFAULT_MAINTENANCE_ANNUAL_EUR,
    analysis_years: int = DEFAULT_ANALYSIS_YEARS,
    aid_eur_per_mwh_enr: float = DEFAULT_AID_EUR_PER_MWH_ENR,
    cost_uncertainty: float = DEFAULT_COST_UNCERTAINTY,
    reference_energy_cost_eur_mwh: float = DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH,
    reference_efficiency: float = DEFAULT_REFERENCE_EFFICIENCY,
    reference_inflation_rate: float = DEFAULT_REFERENCE_INFLATION,
    gas_reference_context: str = GAS_REFERENCE_EXISTING_BOILER,
    reference_boiler_power_kw: float = 0.0,
    pac_scenario_boiler_power_kw: float | None = None,
    reference_boiler_p2_eur_kw_year: float = DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR,
    reference_boiler_capex_eur_kw: float = DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW,
) -> PacEconomicResults:
    """Calcule énergie, aides et coût de chaleur P1/P2/P4.

    P1 = coût annuel de l'électricité PAC + auxiliaires / chaleur utile.
    P2 = forfait annuel de maintenance PAC solaire / chaleur utile.
    P4 = CAPEX net aidé / (chaleur utile × durée d'analyse).

    La formule P4 est volontairement celle du modèle HelioEco simplifié, sans
    actualisation financière. Le taux de récupération du capital pourra être
    ajouté ultérieurement comme variante LCOH.
    """

    rows = build_monthly_pac_energy(
        monthly_heat_mwh,
        monthly_cop=monthly_cop,
        auxiliary_electricity_mwh=auxiliary_electricity_mwh,
    )
    annual_heat = sum(row.heat_mwh for row in rows)
    e_comp = sum(row.compressor_electricity_mwh for row in rows)
    e_aux = sum(row.auxiliary_electricity_mwh for row in rows)
    e_total = e_comp + e_aux
    q_enr = sum(row.renewable_heat_mwh for row in rows)
    seasonal_cop = _safe_divide(annual_heat, e_comp)
    system_cop = _safe_divide(annual_heat, e_total)
    renewable_share = _safe_divide(q_enr, annual_heat)

    capex = (
        REX_FIXED_COST_EUR
        + REX_POWER_COST_EUR_PER_KW * max(0.0, float(selected_pac_power_kw))
        + REX_COLLECTOR_COST_EUR_PER_M2 * max(0.0, float(source_surface_m2))
    )
    uncertainty = min(0.90, max(0.0, float(cost_uncertainty)))
    capex_low = capex * (1.0 - uncertainty)
    capex_high = capex * (1.0 + uncertainty)
    aid = q_enr * max(0.0, float(aid_eur_per_mwh_enr))
    net_capex = max(0.0, capex - aid)
    net_capex_low = max(0.0, capex_low - aid)
    net_capex_high = max(0.0, capex_high - aid)

    electricity_cost = max(0.0, float(electricity_cost_eur_mwh))
    p1_annual = e_total * electricity_cost
    p1 = _safe_divide(p1_annual, annual_heat)

    pac_maintenance_annual = max(0.0, float(maintenance_annual_eur))

    years = max(1, int(analysis_years))

    # En contexte « chaudière gaz à renouveler », les deux scénarios doivent
    # supporter l'investissement d'une chaudière gaz :
    # - référence : chaudière 100 % gaz ;
    # - PAC solaire : chaudière d'appoint / secours + PAC solaire.
    # Par défaut, la puissance de la chaudière du scénario PAC est identique
    # à celle de la référence, mais elle peut être saisie séparément.
    pac_boiler_power = (
        max(0.0, float(reference_boiler_power_kw))
        if pac_scenario_boiler_power_kw is None
        else max(0.0, float(pac_scenario_boiler_power_kw))
    )
    pac_scenario_boiler_investment = 0.0
    pac_scenario_boiler_p2_annual = 0.0
    if includes_gas_boiler_fixed_costs(gas_reference_context):
        pac_scenario_boiler_investment = pac_boiler_power * max(0.0, float(reference_boiler_capex_eur_kw))
        pac_scenario_boiler_p2_annual = pac_boiler_power * max(0.0, float(reference_boiler_p2_eur_kw_year))

    p2_annual = pac_maintenance_annual + pac_scenario_boiler_p2_annual
    p2 = _safe_divide(p2_annual, annual_heat)

    pac_scenario_gross_investment = capex + pac_scenario_boiler_investment
    pac_scenario_net_investment = net_capex + pac_scenario_boiler_investment
    pac_scenario_net_low = net_capex_low + pac_scenario_boiler_investment
    pac_scenario_net_high = net_capex_high + pac_scenario_boiler_investment

    p4 = _safe_divide(pac_scenario_net_investment, annual_heat * years)
    p4_low = _safe_divide(pac_scenario_net_low, annual_heat * years)
    p4_high = _safe_divide(pac_scenario_net_high, annual_heat * years)
    heat_cost = p1 + p2 + p4
    heat_cost_low = p1 + p2 + p4_low
    heat_cost_high = p1 + p2 + p4_high

    eta_ref = max(1e-6, float(reference_efficiency))
    reference_p1 = (
        max(0.0, float(reference_energy_cost_eur_mwh))
        / eta_ref
        * _average_escalation_factor(float(reference_inflation_rate), years)
    )
    reference_p2 = 0.0
    reference_p4 = 0.0
    reference_boiler_investment = 0.0
    if includes_gas_boiler_fixed_costs(gas_reference_context):
        boiler_power = max(0.0, float(reference_boiler_power_kw))
        reference_p2 = _safe_divide(
            boiler_power * max(0.0, float(reference_boiler_p2_eur_kw_year)),
            annual_heat,
        )
        reference_boiler_investment = boiler_power * max(0.0, float(reference_boiler_capex_eur_kw))
        reference_p4 = _safe_divide(reference_boiler_investment, annual_heat * years)
    average_ref = reference_p1 + reference_p2 + reference_p4
    reference_scenario_gross_investment = reference_boiler_investment
    reference_scenario_net_investment = reference_boiler_investment
    incremental_net_investment = pac_scenario_net_investment - reference_scenario_net_investment
    # Économies annuelles d'exploitation : comparaison P1 + P2 uniquement.
    # Les investissements restent comparés séparément via P4 et le surinvestissement net.
    annual_savings = annual_heat * (reference_p1 + reference_p2) - p1_annual - p2_annual
    payback = incremental_net_investment / annual_savings if annual_savings > 0 and incremental_net_investment > 0 else None

    return PacEconomicResults(
        monthly_rows=rows,
        annual_heat_mwh=annual_heat,
        seasonal_cop_machine=seasonal_cop,
        compressor_electricity_mwh=e_comp,
        auxiliary_electricity_mwh=e_aux,
        total_electricity_mwh=e_total,
        system_cop_including_aux=system_cop,
        renewable_heat_mwh=q_enr,
        renewable_share=renewable_share,
        aid_eur_per_mwh_enr=float(aid_eur_per_mwh_enr),
        estimated_aid_eur=aid,
        capex_mid_eur=capex,
        capex_low_eur=capex_low,
        capex_high_eur=capex_high,
        net_investment_eur=net_capex,
        net_investment_low_eur=net_capex_low,
        net_investment_high_eur=net_capex_high,
        p1_annual_eur=p1_annual,
        p1_eur_mwh=p1,
        p2_annual_eur=p2_annual,
        p2_eur_mwh=p2,
        p4_eur_mwh=p4,
        p4_low_eur_mwh=p4_low,
        p4_high_eur_mwh=p4_high,
        heat_cost_eur_mwh=heat_cost,
        heat_cost_low_eur_mwh=heat_cost_low,
        heat_cost_high_eur_mwh=heat_cost_high,
        average_reference_heat_cost_eur_mwh=average_ref,
        reference_heat_p1_eur_mwh=reference_p1,
        reference_heat_p2_eur_mwh=reference_p2,
        reference_heat_p4_eur_mwh=reference_p4,
        reference_boiler_investment_eur=reference_boiler_investment,
        pac_scenario_boiler_investment_eur=pac_scenario_boiler_investment,
        pac_scenario_boiler_p2_annual_eur=pac_scenario_boiler_p2_annual,
        pac_scenario_gross_investment_eur=pac_scenario_gross_investment,
        pac_scenario_net_investment_eur=pac_scenario_net_investment,
        reference_scenario_gross_investment_eur=reference_scenario_gross_investment,
        reference_scenario_net_investment_eur=reference_scenario_net_investment,
        incremental_net_investment_eur=incremental_net_investment,
        annual_savings_eur=annual_savings,
        raw_payback_years=payback,
        analysis_years=years,
        p1_electricity_annual_eur=p1_annual,
        p1_gas_annual_eur=0.0,
        gas_backup_heat_mwh=0.0,
        gas_backup_fuel_mwh=0.0,
    )



def compute_pac_heat_cost_from_solopac(
    *,
    solopac: SoloPacResults,
    selected_pac_power_kw: float,
    source_surface_m2: float,
    electricity_cost_eur_mwh: float = DEFAULT_ELECTRICITY_COST_EUR_MWH,
    maintenance_annual_eur: float = DEFAULT_MAINTENANCE_ANNUAL_EUR,
    analysis_years: int = DEFAULT_ANALYSIS_YEARS,
    aid_eur_per_mwh_enr: float = DEFAULT_AID_EUR_PER_MWH_ENR,
    cost_uncertainty: float = DEFAULT_COST_UNCERTAINTY,
    reference_energy_cost_eur_mwh: float = DEFAULT_REFERENCE_ENERGY_COST_EUR_MWH,
    reference_efficiency: float = DEFAULT_REFERENCE_EFFICIENCY,
    reference_inflation_rate: float = DEFAULT_REFERENCE_INFLATION,
    gas_reference_context: str = GAS_REFERENCE_EXISTING_BOILER,
    reference_boiler_power_kw: float = 0.0,
    pac_scenario_boiler_power_kw: float | None = None,
    reference_boiler_p2_eur_kw_year: float = DEFAULT_REFERENCE_BOILER_P2_EUR_KW_YEAR,
    reference_boiler_capex_eur_kw: float = DEFAULT_REFERENCE_BOILER_CAPEX_EUR_KW,
) -> PacEconomicResults:
    """Actualise le bilan économique à partir des flux réellement simulés par SOLOPAC.

    Contrairement au prédimensionnement de l'onglet 7, aucun COP théorique n'est
    appliqué : électricité compresseur, auxiliaires, énergie renouvelable et
    appoint chaudière proviennent directement du fichier SOLOPAC.
    """

    annual_heat = max(0.0, solopac.annual_useful_need_mwh)
    e_comp = max(0.0, solopac.annual_compressor_electricity_mwh)
    e_aux = max(0.0, solopac.annual_auxiliary_electricity_mwh)
    e_total = e_comp + e_aux
    q_enr = max(0.0, solopac.annual_renewable_evaporator_mwh)
    q_gas = max(0.0, solopac.annual_gas_backup_heat_mwh)
    q_cond = max(0.0, solopac.annual_pac_condenser_mwh)

    rows = tuple(
        MonthlyPacEnergyRow(
            month=row.month,
            heat_mwh=row.useful_need_mwh,
            cop_machine=_safe_divide(row.pac_condenser_mwh, row.compressor_electricity_mwh),
            compressor_electricity_mwh=row.compressor_electricity_mwh,
            auxiliary_electricity_mwh=row.auxiliary_electricity_mwh,
            total_electricity_mwh=row.compressor_electricity_mwh + row.auxiliary_electricity_mwh,
            system_cop=row.cop_system,
            renewable_heat_mwh=row.renewable_evaporator_mwh,
        )
        for row in solopac.monthly_rows
    )

    capex = (
        REX_FIXED_COST_EUR
        + REX_POWER_COST_EUR_PER_KW * max(0.0, float(selected_pac_power_kw))
        + REX_COLLECTOR_COST_EUR_PER_M2 * max(0.0, float(source_surface_m2))
    )
    uncertainty = min(0.90, max(0.0, float(cost_uncertainty)))
    capex_low = capex * (1.0 - uncertainty)
    capex_high = capex * (1.0 + uncertainty)
    aid = q_enr * max(0.0, float(aid_eur_per_mwh_enr))
    net_capex = max(0.0, capex - aid)
    net_capex_low = max(0.0, capex_low - aid)
    net_capex_high = max(0.0, capex_high - aid)

    years = max(1, int(analysis_years))
    eta_gas = max(1e-6, float(reference_efficiency))
    gas_average_price = max(0.0, float(reference_energy_cost_eur_mwh)) * _average_escalation_factor(
        float(reference_inflation_rate), years
    )
    gas_fuel_mwh = q_gas / eta_gas
    p1_electricity_annual = e_total * max(0.0, float(electricity_cost_eur_mwh))
    p1_gas_annual = gas_fuel_mwh * gas_average_price
    p1_annual = p1_electricity_annual + p1_gas_annual
    p1 = _safe_divide(p1_annual, annual_heat)

    pac_boiler_power = (
        max(0.0, float(reference_boiler_power_kw))
        if pac_scenario_boiler_power_kw is None
        else max(0.0, float(pac_scenario_boiler_power_kw))
    )
    pac_scenario_boiler_investment = 0.0
    pac_scenario_boiler_p2_annual = 0.0
    if includes_gas_boiler_fixed_costs(gas_reference_context):
        pac_scenario_boiler_investment = pac_boiler_power * max(0.0, float(reference_boiler_capex_eur_kw))
        pac_scenario_boiler_p2_annual = pac_boiler_power * max(0.0, float(reference_boiler_p2_eur_kw_year))

    p2_annual = max(0.0, float(maintenance_annual_eur)) + pac_scenario_boiler_p2_annual
    p2 = _safe_divide(p2_annual, annual_heat)

    pac_scenario_gross_investment = capex + pac_scenario_boiler_investment
    pac_scenario_net_investment = net_capex + pac_scenario_boiler_investment
    pac_scenario_net_low = net_capex_low + pac_scenario_boiler_investment
    pac_scenario_net_high = net_capex_high + pac_scenario_boiler_investment
    p4 = _safe_divide(pac_scenario_net_investment, annual_heat * years)
    p4_low = _safe_divide(pac_scenario_net_low, annual_heat * years)
    p4_high = _safe_divide(pac_scenario_net_high, annual_heat * years)
    heat_cost = p1 + p2 + p4
    heat_cost_low = p1 + p2 + p4_low
    heat_cost_high = p1 + p2 + p4_high

    reference_p1 = gas_average_price / eta_gas
    reference_p2 = 0.0
    reference_p4 = 0.0
    reference_boiler_investment = 0.0
    if includes_gas_boiler_fixed_costs(gas_reference_context):
        boiler_power = max(0.0, float(reference_boiler_power_kw))
        reference_p2 = _safe_divide(
            boiler_power * max(0.0, float(reference_boiler_p2_eur_kw_year)), annual_heat
        )
        reference_boiler_investment = boiler_power * max(0.0, float(reference_boiler_capex_eur_kw))
        reference_p4 = _safe_divide(reference_boiler_investment, annual_heat * years)
    average_ref = reference_p1 + reference_p2 + reference_p4

    reference_scenario_gross_investment = reference_boiler_investment
    reference_scenario_net_investment = reference_boiler_investment
    incremental_net_investment = pac_scenario_net_investment - reference_scenario_net_investment
    annual_savings = annual_heat * (reference_p1 + reference_p2) - p1_annual - p2_annual
    payback = incremental_net_investment / annual_savings if annual_savings > 0 and incremental_net_investment > 0 else None

    return PacEconomicResults(
        monthly_rows=rows,
        annual_heat_mwh=annual_heat,
        seasonal_cop_machine=_safe_divide(q_cond, e_comp),
        compressor_electricity_mwh=e_comp,
        auxiliary_electricity_mwh=e_aux,
        total_electricity_mwh=e_total,
        system_cop_including_aux=_safe_divide(q_cond, e_total),
        renewable_heat_mwh=q_enr,
        renewable_share=_safe_divide(q_enr, annual_heat),
        aid_eur_per_mwh_enr=float(aid_eur_per_mwh_enr),
        estimated_aid_eur=aid,
        capex_mid_eur=capex,
        capex_low_eur=capex_low,
        capex_high_eur=capex_high,
        net_investment_eur=net_capex,
        net_investment_low_eur=net_capex_low,
        net_investment_high_eur=net_capex_high,
        p1_annual_eur=p1_annual,
        p1_eur_mwh=p1,
        p2_annual_eur=p2_annual,
        p2_eur_mwh=p2,
        p4_eur_mwh=p4,
        p4_low_eur_mwh=p4_low,
        p4_high_eur_mwh=p4_high,
        heat_cost_eur_mwh=heat_cost,
        heat_cost_low_eur_mwh=heat_cost_low,
        heat_cost_high_eur_mwh=heat_cost_high,
        average_reference_heat_cost_eur_mwh=average_ref,
        reference_heat_p1_eur_mwh=reference_p1,
        reference_heat_p2_eur_mwh=reference_p2,
        reference_heat_p4_eur_mwh=reference_p4,
        reference_boiler_investment_eur=reference_boiler_investment,
        pac_scenario_boiler_investment_eur=pac_scenario_boiler_investment,
        pac_scenario_boiler_p2_annual_eur=pac_scenario_boiler_p2_annual,
        pac_scenario_gross_investment_eur=pac_scenario_gross_investment,
        pac_scenario_net_investment_eur=pac_scenario_net_investment,
        reference_scenario_gross_investment_eur=reference_scenario_gross_investment,
        reference_scenario_net_investment_eur=reference_scenario_net_investment,
        incremental_net_investment_eur=incremental_net_investment,
        annual_savings_eur=annual_savings,
        raw_payback_years=payback,
        analysis_years=years,
        p1_electricity_annual_eur=p1_electricity_annual,
        p1_gas_annual_eur=p1_gas_annual,
        gas_backup_heat_mwh=q_gas,
        gas_backup_fuel_mwh=gas_fuel_mwh,
    )
