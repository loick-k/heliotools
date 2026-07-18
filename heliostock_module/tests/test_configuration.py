from dataclasses import replace
from pathlib import Path
import inspect

import heliostock.borefield_savings as borefield_savings_module
from heliostock.app_service import CalculationSelection, run_hourly_calculation
from heliostock.engine import BtesConfig
from heliostock.scenarios import run_hourly_scenario
from heliostock.ui_inputs import (
    DEFAULT_EPW_REGIONS,
    DEFAULT_EPW_STATIONS,
    FixedEconomicsAssumptions,
    FixedGeoAssumptions,
    FixedSolarAssumptions,
)


def test_default_technical_years_is_25():
    selection = CalculationSelection()
    assert selection.calculation_profile == "calcul_final"
    assert selection.technical_simulation_years == 25
    assert selection.custom_display_year == 25
    assert selection.savings_search_mode == "fast"
    assert selection.run_reduced_borefield is True


def test_technical_years_not_economic_years():
    app_source = inspect.getsource(run_hourly_calculation)
    scenario_source = inspect.getsource(run_hourly_scenario)
    assert "technical_simulation_years=int(technical_simulation_years)" in app_source
    assert "technical_simulation_years or 25" in scenario_source
    assert "technical_simulation_years or economics.analysis_years" not in scenario_source


def test_solar_parametric_reference_uses_technical_years():
    scenario_source = inspect.getsource(run_hourly_scenario)
    assert '"simulation_years": int(multiyear_years)' in scenario_source
    assert '"simulation_years": int(economics.analysis_years)' not in scenario_source


def test_default_borefield_spacing_is_10m():
    config = BtesConfig()
    geo = FixedGeoAssumptions()

    assert config.spacing_m == 10.0
    assert geo.spacing_m == 10.0
    default_length_m = config.boreholes * config.depth_m
    changed_config = replace(config, spacing_m=5.0)
    changed_spacing_length_m = changed_config.boreholes * changed_config.depth_m
    assert default_length_m == changed_spacing_length_m


def test_fixed_ui_assumptions_keep_expected_defaults():
    solar = FixedSolarAssumptions()
    geo = FixedGeoAssumptions()
    economics = FixedEconomicsAssumptions()

    assert "Bretagne" in DEFAULT_EPW_REGIONS
    assert "Pays de la Loire" in DEFAULT_EPW_REGIONS
    assert "Rennes - St Jacques" in DEFAULT_EPW_REGIONS["Bretagne"]
    assert "Nantes Atlantique" in DEFAULT_EPW_REGIONS["Pays de la Loire"]
    assert "Pays de la Loire - Nantes Atlantique" in DEFAULT_EPW_STATIONS
    assert solar.daily_buffer_l_per_m2 == 60.0
    assert solar.daily_buffer_tank_count == 1
    assert solar.daily_buffer_insulation_thickness_cm == 10.0
    assert solar.daily_buffer_insulation_lambda_w_m_k == 0.035
    assert "Volume ballon" not in set(solar.to_table()["Hypothese"])
    assert geo.spacing_m == 10.0
    assert geo.carnot_efficiency == 0.54
    assert geo.t_min_c == -3.0
    assert geo.gmi_t_min_c == -3.0
    assert geo.gmi_t_max_c == 40.0
    assert geo.predesign_power_ratio_w_m == 50.0
    assert geo.predesign_energy_ratio_kwh_m_year == 100.0
    assert geo.probe_power_ratio_w_m == 50.0
    assert geo.max_extraction_kwh_per_m_year == 100.0
    assert geo.max_extraction_w_m == 70.0
    assert geo.max_injection_w_m == 80.0
    assert geo.extraction_warning_w_m == 50.0
    assert geo.extraction_strong_warning_w_m == 60.0
    assert geo.injection_warning_w_m == 60.0
    assert geo.injection_strong_warning_w_m == 80.0
    assert geo.safety_factor == 1.20
    assert geo.reduced_borefield_safety_factor == 1.10
    assert economics.analysis_years == 20
    assert economics.ademe_eur_mwh_year == 63.0


def test_found_false_when_no_real_savings():
    result = borefield_savings_module._base_return(
        found=True,
        base_length_m=1000.0,
        boreholes=10,
        equivalent_cop=4.0,
        equivalent_bt_pac_kwh=1000.0,
        final_metrics={"depth_m": 100.0, "final_cop": 4.0},
        estimated_length_m=1000.0,
        simulations_count=0,
    )

    assert result["found"] is False
    assert float(result["saved_length_m"]) == 0.0
    assert float(result["saved_fraction"]) == 0.0
    assert result["message"] == "Aucune réduction de sondes validée"

    searched_result = borefield_savings_module._base_return(
        found=False,
        base_length_m=1000.0,
        boreholes=10,
        equivalent_cop=4.0,
        equivalent_bt_pac_kwh=1000.0,
        final_metrics={"depth_m": 100.0, "final_cop": 4.0},
        estimated_length_m=1000.0,
        simulations_count=2,
    )
    assert searched_result["message"] == "Recherche realisee ; aucun champ reduit n'a ete retenu pour affichage."


def test_no_pygfunction_parallel():
    root = Path(__file__).resolve().parents[1] / "heliostock"
    simulation_files = [
        "app_service.py",
        "borefield_savings.py",
        "btes_models.py",
        "hourly_engine.py",
        "scenario_compact.py",
        "scenarios.py",
        "simulation_cache.py",
    ]
    source = "\n".join((root / name).read_text(encoding="utf-8") for name in simulation_files)
    assert "ThreadPoolExecutor" not in source
    assert "ProcessPoolExecutor" not in source


def test_load_aggregation_mode_default():
    config = BtesConfig()
    assert config.load_aggregation_mode == "pygfunction_default"
