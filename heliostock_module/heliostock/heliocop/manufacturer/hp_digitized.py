"""Import des courbes fabricant numérisées avec traçabilité."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

from .hp_map import HeatPumpMapPoint, HeatPumpPerformanceMap
from .quality import HeatPumpDataQuality
from .schemas import HeatPumpProduct

_REQUIRED = {"manufacturer", "model", "T_source_in_C", "T_sink_value_C", "T_sink_convention", "P_heat_kW", "COP"}


def load_digitized_heat_pump_csv(path: str | Path) -> HeatPumpProduct:
    path = Path(path)
    df = pd.read_csv(path)
    missing = _REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans {path.name}: {sorted(missing)}")
    manufacturers = {str(v).strip() for v in df["manufacturer"].dropna().unique()}
    models = {str(v).strip() for v in df["model"].dropna().unique()}
    conventions = {str(v).strip() for v in df["T_sink_convention"].dropna().unique()}
    if len(manufacturers) != 1 or len(models) != 1 or len(conventions) != 1:
        raise ValueError("Un fichier numérisé doit contenir un seul produit et une seule convention de température.")
    convention_raw = conventions.pop().lower()
    convention = {"sink_in": "sink_in", "sink_out": "sink_out", "inlet": "sink_in", "outlet": "sink_out"}.get(convention_raw)
    if convention is None:
        raise ValueError(f"Convention côté chaud non reconnue : {convention_raw}")

    quality = HeatPumpDataQuality.DIGITIZED_MANUFACTURER_CURVES
    if "data_quality" in df and df["data_quality"].notna().any():
        raw_quality = str(df["data_quality"].dropna().iloc[0]).strip()
        try:
            quality = HeatPumpDataQuality(raw_quality)
        except ValueError as exc:
            raise ValueError(f"Qualité de donnée PAC inconnue dans {path.name}: {raw_quality}") from exc

    points: list[HeatPumpMapPoint] = []
    for row in df.to_dict("records"):
        pheat = float(row["P_heat_kW"])
        cop = float(row["COP"])
        pel_raw = row.get("P_el_kW")
        pel = float(pel_raw) if pel_raw is not None and pd.notna(pel_raw) and float(pel_raw) > 0 else pheat / cop
        if pheat <= 0 or pel <= 0 or cop <= 0:
            continue
        source_doc = str(row.get("source_document", "")).strip()
        source_page = str(row.get("source_page", "")).strip()
        provenance = str(row.get("provenance", "digitized manufacturer curve")).strip()
        if source_doc:
            provenance = f"{provenance}; {source_doc}" + (f" p.{source_page}" if source_page else "")
        unc = row.get("estimated_uncertainty_pct")
        uncertainty = float(unc) if unc is not None and pd.notna(unc) else None
        points.append(
            HeatPumpMapPoint(
                T_source_in_C=float(row["T_source_in_C"]),
                T_sink_C=float(row["T_sink_value_C"]),
                P_heat_kW=pheat,
                P_el_kW=pel,
                COP=pheat / pel,
                provenance=provenance,
                uncertainty_pct=uncertainty,
            )
        )
    if len(points) < 6:
        raise ValueError(f"Carte numérisée insuffisante pour {path.name}.")
    manufacturer = next(iter(manufacturers))
    model = next(iter(models))
    perf_map = HeatPumpPerformanceMap(
        points,
        quality=quality,
        sink_temperature_convention=convention,
        name=f"{manufacturer} {model}",
    )
    nominal = float(df["nominal_power_kw"].dropna().iloc[0]) if "nominal_power_kw" in df and df["nominal_power_kw"].notna().any() else max(p.P_heat_kW for p in points)

    def _first_positive(column: str) -> float | None:
        if column not in df:
            return None
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        values = values[values > 0]
        return float(values.iloc[0]) if not values.empty else None

    def _first_numeric(column: str) -> float | None:
        if column not in df:
            return None
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        return float(values.iloc[0]) if not values.empty else None

    source_flow = _first_positive("source_flow_m3h")
    sink_flow = _first_positive("sink_flow_m3h")
    sink_outlet_max = _first_positive("sink_outlet_max_C")
    source_operating_min = _first_numeric("source_operating_min_C")
    source_operating_max = _first_numeric("source_operating_max_C")
    source_pump = _first_positive("source_pump_kW")
    sink_pump = _first_positive("sink_pump_kW")
    notes = ""
    if "notes" in df and df["notes"].notna().any():
        notes = str(df["notes"].dropna().iloc[0]).strip()
    if not notes:
        notes = "Courbes fabricant numérisées. Utiliser uniquement dans le domaine couvert par le graphique."

    return HeatPumpProduct(
        manufacturer=manufacturer,
        model=model,
        nominal_power_kw=nominal,
        data_quality=quality,
        rated_points=tuple(points),
        performance_map=perf_map,
        # Les bornes du produit peuvent être plus larges que la carte numérisée;
        # le solveur dynamique reste borné par performance_map.source_bounds_C.
        source_temperature_min_C=source_operating_min if source_operating_min is not None else perf_map.source_bounds_C[0],
        source_temperature_max_C=source_operating_max if source_operating_max is not None else perf_map.source_bounds_C[1],
        sink_temperature_max_C=sink_outlet_max if sink_outlet_max is not None else perf_map.sink_bounds_C[1],
        sink_outlet_temperature_max_C=sink_outlet_max,
        source_flow_m3h=source_flow,
        sink_flow_m3h=sink_flow,
        source_pump_kW=source_pump,
        sink_pump_kW=sink_pump,
        provenance=perf_map.provenance,
        notes=notes,
    )
