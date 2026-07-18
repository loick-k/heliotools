from heliostock.opportunity_notes.cesc_economic_model import (
    CescEconomicInputs,
    compute_cesc_economic_model,
)
from heliostock.opportunity_notes.opportunity_model import (
    LoopInputs,
    NeedsInputs,
    SizingInputs,
    SiteInputs,
    compute_opportunity_results,
)
from heliostock.opportunity_notes.pdf_export import build_opportunity_note_pdf
from pypdf import PdfReader
from io import BytesIO


def test_opportunity_note_pdf_export_builds_from_default_results():
    site_inputs = SiteInputs(project_name="Projet test PDF")
    needs_inputs = NeedsInputs()
    sizing_inputs = SizingInputs()
    loop_inputs = LoopInputs()
    opportunity_results = compute_opportunity_results(site_inputs, needs_inputs, sizing_inputs, loop_inputs)
    economic_inputs = CescEconomicInputs(
        surface_m2=opportunity_results.collectors.surface_m2,
        productivity_kwh_m2_year=sizing_inputs.productivity_kwh_m2_year,
    )
    economic_results = compute_cesc_economic_model(economic_inputs)

    payload = build_opportunity_note_pdf(
        site_inputs=site_inputs,
        needs_inputs=needs_inputs,
        sizing_inputs=sizing_inputs,
        loop_inputs=loop_inputs,
        economic_inputs=economic_inputs,
        opportunity_results=opportunity_results,
        economic_results=economic_results,
    )

    assert payload.startswith(b"%PDF")
    assert len(payload) > 5000
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)
    assert "Répartition annuelle des besoins" in text
    assert "ECS utile / bouclage" in text
    assert "ECS utile / bouclage / chauffage" in text
    assert "Chauffage estimé" in text
