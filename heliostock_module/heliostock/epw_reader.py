from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .hourly_engine import HourlyWeather


@dataclass(frozen=True)
class EpwLocation:
    city: str
    country: str
    latitude_deg: float
    longitude_deg: float
    timezone_h: float
    elevation_m: float


def _parse_epw_from_zip(zip_path: Path) -> tuple[list[str], list[list[str]]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        epw_names = [n for n in zf.namelist() if n.lower().endswith(".epw")]
        if not epw_names:
            raise ValueError("Aucun fichier .epw trouve dans le zip")
        lines = zf.read(epw_names[0]).decode("utf-8", errors="ignore").splitlines()

    if len(lines) <= 8:
        raise ValueError("Fichier EPW invalide: moins de 8 lignes d'entete")
    return lines[:8], [next(csv.reader(io.StringIO(line))) for line in lines[8:]]


def _parse_location(header_line_1: str) -> EpwLocation:
    cols = next(csv.reader(io.StringIO(header_line_1)))
    if len(cols) < 10 or cols[0].strip().upper() != "LOCATION":
        raise ValueError("Entete LOCATION EPW invalide")
    return EpwLocation(
        city=cols[1],
        country=cols[3],
        latitude_deg=float(cols[6]),
        longitude_deg=float(cols[7]),
        timezone_h=float(cols[8]),
        elevation_m=float(cols[9]),
    )


def _solar_geometry_cos_incidence(
    *,
    lat_deg: float,
    lon_deg: float,
    tz_h: float,
    year: int,
    month: int,
    day: int,
    hour_epw: int,
    tilt_deg: float,
    azimuth_deg_south: float,
) -> tuple[float, float]:
    # EPW hour is 1..24. Use the middle of the hour.
    hour_local = float(hour_epw) - 0.5
    try:
        n = date(year, month, day).timetuple().tm_yday
    except ValueError:
        n = date(2001, month, day).timetuple().tm_yday

    b = math.radians(360.0 * (n - 81) / 364.0)
    eot_min = 9.87 * math.sin(2.0 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    lon_std = 15.0 * tz_h
    solar_time_h = hour_local + (4.0 * (lon_std - lon_deg) + eot_min) / 60.0
    omega = math.radians(15.0 * (solar_time_h - 12.0))

    delta = math.radians(23.45 * math.sin(math.radians(360.0 * (284 + n) / 365.0)))
    phi = math.radians(lat_deg)
    beta = math.radians(tilt_deg)
    gamma = math.radians(azimuth_deg_south)  # 0=south, -90=east, +90=west

    cos_theta_z = (
        math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.cos(omega)
    )
    cos_theta_i = (
        math.sin(delta) * math.sin(phi) * math.cos(beta)
        - math.sin(delta) * math.cos(phi) * math.sin(beta) * math.cos(gamma)
        + math.cos(delta) * math.cos(phi) * math.cos(beta) * math.cos(omega)
        + math.cos(delta) * math.sin(phi) * math.sin(beta) * math.cos(gamma) * math.cos(omega)
        + math.cos(delta) * math.sin(beta) * math.sin(gamma) * math.sin(omega)
    )
    return cos_theta_i, cos_theta_z


def read_epw_hourly_weather_from_zip(
    zip_path: str | Path,
    *,
    tilt_deg: float,
    azimuth_deg_south: float,
    albedo: float = 0.2,
) -> tuple[EpwLocation, list[HourlyWeather]]:
    """Read an EPW zip and return hourly weather on the collector plane."""

    header, rows = _parse_epw_from_zip(Path(zip_path))
    location = _parse_location(header[0])
    cos_beta = math.cos(math.radians(tilt_deg))
    hourly: list[HourlyWeather] = []

    for index, cols in enumerate(rows):
        if len(cols) < 16:
            continue
        year = int(float(cols[0]))
        month = int(float(cols[1]))
        day = int(float(cols[2]))
        hour = int(float(cols[3]))
        tair = float(cols[6])
        ghi_wh_m2 = max(0.0, float(cols[13]))
        dni_wh_m2 = max(0.0, float(cols[14]))
        dhi_wh_m2 = max(0.0, float(cols[15]))

        cos_i, cos_z = _solar_geometry_cos_incidence(
            lat_deg=location.latitude_deg,
            lon_deg=location.longitude_deg,
            tz_h=location.timezone_h,
            year=year if year > 0 else 2001,
            month=month,
            day=day,
            hour_epw=hour,
            tilt_deg=tilt_deg,
            azimuth_deg_south=azimuth_deg_south,
        )

        beam = dni_wh_m2 * max(0.0, cos_i) if cos_z > 0.0 else 0.0
        diffuse = dhi_wh_m2 * (1.0 + cos_beta) / 2.0
        reflected = ghi_wh_m2 * max(0.0, albedo) * (1.0 - cos_beta) / 2.0
        g_tilt_kwh_m2 = max(0.0, beam + diffuse + reflected) / 1000.0

        hourly.append(
            HourlyWeather(
                hour_index=index,
                month=month,
                day=day,
                hour=hour,
                tair_c=tair,
                g_tilt_kwh_m2=g_tilt_kwh_m2,
            )
        )

    return location, hourly
