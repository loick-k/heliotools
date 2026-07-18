from pathlib import Path

import pandas as pd

from heliostock.ui_formatting import display_dataframe, round_display_df


def _module_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_streamlit_calls_use_width_instead_of_deprecated_container_width():
    module_dir = _module_root() / "heliostock"
    streamlit_sources = [
        path
        for path in module_dir.glob("*.py")
        if path.name.startswith(("ui_", "streamlit", "solar_thermal_dashboard"))
    ]

    offenders = [
        str(path.relative_to(module_dir.parent))
        for path in streamlit_sources
        if "use_container_width" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_ui_text_does_not_contain_common_mojibake_sequences():
    module_dir = _module_root() / "heliostock"
    ui_sources = [
        path
        for path in module_dir.glob("*.py")
        if path.name.startswith(("ui_", "streamlit"))
    ]
    mojibake_markers = (chr(0x00C2), chr(0x00C3))

    offenders = []
    suspicious_question_marks = []
    for path in ui_sources:
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in mojibake_markers):
            offenders.append(str(path.relative_to(module_dir.parent)))
        for line_no, line in enumerate(text.splitlines(), start=1):
            if "?" in line and "?ref=" not in line:
                suspicious_question_marks.append(f"{path.name}:{line_no}")

    assert offenders == []
    assert suspicious_question_marks == []


def test_ui_results_hides_irrelevant_blocks_by_demand_scope():
    source = (_module_root() / "heliostock" / "ui_results.py").read_text(encoding="utf-8")

    assert 'if show_solar_blocks:' in source
    assert 'if show_geothermal_blocks:' in source
    assert 'result_sections = []' in source
    assert 'result_sections.append("Paramétrique PAC")' in source
    assert 'result_sections.append("Paramétrique solaire")' in source
    assert "Solaire thermique" in source
    assert "PAC géothermie" in source
    assert "Scénario A - Géothermie seule" in source
    assert "Scénario B - Géothermie avec recharge solaire BT // Solaire thermique HT" in source
    assert "Scénario C - Géothermie avec recharge solaire BT et linéaire de sondes réduites // Solaire thermique HT" in source
    assert "Appoint gaz" in source


def test_round_display_df_keeps_one_decimal_for_cop_columns():
    df = pd.DataFrame(
        {
            "COP PAC moyen": [5.94],
            "CAPEX net (EUR)": [1234.56],
        }
    )
    rounded = round_display_df(df)

    assert float(rounded["COP PAC moyen"].iloc[0]) == 5.9
    assert int(rounded["CAPEX net (EUR)"].iloc[0]) == 1235


def test_display_dataframe_normalizes_mixed_object_columns():
    df = pd.DataFrame(
        {
            "Progression (%)": [None, 15, 35.0],
            "Message": ["start", 2, None],
            "Economie sondes trouvee": [True, False, True],
            "_private": [object(), object(), object()],
        }
    )

    display_df = display_dataframe(df)

    assert "_private" not in display_df
    assert pd.api.types.is_numeric_dtype(display_df["Progression (%)"])
    assert pd.api.types.is_string_dtype(display_df["Message"])
    assert pd.api.types.is_bool_dtype(display_df["Economie sondes trouvee"])


def test_ui_results_uses_single_active_section_instead_of_tabs():
    source = (_module_root() / "heliostock" / "ui_results.py").read_text(encoding="utf-8")
    assert "st.tabs(" not in source
    assert "st.radio(" in source
