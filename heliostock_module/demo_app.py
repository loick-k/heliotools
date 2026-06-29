import streamlit as st

from heliostock.streamlit_module import render_heliostock_hourly


st.set_page_config(page_title="HelioStock", layout="wide")

render_heliostock_hourly()
