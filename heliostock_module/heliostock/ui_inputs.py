from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .collector_library import COLLECTOR_LIBRARY


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class WeatherStation:
    path: Path
    region: str
    label: str
    latitude_deg: float
    longitude_deg: float


def _station(region: str, label: str, filename: str, latitude_deg: float, longitude_deg: float) -> WeatherStation:
    return WeatherStation(
        path=DATA_DIR / filename,
        region=region,
        label=label,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
    )


DEFAULT_EPW_STATIONS = {
    "Bretagne - Rennes": _station("Bretagne", "Rennes", "FRA_BT_Rennes-St.Jacques.AP.071300_TMYx.zip", 48.0689, -1.7339),
    "Bretagne - Île-de-Batz": _station("Bretagne", "Île-de-Batz", "FRA_BT_Batz.Island.071160_TMYx.zip", 48.75, -4.017),
    "Bretagne - Île-de-Bréhat": _station("Bretagne", "Île-de-Bréhat", "FRA_BT_Brehat.Island.071210_TMYx.zip", 48.85, -3.0),
    "Bretagne - Brest": _station("Bretagne", "Brest", "FRA_BT_Brest.Bretagne.AP.071100_TMYx.zip", 48.45, -4.3833),
    "Bretagne - Brignogan-Plages": _station("Bretagne", "Brignogan-Plages", "FRA_BT_Brignogan-Plages.071070_TMYx.zip", 48.6644, -4.3266),
    "Bretagne - Dinard": _station("Bretagne", "Dinard", "FRA_BT_Dinard-Bretagne.AP.071250_TMYx.zip", 48.5889, -2.0758),
    "Bretagne - Cancale": _station("Bretagne", "Cancale", "FRA_BT_Grouin.de.Cancale.071270_TMYx.zip", 48.705, -1.8487),
    "Bretagne - Île de Groix": _station("Bretagne", "Île de Groix", "FRA_BT_Ile.de.Groix.072030_TMYx.zip", 47.6522, -3.5022),
    "Bretagne - Landivisiau": _station("Bretagne", "Landivisiau", "FRA_BT_Landivisiau.AB.071060_TMYx.zip", 48.5256, -4.1472),
    "Bretagne - Lannion": _station("Bretagne", "Lannion", "FRA_BT_Lannion.AP.071180_TMYx.zip", 48.7553, -3.4686),
    "Bretagne - Lanvéoc": _station("Bretagne", "Lanvéoc", "FRA_BT_Lanveoc-Poulmic.AB.071090_TMYx.zip", 48.2794, -4.4394),
    "Bretagne - Ouessant": _station("Bretagne", "Ouessant", "FRA_BT_Le.Stiff-Ouessant.Island.071000_TMYx.zip", 48.4733, -5.057),
    "Bretagne - Lorient": _station("Bretagne", "Lorient", "FRA_BT_Lorient.Bretagne.Sud.AP.072050_TMYx.zip", 47.7628, -3.4356),
    "Bretagne - Morlaix": _station("Bretagne", "Morlaix", "FRA_BT_Morlaix-Ploujean.AP.071604_TMYx.zip", 48.603, -3.816),
    "Bretagne - Perros-Guirec": _station("Bretagne", "Perros-Guirec", "FRA_BT_Ploumanach-Perros-Guirec.071170_TMYx.zip", 48.8258, -3.4731),
    "Bretagne - Penmarc'h": _station("Bretagne", "Penmarc'h", "FRA_BT_Point.de.Penmarch.072000_TMYx.2011-2025.zip", 47.8, -4.367),
    "Bretagne - Camaret-sur-Mer": _station("Bretagne", "Camaret-sur-Mer", "FRA_BT_Pointe.de.Toulinguet.071040_TMYx.zip", 48.2793, -4.6212),
    "Bretagne - Pointe du Raz": _station("Bretagne", "Pointe du Raz", "FRA_BT_Pointe.du.Raz.071030_TMYx.zip", 48.0381, -4.7309),
    "Bretagne - Belle-Île-en-Mer": _station("Bretagne", "Belle-Île-en-Mer", "FRA_BT_Pointe.du.Talut-Belle.Island.072070_TMYx.zip", 47.2944, -3.2183),
    "Bretagne - Plougonvelin": _station("Bretagne", "Plougonvelin", "FRA_BT_Pointe.St.Mathieu.071020_TMYx.zip", 48.333, -4.767),
    "Bretagne - Quiberon": _station("Bretagne", "Quiberon", "FRA_BT_Quiberon-Morbihan.AP.072080_TMYx.zip", 47.4799, -3.0998),
    "Bretagne - Quimper": _station("Bretagne", "Quimper", "FRA_BT_Quimper-Cornouaille.AP.072010_TMYx.zip", 47.9728, -4.1606),
    "Bretagne - Rostrenen": _station("Bretagne", "Rostrenen", "FRA_BT_Rostrenen.071190_TMYx.zip", 48.233, -3.3),
    "Bretagne - Saint-Brieuc": _station("Bretagne", "Saint-Brieuc", "FRA_BT_St.Brieuc-Armor.AP.071200_TMYx.zip", 48.5347, -2.8519),
    "Bretagne - Vannes": _station("Bretagne", "Vannes", "FRA_BT_Vannes.Sene.072100_TMYx.zip", 47.6, -2.717),
    "Pays de la Loire - Angers": _station("Pays de la Loire", "Angers", "FRA_PL_Angers.Loire.AP.073901_TMYx.zip", 47.56, -0.312),
    "Pays de la Loire - Beaucouzé": _station("Pays de la Loire", "Beaucouzé", "FRA_PL_Beaucouze.072300_TMYx.zip", 47.4789, -0.6144),
    "Pays de la Loire - La Roche-sur-Yon": _station("Pays de la Loire", "La Roche-sur-Yon", "FRA_PL_La.Roche.sur.Yon-Les.Ajoncs.AP.073060_TMYx.zip", 46.7056, -1.3817),
    "Pays de la Loire - Laval": _station("Pays de la Loire", "Laval", "FRA_PL_Laval-Etrammes.AP.071340_TMYx.zip", 48.0306, -0.7464),
    "Pays de la Loire - Le Mans": _station("Pays de la Loire", "Le Mans", "FRA_PL_Le.Mans.Arnage.AP.072350_TMYx.zip", 47.9408, 0.1897),
    "Pays de la Loire - Nantes": _station("Pays de la Loire", "Nantes", "FRA_PL_Nantes.Atlantique.AP.072220_TMYx.zip", 47.15, -1.6089),
    "Pays de la Loire - Saint-Nazaire - Chemoulin": _station("Pays de la Loire", "Saint-Nazaire - Chemoulin", "FRA_PL_Pointe.de.Chemoulin.072160_TMYx.zip", 47.2342, -2.2986),
    "Pays de la Loire - Île de Ré": _station("Pays de la Loire", "Île de Ré", "FRA_PL_Pointe.Des.Baleines.073110_TMYx.zip", 46.2437, -1.5605),
    "Pays de la Loire - Saint-Nazaire - Montoir": _station("Pays de la Loire", "Saint-Nazaire - Montoir", "FRA_PL_St.Nazaire-Montoir.AP.072170_TMYx.zip", 47.3139, -2.1544),
    "Pays de la Loire - Île d'Yeu": _station("Pays de la Loire", "Île d'Yeu", "FRA_PL_St.Sauveur-d-Yeu.Island.073000_TMYx.zip", 46.6936, -2.3303),
}

