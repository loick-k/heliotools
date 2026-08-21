"""HelioCOP — note d'opportunité PAC solaire."""


def render_heliocop_app() -> None:
    from .streamlit_heliocop_app import render_heliocop_app as _render

    _render()


__all__ = ["render_heliocop_app"]
