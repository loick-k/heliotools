from heliostock.common.pdf import PdfReport


def test_common_pdf_report_builds_valid_pdf_bytes():
    report = PdfReport(title="Test HelioTools", subtitle="Rapport commun")
    y = report.start_page()
    y = report.section_title("Indicateurs", x=34, y=y)
    report.kpi_grid(
        [("Surface", "100 m2"), ("Production", "50 MWh/an")],
        x=34,
        y=y,
        width=report.page_width - 68,
    )
    report.draw_footer()
    payload = report.finish()

    assert payload.startswith(b"%PDF")
    assert len(payload) > 1000
