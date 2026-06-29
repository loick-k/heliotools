from __future__ import annotations

import pandas as pd


def round_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Round numeric display columns while preserving one decimal for COP."""

    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_numeric_dtype(out[column]):
            decimals = 1 if "COP" in str(column).upper() else 0
            rounded = out[column].round(decimals)
            if rounded.notna().all():
                out[column] = rounded if decimals else rounded.astype("int64")
            else:
                out[column] = rounded
    return out
