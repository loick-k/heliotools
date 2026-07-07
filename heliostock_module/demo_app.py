import streamlit as st

from heliostock.streamlit_module import render_heliostock_hourly
from heliostock.ui_portal import render_login_portal, render_portal_sidebar


st.set_page_config(page_title="HelioStock", layout="wide")

if not render_login_portal():
    st.stop()

selected_app = render_portal_sidebar()
if selected_app == "HelioStock":
    render_heliostock_hourly()
