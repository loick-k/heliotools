"""Erreurs métier explicites du noyau HelioCOP V2.

Aucune donnée fabricant manquante ne doit être remplacée silencieusement par
une hypothèse générique dans les calculs produit.
"""

class HelioCopError(Exception):
    code = "HELIOCOP_ERROR"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)


class MissingHeatPumpMapError(HelioCopError):
    code = "MISSING_HP_MAP"


class OutsideHeatPumpMapError(HelioCopError):
    code = "OUTSIDE_HP_MAP"


class UnknownTemperatureConventionError(HelioCopError):
    code = "UNKNOWN_TEMPERATURE_CONVENTION"


class MissingHeatPumpAuxiliaryDataError(HelioCopError):
    code = "MISSING_HP_AUXILIARY_DATA"


class MissingCollectorDataError(HelioCopError):
    code = "MISSING_COLLECTOR_DATA"


class WISCSchemaUnverifiedError(HelioCopError):
    code = "WISC_SCHEMA_UNVERIFIED"


class OutsideCollectorValidityError(HelioCopError):
    code = "OUTSIDE_COLLECTOR_VALIDITY"


class Invalid8760ProfileError(HelioCopError):
    code = "INVALID_8760_PROFILE"


class NonCyclicAnnualStateError(HelioCopError):
    code = "NON_CYCLIC_ANNUAL_STATE"


class UnsupportedHydraulicRuleError(HelioCopError):
    code = "UNSUPPORTED_HYDRAULIC_RULE"
