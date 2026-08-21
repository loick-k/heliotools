"""Topologies fonctionnelles explicites HelioCOP."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class ApplicationTopology(str, Enum):
    ECS1 = "ECS1"
    ECS2 = "ECS2"


class StorageLayout(str, Enum):
    SINGLE_ZONED_TANK = "single_zoned_tank"
    TWO_TANKS = "two_tanks"
    SERIES_TANKS = "series_tanks"


class ChargeInterface(str, Enum):
    DIRECT = "direct"
    EXTERNAL_HX = "external_hx"
    INTERNAL_COIL = "internal_coil"


class BackupPlacement(str, Enum):
    DOWNSTREAM = "downstream"
    UPPER_ZONE = "upper_zone"
    SEPARATE = "separate"


class BouclageMode(str, Enum):
    DOWNSTREAM_BACKUP = "downstream_backup"
    HEAT_PUMP = "heat_pump"
    SEPARATE = "separate"
    NONE = "none"


@dataclass(frozen=True)
class TopologyConfig:
    application_topology: ApplicationTopology = ApplicationTopology.ECS1
    storage_layout: StorageLayout = StorageLayout.SINGLE_ZONED_TANK
    charge_interface: ChargeInterface = ChargeInterface.DIRECT
    backup_placement: BackupPlacement = BackupPlacement.DOWNSTREAM
    bouclage_mode: BouclageMode = BouclageMode.DOWNSTREAM_BACKUP
