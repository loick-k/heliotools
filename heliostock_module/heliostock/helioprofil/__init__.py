"""HelioProfil calculation package."""

from __future__ import annotations

__all__ = ["render_helioprofil_app"]


def render_helioprofil_app() -> None:
    from .streamlit_helioprofil_app import render_helioprofil_app as _render

    return _render()
