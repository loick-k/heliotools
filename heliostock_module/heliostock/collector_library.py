"""Bibliothèque commune de capteurs solaires thermiques."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectorReference:
    manufacturer: str
    model: str
    area_m2: float
    eta0: float
    a1_w_m2_k: float
    a2_w_m2_k2: float

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.model}"


COLLECTOR_LIBRARY: dict[str, CollectorReference] = {
    "SunOptimo 245V": CollectorReference(
        manufacturer="SunOptimo",
        model="245V",
        area_m2=2.32,
        eta0=0.824,
        a1_w_m2_k=2.905,
        a2_w_m2_k2=0.030,
    ),
    "Générique plan vitré": CollectorReference(
        manufacturer="Générique",
        model="Plan vitré",
        area_m2=2.32,
        eta0=0.750,
        a1_w_m2_k=3.500,
        a2_w_m2_k2=0.015,
    ),
}

DEFAULT_COLLECTOR_NAME = "SunOptimo 245V"


def get_collector_reference(name: str | None) -> CollectorReference:
    if name in COLLECTOR_LIBRARY:
        return COLLECTOR_LIBRARY[str(name)]
    return COLLECTOR_LIBRARY[DEFAULT_COLLECTOR_NAME]

