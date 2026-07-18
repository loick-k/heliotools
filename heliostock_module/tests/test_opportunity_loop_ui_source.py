from pathlib import Path

from heliostock.opportunity_notes.opportunity_model import (
    LoopInputs,
    MONTH_NAMES,
    NeedsInputs,
    SizingInputs,
    SiteInputs,
    compute_opportunity_results,
)


SOURCE = Path(__file__).resolve().parents[1] / "heliostock" / "opportunity_notes" / "streamlit_opportunity_app.py"


def test_loop_tab_no_excel_paste_box_and_has_heating_outputs():
    source = SOURCE.read_text(encoding="utf-8")
    loop_block = source.split("# Bouclage sanitaire.", 1)[1].split("# Prédimensionnement.", 1)[0]

    assert "add_excel_paste_box" not in loop_block
    assert "Chauffage estimé" in loop_block
    assert "Répartition annuelle ECS utile / bouclage / chauffage" in source


def test_gas_invoice_analysis_exposes_heating_above_summer_baseload():
    gas_monthly_kwh = {month: 1000.0 for month in MONTH_NAMES}
    gas_monthly_kwh["Janvier"] = 3000.0
    loop = LoopInputs(
        method="Analyse factures gaz",
        gas_monthly_kwh=gas_monthly_kwh,
        boiler_efficiency=0.8,
    )

    results = compute_opportunity_results(
        SiteInputs(),
        NeedsInputs(housing_counts={"T1": 0, "T2": 1, "T3": 0, "T4": 0, "T5": 0, "T6 et +": 0}),
        SizingInputs(),
        loop,
    )
    january = next(row for row in results.monthly_needs if row.month == "Janvier")

    assert january.gas_consumption_kwh == 3000.0
    assert january.heating_after_boiler_kwh > 0.0
    assert results.annual_heating_after_boiler_mwh > 0.0
