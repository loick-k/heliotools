import pandas as pd

from heliostock.economics import (
    compute_heat_costs,
    compute_solar_thermal_economics,
    solar_capex_eur,
    solar_energy_allocation,
    solar_recharge_value,
)
from heliostock.scenarios import ScenarioEconomicsConfig, _multiyear_heat_cost


def test_mix_backup_gas_p1_uses_same_inflated_cost_as_reference_gas():
    solar_economics = {
        "p1_eur_mwh": 0.0,
        "p2_eur_mwh": 0.0,
        "p4_eur_mwh": 0.0,
        "capex_eur": 0.0,
        "ademe_aid_eur": 0.0,
        "aid_total_eur": 0.0,
        "net_capex_eur": 0.0,
    }
    heat_costs = compute_heat_costs(
        solar_economics=solar_economics,
        annual_solar_mwh=0.0,
        annual_pac_heat_mwh=0.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=100.0,
        backup_power_kw=100.0,
        reference_heat_mwh=100.0,
        reference_power_kw=100.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=0.82,
        gas_reference_inflation_rate=0.03,
        geothermal_p1_eur_mwh=200.0,
        backup_p1_eur_mwh=70.0,
        backup_p2_eur_kw_year=10.0,
    )
    p1_table = heat_costs["p1_p2_p4"]
    backup_p1 = float(
        p1_table[(p1_table["Generateur"] == "Appoint gaz") & (p1_table["Poste"] == "P1")]["EUR/MWh"].iloc[0]
    )
    backup_p2 = float(
        p1_table[(p1_table["Generateur"] == "Appoint gaz") & (p1_table["Poste"] == "P2")]["EUR/MWh"].iloc[0]
    )
    reference_p1 = float(heat_costs["reference_p1_eur_mwh"])
    reference_p2 = float(heat_costs["reference_p2_eur_mwh"])

    assert backup_p1 == reference_p1
    assert backup_p1 > 70.0 / 0.82
    assert backup_p2 == 10.0
    assert reference_p2 == 10.0


def test_solar_p2_uses_one_percent_capex_over_total_solar_production():
    surface_m2 = 500.0
    total_solar_mwh = 250.0
    capex = solar_capex_eur(surface_m2)
    economics = compute_solar_thermal_economics(
        surface_m2=surface_m2,
        annual_solar_valued_mwh=100.0,
        reference_energy_cost_eur_mwh=70.0,
        reference_energy_inflation_rate=0.03,
        analysis_years=20,
        eta_appoint=0.82,
        auxiliary_electricity_ratio=0.03,
        electricity_cost_eur_mwh=200.0,
        maintenance_cost_eur_m2_year=999.0,
        ademe_eur_mwh_year=63.0,
        other_public_aid_eur=0.0,
        annual_solar_total_mwh=total_solar_mwh,
    )

    assert abs(float(economics["p2_annual_eur"]) - 0.01 * capex) <= 1e-9
    assert abs(float(economics["p2_eur_mwh"]) - (0.01 * capex / total_solar_mwh)) <= 1e-9
    assert abs(float(economics["p1_eur_mwh"]) - 0.03 * 200.0) <= 1e-9


