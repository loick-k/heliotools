"""Bibliothèque partagée de capteurs solaires thermiques.

Ce module sert de source unique pour HelioDyn, HelioNOP et HelioSOLO. Les
coefficients sont stockés dans la convention EN 12975/ISO 9806 :
eta0, a1 en W/m²/K et a2 en W/m²/K².
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


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


def collector_key(manufacturer: str, model: str) -> str:
    return f"{manufacturer.strip()} {model.strip()}".strip()


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
