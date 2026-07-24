from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def load_locations() -> pd.DataFrame:
    data = pd.read_csv(DATA_DIR / "locations.csv", dtype={"department": str})
    return data.sort_values(["department", "city"], kind="stable").reset_index(drop=True)


@lru_cache(maxsize=1)
def load_weather() -> pd.DataFrame:
    data = pd.read_csv(DATA_DIR / "weather_monthly.csv")
    data["month_number"] = data["month_number"].astype(int)
    return data.sort_values(["city", "month_number"], kind="stable").reset_index(drop=True)


def weather_for_city(city: str) -> pd.DataFrame:
    data = load_weather()
    selected = data.loc[data["city"] == city].copy()
    if len(selected) != 12:
        raise ValueError(f"Données météorologiques incomplètes pour {city!r}.")
    return selected.sort_values("month_number").reset_index(drop=True)


def location_from_label(label: str) -> dict[str, object]:
    locations = load_locations()
    selected = locations.loc[locations["label"] == label]
    if selected.empty:
        raise ValueError(f"Localisation inconnue : {label}")
    return selected.iloc[0].to_dict()