def test_solar_recharge_p2_does_not_penalize_solar_ht_cost():
    base_solar_economics = {
        "p1_eur_mwh": 0.0,
        "p2_eur_mwh": 0.0,
        "p4_eur_mwh": 0.0,
        "p2_annual_eur": 3_000.0,
        "capex_eur": 0.0,
        "ademe_aid_eur": 0.0,
        "aid_total_eur": 0.0,
        "net_capex_eur": 0.0,
    }
    no_recharge = compute_heat_costs(
        solar_economics={**base_solar_economics, "annual_solar_total_mwh": 100.0},
        annual_solar_mwh=100.0,
        annual_pac_heat_mwh=200.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=0.0,
        backup_power_kw=0.0,
        reference_heat_mwh=300.0,
        reference_power_kw=0.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=1.0,
        gas_reference_inflation_rate=0.0,
        geothermal_p1_eur_mwh=200.0,
    )
    with_recharge = compute_heat_costs(
        solar_economics={**base_solar_economics, "annual_solar_total_mwh": 300.0},
        annual_solar_mwh=100.0,
        annual_pac_heat_mwh=200.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=0.0,
        backup_power_kw=0.0,
        reference_heat_mwh=300.0,
        reference_power_kw=0.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=1.0,
        gas_reference_inflation_rate=0.0,
        geothermal_p1_eur_mwh=200.0,
    )

    assert float(no_recharge["solar_p2_ht_annual_eur"]) == 3_000.0
    assert float(no_recharge["solar_p2_recharge_annual_eur"]) == 0.0
    assert float(with_recharge["solar_p2_ht_annual_eur"]) == 1_000.0
    assert float(with_recharge["solar_p2_recharge_annual_eur"]) == 2_000.0
    assert float(with_recharge["geo_p2_with_recharge_annual_eur"]) == 2_000.0


def test_recharge_annual_gain_has_no_borefield_p2_term():
    allocation = solar_energy_allocation(
        solar_ht_mwh=10.0,
        solar_btes_mwh=30.0,
        solar_net_capex_eur=100_000.0,
        solar_p2_annual_eur=4_000.0,
        solar_p4_annual_eur=5_000.0,
    )
    value = solar_recharge_value(
        allocation=allocation,
        saved_borefield_length_m=100.0,
        borefield_unit_cost_eur_m=100.0,
        electricity_savings_mwh=5.0,
        average_electricity_cost_eur_mwh=200.0,
        analysis_years=20,
    )

    expected = 100.0 * 100.0 / 20.0 + 5.0 * 200.0
    assert float(value["annual_recharge_gain_eur_an"]) == expected
    assert float(value["p2_borefield_savings_eur_an"]) == 0.0


def test_recharge_annual_gain_can_use_net_borefield_capex_savings():
    allocation = solar_energy_allocation(
        solar_ht_mwh=10.0,
        solar_btes_mwh=30.0,
        solar_net_capex_eur=100_000.0,
        solar_p2_annual_eur=4_000.0,
        solar_p4_annual_eur=5_000.0,
    )
    value = solar_recharge_value(
        allocation=allocation,
        saved_borefield_length_m=100.0,
        borefield_unit_cost_eur_m=100.0,
        saved_borefield_net_capex_eur=3_500.0,
        electricity_savings_mwh=5.0,
        average_electricity_cost_eur_mwh=200.0,
        analysis_years=20,
    )

    expected = 3_500.0 / 20.0 + 5.0 * 200.0
    assert float(value["saved_borefield_capex_eur"]) == 10_000.0
    assert float(value["saved_borefield_net_capex_eur"]) == 3_500.0
    assert float(value["annual_recharge_gain_eur_an"]) == expected
    assert float(value["p2_borefield_savings_eur_an"]) == 0.0


def test_solar_energy_allocation_prorata_sums_to_one():
    allocation = solar_energy_allocation(
        solar_ht_mwh=25.0,
        solar_btes_mwh=75.0,
        solar_net_capex_eur=100_000.0,
        solar_p2_annual_eur=4_000.0,
        solar_p4_annual_eur=5_000.0,
    )

    assert abs(float(allocation["part_ht"]) + float(allocation["part_recharge"]) - 1.0) <= 1e-12
    assert float(allocation["capex_solar_ht_eur"]) == 25_000.0
    assert float(allocation["capex_solar_recharge_eur"]) == 75_000.0


