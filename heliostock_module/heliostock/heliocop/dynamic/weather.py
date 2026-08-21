"""Météo horaire enrichie pour le solveur ECS1 dynamique.

La lecture part d'un EPW contenu dans un ZIP, comme le reste de HelioTools.
Le modèle conserve séparément le rayonnement direct/diffus/réfléchi sur le plan,
le rayonnement IR du ciel, le vent et l'humidité relative. Les grandeurs EPW
sont des moyennes horaires ; numériquement Wh/m² sur une heure = W/m² moyen.
"""
from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


SIGMA = 5.670374419e-8


@dataclass(frozen=True)
class DynamicWeatherHour:
    hour_index: int
    month: int
    day: int
    hour: int
    datetime_local: datetime
    t_amb_c: float
    wind_ms: float
    rh_pct: float
    horizontal_ir_wm2: float
    ghi_wm2: float
    dni_wm2: float
    dhi_wm2: float
    beam_poa_wm2: float
    diffuse_poa_wm2: float
    reflected_poa_wm2: float
    g_poa_wm2: float
    incidence_angle_deg: float
    longwave_poa_wm2: float


@dataclass(frozen=True)
class DynamicWeather8760:
    city: str
    country: str
    latitude_deg: float
    longitude_deg: float
    timezone_h: float
    elevation_m: float
    tilt_deg: float
    azimuth_deg_south: float
    hours: tuple[DynamicWeatherHour, ...]
    source_name: str

    def validate(self) -> None:
        if len(self.hours) != 8760:
            raise ValueError(f"Météo dynamique V1 : 8760 heures requises, {len(self.hours)} détectées.")


def _parse_zip(path: Path) -> tuple[list[str], list[list[str]]]:
    with zipfile.ZipFile(path, "r") as zf:
        epw_names = [name for name in zf.namelist() if name.lower().endswith(".epw")]
        if not epw_names:
            raise ValueError(f"Aucun fichier EPW trouvé dans {path.name}.")
        lines = zf.read(epw_names[0]).decode("utf-8", errors="ignore").splitlines()
    if len(lines) <= 8:
        raise ValueError("EPW invalide : en-tête incomplet.")
    rows = [next(csv.reader(io.StringIO(line))) for line in lines[8:]]
    return lines[:8], rows


def _location(header: str) -> tuple[str, str, float, float, float, float]:
    cols = next(csv.reader(io.StringIO(header)))
    if len(cols) < 10 or cols[0].strip().upper() != "LOCATION":
        raise ValueError("En-tête LOCATION EPW invalide.")
    return cols[1], cols[3], float(cols[6]), float(cols[7]), float(cols[8]), float(cols[9])


def _solar_geometry(
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
) -> tuple[float, float, float]:
    """Retourne cos(theta_i), cos(theta_z), theta_i en degrés."""
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
    gamma = math.radians(azimuth_deg_south)
    cos_z = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(omega)
    cos_i = (
        math.sin(delta) * math.sin(phi) * math.cos(beta)
        - math.sin(delta) * math.cos(phi) * math.sin(beta) * math.cos(gamma)
        + math.cos(delta) * math.cos(phi) * math.cos(beta) * math.cos(omega)
        + math.cos(delta) * math.sin(phi) * math.sin(beta) * math.cos(gamma) * math.cos(omega)
        + math.cos(delta) * math.sin(beta) * math.sin(gamma) * math.sin(omega)
    )
    cos_i_clamped = max(-1.0, min(1.0, cos_i))
    theta = math.degrees(math.acos(cos_i_clamped)) if cos_z > 0.0 else 90.0
    return cos_i, cos_z, theta


def read_dynamic_weather_epw_zip(
    path: str | Path,
    *,
    tilt_deg: float,
    azimuth_deg_south: float,
    albedo: float = 0.2,
    ground_emissivity: float = 1.0,
) -> DynamicWeather8760:
    """Lit un EPW et calcule les conditions sur le plan du champ WISC.

    Le rayonnement IR incliné est approximé par facteurs de vue ciel/sol :
    F_sky=(1+cos(beta))/2 et F_ground=(1-cos(beta))/2. Le sol est supposé à
    la température de l'air dans cette V1.
    """
    path = Path(path)
    header, rows = _parse_zip(path)
    city, country, lat, lon, tz, elev = _location(header[0])
    beta = math.radians(float(tilt_deg))
    cos_beta = math.cos(beta)
    f_sky = (1.0 + cos_beta) / 2.0
    f_ground = (1.0 - cos_beta) / 2.0
    out: list[DynamicWeatherHour] = []

    for index, cols in enumerate(rows):
        if len(cols) < 22:
            continue
        year = int(float(cols[0]))
        month = int(float(cols[1]))
        day = int(float(cols[2]))
        hour = int(float(cols[3]))
        t_amb = float(cols[6])
        rh = max(0.0, min(100.0, float(cols[8])))
        horizontal_ir = max(0.0, float(cols[12]))
        ghi = max(0.0, float(cols[13]))
        dni = max(0.0, float(cols[14]))
        dhi = max(0.0, float(cols[15]))
        wind = max(0.0, float(cols[21]))
        cos_i, cos_z, theta = _solar_geometry(
            lat_deg=lat,
            lon_deg=lon,
            tz_h=tz,
            year=year if year > 0 else 2001,
            month=month,
            day=day,
            hour_epw=hour,
            tilt_deg=float(tilt_deg),
            azimuth_deg_south=float(azimuth_deg_south),
        )
        beam = dni * max(0.0, cos_i) if cos_z > 0.0 else 0.0
        diffuse = dhi * f_sky
        reflected = ghi * max(0.0, float(albedo)) * f_ground
        g_poa = max(0.0, beam + diffuse + reflected)
        t_amb_k = t_amb + 273.15
        ground_ir = max(0.0, float(ground_emissivity)) * SIGMA * t_amb_k**4
        longwave_poa = f_sky * horizontal_ir + f_ground * ground_ir
        # EPW encode parfois une année TMY non calendaire. 2001 sert d'année neutre.
        safe_year = year if 1900 <= year <= 2200 else 2001
        try:
            dt_local = datetime(safe_year, month, day, max(0, min(23, hour - 1)))
        except ValueError:
            dt_local = datetime(2001, month, min(day, 28), max(0, min(23, hour - 1)))
        out.append(
            DynamicWeatherHour(
                hour_index=index,
                month=month,
                day=day,
                hour=hour,
                datetime_local=dt_local,
                t_amb_c=t_amb,
                wind_ms=wind,
                rh_pct=rh,
                horizontal_ir_wm2=horizontal_ir,
                ghi_wm2=ghi,
                dni_wm2=dni,
                dhi_wm2=dhi,
                beam_poa_wm2=beam,
                diffuse_poa_wm2=diffuse,
                reflected_poa_wm2=reflected,
                g_poa_wm2=g_poa,
                incidence_angle_deg=theta,
                longwave_poa_wm2=longwave_poa,
            )
        )
    weather = DynamicWeather8760(
        city=city,
        country=country,
        latitude_deg=lat,
        longitude_deg=lon,
        timezone_h=tz,
        elevation_m=elev,
        tilt_deg=float(tilt_deg),
        azimuth_deg_south=float(azimuth_deg_south),
        hours=tuple(out),
        source_name=path.name,
    )
    weather.validate()
    return weather
