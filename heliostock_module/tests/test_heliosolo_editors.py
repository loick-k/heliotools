from __future__ import annotations

from pathlib import Path

import pandas as pd

from heliostock.heliosolo.solo2018_rebuild.ui import editors


MODULE_ROOT = Path(__file__).resolve().parents[1]


def test_apply_editor_pending_edits_keeps_first_streamlit_rerun_value(monkeypatch):
    monkeypatch.setattr(
        editors.st,
        "session_state",
        {
            "monthly_profiles_editor": {
                "edited_rows": {
                    "0": {"VECS (L/j)": 1234.0},
                    1: {"Temperature ECS (degC)": 62.5},
                }
            }
        },
    )
    df = pd.DataFrame(
        {
            "Mois": ["Janvier", "Février"],
            "VECS (L/j)": [1500.0, 1500.0],
            "Temperature ECS (degC)": [60.0, 60.0],
        }
    )

    edited = editors.apply_editor_pending_edits(df, "monthly_profiles_editor")

    assert edited.loc[0, "VECS (L/j)"] == 1234.0
    assert edited.loc[1, "Temperature ECS (degC)"] == 62.5


def test_heliosolo_monthly_profiles_table_applies_pending_edits():
    source = (
        MODULE_ROOT
        / "heliostock"
        / "heliosolo"
        / "solo2018_rebuild"
        / "ui"
        / "modelisation_besoins.py"
    ).read_text(encoding="utf-8")

    assert "monthly_profiles_df = _apply_editor_pending_edits(monthly_profiles_df, \"monthly_profiles_editor\")" in source
