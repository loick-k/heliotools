from __future__ import annotations

import re

import pandas as pd


def to_float(value):
    """Extrait un nombre flottant d'une chaîne du type '5 000 L' ou '45%'."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d[\d\s]*(?:[.,]\d+)?", str(value))
    if not match:
        return None
    cleaned = match.group(0).replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def to_year(value):
    """Extrait une année à 4 chiffres (19xx ou 20xx) d'une chaîne."""
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def join_values(value):
    """Uniformise les valeurs de type liste (lookups) en chaîne lisible."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else None
    return value


def group_small_categories(
    counts: pd.DataFrame, label_col: str, value_col: str, seuil_pct: float = 3.0
) -> pd.DataFrame:
    """Regroupe les petites catégories pour éviter les graphiques illisibles."""
    total = counts[value_col].sum()
    if total == 0 or counts.empty:
        return counts
    counts = counts.copy()
    counts["_pct"] = counts[value_col] / total * 100
    principales = counts[counts["_pct"] >= seuil_pct][[label_col, value_col]]
    petites = counts[counts["_pct"] < seuil_pct]
    if not petites.empty:
        ligne_autres = pd.DataFrame(
            {label_col: ["Autres"], value_col: [petites[value_col].sum()]}
        )
        if principales.empty:
            principales = ligne_autres
        else:
            principales = pd.concat([principales, ligne_autres], ignore_index=True)
    return principales.sort_values(value_col, ascending=False)

