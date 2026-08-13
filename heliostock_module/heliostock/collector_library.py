"""Compatibilité : la bibliothèque capteurs vit dans heliostock.common."""

from __future__ import annotations

from .common.collector_library import (
    COLLECTOR_LIBRARY,
    DEFAULT_COLLECTOR_NAME,
    MANUAL_COLLECTOR_LABEL,
    CollectorReference,
    as_heliosolo_capteur_library,
    build_collector_library,
    collector_key,
    collector_names,
    get_collector_reference,
    make_collector_reference,
    validate_collector_reference,
)

__all__ = [
    "COLLECTOR_LIBRARY",
    "DEFAULT_COLLECTOR_NAME",
    "MANUAL_COLLECTOR_LABEL",
    "CollectorReference",
    "as_heliosolo_capteur_library",
    "build_collector_library",
    "collector_key",
    "collector_names",
    "get_collector_reference",
    "make_collector_reference",
    "validate_collector_reference",
]
