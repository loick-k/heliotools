"""Règles COSTIC/SOCOL rattachées explicitement à leur topologie."""
from __future__ import annotations
from dataclasses import dataclass

from ..domain.errors import UnsupportedHydraulicRuleError
from ..domain.topology import ApplicationTopology, ChargeInterface
from ..model import costic_pecs_kw, costic_pac_min_kw


@dataclass(frozen=True)
class CosticSizingReference:
    topology: ApplicationTopology
    charge_interface: ChargeInterface
    pecs_kw: float
    pac_min_kw: float
    source: str
    warning: str = ""


def costic_reference(
    *,
    topology: ApplicationTopology,
    charge_interface: ChargeInterface,
    standard_dwellings: int,
    storage_volume_l: float,
    loop_loss_power_kw: float = 0.0,
) -> CosticSizingReference:
    if topology != ApplicationTopology.ECS2:
        raise UnsupportedHydraulicRuleError(
            "La relation COSTIC actuelle de HelioCOP est documentée pour ECS2, pas pour ECS1."
        )
    if charge_interface != ChargeInterface.DIRECT:
        raise UnsupportedHydraulicRuleError(
            "V1 : formule validée uniquement pour la charge directe / stratification dynamique. "
            "Les échangeurs externe/interne seront intégrés avec leurs abaques dédiés."
        )
    pecs = costic_pecs_kw(standard_dwellings, storage_volume_l)
    return CosticSizingReference(
        topology=topology,
        charge_interface=charge_interface,
        pecs_kw=pecs,
        pac_min_kw=costic_pac_min_kw(pecs, loop_loss_power_kw),
        source="COSTIC + adaptation SOCOL PAC solaire ECS2",
        warning="À confirmer par simulation dynamique ; ne pas extrapoler hors domaine des abaques.",
    )
