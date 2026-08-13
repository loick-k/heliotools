from __future__ import annotations

import pandas as pd
import streamlit as st


def apply_editor_pending_edits(df: pd.DataFrame, editor_key: str) -> pd.DataFrame:
    """Apply Streamlit data_editor pending edits before the next rerun commits them."""
    state = st.session_state.get(editor_key)
    if not isinstance(state, dict):
        return df

    edited_rows = state.get("edited_rows", {})
    if not isinstance(edited_rows, dict) or not edited_rows:
        return df

    out = df.copy()
    for row_idx_raw, changes in edited_rows.items():
        if not isinstance(changes, dict):
            continue
        try:
            row_idx = int(row_idx_raw)
        except (TypeError, ValueError):
            continue
        if row_idx < 0 or row_idx >= len(out):
            continue
        for col, value in changes.items():
            if col in out.columns:
                out.at[out.index[row_idx], col] = value
    return out