WEATHER_STATION_LABEL_ALIASES = {
    "Rennes - St Jacques": "Rennes",
    "Batz Island": "Île-de-Batz",
    "Brehat Island": "Île-de-Bréhat",
    "Brest Bretagne": "Brest",
    "Dinard Bretagne": "Dinard",
    "Grouin de Cancale": "Cancale",
    "Ile de Groix": "Île de Groix",
    "Lanveoc Poulmic": "Lanvéoc",
    "Le Stiff - Ouessant": "Ouessant",
    "Lorient Bretagne Sud": "Lorient",
    "Morlaix Ploujean": "Morlaix",
    "Ploumanach - Perros-Guirec": "Perros-Guirec",
    "Point de Penmarch": "Penmarc'h",
    "Pointe de Toulinguet": "Camaret-sur-Mer",
    "Pointe du Talut - Belle-Ile": "Belle-Île-en-Mer",
    "Pointe St Mathieu": "Plougonvelin",
    "Quiberon Morbihan": "Quiberon",
    "Quimper Cornouaille": "Quimper",
    "St Brieuc Armor": "Saint-Brieuc",
    "Vannes Sene": "Vannes",
    "Angers Loire": "Angers",
    "Beaucouze": "Beaucouzé",
    "La Roche sur Yon - Les Ajoncs": "La Roche-sur-Yon",
    "Laval Etrammes": "Laval",
    "Le Mans Arnage": "Le Mans",
    "Nantes Atlantique": "Nantes",
    "Pointe de Chemoulin": "Saint-Nazaire - Chemoulin",
    "Pointe des Baleines": "Île de Ré",
    "St Nazaire Montoir": "Saint-Nazaire - Montoir",
    "St Sauveur d'Yeu": "Île d'Yeu",
}
DEFAULT_EPW_REGIONS = {
    region: {
        station.label: station
        for station in DEFAULT_EPW_STATIONS.values()
        if station.region == region
    }
    for region in ["Bretagne", "Pays de la Loire"]
}

