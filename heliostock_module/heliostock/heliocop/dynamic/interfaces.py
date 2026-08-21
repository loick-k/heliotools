"""Interfaces minimales du futur solveur dynamique ECS1/ECS2.

La V1 code les contrats sans activer un modèle WISC dont le schéma normatif
n'est pas encore verrouillé.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from ..domain.errors import WISCSchemaUnverifiedError
from ..manufacturer.schemas import WISCCollectorProduct


@dataclass(frozen=True)
class Weather8760:
    frame: pd.DataFrame

    def validate(self) -> None:
        required = {"G_POA_Wm2", "T_amb_C", "wind_ms"}
        missing = required - set(self.frame.columns)
        if missing:
            raise ValueError(f"Météo incomplète : {sorted(missing)}")
        if len(self.frame) != 8760:
            raise ValueError(f"Météo V1 : 8760 lignes requises, {len(self.frame)} détectées.")


class WISCCollectorModel:
    def __init__(self, product: WISCCollectorProduct) -> None:
        self.product = product

    def evaluate(self, **_: float) -> float:
        if not self.product.schema_verified:
            raise WISCSchemaUnverifiedError(
                f"{self.product.manufacturer} {self.product.model}: schéma a1...a8 non verrouillé."
            )
        raise NotImplementedError("Solveur WISC physique à implémenter après validation du schéma normatif.")
