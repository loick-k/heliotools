from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

import pandas as pd


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stable_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(_jsonable(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dataframe_content_hash(df: pd.DataFrame | None) -> str:
    if df is None or df.empty:
        return ""
    stable_df = df.copy()
    stable_df = stable_df.reindex(sorted(stable_df.columns), axis=1)
    csv_bytes = stable_df.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(csv_bytes).hexdigest()


def bytes_hash(value: bytes | bytearray | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(bytes(value)).hexdigest()


def build_calculation_snapshot(
    *,
    weather_station: str,
    weather_region: str,
    weather_tilt_deg: Any,
    weather_azimuth_deg_south: Any,
    weather_albedo: Any,
    demand_file_name: str,
    demand_file_hash: str,
    hourly_profile_df: pd.DataFrame | None,
    process_bt_target_c: Any,
    process_ht_target_c: Any,
    demand_scope: Any,
    solar: Any,
    btes: Any,
    heat_pump: Any,
    economics: Any,
    pac_power_fraction_pct: Any,
    use_probe_predesign: Any,
    probe_power_ratio_w_m: Any,
    probe_energy_ratio_kwh_m: Any,
    probe_unit_depth_m: Any,
    calculation_selection: Any,
    pac_parametric: Any,
    solar_parametric: Any,
    gmi: Any | None = None,
    project: Any | None = None,
) -> dict[str, Any]:
    return {
        "project": _jsonable(project or {}),
        "weather": {
            "region": weather_region,
            "station": weather_station,
            "tilt_deg": weather_tilt_deg,
            "azimuth_deg_south": weather_azimuth_deg_south,
            "albedo": weather_albedo,
        },
        "demand": {
            "file_name": demand_file_name,
            "file_hash": demand_file_hash,
            "profile_hash": dataframe_content_hash(hourly_profile_df),
            "process_bt_target_c": process_bt_target_c,
            "process_ht_target_c": process_ht_target_c,
            "scope": demand_scope,
        },
        "solar": _jsonable(solar),
        "geothermal": {
            "btes": _jsonable(btes),
            "pac_power_fraction_pct": pac_power_fraction_pct,
            "use_probe_predesign": use_probe_predesign,
            "probe_power_ratio_w_m": probe_power_ratio_w_m,
            "probe_energy_ratio_kwh_m": probe_energy_ratio_kwh_m,
            "probe_unit_depth_m": probe_unit_depth_m,
        },
        "heat_pump": _jsonable(heat_pump),
        "economics": _jsonable(economics),
        "calculation_selection": _jsonable(calculation_selection),
        "parametric": {
            "pac": _jsonable(pac_parametric),
            "solar": _jsonable(solar_parametric),
        },
        "gmi": _jsonable(gmi or {}),
    }


def timestamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")
