"""Shared solar-thermal primitives for HelioTools applications.

This module is intentionally a thin facade for now: it exposes existing
HelioStock solar helpers without changing the calculation path. It prepares the
future HELIOSOLO module while avoiding duplicated implementations.
"""

from __future__ import annotations

from .economics import (
    ademe_solar_aid_eur,
    compute_solar_thermal_economics,
    solar_capex_eur,
    solar_capex_unit_eur_m2,
)
from .hourly_engine import (
    _daily_buffer_capacity_kwh,
    _daily_buffer_heat_capacity_kwh_k,
    _daily_buffer_volume_l,
    _hourly_buffer_loss,
    _solo2018_buffer_loss_diagnostic,
    _solo2018_cr_stock_wh_l_k_day,
    _solo2018_tank_surface_m2,
)

__all__ = [
    "_daily_buffer_capacity_kwh",
    "_daily_buffer_heat_capacity_kwh_k",
    "_daily_buffer_volume_l",
    "_hourly_buffer_loss",
    "_solo2018_buffer_loss_diagnostic",
    "_solo2018_cr_stock_wh_l_k_day",
    "_solo2018_tank_surface_m2",
    "ademe_solar_aid_eur",
    "compute_solar_thermal_economics",
    "solar_capex_eur",
    "solar_capex_unit_eur_m2",
]

