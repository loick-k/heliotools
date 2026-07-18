"""Shared economic primitives for HelioTools applications.

The functions are re-exported from the existing HelioStock and HelioNOP modules
so future applications can depend on one stable namespace.
"""

from __future__ import annotations

from .economics import (
    ademe_solar_aid_eur,
    annualized_capex_eur,
    annuity_average_factor,
    compute_heat_costs,
    compute_solar_thermal_economics,
    solar_capex_eur,
    solar_capex_unit_eur_m2,
)
from .opportunity_notes.cesc_economic_model import (
    CescEconomicInputs,
    CescEconomicResults,
    build_yearly_cashflow_projection,
    compute_cesc_economic_model,
)

__all__ = [
    "CescEconomicInputs",
    "CescEconomicResults",
    "ademe_solar_aid_eur",
    "annualized_capex_eur",
    "annuity_average_factor",
    "build_yearly_cashflow_projection",
    "compute_cesc_economic_model",
    "compute_heat_costs",
    "compute_solar_thermal_economics",
    "solar_capex_eur",
    "solar_capex_unit_eur_m2",
]

