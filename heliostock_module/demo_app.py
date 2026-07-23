import traceback

import streamlit as st

from heliostock import ui_portal


st.set_page_config(page_title="HelioTools", layout="wide")


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

if selected_app == ui_portal.APP_HOME_LABEL:
    ui_portal.render_heliotools_home_page()

elif selected_app == ui_portal.APP_ADMIN_LABEL:
    ui_portal.render_admin_dashboard_page()

elif selected_app == ui_portal.APP_HELIOSTOCK_LABEL:
    try:
        if st.session_state.get("heliostock_view", "solver") == "notice":
            ui_portal.render_heliostock_notice_page()
        else:
            from heliostock.streamlit_module import render_heliostock_hourly

            render_heliostock_hourly()
    except Exception:
        _show_startup_error("HelioStock n'a pas pu démarrer.")

elif selected_app == ui_portal.APP_DASHBOARD_LABEL:
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

elif selected_app == ui_portal.APP_OPPORTUNITY_LABEL:
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
        _show_startup_error("HelioNOP a rencontré une erreur.")

elif selected_app == ui_portal.APP_HELIOECO_LABEL:
    try:
        from heliostock.helioeco import render_helioeco_app

        render_helioeco_app()
    except ModuleNotFoundError as exc:
        st.error(
            "HelioEco nécessite des dépendances optionnelles. "
            "Vérifie que `plotly` et `pandas` sont installés, puis relance l'application."
        )
        st.caption(str(exc))
    except Exception:
        _show_startup_error("HelioEco a rencontré une erreur.")

elif selected_app == ui_portal.APP_SOCOL_LABEL:
    try:
        from heliostock.socol_schematheque import render_socol_schematheque_app

        render_socol_schematheque_app()
    except ModuleNotFoundError as exc:
        st.error(
            "La schémathèque SOCOL nécessite des dépendances optionnelles. "
            "Vérifie que `Pillow` est installé, puis relance l'application."
        )
        st.caption(str(exc))
    except Exception:
        _show_startup_error("La schémathèque SOCOL a rencontré une erreur.")

