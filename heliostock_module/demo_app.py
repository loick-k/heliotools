import streamlit as st

from heliostock.streamlit_module import render_heliostock_hourly
from heliostock.ui_portal import render_login_portal, render_portal_sidebar


st.set_page_config(page_title="HelioStock", layout="wide")

if not render_login_portal():
    st.stop()

selected_app = render_portal_sidebar()
if selected_app == "HelioStock":
    render_heliostock_hourly()
elif selected_app == "Dashboard solaire thermique":
    try:
        from heliostock.solar_thermal_dashboard import render_solar_thermal_dashboard
    except ModuleNotFoundError as exc:
        st.error(
            "Le dashboard solaire thermique nécessite des dépendances optionnelles. "
            "Installe `pyairtable`, `plotly`, `folium` et `streamlit-folium`, puis relance l'application."
        )
        st.caption(str(exc))
    else:
        render_solar_thermal_dashboard()