def test_solar_recharge_p2_is_counted_globally_as_geothermal_p2():
    solar_economics = {
        "p1_eur_mwh": 0.0,
        "p2_eur_mwh": 10.0,
        "p4_eur_mwh": 0.0,
        "p2_annual_eur": 3_000.0,
        "annual_solar_total_mwh": 300.0,
        "capex_eur": 0.0,
        "ademe_aid_eur": 0.0,
        "aid_total_eur": 0.0,
        "net_capex_eur": 0.0,
    }
    heat_costs = compute_heat_costs(
        solar_economics=solar_economics,
        annual_solar_mwh=100.0,
        annual_pac_heat_mwh=200.0,
        annual_pac_electricity_mwh=0.0,
        pac_power_kw=0.0,
        borefield_length_m=0.0,
        full_borefield_length_m=0.0,
        annual_backup_heat_mwh=0.0,
        backup_power_kw=0.0,
        reference_heat_mwh=300.0,
        reference_power_kw=0.0,
        analysis_years=20,
        gas_reference_p1_eur_mwh_pci=70.0,
        gas_reference_efficiency=0.82,
        gas_reference_inflation_rate=0.0,
        geothermal_p1_eur_mwh=200.0,
    )
    p2_table = heat_costs["p1_p2_p4"]
    solar_p2 = float(
        p2_table[(p2_table["Generateur"] == "Solaire thermique") & (p2_table["Poste"] == "P2")][
            "EUR/MWh"
        ].iloc[0]
    )
    geo_p2 = float(
        p2_table[(p2_table["Generateur"] == "Geothermie PAC") & (p2_table["Poste"] == "P2")][
            "EUR/MWh"
        ].iloc[0]
    )
    trajectory = pd.DataFrame(
        [
            {
                "Annee": 1,
                "Solaire HT (MWh)": 100.0,
                "Chaleur PAC BT (MWh)": 200.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 0.0,
                "E utile totale (MWh)": 300.0,
            },
            {
                "Annee": 2,
                "Solaire HT (MWh)": 100.0,
                "Chaleur PAC BT (MWh)": 200.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 0.0,
                "E utile totale (MWh)": 300.0,
            },
        ]
    )
    multiyear = _multiyear_heat_cost(
        trajectory_df=trajectory,
        heat_costs=heat_costs,
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=70.0,
            reference_energy_inflation_pct=0.0,
            eta_appoint_eco=0.82,
            analysis_years=20,
            auxiliary_electricity_ratio_pct=0.0,
            electricity_cost_eur_mwh=200.0,
            maintenance_cost_eur_m2_year=22.0,
            ademe_eur_mwh_year=63.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=10.0,
        ),
        capex_net_eur=0.0,
    )

    assert float(heat_costs["solar_p2_total_annual_eur"]) == 3_000.0
    assert float(heat_costs["solar_p2_ht_annual_eur"]) == 1_000.0
    assert float(heat_costs["solar_p2_recharge_annual_eur"]) == 2_000.0
    assert float(heat_costs["geo_p2_with_recharge_annual_eur"]) == 2_000.0
    assert solar_p2 == 10.0
    assert geo_p2 == 10.0
    assert float(heat_costs["mix_p2_eur_mwh"]) == 10.0
    assert float(multiyear["p2_annual_eur"]) == 3_000.0


