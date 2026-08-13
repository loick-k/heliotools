from __future__ import annotations


from pathlib import Path

try:
    from heliostock.ui_inputs import DEFAULT_EPW_REGIONS
except Exception:  # pragma: no cover - fallback for standalone uses of the SOLO module.
    DEFAULT_EPW_REGIONS = {}


MONTHS = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
DAYS_BY_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _epw_zip_path(label: str, fallback_filename: str) -> str:
    """Resolve HelioSOLO weather files from the shared HelioTools EPW catalog."""

    for stations in DEFAULT_EPW_REGIONS.values():
        station = stations.get(label)
        if station is not None:
            return str(station.path)
    return str(DATA_DIR / fallback_filename)


CITY_EPW_ZIP_PATHS = {
    "Nantes": _epw_zip_path("Nantes", "FRA_PL_Nantes.Atlantique.AP.072220_TMYx.zip"),
    "Rennes": _epw_zip_path("Rennes", "FRA_BT_Rennes-St.Jacques.AP.071300_TMYx.zip"),
    "Brest": _epw_zip_path("Brest", "FRA_BT_Brest.Bretagne.AP.071100_TMYx.zip"),
    "Saint-Brieuc": _epw_zip_path("Saint-Brieuc", "FRA_BT_St.Brieuc-Armor.AP.071200_TMYx.zip"),
    "Vannes": _epw_zip_path("Vannes", "FRA_BT_Vannes.Sene.072100_TMYx.zip"),
    "Angers": _epw_zip_path("Angers", "FRA_PL_Angers.Loire.AP.073901_TMYx.zip"),
    "Laval": _epw_zip_path("Laval", "FRA_PL_Laval-Etrammes.AP.071340_TMYx.zip"),
    "Le Mans": _epw_zip_path("Le Mans", "FRA_PL_Le.Mans.Arnage.AP.072350_TMYx.zip"),
    "La Roche-sur-Yon": _epw_zip_path(
        "La Roche-sur-Yon",
        "FRA_PL_La.Roche.sur.Yon-Les.Ajoncs.AP.073060_TMYx.zip",
    ),
}
NANTES_ZIP_DEFAULT = CITY_EPW_ZIP_PATHS["Nantes"]

CAPTEUR_LIBRARY = {
    "Eklor": {
        "C.SOL 423 EKS": {
            "surface_utile_m2": 2.29,
            "n0": 0.79,
            "a1": 3.88,
            "a2": 0.01,
        }
    },
    "Ellios Technologies": {
        "GK3133": {
            "surface_utile_m2": 12.37,
            "n0": 0.814,
            "a1": 2.102,
            "a2": 0.016,
        }
    },
    "SunOptimo": {
        "245V": {
            "surface_utile_m2": 2.45,
            "n0": 0.852,
            "a1": 3.922,
            "a2": 0.015,
        },
        "DIS150": {
            "surface_utile_m2": 15.5,
            "n0": 0.765,
            "a1": 2.23,
            "a2": 0.008,
        },
    },
    "TVP Solar": {
        "MT power v4": {
            "surface_utile_m2": 1.96,
            "n0": 0.737,
            "a1": 0.504,
            "a2": 0.006,
        }
    },
}

TYPOLOGIE_RATIOS_L_J_UNITE = {
    "Logement collectif": 30.0,
    "EHPAD": 15.0,
    "Hopital": 25.0,
}
LOGEMENT_RATIOS_L_J_LOGEMENT = {
    "Personne seule": 30.0,
    "T1 (1.4 personnes)": 42.0,
    "T2 (1.6 personnes)": 48.0,
    "T3 (2.1 personnes)": 63.0,
    "T4 (2.6 personnes)": 78.0,
    "T5 (2.8 personnes)": 84.0,
    "T6 et plus (3 personnes)": 90.0,
}
HOTELLERIE_RATIOS_L_J_CHAMBRE = {
    "Eco": 30.0,
    "1 & 2 etoiles": 45.0,
    "3 & 4 etoiles": 60.0,
    "5 etoiles et plus": 80.0,
}