@dataclass(frozen=True)
class FixedSolarAssumptions:
    system_efficiency: float = 0.90
    daily_buffer_charge_factor_ht: float = 1.0
    daily_buffer_l_per_m2: float = 60.0
    daily_buffer_tank_count: int = 1
    daily_buffer_insulation_thickness_cm: float = 10.0
    daily_buffer_insulation_lambda_w_m_k: float = 0.035
    solar_buffer_hx_approach_k: float = 5.0
    solar_buffer_collector_approach_k: float = 10.0

    def to_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                ("Rendement hydraulique global", self.system_efficiency, "-"),
                ("Facteur charge ballon solaire", self.daily_buffer_charge_factor_ht, "-"),
                ("Modèle pertes ballon", "SOLO2018 détaillé", "-"),
                ("Nombre de ballons", self.daily_buffer_tank_count, "-"),
                ("Épaisseur isolant ballon", self.daily_buffer_insulation_thickness_cm, "cm"),
                ("Lambda isolant ballon", self.daily_buffer_insulation_lambda_w_m_k, "W/m/K"),
                ("Approche echangeur ballon-process", self.solar_buffer_hx_approach_k, "K"),
                ("Approche capteur sur ballon", self.solar_buffer_collector_approach_k, "K"),
            ],
            columns=["Hypothese", "Valeur", "Unite"],
        )