def test_multiyear_pac_electricity_cost_uses_economics_value():
    trajectory = pd.DataFrame(
        [
            {
                "Annee": 1,
                "Solaire HT (MWh)": 0.0,
                "Chaleur PAC BT (MWh)": 40.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 10.0,
                "E utile totale (MWh)": 40.0,
            },
            {
                "Annee": 2,
                "Solaire HT (MWh)": 0.0,
                "Chaleur PAC BT (MWh)": 40.0,
                "Appoint gaz total (MWh)": 0.0,
                "Electricite PAC (MWh)": 10.0,
                "E utile totale (MWh)": 40.0,
            },
        ]
    )
    costs = _multiyear_heat_cost(
        trajectory_df=trajectory,
        heat_costs={"p1_p2_p4": pd.DataFrame(), "capex_summary": pd.DataFrame()},
        economics=ScenarioEconomicsConfig(
            reference_energy_cost_eur_mwh=999.0,
            reference_energy_inflation_pct=0.0,
            eta_appoint_eco=1.0,
            analysis_years=2,
            auxiliary_electricity_ratio_pct=0.0,
            electricity_cost_eur_mwh=123.0,
            maintenance_cost_eur_m2_year=0.0,
            ademe_eur_mwh_year=0.0,
            other_public_aid_eur=0.0,
            backup_p2_eur_kw_year=0.0,
        ),
        capex_net_eur=0.0,
    )

    assert float(costs["p1_cumulative_eur"]) == 20.0 * 123.0
    assert float(costs["multiyear_heat_cost_eur_mwh"]) == (20.0 * 123.0) / 80.0


def test_four_economic_scenarios_have_simple_expected_multiyear_costs():
    economics = ScenarioEconomicsConfig(
        reference_energy_cost_eur_mwh=90.0,
        reference_energy_inflation_pct=0.0,
        eta_appoint_eco=1.0,
        analysis_years=2,
        auxiliary_electricity_ratio_pct=0.0,
        electricity_cost_eur_mwh=100.0,
        maintenance_cost_eur_m2_year=0.0,
        ademe_eur_mwh_year=0.0,
        other_public_aid_eur=0.0,
        backup_p2_eur_kw_year=0.0,
    )
    heat_costs = {"p1_p2_p4": pd.DataFrame(), "capex_summary": pd.DataFrame()}

    def trajectory(*, solar: float, pac_heat: float, pac_electricity: float, backup: float) -> pd.DataFrame:
        useful = solar + pac_heat + backup
        return pd.DataFrame(
            [
                {
                    "Annee": year,
                    "Solaire HT (MWh)": solar,
                    "Chaleur PAC BT (MWh)": pac_heat,
                    "Appoint gaz total (MWh)": backup,
                    "Electricite PAC (MWh)": pac_electricity,
                    "E utile totale (MWh)": useful,
                }
                for year in [1, 2]
            ]
        )

    costs_by_scenario = {
        "Reference 100 % gaz": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=0.0, pac_heat=0.0, pac_electricity=0.0, backup=100.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
            reference=True,
        ),
        "Geothermie seule": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=0.0, pac_heat=80.0, pac_electricity=20.0, backup=20.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
        ),
        "Geothermie + solaire meme sondes": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=20.0, pac_heat=60.0, pac_electricity=15.0, backup=20.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
        ),
        "Geothermie + solaire sondes reduites": _multiyear_heat_cost(
            trajectory_df=trajectory(solar=20.0, pac_heat=60.0, pac_electricity=14.0, backup=20.0),
            heat_costs=heat_costs,
            economics=economics,
            capex_net_eur=0.0,
        ),
    }

    assert set(costs_by_scenario) == {
        "Reference 100 % gaz",
        "Geothermie seule",
        "Geothermie + solaire meme sondes",
        "Geothermie + solaire sondes reduites",
    }
    assert float(costs_by_scenario["Reference 100 % gaz"]["multiyear_heat_cost_eur_mwh"]) == 90.0
    assert float(costs_by_scenario["Geothermie seule"]["multiyear_heat_cost_eur_mwh"]) == 38.0
    assert float(costs_by_scenario["Geothermie + solaire meme sondes"]["multiyear_heat_cost_eur_mwh"]) == 33.0
    assert float(costs_by_scenario["Geothermie + solaire sondes reduites"]["multiyear_heat_cost_eur_mwh"]) == 32.0
    assert float(costs_by_scenario["Geothermie + solaire sondes reduites"]["pac_electricity_cumulative_mwh"]) == 28.0
    assert float(costs_by_scenario["Geothermie + solaire meme sondes"]["backup_gas_cumulative_mwh"]) == 40.0