RATIOS_POINTE_ECS_MOYENS = {
    "solo2018_defaut": 0.50,
    "logement_collectif_grand": 0.45,
    "logement_collectif_moyen": 0.70,
    "logement_collectif_petit": 1.00,
    "residence_etudiante_fjt": 0.85,
    "hotel_standard": 0.80,
    "hotel_haut_de_gamme": 1.20,
    "residence_hoteliere": 0.65,
    "ehpad_complet_cuisine_lingerie_vaisselle_ecs": 0.60,
    "ehpad_cuisine_lingerie_vaisselle_non_ecs": 0.85,
    "ehpad_cuisine_sans_lingerie_ecs": 0.75,
    "ehpad_sans_cuisine_avec_lingerie": 1.00,
    "ehpad_tres_faible_besoin": 1.40,
    "hopital_etablissement_sante": 0.70,
    "foyer_handicap_fam_foyer_vie": 0.80,
    "restauration_collective_standard": 0.80,
    "cuisine_collective_tres_debitante": 1.10,
    "piscine_douches_seules": 0.80,
    "piscine_avec_renouvellement_bassin": 0.30,
    "gymnase_vestiaires": 1.20,
    "camping_blocs_sanitaires": 1.00,
    "lingerie_dominante": 1.40,
    "process_industriel_regulier": 0.25,
}
RATIOS_POINTE_ECS_LABELS = {
    "solo2018_defaut": "SOLO2018 defaut",
    "logement_collectif_grand": "Logement collectif grand",
    "logement_collectif_moyen": "Logement collectif moyen",
    "logement_collectif_petit": "Logement collectif petit",
    "residence_etudiante_fjt": "Residence etudiante / FJT",
    "hotel_standard": "Hotel standard",
    "hotel_haut_de_gamme": "Hotel haut de gamme",
    "residence_hoteliere": "Residence hoteliere",
    "ehpad_complet_cuisine_lingerie_vaisselle_ecs": "EHPAD complet cuisine/lingerie/vaisselle ECS",
    "ehpad_cuisine_lingerie_vaisselle_non_ecs": "EHPAD cuisine/lingerie/vaisselle non ECS",
    "ehpad_cuisine_sans_lingerie_ecs": "EHPAD cuisine sans lingerie ECS",
    "ehpad_sans_cuisine_avec_lingerie": "EHPAD sans cuisine avec lingerie",
    "ehpad_tres_faible_besoin": "EHPAD tres faible besoin",
    "hopital_etablissement_sante": "Hopital / etablissement de sante",
    "foyer_handicap_fam_foyer_vie": "Foyer handicap / FAM / foyer de vie",
    "restauration_collective_standard": "Restauration collective standard",
    "cuisine_collective_tres_debitante": "Cuisine collective tres debitante",
    "piscine_douches_seules": "Piscine douches seules",
    "piscine_avec_renouvellement_bassin": "Piscine avec renouvellement bassin",
    "gymnase_vestiaires": "Gymnase / vestiaires",
    "camping_blocs_sanitaires": "Camping blocs sanitaires",
    "lingerie_dominante": "Lingerie dominante",
    "process_industriel_regulier": "Process industriel regulier",
}

SOLO_CI_ALGO_DEFAULT = "CorrectionMidi10h"
SOLO_CI_COEFF0_DEFAULT = 1.0
SOLO_CI_COEFF1_DEFAULT = 0.0
SOLO_CI_COEFF3_DEFAULT = -7e-7

SOLO_NANTES_GH_KWH_M2_J = [0.992, 1.735, 3.075, 4.221, 5.052, 5.723, 5.800, 5.001, 3.715, 2.300, 1.304, 0.815]
SOLO_NANTES_CAP_KWH_M2_J = [1.532, 2.441, 3.882, 4.445, 4.778, 5.173, 5.355, 5.073, 4.402, 3.195, 2.112, 1.287]
SOLO_NANTES_DISPO_KWH_M2_J = [1.504, 2.418, 3.864, 4.428, 4.740, 5.113, 5.303, 5.049, 4.387, 3.170, 2.073, 1.252]
SOLO_ANGERS_TEXT_C = [5.7, 7.0, 9.1, 10.6, 14.6, 17.6, 19.4, 20.3, 16.4, 13.4, 8.5, 6.1]
SOLO_STBRIEUC_GH_KWH_M2_J = [0.875, 1.648, 2.796, 4.317, 5.161, 5.694, 5.633, 4.766, 3.492, 2.001, 1.160, 0.744]
SOLO_STBRIEUC_CAP_KWH_M2_J = [1.210, 2.110, 3.062, 4.081, 4.327, 4.534, 4.578, 4.251, 3.630, 2.363, 1.660, 1.095]
SOLO_STBRIEUC_DISPO_KWH_M2_J = [1.091, 1.918, 2.788, 3.684, 3.844, 3.992, 4.039, 3.814, 3.301, 2.148, 1.496, 0.979]
SOLO_STBRIEUC_TEXT_C = [6.7, 7.7, 9.0, 10.0, 13.2, 15.7, 17.5, 18.4, 16.0, 13.3, 9.6, 7.2]

DEFAULT_T_ENV_STOCK_C = 19.0
SOLO2018_T_ENV_STOCK_STRICT_C = 20.0


