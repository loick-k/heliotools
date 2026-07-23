from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from itertools import product
import json
from pathlib import Path
from typing import Iterable

from PIL import Image


CIRCUITS = (
    "Circuit autovidangeable",
    "Circuit sous pression",
)
EXCHANGERS = (
    "Échangeur externe au ballon",
    "Échangeur interne au ballon",
)
BACKUP_ENERGIES = (
    "Hydraulique",
    "Électrique",
)
STORAGE_FLUIDS = (
    "Eau chaude sanitaire",
    "Eau technique",
)
BACKUP_TYPES = (
    "Appoint séparé",
    "Appoint intégré",
)
TANK_COUNTS = (
    "1 ballon solaire",
    "2 ballons solaires ou plus",
)
ECS_PRODUCTION_TYPES = (
    "Échangeur à plaques et circulateur",
    "Échangeur serpentin immergé",
)
LOOP_TYPES = (
    "Pas de bouclage sanitaire",
    "Bouclage sanitaire réchauffé par l’appoint",
    "Bouclage sanitaire réchauffé par le solaire ou l’appoint",
)


@dataclass(frozen=True)
class Selection:
    circuit: str = "Circuit sous pression"
    exchanger: str = "Échangeur interne au ballon"
    backup_energy: str = "Électrique"
    storage_fluid: str = "Eau chaude sanitaire"
    backup_type: str = "Appoint séparé"
    tank_count: str = "1 ballon solaire"
    ecs_production: str = "Échangeur serpentin immergé"
    loop_type: str = "Bouclage sanitaire réchauffé par le solaire ou l’appoint"


@dataclass(frozen=True)
class ComponentResult:
    category: str
    requested_code: str
    matched_code: str
    image_path: Path
    valid: bool
    source_row: int


@dataclass(frozen=True)
class DiagramResult:
    selection: Selection
    production: ComponentResult
    storage: ComponentResult
    distribution: ComponentResult

    @property
    def valid(self) -> bool:
        return self.production.valid and self.storage.valid and self.distribution.valid

    @property
    def codes(self) -> dict[str, str]:
        return {
            "production": self.production.requested_code,
            "storage": self.storage.requested_code,
            "distribution": self.distribution.requested_code,
        }


class ComponentCatalog:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        with (self.root / "data" / "components.json").open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        self.source_version = raw["source_version"]
        self.source_date = raw["source_date"]
        self._items: dict[str, dict[str, dict]] = {}
        self._error_items: dict[str, dict] = {}
        for category, rows in raw["components"].items():
            self._items[category] = {}
            for item in rows:
                code = item.get("code") or ""
                normalized = self.normalize(code)
                self._items[category][normalized] = item
                if item.get("is_error"):
                    self._error_items[category] = item

    @staticmethod
    def normalize(value: str) -> str:
        return value.strip().casefold()

    def resolve(self, category: str, requested_code: str) -> ComponentResult:
        item = self._items[category].get(self.normalize(requested_code))
        valid = bool(item and not item.get("is_error"))
        if item is None:
            item = self._error_items[category]
        return ComponentResult(
            category=category,
            requested_code=requested_code,
            matched_code=item.get("code") or "Erreur",
            image_path=self.root / item["image"],
            valid=valid,
            source_row=int(item["row"]),
        )

    def contains(self, category: str, code: str) -> bool:
        item = self._items[category].get(self.normalize(code))
        return bool(item and not item.get("is_error"))


def _loop_suffix(loop_type: str, separator: str = "-") -> str:
    if loop_type == LOOP_TYPES[0]:
        token = "NoBou"
    elif loop_type == LOOP_TYPES[1]:
        token = "BouApp"
    else:
        token = "BouAppSol"
    return f"{separator}{token}"


