"""Import de points fabricant tabulés complémentaires.

Ces fichiers ne constituent pas des cartes dynamiques. Ils enrichissent les
points de référence utilisables en prédimensionnement, avec une provenance
explicite. Ils peuvent être fusionnés avec les XML SoloPAC legacy.
"""
from __future__ import annotations
import csv
from pathlib import Path

from .hp_map import HeatPumpMapPoint
from .quality import HeatPumpDataQuality
from .schemas import HeatPumpProduct


def _f(row: dict[str, str], key: str) -> float | None:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_rated_heat_pump_csv(path: str | Path) -> HeatPumpProduct:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Fichier de points PAC vide : {path}")
    first = rows[0]
    manufacturer = (first.get("manufacturer") or "Inconnu").strip()
    model = (first.get("model") or path.stem).strip()
    points: list[HeatPumpMapPoint] = []
    for row in rows:
        source = _f(row, "T_source_in_C")
        sink = _f(row, "T_sink_out_C")
        pheat = _f(row, "P_heat_kW")
        pel = _f(row, "P_el_kW")
        cop = _f(row, "COP")
        if None in (source, sink, pheat, pel, cop):
            continue
        if pheat <= 0 or pel <= 0 or cop <= 0:
            continue
        points.append(
            HeatPumpMapPoint(
                T_source_in_C=float(source),
                T_sink_C=float(sink),
                P_heat_kW=float(pheat),
                P_el_kW=float(pel),
                COP=float(cop),
                provenance=(row.get("provenance") or f"Table fabricant: {path.name}").strip(),
            )
        )
    return HeatPumpProduct(
        manufacturer=manufacturer,
        model=model,
        nominal_power_kw=float(_f(first, "nominal_power_kw") or 0.0),
        data_quality=HeatPumpDataQuality.SPARSE_RATED_POINTS if points else HeatPumpDataQuality.MISSING,
        rated_points=tuple(sorted(points, key=lambda p: (p.T_source_in_C, p.T_sink_C))),
        source_temperature_min_C=_f(first, "source_temperature_min_C"),
        source_temperature_max_C=_f(first, "source_temperature_max_C"),
        sink_temperature_max_C=_f(first, "sink_temperature_max_C"),
        source_flow_m3h=_f(first, "source_flow_m3h"),
        provenance=(first.get("provenance") or f"Table fabricant: {path.name}").strip(),
        notes="Points tabulés fabricant : prédimensionnement seulement ; aucune extrapolation dynamique.",
    )
