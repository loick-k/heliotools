"""Bibliothèque partagée de capteurs solaires thermiques.

Ce module sert de source unique pour HelioDyn, HelioNOP et HelioSOLO. Les
coefficients sont stockés dans la convention EN 12975/ISO 9806 :
eta0, a1 en W/m²/K et a2 en W/m²/K².
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class CollectorReference:
    manufacturer: str
    model: str
    area_m2: float
    eta0: float
    a1_w_m2_k: float
    a2_w_m2_k2: float
    source: str = "Bibliothèque HelioTools"
    notes: str = ""

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.model}"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def as_solo_dict(self) -> dict[str, float]:
        return {
            "surface_utile_m2": float(self.area_m2),
            "n0": float(self.eta0),
            "a1": float(self.a1_w_m2_k),
            "a2": float(self.a2_w_m2_k2),
        }


@dataclass(frozen=True)
class PacSolarCollectorReference:
    """Reference commune pour les capteurs PAC solaire / WISC.

    HelioCOP utilise des XML fabricant plus riches que les capteurs thermiques
    classiques : coefficients quasi-dynamiques, facteurs d'incidence et
    certification. Ce type garde ces champs dans la bibliotheque commune sans
    imposer ces details aux modules HelioDyn, HelioNOP ou HelioSOLO.
    """

    manufacturer: str
    model: str
    collector_type: str
    unit_area_m2: float
    eta0: float
    a1_w_m2_k: float
    a2_w_m2_k2: float
    a3: float = 0.0
    a4: float = 0.0
    a5: float = 0.0
    a6: float = 0.0
    a7: float = 0.0
    a8: float = 0.0
    kd: float = 1.0
    kt_by_angle: Mapping[int, float] | None = None
    kl_by_angle: Mapping[int, float] | None = None
    certification: str = ""
    source: str = "Bibliotheque HelioCOP"
    standard_version: str = ""
    equation_schema: str = "ISO9806_QDT_XML_A1_A8_V1"
    schema_verified: bool = False
    data_path: str = ""

    @property
    def id(self) -> str:
        return f"{self.manufacturer}::{self.model}"

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.model}"

    @property
    def coefficients(self) -> dict[str, float]:
        return {
            "eta0": float(self.eta0),
            "a1": float(self.a1_w_m2_k),
            "a2": float(self.a2_w_m2_k2),
            "a3": float(self.a3),
            "a4": float(self.a4),
            "a5": float(self.a5),
            "a6": float(self.a6),
            "a7": float(self.a7),
            "a8": float(self.a8),
        }

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_COLLECTOR_NAME = "SunOptimo 245V"
MANUAL_COLLECTOR_LABEL = "Saisie manuelle"


_DEFAULT_COLLECTORS: tuple[CollectorReference, ...] = (
    CollectorReference("SunOptimo", "245V", 2.32, 0.824, 2.905, 0.030, "HelioDyn / HelioNOP"),
    CollectorReference("Générique", "Plan vitré", 2.32, 0.750, 3.500, 0.015, "Hypothèse standard HelioTools"),
    CollectorReference("Eklor", "C.SOL 423 EKS", 2.29, 0.790, 3.880, 0.010, "Bibliothèque HelioSOLO initiale"),
    CollectorReference("Ellios Technologies", "GK3133", 12.37, 0.814, 2.102, 0.016, "Bibliothèque HelioSOLO initiale"),
    CollectorReference("SunOptimo", "245V - référence HelioSOLO", 2.45, 0.852, 3.922, 0.015, "Bibliothèque HelioSOLO initiale"),
    CollectorReference("SunOptimo", "DIS150", 15.50, 0.765, 2.230, 0.008, "Bibliothèque HelioSOLO initiale"),
    CollectorReference("TVP Solar", "MT power v4", 1.96, 0.737, 0.504, 0.006, "Bibliothèque HelioSOLO initiale"),
)


def _normalise_key(value: str) -> str:
    return " ".join(str(value).strip().split()).lower()


def _normalise_catalog_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def collector_key(manufacturer: str, model: str) -> str:
    return f"{manufacturer.strip()} {model.strip()}".strip()


def _xml_values(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {child.tag: (child.text or "").strip() for child in root}


def _xml_float(values: Mapping[str, str], key: str, default: float = 0.0) -> float:
    try:
        raw = values.get(key, "")
        return float(raw) if raw not in ("", None) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _default_heliocop_collector_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "heliocop" / "data" / "capteurs"


def validate_collector_reference(collector: CollectorReference) -> CollectorReference:
    if not collector.manufacturer.strip():
        raise ValueError("Le fabricant du capteur est obligatoire.")
    if not collector.model.strip():
        raise ValueError("Le modèle du capteur est obligatoire.")
    if collector.area_m2 <= 0:
        raise ValueError("La surface utile du capteur doit être positive.")
    if not 0 <= collector.eta0 <= 1:
        raise ValueError("eta0 doit être compris entre 0 et 1.")
    if collector.a1_w_m2_k < 0:
        raise ValueError("a1 doit être positif ou nul.")
    if collector.a2_w_m2_k2 < 0:
        raise ValueError("a2 doit être positif ou nul.")
    return collector


def make_collector_reference(
    *,
    manufacturer: str,
    model: str,
    area_m2: float,
    eta0: float,
    a1_w_m2_k: float,
    a2_w_m2_k2: float,
    source: str = "Saisie utilisateur",
    notes: str = "",
) -> CollectorReference:
    return validate_collector_reference(
        CollectorReference(
            manufacturer=str(manufacturer).strip(),
            model=str(model).strip(),
            area_m2=float(area_m2),
            eta0=float(eta0),
            a1_w_m2_k=float(a1_w_m2_k),
            a2_w_m2_k2=float(a2_w_m2_k2),
            source=str(source).strip() or "Saisie utilisateur",
            notes=str(notes).strip(),
        )
    )


def _library_from_collectors(collectors: list[CollectorReference]) -> dict[str, CollectorReference]:
    library: dict[str, CollectorReference] = {}
    seen: set[str] = set()
    for collector in collectors:
        reference = validate_collector_reference(collector)
        base_label = reference.label
        label = base_label
        normalised = _normalise_key(label)
        suffix = 2
        while normalised in seen:
            label = f"{base_label} ({suffix})"
            normalised = _normalise_key(label)
            suffix += 1
        library[label] = reference
        seen.add(normalised)
    return library


def build_collector_library(extra_collectors: Mapping[str, CollectorReference] | None = None) -> dict[str, CollectorReference]:
    collectors = list(_DEFAULT_COLLECTORS)
    if extra_collectors:
        collectors.extend(extra_collectors.values())
    return _library_from_collectors(collectors)


COLLECTOR_LIBRARY: dict[str, CollectorReference] = build_collector_library()


def get_collector_reference(
    name: str | None,
    *,
    extra_collectors: Mapping[str, CollectorReference] | None = None,
) -> CollectorReference:
    library = build_collector_library(extra_collectors)
    if name in library:
        return library[str(name)]
    return library[DEFAULT_COLLECTOR_NAME]


def collector_names(*, extra_collectors: Mapping[str, CollectorReference] | None = None) -> list[str]:
    return list(build_collector_library(extra_collectors).keys())


def as_heliosolo_capteur_library(
    *,
    extra_collectors: Mapping[str, CollectorReference] | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Return the shared library in HelioSOLO's legacy nested format."""

    nested: dict[str, dict[str, dict[str, float]]] = {}
    for reference in build_collector_library(extra_collectors).values():
        nested.setdefault(reference.manufacturer, {})[reference.model] = reference.as_solo_dict()
    return nested


