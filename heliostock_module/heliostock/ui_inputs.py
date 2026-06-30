from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_NANTES_EPW_ZIP = DATA_DIR / "FRA_PL_Nantes.Atlantique.AP.072220_TMYx.zip"
DEFAULT_ANGERS_EPW_ZIP = DATA_DIR / "FRA_PL_Angers.Loire.AP.073901_TMYx.zip"
DEFAULT_EPW_STATIONS = {
    "Nantes": DEFAULT_NANTES_EPW_ZIP,
    "Angers": DEFAULT_ANGERS_EPW_ZIP,
}

COLLECTOR_LIBRARY = {
    "SunOptimo 245V": {
        "manufacturer": "SunOptimo",
        "model": "245V",
        "eta0": 0.824,
        "a1_w_m2_k": 2.905,
        "a2_w_m2_k2": 0.030,
    },
    "Generique plan vitré": {
        "manufacturer": "Générique",
        "model": "Plan vitré",
        "eta0": 0.750,
        "a1_w_m2_k": 3.500,
        "a2_w_m2_k2": 0.015,
    },
}


@dataclass(frozen=True)
class FixedSolarAssumptions:
    system_efficiency: float = 0.90
    daily_buffer_charge_factor_ht: float = 1.0
    daily_buffer_l_per_m2: float = 60.0
    daily_buffer_loss_pct: float = 2.0
    solar_buffer_hx_approach_k: float = 5.0
    solar_buffer_collector_approach_k: float = 10.0

    def to_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                ("Rendement hydraulique global", self.system_efficiency, "-"),
                ("Facteur charge ballon solaire", self.daily_buffer_charge_factor_ht, "-"),
                ("Volume ballon", self.daily_buffer_l_per_m2, "L/m2 capteur"),
                ("Pertes ballon", self.daily_buffer_loss_pct, "%/jour"),
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
    t_min_c: float = 5.0
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
    probe_power_ratio_w_m: float = 40.0
    max_injection_w_m: float = 40.0
    max_extraction_kwh_per_m_year: float = 60.0
    safety_factor: float = 1.20
    aux_pac_ratio: float = 0.15
    standby_power_kw: float = 0.05

    def to_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                ("Air cible BT calcul", self.air_target_bt_c, "C"),
                ("Approche condenseur calcul", self.condenser_approach_k, "K"),
                ("Approche evaporateur calcul", self.evaporator_approach_k, "K"),
                ("Rendement Carnot calcul", self.carnot_efficiency, "-"),
                ("COP min calcul", self.cop_min, "-"),
                ("COP max calcul", self.cop_max, "-"),
                ("Tsol initial", self.t_initial_c, "C"),
                ("Tmin source PAC operationnelle", self.t_min_c, "C"),
                ("Tmin GMI", self.gmi_t_min_c, "C"),
                ("Tmax GMI", self.gmi_t_max_c, "C"),
                ("Critere GMI actif", self.gmi_check_enabled, "-"),
                ("Tmax injection BTES", self.t_max_c, "C"),
                ("Espacement moyen force", self.spacing_m, "m"),
                ("Conductivite sol", self.ground_conductivity_w_m_k, "W/m.K"),
                ("Diffusivite sol", self.ground_diffusivity_m2_s, "m2/s"),
                ("Rayon forage", self.borehole_radius_m, "m"),
                ("Profondeur enterree", self.borehole_buried_depth_m, "m"),
                ("Resistance forage Rb_eff", self.borehole_thermal_resistance_m_k_w, "m.K/W"),
                ("Puissance lineique extraction max", self.probe_power_ratio_w_m, "W/ml"),
                ("Puissance lineique injection max", self.max_injection_w_m, "W/ml"),
                ("Extraction max annuelle sondes", self.max_extraction_kwh_per_m_year, "kWh/ml.an"),
                ("Facteur securite predimensionnement", self.safety_factor, "-"),
                ("Forfait auxiliaires PAC/geothermie", self.aux_pac_ratio, "part elec compresseur"),
                ("Veille/regulation PAC", self.standby_power_kw, "kW"),
            ],
            columns=["Hypothese", "Valeur", "Unite"],
        )


@dataclass(frozen=True)
class FixedEconomicsAssumptions:
    analysis_years: int = 25
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
