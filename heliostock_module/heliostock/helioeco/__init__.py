from __future__ import annotations

__all__ = ["render_helioeco_app"]


def __getattr__(name: str):
    if name == "render_helioeco_app":
        from .streamlit_helioeco_app import render_helioeco_app

        return render_helioeco_app
    raise AttributeError(name)
