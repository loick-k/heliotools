from __future__ import annotations

import json
from datetime import date

import streamlit as st

from .solo2018_rebuild.services.app_config import ensure_app_state as _ensure_app_state
from .solo2018_rebuild.ui.config_io import (
    apply_config_payload as _apply_config_payload,
    build_config_payload as _build_config_payload,
    json_default as _json_default,
)
from .solo2018_rebuild.ui.context import ModelisationContext
from .solo2018_rebuild.ui.description import render_description as _render_description
from .solo2018_rebuild.ui.modelisation import render_modelisation as _render_modelisation
from .solo2018_rebuild.ui.resultats import render_resultats as _render_resultats
from .notice_heliosolo import render_heliosolo_notice as _render_heliosolo_notice


def _render_legacy_solo_styles() -> None:
    st.markdown(
        """
        <style>
        .solo-header {
          background:#e6e6e6;border:1px solid #8f8f8f;padding:6px 10px;margin-bottom:8px;
          font-size:14px;font-weight:600;display:flex;justify-content:space-between;align-items:center;
        }
        .solo-grid { display:grid; grid-template-columns:repeat(4,minmax(220px,1fr)); gap:8px; margin-bottom:10px; }
        .solo-card { border:1px solid #8f8f8f; background:#f0f0f0; height:100%; }
        .solo-card-title {
          background:#d9d9d9; border-bottom:1px solid #8f8f8f; font-weight:700;
          min-height:32px; display:flex; align-items:center; justify-content:center; text-align:center; padding:4px 8px;
        }
        table.solo-kv { width:100%; border-collapse:collapse; font-size:13px; }
        table.solo-kv th, table.solo-kv td { border-top:1px solid #b5b5b5; padding:4px 6px; text-align:left; }
        table.solo-kv th { width:52%; font-weight:600; background:#efefef; }

        div[data-testid="stExpander"] details {
          border: 1px solid rgba(39, 54, 73, 0.18);
          border-radius: 14px;
          overflow: hidden;
          background: #ffffff;
          box-shadow: 0 10px 26px rgba(39, 54, 73, 0.07);
        }
        div[data-testid="stExpander"] details > summary {
          border-radius: 12px 12px 0 0;
          border-bottom: 1px solid rgba(39, 54, 73, 0.12);
          background: #eef6f8;
        }
        div[data-testid="stExpander"] details > summary p {
          color: #16313d;
          font-weight: 750;
          letter-spacing: 0.01em;
        }
        div[data-testid="stExpander"] details > div {
          background: #ffffff;
        }
        div[data-testid="stExpander"]:nth-of-type(odd) details {
          border-color: rgba(31, 111, 139, 0.28);
          background: #fbfdfe;
        }
        div[data-testid="stExpander"]:nth-of-type(odd) details > summary {
          background: #eef6f8;
        }
        div[data-testid="stExpander"]:nth-of-type(odd) details > div {
          background: #fbfdfe;
        }
        div[data-testid="stExpander"]:nth-of-type(even) details {
          border-color: rgba(183, 121, 31, 0.28);
          background: #fffdf8;
        }
        div[data-testid="stExpander"]:nth-of-type(even) details > summary {
          background: #fbf2dd;
        }
        div[data-testid="stExpander"]:nth-of-type(even) details > div {
          background: #fffdf8;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_heliosolo_app() -> None:
    st.title("HelioSOLO")
    st.caption("Reconstitution SOLO 2018 pour le calcul solaire thermique ECS.")
    _render_legacy_solo_styles()

    app_config = _ensure_app_state(st.session_state)

    cfg_load_col, cfg_save_col = st.columns(2)
    with cfg_load_col:
        uploaded_config = st.file_uploader(
            "Charger une configuration",
            type=["json"],
            key="heliosolo_config_upload_json",
        )
        if uploaded_config is not None and st.button("Appliquer la configuration", width="stretch"):
            try:
                payload = json.loads(uploaded_config.read().decode("utf-8-sig"))
                _apply_config_payload(payload)
                st.success("Configuration rechargée.")
                st.rerun()
            except Exception as exc:
                st.error(f"Configuration impossible à recharger : {exc}")

    with cfg_save_col:
        config_payload = _build_config_payload()
        st.download_button(
            "Sauvegarder une configuration",
            data=json.dumps(config_payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8"),
            file_name=f"heliosolo_config_{date.today().strftime('%Y-%m-%d')}.json",
            mime="application/json",
            width="stretch",
        )

    tab_description, tab_modelisation, tab_resultats, tab_notice = st.tabs(
        ["1) Description de l'opération", "2) Modélisation", "3) Résultats", "4) Notice"]
    )
    with tab_description:
        description_state = _render_description()

    with tab_modelisation:
        resultats_context = _render_modelisation(ModelisationContext(description_state, app_config))

    with tab_resultats:
        _render_resultats(resultats_context)

    with tab_notice:
        _render_heliosolo_notice()

