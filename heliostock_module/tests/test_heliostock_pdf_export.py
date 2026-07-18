from __future__ import annotations

import pandas as pd

from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, SimulationConfig
from heliostock.heliostock_pdf_export import build_heliostock_overview_pdf
from heliostock.scenario_outputs import ScenarioResult


def _minimal_scenario_result() -> ScenarioResult:
    trajectory = pd.DataFrame(
        [
            {
                "Scenario": "Geothermie seule",
                "Annee": 1,
                "Taux EnR (%)": 70.0,
                "Appoint gaz total (MWh)": 120.0,
            },
            {
                "Scenario": "Geothermie seule",
                "Annee": 25,
                "Taux EnR (%)": 68.0,
                "COP moyen": 5.1,
                "SPF PAC complet": 4.4,
                "Chaleur PAC BT (MWh)": 900.0,
                "Couverture PAC BT (%)": 94.0,
                "Electricite PAC (MWh)": 205.0,
                "Appoint gaz total (MWh)": 140.0,
                "T_source_PAC_min (C)": -2.5,
                "Heures sous Tmin GMI": 0.0,
                "Heures sur Tmax GMI": 0.0,
                "Heures limite source": 120.0,
                "q_extraction_W_m_max": 42.0,
                "q_injection_W_m_max": 0.0,
            },
            {
                "Scenario": "Geothermie + solaire meme sondes",
                "Annee": 1,
                "Taux EnR (%)": 78.0,
                "Appoint gaz total (MWh)": 80.0,
            },
            {
                "Scenario": "Geothermie + solaire meme sondes",
                "Annee": 25,
                "Taux EnR (%)": 76.0,
                "COP moyen": 5.5,
                "SPF PAC complet": 4.8,
                "Chaleur PAC BT (MWh)": 910.0,
                "Couverture PAC BT (%)": 95.0,
                "Electricite PAC (MWh)": 190.0,
                "Appoint gaz total (MWh)": 90.0,
                "T_source_PAC_min (C)": -1.0,
                "Heures sous Tmin GMI": 0.0,
                "Heures sur Tmax GMI": 0.0,
                "Heures limite source": 80.0,
                "q_extraction_W_m_max": 40.0,
                "q_injection_W_m_max": 35.0,
            },
            {
                "Scenario": "Geothermie + solaire sondes reduites",
                "Annee": 25,
                "Taux EnR (%)": 75.0,
                "COP moyen": 5.3,
                "SPF PAC complet": 4.6,
                "Chaleur PAC BT (MWh)": 905.0,
                "Couverture PAC BT (%)": 94.0,
                "Electricite PAC (MWh)": 196.0,
                "Appoint gaz total (MWh)": 95.0,
                "T_source_PAC_min (C)": -2.8,
                "Heures sous Tmin GMI": 0.0,
                "Heures sur Tmax GMI": 0.0,
                "Heures limite source": 100.0,
                "q_extraction_W_m_max": 48.0,
                "q_injection_W_m_max": 43.0,
            },
        ]
    )
    comparison = pd.DataFrame(
        [
            {
                "Scenario": "Geothermie seule",
                "Cout chaleur global (EUR/MWh)": 90.0,
                "CAPEX net (EUR)": 700000.0,
                "P1 cumule (EUR)": 100000.0,
                "P2 cumule (EUR)": 200000.0,
                "Appoint gaz cumule (MWh)": 2500.0,
                "Lineaire sondes (ml)": 15000.0,
            },
            {
                "Scenario": "Geothermie + solaire meme sondes",
                "Cout chaleur global (EUR/MWh)": 85.0,
                "CAPEX net (EUR)": 900000.0,
                "P1 cumule (EUR)": 95000.0,
                "P2 cumule (EUR)": 240000.0,
                "Appoint gaz cumule (MWh)": 1700.0,
                "Lineaire sondes (ml)": 15000.0,
            },
            {
                "Scenario": "Geothermie + solaire sondes reduites",
                "Cout chaleur global (EUR/MWh)": 84.0,
                "CAPEX net (EUR)": 880000.0,
                "P1 cumule (EUR)": 98000.0,
                "P2 cumule (EUR)": 240000.0,
                "Appoint gaz cumule (MWh)": 1800.0,
                "Lineaire sondes (ml)": 14000.0,
            },
        ]
    )
    hourly = pd.DataFrame(
        [
            {
                "Jour annee": day,
                "solar_ht_buffer_temp_end_c": 40.0 + day * 0.2,
                "T_source_PAC_fin_heure_C": 5.0 - day * 0.02,
                "T_paroi_forage_C": 6.0 - day * 0.015,
                "T_evaporateur_PAC_C": 2.0 - day * 0.02,
            }
            for day in range(0, 365, 12)
        ]
    )
    monthly = pd.DataFrame(
        [
            {
                "Mois": f"{month:02d}",
                "Prechauffage HT solaire (MWh)": 12.0 + month,
                "Injection BTES (MWh)": 6.0 + month / 2,
                "BT PAC (MWh)": 70.0 + month,
                "Appoint HT (MWh)": 4.0,
                "Appoint BT (MWh)": 3.0,
            }
            for month in range(1, 13)
        ]
    )
    multiyear = pd.DataFrame(
        [
            {
                "Annee": year,
                "Mois index": (year - 1) * 12 + month,
                "Mois": f"A{year:02d}-{month:02d}",
                "T source PAC fin (C)": 6.0 - year * 0.1 + month * 0.03,
            }
            for year in range(1, 4)
            for month in range(1, 13)
        ]
    )
    no_solar_multiyear = multiyear.assign(**{"T source PAC fin (C)": multiyear["T source PAC fin (C)"] - 1.0})
    reduced_multiyear = multiyear.assign(**{"T source PAC fin (C)": multiyear["T source PAC fin (C)"] - 0.4})
    return ScenarioResult(
        config=SimulationConfig(
            collector=CollectorConfig(area_m2=850.0, daily_buffer_l_per_m2=60.0),
            btes=BtesConfig(boreholes=150, depth_m=100.0),
            heat_pump=HeatPumpConfig(max_thermal_power_kw=730.0),
        ),
        hourly_df=hourly,
        no_solar_hourly_df=pd.DataFrame(),
        multiyear_btes_df=multiyear,
        no_solar_multiyear_btes_df=no_solar_multiyear,
        reduced_multiyear_btes_df=reduced_multiyear,
        annual_df=pd.DataFrame(),
        hourly_by_month_df=monthly,
        savings={"simulated": True, "found": True, "candidate_length_m": 14000.0, "saved_length_m": 1000.0},
        solar_economics={},
        heat_costs={},
        economic_comparison_df=comparison,
        economic_comparison_chart_df=pd.DataFrame(),
        economic_trajectory_df=trajectory,
        solar_parametric_reference={},
        recharge_value={},
        solar_allocation={},
        total_ht_kwh=350000.0,
        total_bt_kwh=1100000.0,
        total_preheat_ht_kwh=240000.0,
        total_charge_buffer_kwh=500000.0,
        total_to_btes_kwh=260000.0,
        total_solar_valued_kwh=500000.0,
        solar_productivity_valued_kwh_m2_year=588.0,
        solar_ht_from_buffer_economic_mwh=240.0,
        total_backup_ht_kwh=110000.0,
        total_backup_bt_kwh=90000.0,
        annual_ht_solar_coverage=0.69,
        total_pac_kwh=910000.0,
        total_compressor_kwh=170000.0,
        total_pac_auxiliaries_kwh=25000.0,
        total_standby_kwh=400.0,
        total_elec_kwh=195400.0,
        total_system_elec_kwh=195400.0,
        mean_cop=5.5,
        spf_pac_total=4.7,
        spf_system=5.9,
        global_ren_rate=0.76,
        no_solar_total_pac_kwh=900000.0,
        no_solar_total_compressor_kwh=176000.0,
        no_solar_total_elec_kwh=205000.0,
        no_solar_cop=5.1,
        backup_power_kw=350.0,
        full_borefield_length_m=15000.0,
        economic_borefield_length_m=14000.0,
        reference_gas_power_kw=900.0,
        simulation_year_displayed=25,
        simulation_years_total=25,
        economic_years_used=25,
        gmi_check_enabled=True,
    )


def test_heliostock_overview_pdf_is_generated_from_scenario_result():
    pdf = build_heliostock_overview_pdf(
        _minimal_scenario_result(),
        calculation_id="test",
        calculated_at="2026-07-18",
    )

    assert pdf.startswith(b"%PDF-1.3") or pdf.startswith(b"%PDF-1.4")
    assert len(pdf) > 16000
    assert b"HelioStock" in pdf
    assert b"graphiques" in pdf
    assert b"Geothermie" in pdf or "Géothermie".encode("cp1252") in pdf
