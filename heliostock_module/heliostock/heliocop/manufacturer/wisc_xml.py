"""Import exhaustif des XML capteur WISC.

Le schéma d'équation n'est volontairement pas deviné : les coefficients sont
catalogués mais le solveur physique doit lever WISC_SCHEMA_UNVERIFIED tant que
la convention normative n'est pas verrouillée.
"""
from __future__ import annotations
from pathlib import Path
import xml.etree.ElementTree as ET

from .schemas import WISCCollectorProduct


def _values(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {child.tag: (child.text or "").strip() for child in root}


def _f(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, ""))
    except (TypeError, ValueError):
        return default


def load_wisc_xml(path: str | Path) -> WISCCollectorProduct:
    path = Path(path)
    values = _values(path)
    coeffs = {"eta0": _f(values, "Coef_eta0")}
    for idx in range(1, 9):
        coeffs[f"a{idx}"] = _f(values, f"Coef_a{idx}")
    kt = {angle: _f(values, f"KT_{angle}") for angle in range(10, 91, 10)}
    kl = {angle: _f(values, f"KL_{angle}") for angle in range(10, 91, 10)}
    return WISCCollectorProduct(
        manufacturer=values.get("Marque_Capteur", "") or "Inconnu",
        model=values.get("Modele_Capteur", "") or path.stem,
        certification=values.get("Certification_Capteur", ""),
        unit_area_m2=_f(values, "Scapt_Uni"),
        coefficients=coeffs,
        Kd=_f(values, "Kd", 1.0),
        KT=kt,
        KL=kl,
        collector_type=values.get("Type_Capteur", ""),
        provenance=f"XML WISC fourni: {path.name}",
        equation_schema="ISO9806_QDT_XML_A1_A8_V1",
        schema_verified=False,
    )
