from pathlib import Path

from heliostock.engine import BtesConfig
from heliostock.geothermal_design import predimension_borefield
from heliostock.inputs import BtesInputs
from heliostock.ui_inputs import FixedGeoAssumptions


def _module_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_predesign_ratio_not_equal_hard_cap():
    geo = FixedGeoAssumptions()
    assert geo.predesign_power_ratio_w_m == 50.0
    assert geo.max_extraction_w_m == 70.0
    assert geo.predesign_power_ratio_w_m != geo.max_extraction_w_m


def test_standard_geo_defaults():
    geo = FixedGeoAssumptions()
    btes_inputs = BtesInputs(
        boreholes=10,
        depth_m=100.0,
        spacing_m=geo.spacing_m,
        t_initial_c=geo.t_initial_c,
        t_min_c=geo.t_min_c,
        t_max_c=geo.t_max_c,
    )
    btes_config = BtesConfig()

    assert geo.predesign_power_ratio_w_m == 50.0
    assert geo.predesign_energy_ratio_kwh_m_year == 100.0
    assert btes_inputs.max_extraction_w_m == 70.0
    assert btes_inputs.max_injection_w_m == 80.0
    assert btes_config.max_extraction_w_m == 70.0
    assert btes_config.max_injection_w_m == 80.0


def test_hourly_engine_uses_hard_caps_not_predesign_ratio():
    source = (_module_root() / "heliostock" / "hourly_engine.py").read_text(encoding="utf-8")
    assert "btes.max_extraction_w_m" in source
    assert "btes.max_injection_w_m" in source
    assert "predesign_power_ratio_w_m" not in source
    assert "probe_power_ratio_w_m" not in source


def test_warning_can_trigger_above_predesign_ratio_without_hard_cap():
    source = (_module_root() / "heliostock" / "ui_results.py").read_text(encoding="utf-8")
    assert "EXTRACTION_WARNING_W_M = 50.0" in source
    assert "EXTRACTION_STRONG_WARNING_W_M = 60.0" in source
    assert "scenario.config.btes.max_extraction_w_m" in source
    assert "Les ratios de prédimensionnement ne sont pas des limites physiques instantanées" in source


def test_annual_kwh_per_m_reporting():
    source = (_module_root() / "heliostock" / "ui_results.py").read_text(encoding="utf-8")
    assert "def _final_btes_energy_per_m" in source
    assert "return float(final_rows[column].sum()) * 1000.0 / max(1e-9, length_m)" in source
    assert "Énergie extraite du sol" in source
    assert "Énergie injectée BTES" in source


def test_borefield_savings_does_not_reject_on_predesign_ratio():
    source = (_module_root() / "heliostock" / "borefield_savings.py").read_text(encoding="utf-8")
    assert "final_q_extraction_max_w_m\"] <= config.btes.max_extraction_w_m" in source
    assert "final_q_injection_max_w_m\"] <= config.btes.max_injection_w_m" in source
    assert "predesign_power_ratio_w_m" not in source
    assert "probe_power_ratio_w_m" not in source


def test_borefield_predesign_uses_prudent_max_of_power_and_annual_extraction():
    predesign = predimension_borefield(
        pac_power_kw=100.0,
        cop=5.0,
        heat_pac_mwh_year=500.0,
        power_ratio_w_per_m=40.0,
        max_extraction_kwh_per_m_year=60.0,
        unit_depth_m=100.0,
        safety_factor=1.20,
    )
    length_power = predesign.ground_power_kw * 1000.0 / 40.0 * 1.20
    length_energy = predesign.ground_heat_mwh_year * 1000.0 / 60.0 * 1.20

    assert predesign.energy_ratio_kwh_per_m_year == 60.0
    assert predesign.required_length_m >= length_power
    assert predesign.required_length_m >= length_energy