def build_codes(selection: Selection) -> dict[str, str]:
    exchanger_code = "EE" if selection.exchanger == EXCHANGERS[0] else "EI"
    circuit_code = "DB" if selection.circuit == CIRCUITS[0] else "P"
    energy_code = "AppHydrau" if selection.backup_energy == BACKUP_ENERGIES[0] else "AppElec"

    production = f"Capteur-{exchanger_code}-{circuit_code}-{energy_code}"

    if selection.storage_fluid == STORAGE_FLUIDS[0]:
        fluid_code = "ECS"
    else:
        fluid_code = "ET_PL" if selection.ecs_production == ECS_PRODUCTION_TYPES[0] else "ET_IM"

    tank_code = "1B" if selection.tank_count == TANK_COUNTS[0] else "2B"
    storage_exchanger_code = "NoEch" if selection.exchanger == EXCHANGERS[0] else "EchInt"
    backup_type_code = "AppSep" if selection.backup_type == BACKUP_TYPES[0] else "AppInt"
    storage_energy_code = "Hydrau" if selection.backup_energy == BACKUP_ENERGIES[0] else "Elec"

    storage = (
        f"Sto-{fluid_code}-{tank_code}-{storage_exchanger_code}-"
        f"{backup_type_code}{storage_energy_code}{_loop_suffix(selection.loop_type)}"
    )
    distribution = (
        f"ProdECS_{fluid_code}_{backup_type_code}"
        f"{_loop_suffix(selection.loop_type, separator='_')}"
    )
    return {
        "production": production,
        "storage": storage,
        "distribution": distribution,
    }


def resolve_diagram(selection: Selection, catalog: ComponentCatalog) -> DiagramResult:
    codes = build_codes(selection)
    return DiagramResult(
        selection=selection,
        production=catalog.resolve("production", codes["production"]),
        storage=catalog.resolve("storage", codes["storage"]),
        distribution=catalog.resolve("distribution", codes["distribution"]),
    )


def compose_diagram(result: DiagramResult) -> Image.Image:
    images: list[Image.Image] = []
    for component in (result.production, result.storage, result.distribution):
        with Image.open(component.image_path) as image:
            images.append(image.convert("RGB"))
    width = sum(image.width for image in images)
    height = max(image.height for image in images)
    canvas = Image.new("RGB", (width, height), "white")
    x = 0
    for image in images:
        canvas.paste(image, (x, 0))
        x += image.width
    return canvas


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def configuration_payload(result: DiagramResult, catalog: ComponentCatalog) -> dict:
    return {
        "application": "Schémathèque dynamique solaire thermique — prototype Streamlit",
        "source": {
            "name": "Schémathèque dynamique SOCOL",
            "version": catalog.source_version,
            "date": catalog.source_date,
        },
        "valid": result.valid,
        "selection": asdict(result.selection),
        "codes": result.codes,
        "resolved_components": {
            component.category: {
                "matched_code": component.matched_code,
                "source_row": component.source_row,
                "valid": component.valid,
            }
            for component in (result.production, result.storage, result.distribution)
        },
    }


def all_selections() -> Iterable[Selection]:
    for values in product(
        CIRCUITS,
        EXCHANGERS,
        BACKUP_ENERGIES,
        STORAGE_FLUIDS,
        BACKUP_TYPES,
        TANK_COUNTS,
        ECS_PRODUCTION_TYPES,
        LOOP_TYPES,
    ):
        selection = Selection(*values)
        # The ECS-production field is hidden and irrelevant for direct ECS storage;
        # keep one canonical value to avoid duplicates.
        if selection.storage_fluid == STORAGE_FLUIDS[0] and selection.ecs_production != ECS_PRODUCTION_TYPES[1]:
            continue
        yield selection


def closest_valid_selections(
    selection: Selection,
    catalog: ComponentCatalog,
    limit: int = 5,
) -> list[tuple[int, Selection]]:
    current = asdict(selection)
    ranked: list[tuple[int, Selection]] = []
    for candidate in all_selections():
        result = resolve_diagram(candidate, catalog)
        if not result.valid:
            continue
        candidate_values = asdict(candidate)
        distance = sum(current[key] != candidate_values[key] for key in current)
        ranked.append((distance, candidate))
    ranked.sort(key=lambda item: (item[0], item[1].storage_fluid, item[1].tank_count))
    return ranked[:limit]
