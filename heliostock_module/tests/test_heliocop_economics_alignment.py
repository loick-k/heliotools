from __future__ import annotations

import pytest

from heliostock.common.economics_core import average_escalation_factor, reference_gas_p1_eur_mwh
from heliostock.gas_reference import GAS_REFERENCE_EXISTING_BOILER, GAS_REFERENCE_RENEWAL
from heliostock.heliocop.economics_pac import compute_pac_heat_cost_model


MONTHLY_HEAT = {
    "Janvier": 10.0,
    "Février": 10.0,
    "Mars": 10.0,
    "Avril": 10.0,
    "Mai": 10.0,
    "Juin": 10.0,
    "Juillet": 10.0,
    "Août": 10.0,
    "Septembre": 10.0,
    "Octobre": 10.0,
    "Novembre": 10.0,
    "Décembre": 10.0,
}


def test_common_reference_gas_matches_helioeco_convention() -> None:
    cost = reference_gas_p1_eur_mwh(
        reference_energy_cost_eur_mwh=103.0,
        reference_efficiency=0.85,
        reference_inflation_rate=0.03,
        analysis_years=20,
    )

    assert average_escalation_factor(0.03, 20) == pytest.approx(1.3435, abs=1e-4)
    assert cost == pytest.approx(162.83, abs=0.02)


def test_heliocop_existing_boiler_keeps_reference_without_gas_fixed_costs() -> None:
    results = compute_pac_heat_cost_model(
        monthly_heat_mwh=MONTHLY_HEAT,
        selected_pac_power_kw=50.0,
        source_surface_m2=100.0,
        reference_energy_cost_eur_mwh=103.0,
        reference_efficiency=0.85,
        reference_inflation_rate=0.03,
        gas_reference_context=GAS_REFERENCE_EXISTING_BOILER,
        reference_boiler_power_kw=250.0,
    )

    assert results.reference_boiler_investment_eur == 0.0
    assert results.reference_heat_p2_eur_mwh == 0.0
    assert results.reference_heat_p4_eur_mwh == 0.0
    assert results.average_reference_heat_cost_eur_mwh == pytest.approx(162.83, abs=0.02)


def test_heliocop_boiler_renewal_adds_p2_p4_to_both_scenarios() -> None:
    results = compute_pac_heat_cost_model(
        monthly_heat_mwh=MONTHLY_HEAT,
        selected_pac_power_kw=50.0,
        source_surface_m2=100.0,
        reference_energy_cost_eur_mwh=103.0,
        reference_efficiency=0.85,
        reference_inflation_rate=0.03,
        gas_reference_context=GAS_REFERENCE_RENEWAL,
        reference_boiler_power_kw=240.0,
        pac_scenario_boiler_power_kw=120.0,
        reference_boiler_p2_eur_kw_year=10.0,
        reference_boiler_capex_eur_kw=200.0,
    )

    assert results.reference_boiler_investment_eur == pytest.approx(48_000.0)
    assert results.pac_scenario_boiler_investment_eur == pytest.approx(24_000.0)
    assert results.pac_scenario_boiler_p2_annual_eur == pytest.approx(1_200.0)
    assert results.reference_heat_p2_eur_mwh == pytest.approx(20.0)
    assert results.reference_heat_p4_eur_mwh == pytest.approx(20.0)
    assert results.average_reference_heat_cost_eur_mwh == pytest.approx(202.83, abs=0.02)
