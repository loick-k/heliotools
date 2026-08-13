from __future__ import annotations

import calendar
import csv
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class MonthlyIrradiance:
    month: int
    month_label: str
    days_m: int
    tair_mean_c: float
    ghi_h_kwh_m2: float
    g_tilt_kwh_m2: float
    r_global_plan_kwh_m2_j: float
    psolmax_hz_kw_m2: float


def _parse_epw_from_zip(zip_path: Path) -> tuple[list[str], list[list[str]]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        epw_names = [n for n in zf.namelist() if n.lower().endswith(".epw")]
        if not epw_names:
            raise ValueError("Aucun fichier .epw trouve dans le zip")
        epw_name = epw_names[0]
        lines = zf.read(epw_name).decode("utf-8", errors="ignore").splitlines()

    if len(lines) <= 8:
        raise ValueError("Fichier EPW invalide (pas assez de lignes)")

    header = lines[:8]
    hourly_rows = [next(csv.reader(io.StringIO(line))) for line in lines[8:]]
    return header, hourly_rows


def _parse_location(header_line_1: str) -> tuple[float, float, float]:
    cols = next(csv.reader(io.StringIO(header_line_1)))
    if len(cols) < 10 or cols[0].strip().upper() != "LOCATION":
        raise ValueError("Entete LOCATION EPW invalide")
    lat = float(cols[6])
    lon = float(cols[7])  # East positive, West negative
    tz = float(cols[8])  # UTC offset in hours
    return lat, lon, tz


def _solar_geometry_cos_incidence(
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
    # EPW hour is 1..24, treat each record at the middle of the hour.
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


def read_epw_monthly_irradiance_from_zip(
    zip_path: str | Path,
    tilt_deg: float,
    azimuth_deg_south: float,
    albedo: float = 0.2,
) -> list[MonthlyIrradiance]:
    """
    Compute the monthly EPW inputs used by the SOLO engine.

    The function returns only weather/irradiance indicators:
    - monthly mean outdoor temperature (degC)
    - horizontal global irradiation (kWh/m2/month)
    - tilted-plane global irradiation (kWh/m2/month)
    - daily tilted-plane global irradiation (kWh/m2/day)
    - monthly peak hourly tilted irradiance proxy (kW/m2)
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {zip_path}")

    header, rows = _parse_epw_from_zip(zip_path)
    lat_deg, lon_deg, tz_h = _parse_location(header[0])
    cos_beta = math.cos(math.radians(tilt_deg))

    m_t_sum = {m: 0.0 for m in range(1, 13)}
    m_t_count = {m: 0 for m in range(1, 13)}
    m_ghi_kwh_m2 = {m: 0.0 for m in range(1, 13)}
    m_gt_kwh_m2 = {m: 0.0 for m in range(1, 13)}
    m_psolmax_kw_m2 = {m: 0.0 for m in range(1, 13)}

    for cols in rows:
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

        cos_theta_i, cos_theta_z = _solar_geometry_cos_incidence(
            lat_deg=lat_deg,
            lon_deg=lon_deg,
            tz_h=tz_h,
            year=year if year > 0 else 2001,
            month=month,
            day=day,
            hour_epw=hour,
            tilt_deg=tilt_deg,
            azimuth_deg_south=azimuth_deg_south,
        )

        beam = 0.0
        if cos_theta_z > 0.0:
            beam = dni_wh_m2 * max(0.0, cos_theta_i)

        diffuse = dhi_wh_m2 * (1.0 + cos_beta) / 2.0
        reflected = ghi_wh_m2 * max(0.0, albedo) * (1.0 - cos_beta) / 2.0
        g_tilt_wh_m2 = max(0.0, beam + diffuse + reflected)

        m_t_sum[month] += tair
        m_t_count[month] += 1
        m_ghi_kwh_m2[month] += ghi_wh_m2 / 1000.0
        m_gt_kwh_m2[month] += g_tilt_wh_m2 / 1000.0
        m_psolmax_kw_m2[month] = max(m_psolmax_kw_m2[month], g_tilt_wh_m2 / 1000.0)

    out: list[MonthlyIrradiance] = []
    for m in range(1, 13):
        tair_mean = m_t_sum[m] / m_t_count[m] if m_t_count[m] else 0.0
        days_m = int(round(m_t_count[m] / 24)) if m_t_count[m] else calendar.monthrange(2001, m)[1]
        r_global_plan = m_gt_kwh_m2[m] / days_m if days_m > 0 else 0.0
        out.append(
            MonthlyIrradiance(
                month=m,
                month_label=calendar.month_abbr[m],
                days_m=days_m,
                tair_mean_c=tair_mean,
                ghi_h_kwh_m2=m_ghi_kwh_m2[m],
                g_tilt_kwh_m2=m_gt_kwh_m2[m],
                r_global_plan_kwh_m2_j=r_global_plan,
                psolmax_hz_kw_m2=m_psolmax_kw_m2[m],
            )
        )
    return out


