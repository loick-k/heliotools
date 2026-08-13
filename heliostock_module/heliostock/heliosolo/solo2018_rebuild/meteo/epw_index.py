from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.request import urlopen


FRA_INDEX_URL = (
    "https://climate.onebuilding.org/WMO_Region_6_Europe/FRA_France/index.html"
)


@dataclass
class EpwStation:
    city: str
    region_code: str
    wmo_code: str
    epw_url: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def fetch_epw_catalog_for_regions(region_codes: tuple[str, ...] = ("BT", "PL")) -> list[EpwStation]:
    """
    Extrait les fichiers météo EPW France pour des régions ciblées.

    Exemples de `region_codes`:
    - "BT" (Bretagne)
    - "PL" (Pays de la Loire)
    """
    with urlopen(FRA_INDEX_URL, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    parser = _LinkParser()
    parser.feed(html)

    stations: list[EpwStation] = []
    for href in parser.links:
        # Exemple attendu:
        # FRA_BT_Rennes.071300_TMYx.2007-2021.zip
        if not href.endswith(".zip"):
            continue
        if not href.startswith("FRA_"):
            continue

        match = re.match(
            r"FRA_([A-Z]{2})_([A-Za-z0-9\-]+)\.([0-9]{6})_TMYx\.[0-9\-]+\.zip$",
            href,
        )
        if not match:
            continue

        region_code, city_raw, wmo_code = match.groups()
        if region_code not in region_codes:
            continue

        city = city_raw.replace("-", " ")
        epw_url = f"https://climate.onebuilding.org/WMO_Region_6_Europe/FRA_France/{href}"
        stations.append(
            EpwStation(
                city=city,
                region_code=region_code,
                wmo_code=wmo_code,
                epw_url=epw_url,
            )
        )

    stations.sort(key=lambda x: (x.region_code, x.city))
    return stations



