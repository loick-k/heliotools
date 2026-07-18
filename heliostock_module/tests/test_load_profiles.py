from pathlib import Path
import tempfile

import pandas as pd

from heliostock.engine import MonthlyDemand
from heliostock.hourly_engine import HourlyWeather
from heliostock.load_profiles import _hourly_demands_from_process_file, apply_demand_scope


def test_hourly_8760_process_profile_maps_generic_ht_and_bt_columns():
    with tempfile.TemporaryDirectory() as tmp:
        workbook = Path(tmp) / "besoin_horaire.xlsx"
        pd.DataFrame(
            {
                "Date heure": pd.date_range("2001-01-01", periods=24, freq="h"),
                "E besoin BT kWh": [2.0] * 24,
                "E besoin HT kWh": [1.0] * 24,
            }
        ).to_excel(workbook, index=False)
        weather = [
            HourlyWeather(
                hour_index=hour,
                month=1,
                day=hour // 24 + 1,
                hour=hour % 24 + 1,
                tair_c=8.0,
                g_tilt_kwh_m2=0.0,
            )
            for hour in range(24)
        ]

        override, monthly, profile, info = _hourly_demands_from_process_file(workbook, weather)

        assert info["format"] == "hourly_8760"
        assert override[0] == (1.0, 2.0)
        assert float(profile["demand_ht_kwh"].sum()) == 24.0
        assert float(profile["demand_bt_kwh"].sum()) == 48.0
        assert monthly[0].process_ht_kwh == 24.0
        assert monthly[0].process_bt_kwh == 48.0


def test_apply_demand_scope_can_keep_only_ht_or_bt_needs():
    demands = [
        MonthlyDemand(month=1, process_ht_kwh=100.0, process_bt_kwh=200.0),
        MonthlyDemand(month=2, process_ht_kwh=300.0, process_bt_kwh=400.0),
    ]
    override = {0: (10.0, 20.0), 1: (30.0, 40.0)}
    profile = pd.DataFrame(
        {
            "hour_index": [0, 1],
            "month": [1, 1],
            "day": [1, 1],
            "hour": [1, 2],
            "demand_ht_kwh": [10.0, 30.0],
            "demand_bt_kwh": [20.0, 40.0],
        }
    )

    bt_demands, bt_override, bt_profile = apply_demand_scope(
        scope="bt_only",
        demands=demands,
        hourly_demand_override=override,
        hourly_profile_df=profile,
    )
    ht_demands, ht_override, ht_profile = apply_demand_scope(
        scope="ht_only",
        demands=demands,
        hourly_demand_override=override,
        hourly_profile_df=profile,
    )

    assert [item.process_ht_kwh for item in bt_demands] == [0.0, 0.0]
    assert [item.process_bt_kwh for item in bt_demands] == [200.0, 400.0]
    assert bt_override == {0: (0.0, 20.0), 1: (0.0, 40.0)}
    assert float(bt_profile["demand_ht_kwh"].sum()) == 0.0
    assert float(bt_profile["demand_bt_kwh"].sum()) == 60.0
    assert set(bt_profile["demand_scope"]) == {"bt_only"}

    assert [item.process_ht_kwh for item in ht_demands] == [100.0, 300.0]
    assert [item.process_bt_kwh for item in ht_demands] == [0.0, 0.0]
    assert ht_override == {0: (10.0, 0.0), 1: (30.0, 0.0)}
    assert float(ht_profile["demand_ht_kwh"].sum()) == 40.0
    assert float(ht_profile["demand_bt_kwh"].sum()) == 0.0
    assert set(ht_profile["demand_scope"]) == {"ht_only"}
