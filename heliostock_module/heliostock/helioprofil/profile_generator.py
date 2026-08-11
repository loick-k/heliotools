from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

InputMode = Literal["gaz_mensuel", "vehicules_mensuels", "vehicules_annuels", "hybride"]
EnergyUnit = Literal["kWh", "MWh", "m3 gaz"]


@dataclass
class GeneratorConfig:
    year: int = 2025
    profile_name: str = "Station de lavage poids lourds"
    demand_temperature_c: float = 60.0
    gas_efficiency: float = 0.75
    gas_unit: EnergyUnit = "kWh"
    gas_conversion_kwh_per_m3: float = 11.2
    kwh_per_vehicle: float = 45.0
    vehicles_per_day: float = 13.0
    input_mode: InputMode = "gaz_mensuel"
    close_weekends: bool = True
    close_french_holidays: bool = True
    compensate_closed_days: bool = True
    remove_feb_29: bool = True
    output_all_in_ht: bool = True


def easter_date(year: int) -> date:
    """Returns Gregorian Easter date using Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def french_public_holidays(year: int) -> set[date]:
    easter = easter_date(year)
    return {
        date(year, 1, 1),
        easter + timedelta(days=1),       # Lundi de Pâques
        date(year, 5, 1),
        date(year, 5, 8),
        easter + timedelta(days=39),      # Ascension
        easter + timedelta(days=50),      # Lundi de Pentecôte
        date(year, 7, 14),
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
    }


def parse_closure_text(text: str) -> set[date]:
    """Parse custom closures: one date per line or a range YYYY-MM-DD:YYYY-MM-DD."""
    closures: set[date] = set()
    if not text:
        return closures
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.replace(" ", "")
        try:
            if ":" in line:
                start_s, end_s = line.split(":", 1)
                start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
                end_d = datetime.strptime(end_s, "%Y-%m-%d").date()
                if end_d < start_d:
                    start_d, end_d = end_d, start_d
                current = start_d
                while current <= end_d:
                    closures.add(current)
                    current += timedelta(days=1)
            else:
                closures.add(datetime.strptime(line, "%Y-%m-%d").date())
        except ValueError as exc:
            raise ValueError(f"Date de fermeture invalide : {raw_line!r}. Format attendu YYYY-MM-DD ou YYYY-MM-DD:YYYY-MM-DD") from exc
    return closures


def load_profile(profile_csv: str | Path) -> pd.DataFrame:
    profile = pd.read_csv(profile_csv)
    required = {"weekday", "hour", "hour_weight", "daily_weight", "raw_weight"}
    missing = required - set(profile.columns)
    if missing:
        raise ValueError(f"Profil type invalide, colonnes manquantes : {sorted(missing)}")
    return profile.copy()


def make_calendar(year: int, remove_feb_29: bool = True) -> pd.DataFrame:
    start = pd.Timestamp(year=year, month=1, day=1, hour=0)
    end = pd.Timestamp(year=year + 1, month=1, day=1, hour=0)
    rng = pd.date_range(start, end, freq="h", inclusive="left")
    cal = pd.DataFrame({"datetime": rng})
    if remove_feb_29:
        cal = cal[~((cal["datetime"].dt.month == 2) & (cal["datetime"].dt.day == 29))].copy()
    cal = cal.reset_index(drop=True)
    cal["hour_index"] = np.arange(len(cal), dtype=int)
    cal["year"] = cal["datetime"].dt.year
    cal["month"] = cal["datetime"].dt.month
    cal["day"] = cal["datetime"].dt.day
    cal["hour"] = cal["datetime"].dt.hour + 1  # HelioStock convention: 1..24
    cal["weekday"] = cal["datetime"].dt.weekday
    cal["weekday_name"] = cal["weekday"].map(dict(enumerate(WEEKDAYS_FR)))
    cal["date"] = cal["datetime"].dt.date
    return cal


def apply_closures(cal: pd.DataFrame, config: GeneratorConfig, custom_closures: Iterable[date] | None = None) -> pd.DataFrame:
    cal = cal.copy()
    closed = pd.Series(False, index=cal.index)
    if config.close_weekends:
        closed = closed | cal["weekday"].isin([5, 6])
    if config.close_french_holidays:
        holidays = french_public_holidays(config.year)
        closed = closed | cal["date"].isin(holidays)
    if custom_closures:
        closed = closed | cal["date"].isin(set(custom_closures))
    cal["is_closed"] = closed
    cal["jour_type"] = np.where(cal["is_closed"], "Fermé", "Ouvert")
    return cal


def monthly_targets_from_gas(gas_monthly: pd.Series, config: GeneratorConfig) -> pd.Series:
    gas = pd.to_numeric(gas_monthly, errors="coerce").fillna(0.0).astype(float)
    if config.gas_unit == "MWh":
        gas_kwh = gas * 1000.0
    elif config.gas_unit == "m3 gaz":
        gas_kwh = gas * config.gas_conversion_kwh_per_m3
    else:
        gas_kwh = gas
    return gas_kwh * config.gas_efficiency


def monthly_targets_from_vehicles_monthly(vehicles_monthly: pd.Series, config: GeneratorConfig) -> pd.Series:
    vehicles = pd.to_numeric(vehicles_monthly, errors="coerce").fillna(0.0).astype(float)
    return vehicles * config.kwh_per_vehicle


def monthly_targets_from_vehicles_daily(cal: pd.DataFrame, config: GeneratorConfig) -> pd.Series:
    open_days = cal.loc[~cal["is_closed"], ["month", "date"]].drop_duplicates().groupby("month").size()
    targets = pd.Series(0.0, index=range(1, 13), dtype=float)
    for month in range(1, 13):
        targets.loc[month] = open_days.get(month, 0) * config.vehicles_per_day * config.kwh_per_vehicle
    return targets


def compute_targets(
    cal: pd.DataFrame,
    config: GeneratorConfig,
    monthly_gas_values: Iterable[float] | None = None,
    monthly_vehicle_values: Iterable[float] | None = None,
) -> pd.Series:
    idx = pd.Index(range(1, 13), name="month")
    target = pd.Series(0.0, index=idx, dtype=float)
    gas_target = None
    veh_target = None
    if monthly_gas_values is not None:
        gas_target = monthly_targets_from_gas(pd.Series(list(monthly_gas_values), index=idx), config)
    if monthly_vehicle_values is not None:
        veh_target = monthly_targets_from_vehicles_monthly(pd.Series(list(monthly_vehicle_values), index=idx), config)

    if config.input_mode == "gaz_mensuel":
        if gas_target is None:
            raise ValueError("Mode gaz mensuel : valeurs mensuelles gaz manquantes.")
        target = gas_target
    elif config.input_mode == "vehicules_mensuels":
        if veh_target is None:
            raise ValueError("Mode véhicules mensuels : valeurs mensuelles véhicules manquantes.")
        target = veh_target
    elif config.input_mode == "vehicules_annuels":
        target = monthly_targets_from_vehicles_daily(cal, config)
    elif config.input_mode == "hybride":
        if gas_target is not None:
            target = gas_target.copy()
        if veh_target is not None:
            if gas_target is None:
                target = veh_target.copy()
            else:
                target = target.where(target > 0, veh_target)
        if gas_target is None and veh_target is None:
            target = monthly_targets_from_vehicles_daily(cal, config)
    else:
        raise ValueError(f"Mode inconnu : {config.input_mode}")
    return target.reindex(idx).fillna(0.0)


def apply_type_profile(cal: pd.DataFrame, profile: pd.DataFrame) -> pd.DataFrame:
    # Weekday/hour weights define the raw shape before monthly scaling.
    shape = profile[["weekday", "hour", "hour_weight", "daily_weight", "raw_weight"]].copy()
    out = cal.merge(shape, on=["weekday", "hour"], how="left")
    out[["hour_weight", "daily_weight", "raw_weight"]] = out[["hour_weight", "daily_weight", "raw_weight"]].fillna(0.0)
    out["raw_weight_open"] = np.where(out["is_closed"], 0.0, out["raw_weight"])
    return out


def rescale_monthly(cal_profile: pd.DataFrame, monthly_targets_kwh: pd.Series, config: GeneratorConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = cal_profile.copy()
    df["target_month_kWh"] = df["month"].map(monthly_targets_kwh.to_dict()).fillna(0.0)
    monthly_raw = df.groupby("month")["raw_weight_open"].sum()
    factors = {}
    fallback_uniform_months: list[int] = []
    for month in range(1, 13):
        target = monthly_targets_kwh.loc[month]
        raw = monthly_raw.get(month, 0.0)
        if raw > 0:
            factors[month] = target / raw
        elif target > 0:
            factors[month] = np.nan
            fallback_uniform_months.append(month)
        else:
            factors[month] = 0.0
    df["facteur_recalage"] = df["month"].map(factors)
    df["E_total_kWh"] = df["raw_weight_open"] * df["facteur_recalage"].fillna(0.0)

    # Fallback: if there is no raw shape but a monthly target, distribute uniformly on open hours.
    for month in fallback_uniform_months:
        month_mask = (df["month"] == month) & (~df["is_closed"])
        n_open_hours = int(month_mask.sum())
        if n_open_hours > 0:
            df.loc[month_mask, "E_total_kWh"] = monthly_targets_kwh.loc[month] / n_open_hours
            df.loc[df["month"] == month, "facteur_recalage"] = np.nan

    if config.output_all_in_ht:
        df["E besoin HT kWh"] = df["E_total_kWh"]
        df["E besoin BT kWh"] = 0.0
    else:
        df["E besoin HT kWh"] = df["E_total_kWh"]
        df["E besoin BT kWh"] = 0.0

    bilan = build_monthly_summary(df, monthly_targets_kwh, monthly_raw, config)
    return df, bilan


def build_monthly_summary(df: pd.DataFrame, targets: pd.Series, monthly_raw: pd.Series, config: GeneratorConfig) -> pd.DataFrame:
    generated = df.groupby("month")["E_total_kWh"].sum().reindex(range(1,13)).fillna(0.0)
    open_days = df.loc[~df["is_closed"], ["month", "date"]].drop_duplicates().groupby("month").size().reindex(range(1,13)).fillna(0).astype(int)
    closed_days = df.loc[df["is_closed"], ["month", "date"]].drop_duplicates().groupby("month").size().reindex(range(1,13)).fillna(0).astype(int)
    peaks = df.groupby("month")["E_total_kWh"].max().reindex(range(1,13)).fillna(0.0)
    rows = []
    for m in range(1,13):
        t = float(targets.loc[m])
        g = float(generated.loc[m])
        raw = float(monthly_raw.get(m, 0.0))
        factor = (t/raw) if raw > 0 else np.nan
        rows.append({
            "month": m,
            "mois": MONTHS_FR[m-1],
            "temperature_besoin_C": config.demand_temperature_c,
            "cible_besoin_utile_kWh": t,
            "E_generee_HT_kWh": g,
            "E_generee_BT_kWh": 0.0,
            "E_total_generee_kWh": g,
            "ecart_cible_kWh": g - t,
            "facteur_recalage": factor,
            "jours_ouverts": int(open_days.loc[m]),
            "jours_fermes": int(closed_days.loc[m]),
            "pic_horaire_kW": float(peaks.loc[m]),
        })
    return pd.DataFrame(rows)


def generate_profile(
    config: GeneratorConfig,
    profile_csv: str | Path,
    monthly_gas_values: Iterable[float] | None = None,
    monthly_vehicle_values: Iterable[float] | None = None,
    custom_closure_text: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cal = make_calendar(config.year, remove_feb_29=config.remove_feb_29)
    closures = parse_closure_text(custom_closure_text)
    cal = apply_closures(cal, config, closures)
    profile = load_profile(profile_csv)
    targets = compute_targets(cal, config, monthly_gas_values, monthly_vehicle_values)
    cal_profile = apply_type_profile(cal, profile)
    generated, bilan = rescale_monthly(cal_profile, targets, config)
    return generated, bilan, profile


def daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.groupby("date", as_index=False).agg(
        month=("month", "first"),
        day=("day", "first"),
        weekday=("weekday", "first"),
        weekday_name=("weekday_name", "first"),
        jour_type=("jour_type", "first"),
        E_HT_kWh=("E besoin HT kWh", "sum"),
        E_BT_kWh=("E besoin BT kWh", "sum"),
        E_total_kWh=("E_total_kWh", "sum"),
        pic_horaire_kW=("E_total_kWh", "max"),
    )
    return out


def normalized_hourly_profile(profile: pd.DataFrame) -> pd.DataFrame:
    out = profile.drop_duplicates("hour")[["hour", "hour_weight"]].copy().sort_values("hour")
    out["part_journaliere_pct"] = out["hour_weight"] * 100.0
    return out


def weekly_distribution(df: pd.DataFrame) -> pd.DataFrame:
    d = daily_summary(df)
    out = d.groupby(["weekday", "weekday_name"], as_index=False)["E_total_kWh"].sum().sort_values("weekday")
    total = out["E_total_kWh"].sum()
    out["part_annuelle_pct"] = np.where(total > 0, out["E_total_kWh"] / total * 100, 0.0)
    return out


def strict_heliostock_sheet(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["hour_index", "month", "day", "hour", "E besoin HT kWh", "E besoin BT kWh"]
    strict = df[cols].copy()
    strict["hour_index"] = strict["hour_index"].astype(int)
    strict["month"] = strict["month"].astype(int)
    strict["day"] = strict["day"].astype(int)
    strict["hour"] = strict["hour"].astype(int)
    strict["E besoin HT kWh"] = strict["E besoin HT kWh"].astype(float)
    strict["E besoin BT kWh"] = strict["E besoin BT kWh"].astype(float)
    if len(strict) != 8760:
        raise ValueError(f"Profil invalide : {len(strict)} heures. HelioStock attend 8760 lignes.")
    return strict


def build_excel_bytes(
    df: pd.DataFrame,
    bilan: pd.DataFrame,
    profile: pd.DataFrame,
    config: GeneratorConfig,
    input_table: pd.DataFrame | None = None,
) -> bytes:
    strict = strict_heliostock_sheet(df)
    detail_cols = [
        "datetime", "date", "weekday_name", "jour_type", "is_closed", "temperature_besoin_C",
        "raw_weight_open", "facteur_recalage", "E besoin HT kWh", "E besoin BT kWh", "E_total_kWh",
    ]
    detail = df.copy()
    detail["temperature_besoin_C"] = config.demand_temperature_c
    detail_export = detail[detail_cols].copy()

    daily = daily_summary(df)
    weekly = weekly_distribution(df)
    hourly_norm = normalized_hourly_profile(profile)

    hypotheses = pd.DataFrame([
        ["Version", "V1 Streamlit"],
        ["Année", config.year],
        ["Profil type", config.profile_name],
        ["Température de besoin", f"{config.demand_temperature_c} °C"],
        ["Rendement gaz", config.gas_efficiency],
        ["Mode d'entrée", config.input_mode],
        ["Unité gaz", config.gas_unit],
        ["Coefficient m3 gaz", config.gas_conversion_kwh_per_m3],
        ["Week-ends fermés", config.close_weekends],
        ["Jours fériés France fermés", config.close_french_holidays],
        ["Fermetures compensées", config.compensate_closed_days],
        ["Sortie", "100 % du besoin en E besoin HT kWh ; E besoin BT kWh = 0"],
        ["Format HelioStock", "Feuille besoins_8760h avec 8760 lignes et colonnes strictes"],
    ], columns=["Paramètre", "Valeur"])

    output = BytesIO()
    sheets = {
        "besoins_8760h": strict,
        "bilan_mensuel": bilan,
        "bilan_journalier": daily,
        "repartition_semaine": weekly,
        "profil_type_horaire": hourly_norm,
        "profil_8760h_detail": detail_export,
        "hypotheses": hypotheses,
    }
    if input_table is not None:
        sheets["donnees_entree"] = input_table

    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm", date_format="yyyy-mm-dd") as writer:
        for sheet_name, data in sheets.items():
            data.to_excel(writer, sheet_name=sheet_name, index=False)

        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#0F766E", "border": 1})
        num_fmt = workbook.add_format({"num_format": "0.00"})
        int_fmt = workbook.add_format({"num_format": "0"})

        for ws_name, worksheet in writer.sheets.items():
            ncols = len(sheets[ws_name].columns)
            worksheet.freeze_panes(1, 0)
            worksheet.set_row(0, None, header_fmt)
            if ncols > 0:
                worksheet.autofilter(0, 0, max(1, len(sheets[ws_name])), ncols - 1)
            worksheet.set_column(0, 0, 14)
            worksheet.set_column(1, min(4, ncols - 1), 14)
            if ncols > 5:
                worksheet.set_column(5, ncols - 1, 18, num_fmt)

        writer.sheets["besoins_8760h"].set_column(0, 3, 11, int_fmt)
        writer.sheets["besoins_8760h"].set_column(4, 5, 18, num_fmt)
        writer.sheets["bilan_mensuel"].set_column(0, 1, 12)
        writer.sheets["bilan_mensuel"].set_column(2, len(bilan.columns)-1, 18, num_fmt)
        writer.sheets["profil_8760h_detail"].set_column(0, 1, 20)
        writer.sheets["profil_8760h_detail"].set_column(2, 4, 14)
        writer.sheets["profil_8760h_detail"].set_column(5, len(detail_export.columns)-1, 18, num_fmt)
        writer.sheets["hypotheses"].set_column(0, 0, 30)
        writer.sheets["hypotheses"].set_column(1, 1, 60)
    return output.getvalue()
