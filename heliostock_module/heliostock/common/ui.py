from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd
import streamlit as st


def render_metric_grid(metrics: Iterable[dict[str, Any]], *, columns: int = 4) -> None:
    """Render metrics in stable left-aligned rows without changing values."""
    items = [metric for metric in metrics if metric]
    if not items:
        return
    for start in range(0, len(items), columns):
        row = items[start : start + columns]
        cols = st.columns(columns)
        for index, metric in enumerate(row):
            cols[index].metric(
                label=str(metric.get("label", "")),
                value=str(metric.get("value", "n.d.")),
                delta=metric.get("delta"),
                help=metric.get("help"),
            )


def render_dataframe_safe(df: pd.DataFrame, **kwargs: Any) -> None:
    """Render a DataFrame after making object columns Arrow-friendly."""
    display_df = df.copy()
    for column in display_df.columns:
        if display_df[column].dtype == "object":
            display_df[column] = display_df[column].map(lambda value: "" if value is None else str(value))
    if "width" not in kwargs and "use_container_width" not in kwargs:
        kwargs["width"] = "stretch"
    st.dataframe(display_df, **kwargs)

