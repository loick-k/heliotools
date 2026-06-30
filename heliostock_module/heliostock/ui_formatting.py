from __future__ import annotations

from numbers import Number

import pandas as pd


def round_display_df(df: pd.DataFrame) -> pd.DataFrame:
    """Round numeric display columns while preserving one decimal for COP."""

    out = df.copy()
    for column in out.columns:
        if pd.api.types.is_bool_dtype(out[column]):
            continue
        if pd.api.types.is_numeric_dtype(out[column]):
            decimals = 1 if "COP" in str(column).upper() else 0
            rounded = out[column].round(decimals)
            if rounded.notna().all():
                out[column] = rounded if decimals else rounded.astype("int64")
            else:
                out[column] = rounded
    return out


def arrow_compatible_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dataframe dtypes before Streamlit serializes them with Arrow."""

    out = df.copy()
    private_columns = [column for column in out.columns if str(column).startswith("_")]
    if private_columns:
        out = out.drop(columns=private_columns)

    for column in out.columns:
        series = out[column]
        if pd.api.types.is_numeric_dtype(series):
            out[column] = pd.to_numeric(series, errors="coerce")
        elif pd.api.types.is_bool_dtype(series):
            out[column] = series.astype("boolean")
        elif pd.api.types.is_datetime64_any_dtype(series):
            out[column] = series
        elif pd.api.types.is_object_dtype(series):
            non_null = series.dropna()
            if non_null.empty:
                out[column] = series.astype("string")
            elif non_null.map(lambda value: isinstance(value, bool)).all():
                out[column] = series.astype("boolean")
            elif non_null.map(lambda value: isinstance(value, Number) and not isinstance(value, bool)).all():
                out[column] = pd.to_numeric(series, errors="coerce")
            else:
                out[column] = series.astype("string")
        else:
            out[column] = series.astype("string")
    return out


def display_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return arrow_compatible_df(round_display_df(df))
