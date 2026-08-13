from __future__ import annotations

from pathlib import Path

import streamlit as st


_NOTICE_PATH = Path(__file__).with_name("NOTICE_HELIOSOLO.md")


def render_heliosolo_notice() -> None:
    """Affiche la notice méthodologique intégrée au module HelioSOLO."""
    try:
        notice = _NOTICE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        st.warning(f"Notice HelioSOLO indisponible : {exc}")
        return
    st.markdown(notice)
