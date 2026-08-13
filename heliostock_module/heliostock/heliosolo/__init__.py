"""HelioSOLO calculation package."""

from __future__ import annotations

__all__ = ["render_heliosolo_app"]


def render_heliosolo_app() -> None:
    from .streamlit_heliosolo_app import render_heliosolo_app as _render

    return _render()

