"""Import strict des XML PAC legacy SoloPAC."""
from __future__ import annotations
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from .hp_map import HeatPumpMapPoint
from .quality import HeatPumpDataQuality
from .schemas import HeatPumpProduct

_POINT_RE = re.compile(r"^COP(-?\d+)_(-?\d+)$")


def _values(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {child.tag: (child.text or "").strip() for child in root}


def _float(values: dict[str, str], key: str) -> float | None:
    raw = values.get(key, "")
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_heat_pump_xml(path: str | Path, *, nominal_power_kw: float | None = None) -> HeatPumpProduct:
    path = Path(path)
    values = _values(path)
    manufacturer = values.get("Marque_PAC", "").strip() or "Inconnu"
    model = values.get("Modele_PAC", "").strip() or path.stem
    points: list[HeatPumpMapPoint] = []
    for key, raw_cop in values.items():
        match = _POINT_RE.match(key)
        if not match:
            continue
        source = float(match.group(1))
        sink = float(match.group(2))
        try:
            cop = float(raw_cop)
        except ValueError:
            continue
        pabs = _float(values, f"PAbs{match.group(1)}_{match.group(2)}") or 0.0
        if cop <= 0 or pabs <= 0:
            continue
        pheat = cop * pabs
        points.append(
            HeatPumpMapPoint(
                source,
                sink,
                pheat,
                pabs,
                cop,
                provenance=f"XML SoloPAC: {path.name}",
            )
        )
    inferred_nominal = nominal_power_kw
    if inferred_nominal is None:
        # Point commercial approximé uniquement comme métadonnée d'affichage.
        inferred_nominal = max((p.P_heat_kW for p in points if abs(p.T_source_in_C - 10.0) < 1e-9), default=0.0)
    return HeatPumpProduct(
        manufacturer=manufacturer,
        model=model,
        nominal_power_kw=float(inferred_nominal or 0.0),
        data_quality=HeatPumpDataQuality.SPARSE_RATED_POINTS if points else HeatPumpDataQuality.MISSING,
        rated_points=tuple(sorted(points, key=lambda p: (p.T_source_in_C, p.T_sink_C))),
        performance_map=None,
        source_temperature_min_C=_float(values, "TminEvaporateur"),
        source_temperature_max_C=_float(values, "TmaxEvaporateur"),
        sink_temperature_max_C=_float(values, "TmaxCondenseur"),
        source_flow_m3h=(_float(values, "DebitNomEvaporateur") or 0.0) / 1000.0 or None,
        sink_flow_m3h=(_float(values, "DebitNomCondenseur") or 0.0) / 1000.0 or None,
        source_pump_kW=_float(values, "PCirculateurEvaporateur"),
        sink_pump_kW=_float(values, "PCirculateurCondenseur"),
        provenance=f"XML SoloPAC fourni: {path.name}",
        notes="Points clairsemés : utilisables en prédimensionnement, pas en solveur dynamique annuel.",
    )