def load_pac_solar_collector_xml(path: str | Path) -> PacSolarCollectorReference:
    """Load a HelioCOP/SoloPAC collector XML into the shared catalog format."""

    xml_path = Path(path)
    values = _xml_values(xml_path)
    unit_area_m2 = _xml_float(values, "Scapt_Uni")
    if unit_area_m2 <= 0:
        raise ValueError(f"Surface unitaire invalide dans {xml_path.name}.")
    kt = {angle: _xml_float(values, f"KT_{angle}") for angle in range(10, 91, 10)}
    kl = {angle: _xml_float(values, f"KL_{angle}") for angle in range(10, 91, 10)}
    return PacSolarCollectorReference(
        manufacturer=values.get("Marque_Capteur", "") or "Inconnu",
        model=values.get("Modele_Capteur", "") or xml_path.stem,
        collector_type=values.get("Type_Capteur", ""),
        unit_area_m2=unit_area_m2,
        eta0=_xml_float(values, "Coef_eta0"),
        a1_w_m2_k=_xml_float(values, "Coef_a1"),
        a2_w_m2_k2=_xml_float(values, "Coef_a2"),
        a3=_xml_float(values, "Coef_a3"),
        a4=_xml_float(values, "Coef_a4"),
        a5=_xml_float(values, "Coef_a5"),
        a6=_xml_float(values, "Coef_a6"),
        a7=_xml_float(values, "Coef_a7"),
        a8=_xml_float(values, "Coef_a8"),
        kd=_xml_float(values, "Kd", 1.0),
        kt_by_angle=kt,
        kl_by_angle=kl,
        certification=values.get("Certification_Capteur", ""),
        source=f"XML HelioCOP: {xml_path.name}",
        standard_version=values.get("Version_Norme", ""),
        data_path=str(xml_path),
    )


def load_heliocop_collector_library(
    data_dir: str | Path | None = None,
) -> dict[str, PacSolarCollectorReference]:
    """Return HelioCOP collector XML references through the shared library.

    The keys are stable product ids (``manufacturer::model``). Existing HelioCOP
    code can still request a collector by XML filename through
    :func:`get_heliocop_collector_reference`.
    """

    directory = Path(data_dir) if data_dir is not None else _default_heliocop_collector_dir()
    library: dict[str, PacSolarCollectorReference] = {}
    if not directory.is_dir():
        return library
    for path in sorted(directory.glob("*.xml")):
        try:
            reference = load_pac_solar_collector_xml(path)
        except (OSError, ET.ParseError, ValueError):
            continue
        library[reference.id] = reference
    return library


def get_heliocop_collector_reference(
    name: str | None,
    *,
    data_dir: str | Path | None = None,
) -> PacSolarCollectorReference | None:
    """Find a HelioCOP collector by id, label, model, stem or XML filename."""

    if not name:
        return None
    directory = Path(data_dir) if data_dir is not None else _default_heliocop_collector_dir()
    requested = str(name).strip()
    direct_path = Path(requested)
    candidates = []
    if direct_path.is_file():
        candidates.append(direct_path)
    if directory.is_dir():
        candidates.append(directory / requested)
        if not requested.lower().endswith(".xml"):
            candidates.append(directory / f"{requested}.xml")
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".xml":
            try:
                return load_pac_solar_collector_xml(candidate)
            except (OSError, ET.ParseError, ValueError):
                return None

    normalised = _normalise_catalog_key(requested)
    for reference in load_heliocop_collector_library(directory).values():
        aliases = (
            reference.id,
            reference.label,
            reference.model,
            Path(reference.data_path).name,
            Path(reference.data_path).stem,
        )
        if any(_normalise_catalog_key(alias) == normalised for alias in aliases):
            return reference
    return None
