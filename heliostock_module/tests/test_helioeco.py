from pathlib import Path

from heliostock.opportunity_notes.cesc_economic_model import (
    CescEconomicInputs,
    build_yearly_cashflow_projection,
    compute_cesc_economic_model,
)


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (MODULE_ROOT / relative_path).read_text(encoding="utf-8")


def approx(value, expected, tolerance=1e-6):
    assert abs(value - expected) <= tolerance, f"{value} != {expected}"


def test_helioeco_default_values_match_imported_excel_v5_model():
    results = compute_cesc_economic_model(CescEconomicInputs())

    approx(results.annual_production_mwh, 18.9956)
    approx(results.average_reference_energy_cost_eur_mwh, 122.88281016302032)
    approx(results.investment_cost_eur, 57758.4)
    approx(results.aid_total_eur, 27384.756)
    approx(results.net_investment_eur, 30373.644)
    approx(results.annual_savings_eur, 1533.6459087326737)
    approx(results.raw_payback_years, 19.804860970221753)
    approx(results.heat_cost_p1_eur_mwh, 3.0)
    approx(results.heat_cost_p2_eur_mwh, 39.145907473309606)
    approx(results.heat_cost_p4_eur_mwh, 79.94915664680242)
    approx(results.solar_heat_cost_eur_mwh, 122.09506412011203)
    approx(results.savings_over_period_eur, 299.27417465347025)


def test_helioeco_app_is_callable_without_page_config():
    package_source = _source("heliostock/helioeco/__init__.py")
    app_source = _source("heliostock/helioeco/streamlit_helioeco_app.py")

    assert 'APP_LABEL = "HelioEco"' in app_source
    assert "def render_helioeco_app() -> None:" in app_source
    assert "build_heat_cost_breakdown_rows" in app_source
    assert "from ..opportunity_notes.cesc_economic_model import" in app_source
    assert "st.set_page_config" not in app_source
    assert "def __getattr__" in package_source


def test_helioeco_cashflow_chart_uses_existing_projection_columns():
    inputs = CescEconomicInputs()
    results = compute_cesc_economic_model(inputs)
    cashflow_rows = list(build_yearly_cashflow_projection(inputs, results))
    app_source = _source("heliostock/helioeco/streamlit_helioeco_app.py")

    assert "Flux annuel inflation annuelle (€)" not in cashflow_rows[0]
    assert "Économie annuelle inflation (€)" in cashflow_rows[0]
    assert '"Économie annuelle inflation (€)"' in app_source
