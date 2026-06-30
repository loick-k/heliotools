from __future__ import annotations

import unicodedata

import pandas as pd

from .engine import MonthlyDemand


def _normalize_column_name(name: object) -> str:
    text = str(name).strip().lower()
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
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

    Expected workbook:
    - `E besoin HT kWh` or `P besoin HT kW` = HT process to 60 C;
    - `E besoin BT kWh` or `P besoin BT kW` = BT process to 25 C.

    If energy columns are present, they are used directly. Otherwise, power kW
    is interpreted as kWh over each one-hour step.
    """

    df = pd.read_excel(excel_file, sheet_name=0)
    ht_energy_col = _column_by_normalized_name(df, ["E besoin HT kWh", "Besoin HT kWh", "E HT kWh"])
    bt_energy_col = _column_by_normalized_name(df, ["E besoin BT kWh", "Besoin BT kWh", "E BT kWh"])
    ht_power_col = _column_by_normalized_name(df, ["P besoin HT kW", "Puissance HT kW", "P HT kW"])
    bt_power_col = _column_by_normalized_name(df, ["P besoin BT kW", "Puissance BT kW", "P BT kW"])

    if ht_energy_col is None and ht_power_col is None:
        raise ValueError("Colonne HT introuvable : attendu `E/P besoin HT`.")
    if bt_energy_col is None and bt_power_col is None:
        raise ValueError("Colonne BT introuvable : attendu `E/P besoin BT`.")

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
    }
    return hourly_override, monthly_demands, hourly_profile_df, info


def _hourly_demands_from_process_file(
    excel_file,
    weather,
) -> tuple[dict[int, tuple[float, float]], list[MonthlyDemand], pd.DataFrame, dict[str, float | str]]:
    df_preview = pd.read_excel(excel_file, sheet_name=0, nrows=5)
    normalized_columns = {_normalize_column_name(column) for column in df_preview.columns}
    hourly_markers = {
        "e besoin ht kwh",
        "besoin ht kwh",
        "e ht kwh",
        "p besoin ht kw",
        "puissance ht kw",
        "p ht kw",
        "e besoin bt kwh",
        "besoin bt kwh",
        "e bt kwh",
        "p besoin bt kw",
        "puissance bt kw",
        "p bt kw",
    }
    if normalized_columns & hourly_markers:
        return _hourly_demands_from_8760_profile(excel_file, weather)
    raise ValueError(
        "Format besoin invalide : HelioStock attend un profil horaire 8760 h avec "
        "`P/E besoin HT` et `P/E besoin BT`."
    )


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

