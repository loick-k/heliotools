from __future__ import annotations

from io import StringIO

import pytest

from heliostock.heliocop.economics_pac import build_monthly_pac_energy, compute_pac_heat_cost_model
from heliostock.heliocop.hourly_profile import (
    HourlyLoadProfile,
    load_hourly_profile,
    simulate_hourly_profile,
)
from heliostock.heliocop.model import MONTH_NAMES


def _flat_monthly_heat(value_mwh: float = 10.0) -> dict[str, float]:
    return {month: value_mwh for month in MONTH_NAMES}


def _cold_water(value_c: float = 10.0) -> dict[str, float]:
    return {month: value_c for month in MONTH_NAMES}


def test_monthly_pac_energy_uses_monthly_cop_and_auxiliaries() -> None:
    rows = build_monthly_pac_energy(
        _flat_monthly_heat(10.0),
        monthly_cop={month: 4.0 for month in MONTH_NAMES},
        auxiliary_electricity_mwh=12.0,
    )

    assert len(rows) == 12
    assert sum(row.heat_mwh for row in rows) == pytest.approx(120.0)
    assert sum(row.compressor_electricity_mwh for row in rows) == pytest.approx(30.0)
    assert sum(row.auxiliary_electricity_mwh for row in rows) == pytest.approx(12.0)
    assert rows[0].system_cop == pytest.approx(10.0 / 3.5)
    assert sum(row.renewable_heat_mwh for row in rows) == pytest.approx(78.0)


def test_pac_heat_cost_model_exposes_consistent_p1_p2_p4_total() -> None:
    results = compute_pac_heat_cost_model(
        monthly_heat_mwh=_flat_monthly_heat(10.0),
        selected_pac_power_kw=50.0,
        source_surface_m2=100.0,
        monthly_cop={month: 4.0 for month in MONTH_NAMES},
        auxiliary_electricity_mwh=12.0,
        electricity_cost_eur_mwh=200.0,
        maintenance_annual_eur=2400.0,
        analysis_years=20,
    )

    assert results.annual_heat_mwh == pytest.approx(120.0)
    assert results.seasonal_cop_machine == pytest.approx(4.0)
    assert results.system_cop_including_aux == pytest.approx(120.0 / 42.0)
    assert results.p1_eur_mwh == pytest.approx(70.0)
    assert results.p2_eur_mwh == pytest.approx(20.0)
    assert results.heat_cost_eur_mwh == pytest.approx(
        results.p1_eur_mwh + results.p2_eur_mwh + results.p4_eur_mwh
    )


def test_load_hourly_profile_sums_ht_and_bt_columns_from_csv() -> None:
    csv_source = StringIO(
        "month,day,hour,E besoin HT kWh,E besoin BT kWh\n"
        "1,1,1,1.5,2.5\n"
        "1,1,2,0,3\n"
        "1,1,3,4,0\n"
    )

    profile = load_hourly_profile(csv_source, source_name="profile.csv", required_hours=3)

    assert profile.hour_count == 3
    assert profile.energy_kwh == pytest.approx((4.0, 3.0, 4.0))
    assert profile.annual_energy_mwh == pytest.approx(0.011)
    assert profile.peak_hourly_kw == pytest.approx(4.0)
    assert profile.energy_columns == ("E besoin HT kWh", "E besoin BT kWh")


def test_load_hourly_profile_rejects_negative_demand() -> None:
    csv_source = StringIO("month,day,hour,E_total_kWh\n1,1,1,-1\n")

    with pytest.raises(ValueError, match="besoins"):
        load_hourly_profile(csv_source, source_name="profile.csv", required_hours=1)


def test_hourly_profile_simulation_tracks_coverage_soc_and_trace() -> None:
    profile = HourlyLoadProfile(
        energy_kwh=(10.0, 10.0, 10.0),
        months=(1, 1, 1),
        days=(1, 1, 1),
        hours=(1, 2, 3),
        source_name="test",
        source_sheet="CSV",
        energy_columns=("E_total_kWh",),
    )

    result, trace = simulate_hourly_profile(
        profile,
        pac_power_kw=20.0,
        storage_volume_l=1000.0,
        cold_water_temperatures_c=_cold_water(10.0),
        with_trace=True,
    )

    assert result.is_feasible
    assert result.coverage_fraction == pytest.approx(1.0)
    assert result.unmet_energy_mwh == pytest.approx(0.0)
    assert result.pac_heat_mwh == pytest.approx(0.03)
    assert result.equivalent_full_load_hours == pytest.approx(1.5)
    assert len(trace) == 3
    assert all(row.unmet_kwh == pytest.approx(0.0) for row in trace)


def test_hourly_profile_simulation_reports_unmet_energy_when_pac_and_stock_are_empty() -> None:
    profile = HourlyLoadProfile(
        energy_kwh=(10.0,),
        months=(1,),
        days=(1,),
        hours=(1,),
        source_name="test",
        source_sheet="CSV",
        energy_columns=("E_total_kWh",),
    )

    result, trace = simulate_hourly_profile(
        profile,
        pac_power_kw=0.0,
        storage_volume_l=1000.0,
        cold_water_temperatures_c=_cold_water(10.0),
        initial_soc_fraction=0.0,
        with_trace=True,
    )

    assert not result.is_feasible
    assert result.coverage_fraction == pytest.approx(0.0)
    assert result.unmet_energy_mwh == pytest.approx(0.01)
    assert result.unmet_hours == 1
    assert trace[0].unmet_kwh == pytest.approx(10.0)


def test_weather_geometry_distinguishes_east_and_west_orientation_by_hour() -> None:
    pytest.importorskip("scipy")
    from heliostock.heliocop.dynamic.weather import _solar_geometry

    morning_east, _, _ = _solar_geometry(
        lat_deg=47.0,
        lon_deg=0.0,
        tz_h=0.0,
        year=2026,
        month=6,
        day=21,
        hour_epw=9,
        tilt_deg=35.0,
        azimuth_deg_south=-45.0,
    )
    morning_west, _, _ = _solar_geometry(
        lat_deg=47.0,
        lon_deg=0.0,
        tz_h=0.0,
        year=2026,
        month=6,
        day=21,
        hour_epw=9,
        tilt_deg=35.0,
        azimuth_deg_south=45.0,
    )
    evening_east, _, _ = _solar_geometry(
        lat_deg=47.0,
        lon_deg=0.0,
        tz_h=0.0,
        year=2026,
        month=6,
        day=21,
        hour_epw=17,
        tilt_deg=35.0,
        azimuth_deg_south=-45.0,
    )
    evening_west, _, _ = _solar_geometry(
        lat_deg=47.0,
        lon_deg=0.0,
        tz_h=0.0,
        year=2026,
        month=6,
        day=21,
        hour_epw=17,
        tilt_deg=35.0,
        azimuth_deg_south=45.0,
    )

    assert morning_east > morning_west
    assert evening_west > evening_east
