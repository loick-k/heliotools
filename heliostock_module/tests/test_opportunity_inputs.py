import importlib.util

import pandas as pd
import pytest

if importlib.util.find_spec("streamlit") is None:
    pytest.skip("streamlit non installé", allow_module_level=True)

from heliostock.opportunity_notes import streamlit_opportunity_app as app
from heliostock.opportunity_notes.opportunity_model import MONTH_NAMES


def test_ecs_profile_conversions_are_reversible_for_monthly_energy():
    daily_l = app._value_to_daily_l_60c(
        value=1.0,
        input_mode="Consommation ECS MWh/mois",
        month="Janvier",
        cold_water_temperature_c=10.0,
    )

    assert daily_l > 0
    assert app._daily_l_to_monthly_mwh(
        daily_l_60c=daily_l,
        month="Janvier",
        cold_water_temperature_c=10.0,
    ) == 1.0


def test_ecs_profile_conversions_cover_volume_and_daily_energy():
    assert app._value_to_daily_l_60c(
        value=31.0,
        input_mode="Volume m³/mois",
        month="Janvier",
        cold_water_temperature_c=10.0,
    ) == 1000.0

    daily_l = app._value_to_daily_l_60c(
        value=10.0,
        input_mode="Consommation ECS kWh/jour",
        month="Janvier",
        cold_water_temperature_c=10.0,
    )
    assert app._daily_l_to_daily_kwh(daily_l_60c=daily_l, cold_water_temperature_c=10.0) == 10.0


def test_esm2_cold_water_temperatures_are_monthly_and_offset_applies():
    monthly_air = {month: float(index) for index, month in enumerate(MONTH_NAMES, start=1)}

    esm2 = app._esm2_cold_water_temperatures(monthly_air)
    esm2_plus_3 = app._esm2_cold_water_temperatures(monthly_air, offset_c=3.0)

    assert set(esm2) == set(MONTH_NAMES)
    assert all(5.0 <= value <= 25.0 for value in esm2.values())
    assert esm2_plus_3["Mars"] > esm2["Mars"]


def test_monthly_profile_upload_without_month_column_uses_first_numeric_column():
    class Upload:
        name = "profil.csv"

        def getvalue(self):
            return b"valeur\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n"

    df = app._read_monthly_profile_upload(Upload(), "Profil")

    assert isinstance(df, pd.DataFrame)
    assert list(df["Mois"]) == list(MONTH_NAMES)
    assert float(df["Profil"].iloc[0]) == 1.0
    assert float(df["Profil"].iloc[-1]) == 12.0


def test_ecs_and_cold_water_blocks_do_not_use_excel_paste_box():
    source = (app.__file__ and open(app.__file__, encoding="utf-8").read()) or ""
    needs_block = source.split("# Besoins ECS.", 1)[1].split("# Bouclage sanitaire.", 1)[0]
    cold_block = source.split("# Eau froide et paramètres de prédimensionnement.", 1)[1].split("# Besoins ECS.", 1)[0]

    assert "add_excel_paste_box" not in needs_block
    assert "add_excel_paste_box" not in cold_block
