import traceback

import streamlit as st

from heliostock import ui_portal


st.set_page_config(page_title="HelioStock", layout="wide")


def _is_user_authenticated() -> bool:
    checker = getattr(ui_portal, "is_user_authenticated", None)
    if callable(checker):
        return bool(checker())
    user = st.session_state.get("user")
    return bool(isinstance(user, dict) and user.get("email"))


def _show_startup_error(title: str) -> None:
    st.error(title)
    st.code(traceback.format_exc(), language="text")


if not _is_user_authenticated():
    ui_portal.render_admin_login()
    st.stop()

selected_app = ui_portal.render_portal_sidebar()

if selected_app == "HelioStock":
    try:
        from heliostock.streamlit_module import render_heliostock_hourly

        render_heliostock_hourly()
    except Exception:
        _show_startup_error("HelioStock n'a pas pu démarrer.")

elif selected_app == "Dashboard solaire thermique":
    try:
        from heliostock.solar_thermal_dashboard import render_solar_thermal_dashboard

        render_solar_thermal_dashboard()
    except ModuleNotFoundError as exc:
        st.error(
            "Le dashboard solaire thermique nécessite des dépendances optionnelles. "
            "Installe `pyairtable`, `plotly`, `folium` et `streamlit-folium`, puis relance l'application."
        )
        st.caption(str(exc))
    except Exception:
        _show_startup_error("Le dashboard solaire thermique a rencontré une erreur.")

elif selected_app == "Note d'opportunité solaire thermique":
    try:
        from heliostock.opportunity_notes import render_opportunity_notes_app

        render_opportunity_notes_app()
    except ModuleNotFoundError as exc:
        st.error(
            "La note d'opportunité solaire thermique nécessite des dépendances optionnelles. "
            "Vérifie que `plotly` et `pandas` sont installés, puis relance l'application."
        )
        st.caption(str(exc))
    except Exception:
        _show_startup_error("La note d'opportunité solaire thermique a rencontré une erreur.")
