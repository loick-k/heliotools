import heliostock.simulation_cache as simulation_cache_module
from heliostock.engine import BtesConfig, CollectorConfig, HeatPumpConfig, MonthlyDemand, SimulationConfig
from heliostock.hourly_engine import HourlyWeather
from heliostock.simulation_cache import SimulationCache


def _hourly_override(weather: list[HourlyWeather], *, ht_kwh: float, bt_kwh: float) -> dict[int, tuple[float, float]]:
    return {hour.hour_index: (ht_kwh, bt_kwh) for hour in weather}


def test_simulation_cache_reuses_identical_hourly_simulations(monkeypatch):
    weather = [
        HourlyWeather(
            hour_index=0,
            month=1,
            day=1,
            hour=1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
    ]
    demands = [MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=100.0)]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=0.0),
        btes=BtesConfig(boreholes=4, depth_m=100.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
    )
    calls = []

    def fake_simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=None,
        simulation_years=1,
        result_sink=None,
        store_results=True,
        **kwargs,
    ):
        calls.append((float(config.collector.area_m2), int(simulation_years)))
        return [{"simulation_year": 1, "hour_index": weather[0].hour_index, "demand_bt_kwh": 100.0}]

    monkeypatch.setattr(simulation_cache_module, "simulate_hourly", fake_simulate_hourly)
    cache = SimulationCache()
    override = _hourly_override(weather, ht_kwh=0.0, bt_kwh=100.0)

    first = cache.simulate(
        weather,
        demands,
        config,
        hourly_demand_override=override,
        simulation_years=25,
        mode="same",
    )
    second = cache.simulate(
        weather,
        demands,
        config,
        hourly_demand_override=override,
        simulation_years=25,
        mode="same",
    )
    cache.simulate(
        weather,
        demands,
        config,
        hourly_demand_override=override,
        simulation_years=1,
        mode="same",
    )

    assert first == second
    assert calls == [(0.0, 25), (0.0, 1)]
    assert cache.summary() == {"hits": 1, "misses": 2, "entries": 2}


def test_simulation_cache_does_not_store_large_hourly_results(monkeypatch):
    weather = [
        HourlyWeather(
            hour_index=hour,
            month=1,
            day=1,
            hour=hour + 1,
            tair_c=8.0,
            g_tilt_kwh_m2=0.0,
        )
        for hour in range(3)
    ]
    demands = [MonthlyDemand(month=1, process_ht_kwh=0.0, process_bt_kwh=300.0)]
    config = SimulationConfig(
        collector=CollectorConfig(area_m2=0.0),
        btes=BtesConfig(boreholes=4, depth_m=100.0),
        heat_pump=HeatPumpConfig(max_thermal_power_kw=50.0),
    )
    calls = []
    events = []

    def fake_simulate_hourly(
        weather,
        demands,
        config,
        hourly_demand_override=None,
        simulation_years=1,
        result_sink=None,
        store_results=True,
        **kwargs,
    ):
        calls.append(int(simulation_years))
        return [
            {"simulation_year": 1, "hour_index": hour.hour_index, "demand_bt_kwh": 100.0}
            for hour in weather
        ]

    monkeypatch.setattr(simulation_cache_module, "simulate_hourly", fake_simulate_hourly)
    cache = SimulationCache(event_callback=events.append, max_entries=2, max_cached_results=2)

    first = cache.simulate(weather, demands, config, simulation_years=25, mode="large")
    second = cache.simulate(weather, demands, config, simulation_years=25, mode="large")

    assert len(first) == 3
    assert len(second) == 3
    assert calls == [25, 25]
    assert cache.summary() == {"hits": 0, "misses": 2, "entries": 0}
    assert events[-1]["Resultats horaires retournes"] == 3
    assert events[-1]["Resultats horaires caches"] == 0