@dataclass(frozen=True)
class FixedGeoAssumptions:
    air_target_bt_c: float = 25.0
    condenser_approach_k: float = 2.0
    evaporator_approach_k: float = 3.0
    carnot_efficiency: float = 0.54
    cop_min: float = 2.0
    cop_max: float = 8.0
    t_initial_c: float = 12.0
    t_min_c: float = -3.0
    t_max_c: float = 40.0
    gmi_t_min_c: float = -3.0
    gmi_t_max_c: float = 40.0
    gmi_check_enabled: bool = True
    spacing_m: float = 10.0
    ground_conductivity_w_m_k: float = 2.5
    ground_diffusivity_m2_s: float = 1.0e-6
    borehole_radius_m: float = 0.075
    borehole_buried_depth_m: float = 4.0
    borehole_thermal_resistance_m_k_w: float = 0.10
    predesign_power_ratio_w_m: float = 50.0
    predesign_energy_ratio_kwh_m_year: float = 100.0
    extraction_warning_w_m: float = 50.0
    extraction_strong_warning_w_m: float = 60.0
    injection_warning_w_m: float = 60.0
    injection_strong_warning_w_m: float = 80.0
    max_extraction_w_m: float = 70.0
    max_injection_w_m: float = 80.0
    safety_factor: float = 1.20
    reduced_borefield_safety_factor: float = 1.10
    aux_pac_ratio: float = 0.15
    standby_power_kw: float = 0.05

    @property
    def probe_power_ratio_w_m(self) -> float:
        return self.predesign_power_ratio_w_m

    @property
    def max_extraction_kwh_per_m_year(self) -> float:
        return self.predesign_energy_ratio_kwh_m_year

    def to_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                ("Air cible BT calcul", self.air_target_bt_c, "°C"),
                ("Approche condenseur calcul", self.condenser_approach_k, "K"),
                ("Approche évaporateur calcul", self.evaporator_approach_k, "K"),
                ("Rendement Carnot calcul", self.carnot_efficiency, "-"),
                ("COP min calcul", self.cop_min, "-"),
                ("COP max calcul", self.cop_max, "-"),
                ("Tsol initial", self.t_initial_c, "°C"),
                ("Tmin source PAC opérationnelle", self.t_min_c, "°C"),
                ("Tmin GMI", self.gmi_t_min_c, "°C"),
                ("Tmax GMI", self.gmi_t_max_c, "°C"),
                ("Critère GMI actif", self.gmi_check_enabled, "-"),
                ("Tmax injection BTES", self.t_max_c, "°C"),
                ("Espacement moyen force", self.spacing_m, "m"),
                ("Conductivité sol", self.ground_conductivity_w_m_k, "W/m.K"),
                ("Diffusivité sol", self.ground_diffusivity_m2_s, "m2/s"),
                ("Rayon forage", self.borehole_radius_m, "m"),
                ("Profondeur enterrée", self.borehole_buried_depth_m, "m"),
                ("Résistance forage Rb_eff", self.borehole_thermal_resistance_m_k_w, "m.K/W"),
                ("Ratio puissance prédimensionnement", self.predesign_power_ratio_w_m, "W/ml"),
                ("Ratio énergie annuelle prédimensionnement", self.predesign_energy_ratio_kwh_m_year, "kWh/ml.an"),
                ("Limite dure extraction simulation", self.max_extraction_w_m, "W/ml"),
                ("Limite dure injection simulation", self.max_injection_w_m, "W/ml"),
                ("Seuil alerte extraction", self.extraction_warning_w_m, "W/ml"),
                ("Seuil alerte forte extraction", self.extraction_strong_warning_w_m, "W/ml"),
                ("Seuil alerte injection", self.injection_warning_w_m, "W/ml"),
                ("Seuil alerte forte injection", self.injection_strong_warning_w_m, "W/ml"),
                ("Facteur sécurité prédimensionnement", self.safety_factor, "-"),
                ("Marge sécurité sondes réduites", self.reduced_borefield_safety_factor, "-"),
                ("Forfait auxiliaires PAC/géothermie", self.aux_pac_ratio, "part élec compresseur"),
                ("Veille/régulation PAC", self.standby_power_kw, "kW"),
            ],
            columns=["Hypothèse", "Valeur", "Unité"],
        )


@dataclass(frozen=True)
class FixedEconomicsAssumptions:
    analysis_years: int = 20
    other_public_aid_eur: float = 0.0
    ademe_eur_mwh_year: float = 63.0

    def p4_table(self) -> pd.DataFrame:
        df = pd.DataFrame(
            [
                ("Duree d'analyse", self.analysis_years, "ans"),
                ("Autres aides publiques", self.other_public_aid_eur, "EUR"),
                ("Aide ADEME forfaitaire solaire thermique", self.ademe_eur_mwh_year, "EUR/MWh.an"),
                ("CAPEX solaire", "loi surfacique HelioStock", "EUR/m2"),
                ("CAPEX PAC geothermie", 1460.0, "EUR/kW"),
                ("CAPEX sondes", 100.0, "EUR/ml"),
                ("CAPEX appoint gaz", 200.0, "EUR/kW"),
                ("Aide ADEME geothermie", 50.0, "EUR/MWh.an"),
                ("Plafond aide solaire/geothermie", 65.0, "% CAPEX"),
            ],
            columns=["Hypothese", "Valeur", "Unite"],
        )
        df["Valeur"] = df["Valeur"].astype(str)
        return df

