from __future__ import annotations

import pandas as pd

from .engine import MonthlyDemand

def _demands_to_dataframe(demands: list[MonthlyDemand]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Mois": [d.month for d in demands],
            "Process HT 60C (kWh/mois)": [d.process_ht_kwh for d in demands],
            "Process BT 25C (kWh/mois)": [d.process_bt_kwh for d in demands],
        }
    )


def _normalize_column_name(name: object) -> str:
    text = str(name).strip().lower()
    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "à": "a",
        "â": "a",
        "ä": "a",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "o",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
        "°": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return " ".join(text.split())


def _column_by_normalized_name(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {_normalize_column_name(column): column for column in df.columns}
    for candidate in candidates:
        match = normalized.get(_normalize_column_name(candidate))
        if match is not None:
            return str(match)
    return None


def _hourly_demands_from_8760_profile(
    excel_file,
    weather,
) -> tuple[dict[int, tuple[float, float]], list[MonthlyDemand], pd.DataFrame, dict[str, float | str]]:
    """Build hourly HT/BT needs from an 8760 h process power/energy profile.

    Expected V2 workbook:
    - `E étuve recalée kWh` or `P étuve recalée kW` = HT process to 60 C;
    - `E cabines recalée kWh` or `P cabines recalée kW` = BT process to 25 C.

    If energy columns are present, they are used directly. Otherwise, power kW
    is interpreted as kWh over each one-hour step.
    """

    df = pd.read_excel(excel_file, sheet_name=0)
    ht_energy_col = _column_by_normalized_name(df, ["E etuve recalee kWh", "E etuves recalee kWh"])
    bt_energy_col = _column_by_normalized_name(df, ["E cabines recalee kWh", "E cabine recalee kWh"])
    ht_power_col = _column_by_normalized_name(df, ["P etuve recalee kW", "P etuves recalee kW"])
    bt_power_col = _column_by_normalized_name(df, ["P cabines recalee kW", "P cabine recalee kW"])

    if ht_energy_col is None and ht_power_col is None:
        raise ValueError("Colonne HT introuvable : attendu `E/P étuve recalée`.")
    if bt_energy_col is None and bt_power_col is None:
        raise ValueError("Colonne BT introuvable : attendu `E/P cabines recalée`.")

    weather_count = len(weather)
    if len(df) < weather_count:
        raise ValueError(f"Le profil horaire contient {len(df)} lignes, mais la météo en contient {weather_count}.")
    clean = df.iloc[:weather_count].copy()

    ht_source = ht_energy_col if ht_energy_col is not None else ht_power_col
    bt_source = bt_energy_col if bt_energy_col is not None else bt_power_col
    assert ht_source is not None
    assert bt_source is not None
    clean["demand_ht_kwh"] = pd.to_numeric(clean[ht_source], errors="coerce").fillna(0.0).clip(lower=0.0)
    clean["demand_bt_kwh"] = pd.to_numeric(clean[bt_source], errors="coerce").fillna(0.0).clip(lower=0.0)

    hourly_override: dict[int, tuple[float, float]] = {}
    rows = []
    for index, w in enumerate(weather):
        ht_kwh = float(clean["demand_ht_kwh"].iloc[index])
        bt_kwh = float(clean["demand_bt_kwh"].iloc[index])
        hourly_override[w.hour_index] = (ht_kwh, bt_kwh)
        rows.append(
            {
                "hour_index": w.hour_index,
                "month": w.month,
                "day": w.day,
                "hour": w.hour,
                "demand_ht_kwh": ht_kwh,
                "demand_bt_kwh": bt_kwh,
            }
        )

    hourly_profile_df = pd.DataFrame(rows)
    monthly_demands = [
        MonthlyDemand(
            month=month,
            process_ht_kwh=float(group["demand_ht_kwh"].sum()),
            process_bt_kwh=float(group["demand_bt_kwh"].sum()),
        )
        for month, group in hourly_profile_df.groupby("month", sort=True)
    ]
    info = {
        "format": "hourly_8760",
        "rows": float(len(clean)),
        "operating_days": float((hourly_profile_df[["demand_ht_kwh", "demand_bt_kwh"]].sum(axis=1) > 0).sum() / 24.0),
        "operating_hours_per_day": 0.0,
        "ht_kwh": float(hourly_profile_df["demand_ht_kwh"].sum()),
        "bt_kwh": float(hourly_profile_df["demand_bt_kwh"].sum()),
        "cabin_scale_factor": 1.0,
        "oven_scale_factor": 1.0,
    }
    return hourly_override, monthly_demands, hourly_profile_df, info


def _hourly_demands_from_process_file(
    excel_file,
    weather,
    *,
    operating_start_hour: int = 5,
    operating_end_hour: int = 21,
    cabin_scale_factor: float = 0.821,
    oven_scale_factor: float = 0.955,
) -> tuple[dict[int, tuple[float, float]], list[MonthlyDemand], pd.DataFrame, dict[str, float | str]]:
    df_preview = pd.read_excel(excel_file, sheet_name=0, nrows=5)
    normalized_columns = {_normalize_column_name(column) for column in df_preview.columns}
    hourly_markers = {
        "e etuve recalee kwh",
        "e cabines recalee kwh",
        "p etuve recalee kw",
        "p cabines recalee kw",
    }
    if normalized_columns & hourly_markers:
        return _hourly_demands_from_8760_profile(excel_file, weather)
    return _hourly_demands_from_process_calendar(
        excel_file,
        weather,
        operating_start_hour=operating_start_hour,
        operating_end_hour=operating_end_hour,
        cabin_scale_factor=cabin_scale_factor,
        oven_scale_factor=oven_scale_factor,
    )


def _hourly_demands_from_process_calendar(
    excel_file,
    weather,
    *,
    operating_start_hour: int = 5,
    operating_end_hour: int = 21,
    cabin_scale_factor: float = 0.821,
    oven_scale_factor: float = 0.955,
) -> tuple[dict[int, tuple[float, float]], list[MonthlyDemand], pd.DataFrame, dict[str, float]]:
    """Build hourly HT/BT needs from the provided daily process calendar.

    Expected file shape, based on the current user workbook:
    - one row per day;
    - `P étuve kW` / `E étuve MWh` = HT process air to 60 C;
    - `P cabines kW` / `E cabines MWh` = BT process air to 25 C;
    - `Fonctionnement` = 1 for open days, 0 for closed days.
    """

    df = pd.read_excel(excel_file, sheet_name=0)
    required = {"Date", "Fonctionnement", "P cabines kW", "E cabines MWh", "P étuve kW", "E étuve MWh"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier besoin horaire/journalier : {sorted(missing)}")

    operating_hours = max(1, int(operating_end_hour) - int(operating_start_hour))
    profile_by_day: dict[tuple[int, int], tuple[float, float]] = {}

    clean = df.copy()
    clean["Date"] = pd.to_datetime(clean["Date"], errors="coerce")
    clean = clean.dropna(subset=["Date"])
    for _, row in clean.iterrows():
        month = int(row["Date"].month)
        day = int(row["Date"].day)
        is_open = float(row.get("Fonctionnement", 0.0) or 0.0) > 0.0
        if not is_open:
            profile_by_day[(month, day)] = (0.0, 0.0)
            continue

        ht_kw_from_energy = max(0.0, float(row.get("E étuve MWh", 0.0) or 0.0) * 1000.0 / operating_hours)
        bt_kw_from_energy = max(0.0, float(row.get("E cabines MWh", 0.0) or 0.0) * 1000.0 / operating_hours)
        ht_kw_raw = ht_kw_from_energy if ht_kw_from_energy > 0.0 else max(0.0, float(row.get("P étuve kW", 0.0) or 0.0))
        bt_kw_raw = bt_kw_from_energy if bt_kw_from_energy > 0.0 else max(0.0, float(row.get("P cabines kW", 0.0) or 0.0))
        ht_kw = ht_kw_raw * max(0.0, float(oven_scale_factor))
        bt_kw = bt_kw_raw * max(0.0, float(cabin_scale_factor))
        profile_by_day[(month, day)] = (ht_kw, bt_kw)

    hourly_override: dict[int, tuple[float, float]] = {}
    rows = []
    for w in weather:
        day_profile = profile_by_day.get((w.month, w.day), (0.0, 0.0))
        is_operating_hour = int(operating_start_hour) <= int(w.hour) < int(operating_end_hour)
        ht_kwh = day_profile[0] if is_operating_hour else 0.0
        bt_kwh = day_profile[1] if is_operating_hour else 0.0
        hourly_override[w.hour_index] = (ht_kwh, bt_kwh)
        rows.append(
            {
                "hour_index": w.hour_index,
                "month": w.month,
                "day": w.day,
                "hour": w.hour,
                "demand_ht_kwh": ht_kwh,
                "demand_bt_kwh": bt_kwh,
            }
        )

    hourly_profile_df = pd.DataFrame(rows)
    monthly_demands = [
        MonthlyDemand(
            month=month,
            process_ht_kwh=float(group["demand_ht_kwh"].sum()),
            process_bt_kwh=float(group["demand_bt_kwh"].sum()),
        )
        for month, group in hourly_profile_df.groupby("month", sort=True)
    ]
    info = {
        "rows": float(len(clean)),
        "operating_days": float((clean["Fonctionnement"].fillna(0).astype(float) > 0).sum()),
        "operating_hours_per_day": float(operating_hours),
        "ht_kwh": float(hourly_profile_df["demand_ht_kwh"].sum()),
        "bt_kwh": float(hourly_profile_df["demand_bt_kwh"].sum()),
        "cabin_scale_factor": float(cabin_scale_factor),
        "oven_scale_factor": float(oven_scale_factor),
    }
    return hourly_override, monthly_demands, hourly_profile_df, info


def _peak_bt_power_kw(
    weather,
    demands: list[MonthlyDemand],
    hourly_demand_override: dict[int, tuple[float, float]] | None,
) -> float:
    if hourly_demand_override:
        return max((max(0.0, float(bt)) for _, bt in hourly_demand_override.values()), default=0.0)

    hour_count_by_month = {month: 0 for month in range(1, 13)}
    for hour in weather:
        hour_count_by_month[hour.month] = hour_count_by_month.get(hour.month, 0) + 1

    peak = 0.0
    for demand in demands:
        hours = max(1, hour_count_by_month.get(demand.month, 0))
        peak = max(peak, max(0.0, demand.process_bt_kwh) / hours)
    return peak


def _estimate_capped_bt_heat_mwh(
    weather,
    demands: list[MonthlyDemand],
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    pac_power_kw: float,
) -> float:
    cap = max(0.0, float(pac_power_kw))
    if cap <= 0.0:
        return 0.0
    if hourly_demand_override:
        return sum(min(max(0.0, float(bt)), cap) for _, bt in hourly_demand_override.values()) / 1000.0

    hour_count_by_month = {month: 0 for month in range(1, 13)}
    for hour in weather:
        hour_count_by_month[hour.month] = hour_count_by_month.get(hour.month, 0) + 1

    total_kwh = 0.0
    for demand in demands:
        hours = max(1, hour_count_by_month.get(demand.month, 0))
        hourly_bt = max(0.0, demand.process_bt_kwh) / hours
        total_kwh += min(hourly_bt, cap) * hours
    return total_kwh / 1000.0

