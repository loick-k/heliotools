"""Compatibilité : la bibliothèque capteurs vit dans heliostock.common."""

from __future__ import annotations

from .common.collector_library import (
    COLLECTOR_LIBRARY,
    DEFAULT_COLLECTOR_NAME,
    MANUAL_COLLECTOR_LABEL,
    CollectorReference,
    PacSolarCollectorReference,
    as_heliosolo_capteur_library,
    build_collector_library,
    collector_key,
    collector_names,
    get_heliocop_collector_reference,
    get_collector_reference,
    load_heliocop_collector_library,
    load_pac_solar_collector_xml,
    make_collector_reference,
    validate_collector_reference,
)

__all__ = [
    "COLLECTOR_LIBRARY",
    "DEFAULT_COLLECTOR_NAME",
    "MANUAL_COLLECTOR_LABEL",
    "CollectorReference",
    "PacSolarCollectorReference",
    "as_heliosolo_capteur_library",
    "build_collector_library",
    "collector_key",
    "collector_names",
    "get_heliocop_collector_reference",
    "get_collector_reference",
    "load_heliocop_collector_library",
    "load_pac_solar_collector_xml",
    "make_collector_reference",
    "validate_collector_reference",
]
