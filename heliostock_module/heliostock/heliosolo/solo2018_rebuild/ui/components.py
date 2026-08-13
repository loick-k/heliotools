from __future__ import annotations

import streamlit as st


def render_kv_table(title: str, rows: list[tuple[str, str]]) -> None:
    trs = "".join(
        f"<tr><th>{label}</th><td>{value}</td></tr>"
        for label, value in rows
    )
    st.markdown(
        f"""
        <div class="solo-card">
          <div class="solo-card-title">{title}</div>
          <table class="solo-kv">
            <tbody>{trs}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


