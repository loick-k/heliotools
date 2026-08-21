from enum import Enum


class HeatPumpDataQuality(str, Enum):
    FULL_NUMERIC_MAP = "FULL_NUMERIC_MAP"
    DIGITIZED_MANUFACTURER_CURVES = "DIGITIZED_MANUFACTURER_CURVES"
    # COP directement numérisé sur courbes fabricant, mais puissance thermique
    # reconstruite à partir d'une courbe partielle et de points fabricant/XML.
    # Autorisé en dynamique V1 uniquement avec avertissement explicite.
    DIGITIZED_COP_WITH_RECONSTRUCTED_POWER = "DIGITIZED_COP_WITH_RECONSTRUCTED_POWER"
    SPARSE_RATED_POINTS = "SPARSE_RATED_POINTS"
    LEGACY_VALIDATION_ONLY = "LEGACY_VALIDATION_ONLY"
    MISSING = "MISSING"

    @property
    def dynamic_allowed(self) -> bool:
        return self in {
            HeatPumpDataQuality.FULL_NUMERIC_MAP,
            HeatPumpDataQuality.DIGITIZED_MANUFACTURER_CURVES,
            HeatPumpDataQuality.DIGITIZED_COP_WITH_RECONSTRUCTED_POWER,
        }

    @property
    def predim_allowed(self) -> bool:
        return self not in {HeatPumpDataQuality.MISSING, HeatPumpDataQuality.LEGACY_VALIDATION_ONLY}
