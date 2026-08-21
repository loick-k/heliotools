"""Registre fabricant unique HelioCOP V2."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Iterable

from ..domain.errors import MissingHeatPumpMapError, MissingCollectorDataError
from .hp_digitized import load_digitized_heat_pump_csv
from .hp_xml import load_heat_pump_xml
from .hp_rated import load_rated_heat_pump_csv
from .schemas import HeatPumpProduct, WISCCollectorProduct
from .wisc_xml import load_wisc_xml

BASE_DIR = Path(__file__).resolve().parents[1]
PAC_DIR = BASE_DIR / "data" / "pac"
DIGITIZED_DIR = BASE_DIR / "data" / "pac_digitized"
WISC_DIR = BASE_DIR / "data" / "capteurs"
RATED_DIR = BASE_DIR / "data" / "pac_rated"
CATALOG_JSON = PAC_DIR / "pac_catalog.json"


def _norm(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _catalog_metadata() -> list[dict]:
    if not CATALOG_JSON.is_file():
        return []
    try:
        return json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []


def _nominal_for_xml(path: Path, metadata: Iterable[dict]) -> float | None:
    stem_norm = _norm(path.stem)
    for row in metadata:
        xml = row.get("xml")
        if xml and _norm(Path(str(xml)).stem) == stem_norm:
            return float(row.get("nominal_power_kw", 0.0) or 0.0)
        model = str(row.get("model", ""))
        if model and _norm(model) in stem_norm or stem_norm in _norm(model):
            value = float(row.get("nominal_power_kw", 0.0) or 0.0)
            if value > 0:
                return value
    # Cas P25 ajouté après le catalogue historique.
    if "p25" in stem_norm:
        return 25.0
    if "p50" in stem_norm:
        return 50.0
    return None


class ManufacturerRegistry:
    def __init__(self, heat_pumps: Iterable[HeatPumpProduct] = (), collectors: Iterable[WISCCollectorProduct] = ()) -> None:
        self._heat_pumps = {p.id: p for p in heat_pumps}
        self._collectors = {c.id: c for c in collectors}

    @classmethod
    def from_package_data(cls) -> "ManufacturerRegistry":
        metadata = _catalog_metadata()
        products: dict[str, HeatPumpProduct] = {}
        for path in sorted(PAC_DIR.glob("*.xml")):
            product = load_heat_pump_xml(path, nominal_power_kw=_nominal_for_xml(path, metadata))
            if _norm(product.manufacturer) == "fictive":
                continue
            products[product.id] = product
        # Les points tabulés fabricant complètent les XML SoloPAC clairsemés.
        if RATED_DIR.is_dir():
            for path in sorted(RATED_DIR.glob("*.csv")):
                rated = load_rated_heat_pump_csv(path)
                existing = products.get(rated.id)
                if existing is None:
                    products[rated.id] = rated
                    continue
                merged: dict[tuple[float, float], object] = {
                    (p.T_source_in_C, p.T_sink_C): p for p in existing.rated_points
                }
                # En cas de point identique, la table fabricant directe prime.
                for point in rated.rated_points:
                    merged[(point.T_source_in_C, point.T_sink_C)] = point
                products[rated.id] = replace(
                    existing,
                    nominal_power_kw=rated.nominal_power_kw or existing.nominal_power_kw,
                    data_quality=rated.data_quality,
                    rated_points=tuple(sorted(merged.values(), key=lambda p: (p.T_source_in_C, p.T_sink_C))),
                    source_temperature_min_C=(
                        rated.source_temperature_min_C if rated.source_temperature_min_C is not None else existing.source_temperature_min_C
                    ),
                    source_temperature_max_C=(
                        rated.source_temperature_max_C if rated.source_temperature_max_C is not None else existing.source_temperature_max_C
                    ),
                    sink_temperature_max_C=(
                        rated.sink_temperature_max_C if rated.sink_temperature_max_C is not None else existing.sink_temperature_max_C
                    ),
                    source_flow_m3h=rated.source_flow_m3h or existing.source_flow_m3h,
                    provenance=f"{existing.provenance}; {rated.provenance}",
                    notes=(existing.notes + " " + rated.notes).strip(),
                )

        # Les cartes numérisées priment sur les points XML clairsemés.
        if DIGITIZED_DIR.is_dir():
            for path in sorted(DIGITIZED_DIR.glob("*.csv")):
                product = load_digitized_heat_pump_csv(path)
                products[product.id] = product
        collectors = [load_wisc_xml(path) for path in sorted(WISC_DIR.glob("*.xml"))]
        return cls(products.values(), collectors)

    @property
    def heat_pumps(self) -> tuple[HeatPumpProduct, ...]:
        return tuple(sorted(self._heat_pumps.values(), key=lambda p: (p.manufacturer.lower(), p.nominal_power_kw, p.model.lower())))

    @property
    def collectors(self) -> tuple[WISCCollectorProduct, ...]:
        return tuple(sorted(self._collectors.values(), key=lambda c: (c.manufacturer.lower(), c.model.lower())))

    def available_heat_pumps(self, *, mode: str = "predim") -> tuple[HeatPumpProduct, ...]:
        mode = mode.lower().strip()
        if mode == "dynamic":
            return tuple(p for p in self.heat_pumps if p.dynamic_available)
        if mode == "predim":
            return tuple(p for p in self.heat_pumps if p.predim_available)
        raise ValueError("mode doit valoir 'predim' ou 'dynamic'.")

    def heat_pump(self, manufacturer: str, model: str, *, mode: str | None = None) -> HeatPumpProduct:
        key = f"{manufacturer}::{model}"
        product = self._heat_pumps.get(key)
        if product is None:
            raise MissingHeatPumpMapError(f"PAC inconnue : {manufacturer} {model}.")
        if mode == "dynamic" and not product.dynamic_available:
            raise MissingHeatPumpMapError(
                f"{manufacturer} {model}: données {product.data_quality.value}; carte dynamique requise."
            )
        if mode == "predim" and not product.predim_available:
            raise MissingHeatPumpMapError(f"{manufacturer} {model}: données insuffisantes pour le prédimensionnement.")
        return product

    def collector(self, manufacturer: str, model: str) -> WISCCollectorProduct:
        key = f"{manufacturer}::{model}"
        product = self._collectors.get(key)
        if product is None:
            raise MissingCollectorDataError(f"Capteur inconnu : {manufacturer} {model}.")
        return product
