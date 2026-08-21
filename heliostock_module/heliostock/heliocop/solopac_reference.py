"""Références techniques importées de SoloPAC 1.1.

Ce module ne réimplémente pas le noyau de calcul SoloPAC. Il lit uniquement les
fichiers XML de caractéristiques mis à disposition avec l'archive SoloPAC 1.1
transmise pour documenter la note d'opportunité HelioCOP.

La matrice dynamique SoloPAC repose sur des interpolations/extrapolations RE2020.
HelioCOP ne reproduit pas ici ces formules. Les valeurs B10/W60 retournées par ce
module sont de simples interpolations linéaires entre les points EN14511 B10/W45
et B10/W65 et sont explicitement présentées comme des repères, pas comme un
résultat SoloPAC.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
import xml.etree.ElementTree as ET

BASE_DIR = Path(__file__).resolve().parent
PAC_DATA_DIR = BASE_DIR / "data" / "pac"
COLLECTOR_DATA_DIR = BASE_DIR / "data" / "capteurs"


@dataclass(frozen=True)
class PacReferencePerformance:
    brand: str
    model: str
    cop_10_45: float
    cop_10_55: float
    cop_10_65: float
    pabs_10_45_kw: float
    pabs_10_55_kw: float
    pabs_10_65_kw: float
    tmin_evaporator_c: float
    tmax_evaporator_c: float
    tmax_condenser_c: float
    evaporator_flow_l_h: float
    condenser_flow_l_h: float
    evaporator_pump_kw: float
    condenser_pump_kw: float

    @property
    def aux_power_kw(self) -> float:
        return self.evaporator_pump_kw + self.condenser_pump_kw

    def linear_reference_at_sink(self, sink_temperature_c: float = 60.0) -> "PacReferencePoint | None":
        """Interpolation linéaire HelioCOP entre points EN14511 disponibles.

        Aucun calcul n'est extrapolé au-delà de la température maximale déclarée
        du condenseur. C'est notamment important pour la Solerpac P50 de la
        gamme P, limitée à 55 °C dans la fiche technique FT1p V3.1.
        """
        sink = float(sink_temperature_c)
        if self.tmax_condenser_c > 0 and sink > self.tmax_condenser_c + 1e-9:
            return None
        points = [
            (45.0, self.cop_10_45, self.pabs_10_45_kw),
            (55.0, self.cop_10_55, self.pabs_10_55_kw),
            (65.0, self.cop_10_65, self.pabs_10_65_kw),
        ]
        valid = [(t, cop, pabs) for t, cop, pabs in points if cop > 0 and pabs > 0]
        if not valid:
            return None
        for t, cop, pabs in valid:
            if abs(sink - t) <= 1e-9:
                thermal = cop * pabs
                system_cop = thermal / (pabs + self.aux_power_kw) if pabs + self.aux_power_kw > 0 else 0.0
                return PacReferencePoint(10.0, sink, cop, pabs, thermal, self.aux_power_kw, system_cop)
        lower = [p for p in valid if p[0] < sink]
        upper = [p for p in valid if p[0] > sink]
        if not lower or not upper:
            return None
        x0, cop0, pabs0 = max(lower, key=lambda p: p[0])
        x1, cop1, pabs1 = min(upper, key=lambda p: p[0])
        ratio = (sink - x0) / (x1 - x0)
        cop = cop0 + ratio * (cop1 - cop0)
        pabs = pabs0 + ratio * (pabs1 - pabs0)
        thermal = max(0.0, cop * pabs)
        system_cop = thermal / (pabs + self.aux_power_kw) if pabs + self.aux_power_kw > 0 else 0.0
        return PacReferencePoint(
            source_temperature_c=10.0,
            sink_temperature_c=sink,
            cop_machine=cop,
            absorbed_power_kw=pabs,
            thermal_power_kw=thermal,
            auxiliary_power_kw=self.aux_power_kw,
            cop_including_pumps=system_cop,
        )



@dataclass(frozen=True)
class PacReferencePoint:
    source_temperature_c: float
    sink_temperature_c: float
    cop_machine: float
    absorbed_power_kw: float
    thermal_power_kw: float
    auxiliary_power_kw: float
    cop_including_pumps: float


@dataclass(frozen=True)
class CollectorReference:
    brand: str
    model: str
    collector_type: str
    unit_area_m2: float
    eta0: float
    a1_w_m2_k: float
    a2_w_m2_k2: float
    a3_j_m3_k: float
    a4: float
    a5_j_m2_k: float
    a6_s_m: float
    certification: str = ""


@dataclass(frozen=True)
class CollectorRounding:
    reference: CollectorReference
    target_surface_m2: float
    collector_count: int
    installed_surface_m2: float
    excess_surface_m2: float


def _xml_values(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {child.tag: (child.text or "").strip() for child in root}


def _xml_file(base_dir: Path, xml_filename: str | None) -> Path | None:
    """Retourne un fichier XML exploitable, jamais un dossier.

    Certaines entrées du catalogue (notamment la Solerpac P25) n'ont pas de
    fichier XML SoloPAC associé. Avec un nom vide, ``base_dir / ""`` pointe
    vers le dossier lui-même : ``Path.exists()`` vaut alors True et
    ``ElementTree.parse`` tente d'ouvrir le dossier, ce qui déclenche un
    PermissionError sous Windows.
    """
    if not xml_filename:
        return None
    candidate = base_dir / str(xml_filename)
    if not candidate.is_file() or candidate.suffix.lower() != ".xml":
        return None
    return candidate


def _f(values: dict[str, str], key: str) -> float:
    raw = values.get(key, "")
    return float(raw) if raw else 0.0


def load_pac_reference(xml_filename: str | None) -> PacReferencePerformance | None:
    path = _xml_file(PAC_DATA_DIR, xml_filename)
    if path is None:
        return None
    try:
        values = _xml_values(path)
    except (OSError, ET.ParseError):
        return None
    cop45 = _f(values, "COP10_45")
    cop55 = _f(values, "COP10_55")
    cop65 = _f(values, "COP10_65")
    p45 = _f(values, "PAbs10_45")
    p55 = _f(values, "PAbs10_55")
    p65 = _f(values, "PAbs10_65")
    if cop45 <= 0 or p45 <= 0:
        return None
    return PacReferencePerformance(
        brand=values.get("Marque_PAC", ""),
        model=values.get("Modele_PAC", ""),
        cop_10_45=cop45,
        cop_10_55=cop55,
        cop_10_65=cop65,
        pabs_10_45_kw=p45,
        pabs_10_55_kw=p55,
        pabs_10_65_kw=p65,
        tmin_evaporator_c=_f(values, "TminEvaporateur"),
        tmax_evaporator_c=_f(values, "TmaxEvaporateur"),
        tmax_condenser_c=_f(values, "TmaxCondenseur"),
        evaporator_flow_l_h=_f(values, "DebitNomEvaporateur"),
        condenser_flow_l_h=_f(values, "DebitNomCondenseur"),
        evaporator_pump_kw=_f(values, "PCirculateurEvaporateur"),
        condenser_pump_kw=_f(values, "PCirculateurCondenseur"),
    )


def load_collector_reference(xml_filename: str | None) -> CollectorReference | None:
    path = _xml_file(COLLECTOR_DATA_DIR, xml_filename)
    if path is None:
        return None
    try:
        values = _xml_values(path)
    except (OSError, ET.ParseError):
        return None
    area = _f(values, "Scapt_Uni")
    if area <= 0:
        return None
    return CollectorReference(
        brand=values.get("Marque_Capteur", ""),
        model=values.get("Modele_Capteur", ""),
        collector_type=values.get("Type_Capteur", ""),
        unit_area_m2=area,
        eta0=_f(values, "Coef_eta0"),
        a1_w_m2_k=_f(values, "Coef_a1"),
        a2_w_m2_k2=_f(values, "Coef_a2"),
        a3_j_m3_k=_f(values, "Coef_a3"),
        a4=_f(values, "Coef_a4"),
        a5_j_m2_k=_f(values, "Coef_a5"),
        a6_s_m=_f(values, "Coef_a6"),
        certification=values.get("Certification_Capteur", ""),
    )


def collector_reference_for_pac_brand(brand: str, source_type: str) -> CollectorReference | None:
    """Référence cohérente avec les exemples SoloPAC fournis.

    Pour les capteurs non vitrés, une référence fabricant est disponible pour
    HelioPAC et Giordano. Pour le PVT, les fichiers SoloPAC fournis contiennent
    deux références Dualsun, indépendantes de la marque de PAC ; aucun modèle
    n'est imposé automatiquement dans HelioCOP.
    """
    if source_type != "Moquette solaire":
        return None
    normalized = brand.strip().lower()
    if normalized == "heliopac":
        return load_collector_reference("HeliopacSolpool.xml")
    if normalized == "giordano":
        return load_collector_reference("GiordanoCapteur4N.xml")
    return None


def available_pvt_references() -> tuple[CollectorReference, ...]:
    refs = []
    for name in ("DualsunDSTI425-108.xml", "DualsunDSTN425-108.xml"):
        ref = load_collector_reference(name)
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def round_collector_surface(target_surface_m2: float, reference: CollectorReference) -> CollectorRounding:
    target = max(0.0, float(target_surface_m2))
    count = max(0, int(ceil(target / reference.unit_area_m2 - 1e-12)))
    installed = count * reference.unit_area_m2
    return CollectorRounding(
        reference=reference,
        target_surface_m2=target,
        collector_count=count,
        installed_surface_m2=installed,
        excess_surface_m2=max(0.0, installed - target),
    )


def solopac_indicators(*, q_pac_mwh: float, q_appoint_mwh: float, w_pac_mwh: float) -> tuple[float, float, float]:
    """Calcule FSAV, COP moyen et FPAC selon le livret SOCOL PAC Solaire ECS2."""
    q_pac = max(0.0, float(q_pac_mwh))
    q_appoint = max(0.0, float(q_appoint_mwh))
    w_pac = max(0.0, float(w_pac_mwh))
    total_heat = q_pac + q_appoint
    fsav = 1.0 - (w_pac + q_appoint) / total_heat if total_heat > 0 else 0.0
    cop = q_pac / w_pac if w_pac > 0 else 0.0
    fpac = q_pac / total_heat if total_heat > 0 else 0.0
    return fsav, cop, fpac
