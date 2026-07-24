"""HelioRC calculation package."""

from .engine import (
    AID_FORFAITS,
    CALCULATION_MODES,
    DEFAULT_MONTHLY_NEEDS_MWH,
    MONTHS_FR,
    REGIMES,
    calculate_opportunity,
    estimate_monthly_needs,
)


def render_heliorc_app():
    from .streamlit_heliorc_app import render_heliorc_app as _render

    return _render()


__all__ = [
    "AID_FORFAITS",
    "CALCULATION_MODES",
    "DEFAULT_MONTHLY_NEEDS_MWH",
    "MONTHS_FR",
    "REGIMES",
    "calculate_opportunity",
    "estimate_monthly_needs",
    "render_heliorc_app",
]
