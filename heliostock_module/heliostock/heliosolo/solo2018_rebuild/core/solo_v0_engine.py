from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable, Literal, Optional


CP_EAU_WH_L_K = 1.1615
CP_ECS_WH_L_K = CP_EAU_WH_L_K
JOURS_MOIS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
JOUR_REF_MOIS = [15, 45, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
LONG1_BOUCLE_BON_M_PAR_LGT = 6.0
LONG1_BOUCLE_MOYEN_M_PAR_LGT = 9.0
LONG1_BOUCLE_MAUVAIS_M_PAR_LGT = 12.0
KL_BOUCLE_BON_W_M_K = 0.2
KL_BOUCLE_MOYEN_W_M_K = 0.3
KL_BOUCLE_MAUVAIS_W_M_K = 0.4

TypeEchangeur = Literal["externe", "noye", "direct"]
TypeCirculation = Literal["forcee", "thermosiphon"]
TypeBouclage = Literal["aucun_apport", "apport_indirect"]
TypeModeKtPrimaire = Literal["auto_simple", "lineaire"]
TypeModeleStockSolaire = Literal["global", "detaille"]
TypeModePertesBouclage = Literal[
    "aucune",
    "saisie_kwh_j",
    "debit_delta",
    "long_kl",
    "bon",
    "moyen",
    "mauvais",
]
TypeAlgoCorrIncidence = Literal[
    "CorrectionMidi10h",
    "CorrectionMidi",
    "Correction10h",
    "Correction9h",
    "CorrectionMidi9h",
]


@dataclass(frozen=True)
class InstallationSoloV0:
    surface_capteurs_m2: float
    volume_stock_l: float
    b_capteur: float = 0.75
    k_capteur_w_m2_k: float = 4.0
    latitude_deg: float = 47.2
    inclinaison_deg: float = 45.0
    azimut_deg: float = 0.0
    type_circulation: TypeCirculation = "forcee"
    type_echangeur: TypeEchangeur = "externe"
    type_bouclage: TypeBouclage = "aucun_apport"
    pech11_w_m2_k: float = 100.0
    efficacite_regul_forcee: float = 0.90
    efficacite_regul_thermosiphon: float = 0.95
    debit_q1_primaire_force_w_m2_k: float = 40.0
    debit_q1_primaire_thermosiphon_w_m2_k: float = 10.0
    mode_kt_primaire: TypeModeKtPrimaire = "auto_simple"
    long_primaire_m: float = 10.0
    kl_primaire_w_m_k: float = 0.3
    t_ref_primaire_c: float = 60.0
    t_env_primaire_c: float = 20.0
    modele_stock_solaire: TypeModeleStockSolaire = "global"
    cr_stock_wh_l_k_j: float = 0.16
    v1_stock_solaire_l: float = 300.0
    epais_iso_stock_solaire_cm: float = 8.0
    lambda_iso_stock_solaire_w_m_k: float = 0.04
    modele_geometrie_ballon: str = "standard"
    algo_sballon: str = "SOLO2018"
    tmax_stock_c: float = 80.0
    t_env_stock_c: float = 20.0
    mode_pertes_bouclage: TypeModePertesBouclage = "aucune"
    vecs_unite_ref_l_j: float = 100.0
    tref_bouclage_c: float = 55.0
    tenv_bouclage_c: float = 20.0
    debit_bouclage_l_h: float = 0.0
    delta_tmax_bouclage_k: float = 0.0
    long_bouclage_m: float = 0.0
    kl_bouclage_w_m_k: float = 0.0
    long1_boucle_bon_m_par_unite: float = LONG1_BOUCLE_BON_M_PAR_LGT
    long1_boucle_moyen_m_par_unite: float = LONG1_BOUCLE_MOYEN_M_PAR_LGT
    long1_boucle_mauvais_m_par_unite: float = LONG1_BOUCLE_MAUVAIS_M_PAR_LGT
    kl_boucle_bon_w_m_k: float = KL_BOUCLE_BON_W_M_K
    kl_boucle_moyen_w_m_k: float = KL_BOUCLE_MOYEN_W_M_K
    kl_boucle_mauvais_w_m_k: float = KL_BOUCLE_MAUVAIS_W_M_K
    ratio_bouclage_actif: float = 1.0
    appliquer_correction_incidence: bool = False
    # Coeffs de courbe de correction incidence (SOLO style)
    coeff0_ci: float = 1.0
    coeff1_ci: float = 0.0
    coeff3_ci: float = -7e-7
    # SOLO2018 applique par defaut la moyenne 10h + midi
    algo_corr_incidence: TypeAlgoCorrIncidence = "CorrectionMidi10h"
    convertir_cr_stock_en_joules: bool = True


@dataclass(frozen=True)
class MoisSoloV0:
    mois: int
    vecs_l_j: float
    tecs_prod_c: float
    tef_c: float
    text_c: float
    r_global_plan_kwh_m2_j: float
    # If set, bypasses incidence correction and uses this value directly.
    r_disponible_kwh_m2_j_override: Optional[float] = None
    pertes_boucle_kwh_j: float = 0.0
    t_env_stock_c: Optional[float] = None


@dataclass(frozen=True)
class ResultatMoisSoloV0:
    mois: int
    jours: int
    vecs_l_j: float
    besoin_ecs_kwh_j: float
    besoin_ref_kwh_j: float
    besoin_etendu_kwh_j: float
    besoin_total_kwh_j: float
    delta_t_eq_boucle_c: float
    tecs_etendu_c: float
    tef_calc_c: float
    t_ref_calc_c: float
    t_sortie_stock_solaire_c: float
    pertes_stock_solaire_kwh_j: float
    production_primaire_kwh_j: float
    besoin_primaire_kwh_j: float
    prod_cesc_base_kwh_j: float
    delta_t_corr_et_c: float
    prod_cescet_avant_pertes_et_kwh_j: float
    pertes_eau_technique_kwh_j: float
    prod_cescet_finale_kwh_j: float
    r_disponible_kwh_m2_j: float
    efficacite_transfert: float
    kg1_primaire_w_m2_k: float
    production_solaire_kwh_j: float
    production_solaire_kwh_mois: float
    productivite_kwh_m2_mois: float
    taux_couverture_ecs: Optional[float]
    taux_economie_energie: Optional[float]


def calc_s_ballon(
    modele_geometrie_ballon: str,
    algo_sballon: str,
    v_ballon_m3: float,
) -> float:
    # Modele standard: ballon cylindrique vertical, ratio H/D = 2.
    # V = pi/4 * D^2 * H = pi/2 * D^3 => D = (2V/pi)^(1/3)
    if v_ballon_m3 <= 0:
        return 0.0
    d = (2.0 * v_ballon_m3 / math.pi) ** (1.0 / 3.0)
    h = 2.0 * d
    s = math.pi * d * h + (math.pi * d * d / 2.0)  # lateral + 2 fonds
    return max(0.0, s)


def calc_cr_stock_solaire(installation: InstallationSoloV0) -> float:
    if installation.modele_stock_solaire == "global":
        return max(0.0, installation.cr_stock_wh_l_k_j)

    v_ballon_m3 = max(1e-6, installation.v1_stock_solaire_l / 1000.0)
    s_ballon_m2 = calc_s_ballon(
        modele_geometrie_ballon=installation.modele_geometrie_ballon,
        algo_sballon=installation.algo_sballon,
        v_ballon_m3=v_ballon_m3,
    )
    epais_iso_m = max(1e-6, installation.epais_iso_stock_solaire_cm / 100.0)
    lambda_iso = max(1e-6, installation.lambda_iso_stock_solaire_w_m_k)
    r_iso = epais_iso_m / lambda_iso
    hconv = 10.0
    condu_globale_w_k = (1.0 / (r_iso + 1.0 / hconv)) * s_ballon_m2
    cr_base_wh_m3_k_j = condu_globale_w_k * 24.0 / v_ballon_m3
    cr_base_wh_l_k_j = cr_base_wh_m3_k_j / 1000.0
    correction_cr = 1.1 + 0.05 / v_ballon_m3
    return max(0.0, correction_cr * cr_base_wh_l_k_j)


def convertir_eta_a1_a2_vers_b_k(eta0: float, a1: float, a2: float) -> tuple[float, float]:
    phi = 1000.0
    delta_t_values = [10, 20, 30, 40, 50, 60]
    x_values = [dt / phi for dt in delta_t_values]
    y_values = [eta0 - a1 * (dt / phi) - a2 * (dt / phi) ** 2 * phi for dt in delta_t_values]

    n = len(x_values)
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n
    sxx = sum((x - x_mean) ** 2 for x in x_values)
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    if sxx == 0:
        raise ValueError("Regression impossible: variance nulle.")
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    b = intercept
    k = -slope
    return b, k


def angle_incidence_deg(
    latitude_deg: float,
    inclinaison_deg: float,
    azimut_deg: float,
    mois: int,
    heure: float,
) -> float:
    jour_ref = JOUR_REF_MOIS[mois - 1]
    lat = math.radians(latitude_deg)
    beta = math.radians(inclinaison_deg)
    gamma = math.radians(azimut_deg)
    decl = math.radians(23.45) * math.sin(math.radians(0.986 * jour_ref - 80.0))
    omega = math.radians((heure - 12.0) * 15.0)
    cos_i = (
        math.sin(decl) * math.sin(lat) * math.cos(beta)
        - math.sin(decl) * math.cos(lat) * math.sin(beta) * math.cos(gamma)
        + math.cos(decl) * math.cos(lat) * math.cos(beta) * math.cos(omega)
        + math.cos(decl) * math.sin(lat) * math.sin(beta) * math.cos(gamma) * math.cos(omega)
        + math.cos(decl) * math.sin(beta) * math.sin(gamma) * math.sin(omega)
    )
    cos_i = min(1.0, max(-1.0, cos_i))
    return math.degrees(math.acos(cos_i))


def correction_incidence_instantanee(
    angle_deg: float,
    coeff0_ci: float = 1.0,
    coeff1_ci: float = 0.0,
    coeff3_ci: float = -7e-7,
) -> float:
    # SOLO décrit un calcul basé sur l'angle arrondi en degrés.
    angle_int = round(angle_deg)
    corr = coeff0_ci + coeff1_ci * angle_int + coeff3_ci * (angle_int**3)
    return min(1.0, max(0.0, corr))


def correction_incidence_mensuelle(installation: InstallationSoloV0, mois: int) -> float:
    def corr_at(hour: float) -> float:
        angle = angle_incidence_deg(
            installation.latitude_deg,
            installation.inclinaison_deg,
            installation.azimut_deg,
            mois,
            hour,
        )
        return correction_incidence_instantanee(
            angle_deg=angle,
            coeff0_ci=installation.coeff0_ci,
            coeff1_ci=installation.coeff1_ci,
            coeff3_ci=installation.coeff3_ci,
        )

    algo = installation.algo_corr_incidence
    if algo == "CorrectionMidi":
        return corr_at(12.0)
    if algo == "Correction10h":
        return corr_at(10.0)
    if algo == "Correction9h":
        return corr_at(9.0)
    if algo == "CorrectionMidi9h":
        return 0.5 * (corr_at(12.0) + corr_at(9.0))
    # défaut SOLO2018
    return 0.5 * (corr_at(12.0) + corr_at(10.0))


def rayonnement_disponible_kwh_m2_j(installation: InstallationSoloV0, mois: MoisSoloV0) -> float:
    if mois.r_disponible_kwh_m2_j_override is not None:
        return max(0.0, mois.r_disponible_kwh_m2_j_override)
    if not installation.appliquer_correction_incidence:
        return max(0.0, mois.r_global_plan_kwh_m2_j)
    corr = correction_incidence_mensuelle(installation, mois.mois)
    return max(0.0, mois.r_global_plan_kwh_m2_j * corr)


def calcul_kt_primaire_w_k(installation: InstallationSoloV0) -> float:
    if installation.mode_kt_primaire == "auto_simple":
        return 5.0 + 0.5 * installation.surface_capteurs_m2

    # Option lineaire: KtPrimaire = KLprimaire * LongPrimaire
    return max(0.01, installation.kl_primaire_w_m_k * installation.long_primaire_m)


def _calc_kg_bouclage_w_k(
    installation: InstallationSoloV0,
    mois: MoisSoloV0,
    text_min_annuel_c: float,
) -> float:
    mode = installation.mode_pertes_bouclage
    if mode == "aucune":
        return 0.0

    if mode in ("bon", "moyen", "mauvais"):
        if mois.vecs_l_j <= 0:
            return 0.0
        nb_unites_estime = mois.vecs_l_j / max(1e-6, installation.vecs_unite_ref_l_j)
        long1 = {
            "bon": installation.long1_boucle_bon_m_par_unite,
            "moyen": installation.long1_boucle_moyen_m_par_unite,
            "mauvais": installation.long1_boucle_mauvais_m_par_unite,
        }[mode]
        kl = {
            "bon": installation.kl_boucle_bon_w_m_k,
            "moyen": installation.kl_boucle_moyen_w_m_k,
            "mauvais": installation.kl_boucle_mauvais_w_m_k,
        }[mode]
        long_boucle = nb_unites_estime * long1
        return max(0.0, long_boucle * kl)

    if mode == "long_kl":
        return max(0.0, installation.long_bouclage_m * installation.kl_bouclage_w_m_k)

    # mode == "debit_delta"
    text_boucle_min = 0.5 * (text_min_annuel_c + installation.tenv_bouclage_c)
    p_perte_boucle_max_w = (
        installation.debit_bouclage_l_h
        * installation.delta_tmax_bouclage_k
        * CP_EAU_WH_L_K
    )
    denom = max(1e-6, installation.tref_bouclage_c - text_boucle_min)
    return max(0.0, p_perte_boucle_max_w / denom)


def pertes_bouclage_kwh_j(
    installation: InstallationSoloV0,
    mois: MoisSoloV0,
    text_min_annuel_c: float,
) -> float:
    if installation.mode_pertes_bouclage == "saisie_kwh_j":
        return max(0.0, mois.pertes_boucle_kwh_j)

    kg_boucle = _calc_kg_bouclage_w_k(installation, mois, text_min_annuel_c)
    if kg_boucle <= 0:
        return 0.0
    text_boucle = 0.5 * (installation.tenv_bouclage_c + mois.text_c)
    p_perte_boucle_w = kg_boucle * max(0.0, installation.tref_bouclage_c - text_boucle)
    e_perte_boucle_kwh_j = 24.0 * p_perte_boucle_w / 1000.0
    return max(0.0, e_perte_boucle_kwh_j * max(0.0, installation.ratio_bouclage_actif))


def calcul_amont_stock(installation: InstallationSoloV0) -> tuple[float, float]:
    s = installation.surface_capteurs_m2
    if s <= 0:
        raise ValueError("surface capteurs doit etre > 0")

    kt = calcul_kt_primaire_w_k(installation)
    kg1 = installation.k_capteur_w_m2_k + kt / s
    if kg1 <= 0:
        raise ValueError("Kg1Primaire doit etre > 0")

    if installation.type_circulation == "forcee":
        debit_q1 = installation.debit_q1_primaire_force_w_m2_k
        effic_regul = installation.efficacite_regul_forcee
    else:
        debit_q1 = installation.debit_q1_primaire_thermosiphon_w_m2_k
        effic_regul = installation.efficacite_regul_thermosiphon

    pech11 = installation.pech11_w_m2_k
    q_sur_pertes = debit_q1 / kg1

    if installation.type_echangeur == "externe":
        effic_echangeur = pech11 / (debit_q1 + pech11)
        denom_exp = math.expm1(1.0 / q_sur_pertes)
        effic_brute = 0.0 if denom_exp <= 0 else q_sur_pertes / (1.0 / effic_echangeur + 1.0 / denom_exp)
    elif installation.type_echangeur == "noye":
        debit_q_sur_pech = debit_q1 / pech11
        effic_brute = (
            1.0 - 1.0 / (2.0 * q_sur_pertes + 12.0 * q_sur_pertes * debit_q_sur_pech)
        ) / (1.0 + debit_q_sur_pech / q_sur_pertes)
    elif installation.type_echangeur == "direct":
        effic_brute = 1.0 - 1.0 / (2.0 * q_sur_pertes)
    else:
        raise ValueError(f"Type echangeur invalide: {installation.type_echangeur}")

    effic_transfert = effic_regul * min(1.0, max(0.0, effic_brute))
    return kg1, effic_transfert


def besoin_ecs_kwh_j(vecs_l_j: float, tecs_prod_c: float, tef_c: float) -> float:
    return calc_becs_jm(
        vecs_pro_jm_l_j=vecs_l_j,
        tef_m_c=tef_c,
        tecs_ref_m_c=tecs_prod_c,
        cp_ecs_wh_l_k=CP_ECS_WH_L_K,
    )


def calc_becs_jm(
    vecs_pro_jm_l_j: float,
    tef_m_c: float,
    tecs_ref_m_c: float,
    cp_ecs_wh_l_k: float = CP_ECS_WH_L_K,
) -> float:
    if vecs_pro_jm_l_j <= 0:
        return 0.0
    delta_t = tecs_ref_m_c - tef_m_c
    if delta_t <= 0:
        return 0.0
    return cp_ecs_wh_l_k * vecs_pro_jm_l_j * delta_t / 1000.0


def calc_tecs_etendu_m(
    vecs_pro_jm_l_j: float,
    tecs_pro_m_c: float,
    tmax_stock_solaire_c: float,
    eperte_boucle_jm_kwh_j: float,
    cp_ecs_wh_l_k: float = CP_ECS_WH_L_K,
) -> tuple[float, float]:
    if vecs_pro_jm_l_j <= 0 or eperte_boucle_jm_kwh_j <= 0:
        delta_t_eq_boucle_c = 0.0
    else:
        delta_t_eq_boucle_c = (
            1000.0 * eperte_boucle_jm_kwh_j
            / (cp_ecs_wh_l_k * vecs_pro_jm_l_j)
        )
    tecs_etendu_m_c = max(
        tecs_pro_m_c,
        min(
            tmax_stock_solaire_c,
            tecs_pro_m_c + delta_t_eq_boucle_c,
        ),
    )
    return delta_t_eq_boucle_c, tecs_etendu_m_c


def calc_besoin_etendu_solarisable(
    vecs_pro_jm_l_j: float,
    tef_m_c: float,
    tecs_pro_m_c: float,
    tmax_stock_solaire_c: float,
    eperte_boucle_jm_kwh_j: float,
    cp_ecs_wh_l_k: float = CP_ECS_WH_L_K,
) -> dict:
    becs_pro_jm_kwh_j = calc_becs_jm(
        vecs_pro_jm_l_j=vecs_pro_jm_l_j,
        tef_m_c=tef_m_c,
        tecs_ref_m_c=tecs_pro_m_c,
        cp_ecs_wh_l_k=cp_ecs_wh_l_k,
    )
    delta_t_eq_boucle_c, tecs_etendu_m_c = calc_tecs_etendu_m(
        vecs_pro_jm_l_j=vecs_pro_jm_l_j,
        tecs_pro_m_c=tecs_pro_m_c,
        tmax_stock_solaire_c=tmax_stock_solaire_c,
        eperte_boucle_jm_kwh_j=eperte_boucle_jm_kwh_j,
        cp_ecs_wh_l_k=cp_ecs_wh_l_k,
    )
    betendu_jm_kwh_j = calc_becs_jm(
        vecs_pro_jm_l_j=vecs_pro_jm_l_j,
        tef_m_c=tef_m_c,
        tecs_ref_m_c=tecs_etendu_m_c,
        cp_ecs_wh_l_k=cp_ecs_wh_l_k,
    )
    eperte_boucle_jm_kwh_j = max(eperte_boucle_jm_kwh_j, 0.0)
    bth_total_jm_kwh_j = becs_pro_jm_kwh_j + eperte_boucle_jm_kwh_j
    betendu_jm_kwh_j = min(betendu_jm_kwh_j, bth_total_jm_kwh_j)
    return {
        "delta_t_eq_boucle_c": delta_t_eq_boucle_c,
        "tecs_etendu_m_c": tecs_etendu_m_c,
        "becs_pro_jm_kwh_j": becs_pro_jm_kwh_j,
        "betendu_jm_kwh_j": betendu_jm_kwh_j,
        "bth_total_jm_kwh_j": bth_total_jm_kwh_j,
    }


def calc_solo2018_primaire_m(
    tef_m_c: float,
    t_ref_m_c: float,
    t_env_stock_solaire_m_c: float,
    v_stock_solaire_l: float,
    cr_stock_solaire_wh_l_k_j: float,
    bref_jm_kwh_j: float,
    esol_jm_kwh_j: float,
) -> dict:
    """
    Calcule la production solaire primaire SOLO2018.

    Production utile = sortie stock solaire.
    Production primaire = entree stock solaire = utile + pertes stock.
    """
    if bref_jm_kwh_j <= 0 or esol_jm_kwh_j <= 0:
        return {
            "t_sortie_stock_solaire_c": tef_m_c,
            "pertes_stock_solaire_kwh_j": 0.0,
            "production_primaire_kwh_j": 0.0,
            "besoin_primaire_kwh_j": 0.0,
        }

    taux_ref = max(0.0, min(esol_jm_kwh_j / bref_jm_kwh_j, 1.5))
    t_sortie_stock_solaire_c = tef_m_c + (t_ref_m_c - tef_m_c) * taux_ref

    pertes_stock_solaire_kwh_j = (
        max(0.0, t_sortie_stock_solaire_c - t_env_stock_solaire_m_c)
        * v_stock_solaire_l
        * cr_stock_solaire_wh_l_k_j
        / 1000.0
    )
    production_primaire_kwh_j = esol_jm_kwh_j + pertes_stock_solaire_kwh_j

    pertes_ref_stock_solaire_kwh_j = (
        max(0.0, t_ref_m_c - t_env_stock_solaire_m_c)
        * v_stock_solaire_l
        * cr_stock_solaire_wh_l_k_j
        / 1000.0
    )
    besoin_primaire_kwh_j = bref_jm_kwh_j + pertes_ref_stock_solaire_kwh_j

    return {
        "t_sortie_stock_solaire_c": t_sortie_stock_solaire_c,
        "pertes_stock_solaire_kwh_j": pertes_stock_solaire_kwh_j,
        "production_primaire_kwh_j": production_primaire_kwh_j,
        "besoin_primaire_kwh_j": besoin_primaire_kwh_j,
    }


def calc_delta_t_corr_et(
    pech_et1_w_k: float,
    debit_ecs_max10_m3_h: float,
    debit_et_m3_h: float,
    tef_c: float,
    vecs_pro_l_j: float,
    esol_cesc_kwh_j: float,
) -> float:
    cp = CP_EAU_WH_L_K
    if vecs_pro_l_j <= 0 or esol_cesc_kwh_j <= 0 or pech_et1_w_k <= 0:
        return 0.0
    mcp_et = cp * debit_et_m3_h * 1000.0
    mcp_ecs = cp * debit_ecs_max10_m3_h * 1000.0
    if mcp_et <= 0 or mcp_ecs <= 0:
        return 0.0
    tecs_cesc_c = tef_c + 1000.0 * esol_cesc_kwh_j / (cp * vecs_pro_l_j)
    if tecs_cesc_c <= tef_c:
        return 0.0
    mcp_min = min(mcp_et, mcp_ecs)
    mcp_max = max(mcp_et, mcp_ecs)
    if mcp_min <= 0 or mcp_max <= 0:
        return 0.0
    qmax_w = mcp_min * (tecs_cesc_c - tef_c)
    if qmax_w <= 0:
        return 0.0
    r = mcp_min / mcp_max
    nut = pech_et1_w_k / mcp_min
    if abs(1.0 - r) > 1e-9:
        coeff_exp = math.exp(-nut * (1.0 - r))
        denom = 1.0 - r * coeff_exp
        eff_ech = (1.0 - coeff_exp) / denom if abs(denom) > 1e-12 else 0.0
    else:
        eff_ech = nut / (1.0 + nut)
    eff_ech = min(1.0, max(0.0, eff_ech))
    delta_t_ecs = eff_ech * qmax_w / mcp_ecs
    tc_ecs = tef_c + delta_t_ecs
    return max(0.0, tecs_cesc_c - tc_ecs)


def calc_eperte_et_jm(
    kget_w_k: float,
    vecs_pro_jm_l_j: float,
    tef_m_c: float,
    esol_cesc_jm_kwh_j: float,
    t_env_stock_solaire_m_c: float,
    cp_et_wh_l_k: float = CP_EAU_WH_L_K,
) -> float:
    if (
        kget_w_k <= 0
        or vecs_pro_jm_l_j <= 0
        or esol_cesc_jm_kwh_j <= 0
    ):
        return 0.0
    tc_et_m_c = tef_m_c + (
        1000.0 * esol_cesc_jm_kwh_j
        / (cp_et_wh_l_k * vecs_pro_jm_l_j)
    )
    p_perte_et_w = kget_w_k * max(0.0, tc_et_m_c - t_env_stock_solaire_m_c)
    return max(0.0, 24.0 * p_perte_et_w / 1000.0)


def temperature_reference_solo(
    installation: InstallationSoloV0,
    mois: MoisSoloV0,
    text_min_annuel_c: float,
) -> float:
    pertes_boucle = pertes_bouclage_kwh_j(installation, mois, text_min_annuel_c)
    if installation.type_bouclage != "apport_indirect" or pertes_boucle <= 0:
        return mois.tecs_prod_c
    _, tecs_etendu = calc_tecs_etendu_m(
        vecs_pro_jm_l_j=mois.vecs_l_j,
        tecs_pro_m_c=mois.tecs_prod_c,
        tmax_stock_solaire_c=installation.tmax_stock_c,
        eperte_boucle_jm_kwh_j=pertes_boucle,
        cp_ecs_wh_l_k=CP_ECS_WH_L_K,
    )
    return max(mois.tecs_prod_c, tecs_etendu)


def calcul_solo2018_mois_core(
    installation: InstallationSoloV0,
    mois: MoisSoloV0,
    text_min_annuel_c: float | None,
    t_ref_m_c: float,
    tef_m_c: float,
    r_disponible_kwh_m2_j: float,
    besoin_ecs_kwh_j: float,
    besoin_etendu_kwh_j: float,
    besoin_total_kwh_j: float,
    delta_t_eq_boucle_c: float,
    tecs_etendu_c: float,
) -> ResultatMoisSoloV0:
    if mois.mois < 1 or mois.mois > 12:
        raise ValueError("mois doit etre entre 1 et 12")
    jours = JOURS_MOIS[mois.mois - 1]
    s_capteurs = installation.surface_capteurs_m2
    v_stock = installation.volume_stock_l
    if s_capteurs <= 0:
        raise ValueError("surface_capteurs_m2 doit etre > 0")
    if v_stock <= 0:
        raise ValueError("volume_stock_l doit etre > 0")

    tef = float(tef_m_c)
    t_ref = float(t_ref_m_c)
    delta_besoin = t_ref - tef
    capa_litre_j_l_k = 3600.0 * CP_EAU_WH_L_K
    b_ref_j_j = mois.vecs_l_j * delta_besoin * capa_litre_j_l_k
    b_ref_kwh_j = max(0.0, b_ref_j_j / 3.6e6)

    if mois.vecs_l_j <= 0 or delta_besoin <= 0:
        return ResultatMoisSoloV0(
            mois=mois.mois,
            jours=jours,
            vecs_l_j=max(0.0, mois.vecs_l_j),
            besoin_ecs_kwh_j=besoin_ecs_kwh_j,
            besoin_ref_kwh_j=0.0,
            besoin_etendu_kwh_j=besoin_etendu_kwh_j,
            besoin_total_kwh_j=besoin_total_kwh_j,
            delta_t_eq_boucle_c=delta_t_eq_boucle_c,
            tecs_etendu_c=tecs_etendu_c,
            tef_calc_c=tef,
            t_ref_calc_c=t_ref,
            t_sortie_stock_solaire_c=tef,
            pertes_stock_solaire_kwh_j=0.0,
            production_primaire_kwh_j=0.0,
            besoin_primaire_kwh_j=0.0,
            prod_cesc_base_kwh_j=0.0,
            delta_t_corr_et_c=0.0,
            prod_cescet_avant_pertes_et_kwh_j=0.0,
            pertes_eau_technique_kwh_j=0.0,
            prod_cescet_finale_kwh_j=0.0,
            r_disponible_kwh_m2_j=0.0,
            efficacite_transfert=0.0,
            kg1_primaire_w_m2_k=0.0,
            production_solaire_kwh_j=0.0,
            production_solaire_kwh_mois=0.0,
            productivite_kwh_m2_mois=0.0,
            taux_couverture_ecs=None,
            taux_economie_energie=None,
        )

    r_dispo = max(0.0, float(r_disponible_kwh_m2_j))
    if r_dispo <= 0:
        return ResultatMoisSoloV0(
            mois=mois.mois,
            jours=jours,
            vecs_l_j=mois.vecs_l_j,
            besoin_ecs_kwh_j=besoin_ecs_kwh_j,
            besoin_ref_kwh_j=b_ref_kwh_j,
            besoin_etendu_kwh_j=besoin_etendu_kwh_j,
            besoin_total_kwh_j=besoin_total_kwh_j,
            delta_t_eq_boucle_c=delta_t_eq_boucle_c,
            tecs_etendu_c=tecs_etendu_c,
            tef_calc_c=tef,
            t_ref_calc_c=t_ref,
            t_sortie_stock_solaire_c=tef,
            pertes_stock_solaire_kwh_j=0.0,
            production_primaire_kwh_j=0.0,
            besoin_primaire_kwh_j=0.0,
            prod_cesc_base_kwh_j=0.0,
            delta_t_corr_et_c=0.0,
            prod_cescet_avant_pertes_et_kwh_j=0.0,
            pertes_eau_technique_kwh_j=0.0,
            prod_cescet_finale_kwh_j=0.0,
            r_disponible_kwh_m2_j=0.0,
            efficacite_transfert=0.0,
            kg1_primaire_w_m2_k=0.0,
            production_solaire_kwh_j=0.0,
            production_solaire_kwh_mois=0.0,
            productivite_kwh_m2_mois=0.0,
            taux_couverture_ecs=0.0 if besoin_ecs_kwh_j > 0 else None,
            taux_economie_energie=0.0 if besoin_total_kwh_j > 0 else None,
        )

    kg1, effic_transfert = calcul_amont_stock(installation)
    if effic_transfert <= 0:
        raise ValueError("efficacite de transfert <= 0")

    r_dispo_j_m2_j = r_dispo * 3.6e6
    cr_stock_effectif_wh_l_k_j = calc_cr_stock_solaire(installation)
    cr_stock_j_l_k_j = cr_stock_effectif_wh_l_k_j * (
        3600.0 if installation.convertir_cr_stock_en_joules else 1.0
    )

    jour_ref = JOUR_REF_MOIS[mois.mois - 1]
    declinaison_deg = 23.45 * math.sin(math.radians(0.986 * jour_ref - 80.0))
    psol_max_hz_w_m2 = 650.0 + 800.0 * math.sin(
        math.radians(1.8 * (60.0 - installation.latitude_deg + declinaison_deg))
    )
    psol_max_hz_w_m2 = max(1.0, psol_max_hz_w_m2)

    t_env_stock = mois.t_env_stock_c if mois.t_env_stock_c is not None else installation.t_env_stock_c
    delta_ballon = t_env_stock - tef
    delta_ambiant = mois.text_c - tef

    coeff_s = (0.8 * cr_stock_j_l_k_j * v_stock) / (mois.vecs_l_j * capa_litre_j_l_k)
    coeff_t = (delta_ambiant + installation.b_capteur * psol_max_hz_w_m2 / kg1) / delta_besoin

    if coeff_t <= 0:
        production_kwh_j = 0.0
    else:
        coeff_q = (
            b_ref_j_j
            * psol_max_hz_w_m2
            / (r_dispo_j_m2_j * s_capteurs * kg1 * effic_transfert * delta_besoin)
        )
        coeff_z = (mois.vecs_l_j / (coeff_t * v_stock)) * (
            1.0 + delta_besoin * coeff_t / installation.tmax_stock_c
        )
        coeff_f2 = (1.0 / (1.0 + coeff_s)) * (
            coeff_t / (1.0 + coeff_q) + coeff_s * delta_ballon / delta_besoin
        )
        exp_term = math.expm1(2.0 * coeff_f2 * coeff_f2)
        if exp_term <= 1e-12:
            couv_solo = 0.0
        else:
            coeff_1_sur_ff = 1.0 + 2.0 / exp_term + 0.2 * coeff_z * coeff_z
            couv_solo = math.sqrt(max(0.0, 1.0 / coeff_1_sur_ff))
        production_kwh_j = b_ref_kwh_j * couv_solo

    production_kwh_j = min(max(0.0, production_kwh_j), b_ref_kwh_j)
    primaire = calc_solo2018_primaire_m(
        tef_m_c=tef,
        t_ref_m_c=t_ref,
        t_env_stock_solaire_m_c=t_env_stock,
        v_stock_solaire_l=v_stock,
        cr_stock_solaire_wh_l_k_j=cr_stock_effectif_wh_l_k_j,
        bref_jm_kwh_j=b_ref_kwh_j,
        esol_jm_kwh_j=production_kwh_j,
    )
    production_kwh_mois = production_kwh_j * jours
    productivite_kwh_m2_mois = production_kwh_mois / s_capteurs

    taux_couv = production_kwh_j / besoin_ecs_kwh_j if besoin_ecs_kwh_j > 0 else None
    taux_eco = production_kwh_j / besoin_total_kwh_j if besoin_total_kwh_j > 0 else None

    return ResultatMoisSoloV0(
        mois=mois.mois,
        jours=jours,
        vecs_l_j=mois.vecs_l_j,
        besoin_ecs_kwh_j=besoin_ecs_kwh_j,
        besoin_ref_kwh_j=b_ref_kwh_j,
        besoin_etendu_kwh_j=besoin_etendu_kwh_j,
        besoin_total_kwh_j=besoin_total_kwh_j,
        delta_t_eq_boucle_c=delta_t_eq_boucle_c,
        tecs_etendu_c=tecs_etendu_c,
        tef_calc_c=tef,
        t_ref_calc_c=t_ref,
        t_sortie_stock_solaire_c=float(primaire["t_sortie_stock_solaire_c"]),
        pertes_stock_solaire_kwh_j=float(primaire["pertes_stock_solaire_kwh_j"]),
        production_primaire_kwh_j=float(primaire["production_primaire_kwh_j"]),
        besoin_primaire_kwh_j=float(primaire["besoin_primaire_kwh_j"]),
        prod_cesc_base_kwh_j=production_kwh_j,
        delta_t_corr_et_c=0.0,
        prod_cescet_avant_pertes_et_kwh_j=production_kwh_j,
        pertes_eau_technique_kwh_j=0.0,
        prod_cescet_finale_kwh_j=production_kwh_j,
        r_disponible_kwh_m2_j=r_dispo,
        efficacite_transfert=effic_transfert,
        kg1_primaire_w_m2_k=kg1,
        production_solaire_kwh_j=production_kwh_j,
        production_solaire_kwh_mois=production_kwh_mois,
        productivite_kwh_m2_mois=productivite_kwh_m2_mois,
        taux_couverture_ecs=taux_couv,
        taux_economie_energie=taux_eco,
    )


def calcul_solo2018_mois(
    installation: InstallationSoloV0,
    mois: MoisSoloV0,
    text_min_annuel_c: float | None = None,
) -> ResultatMoisSoloV0:
    tef = mois.tef_c
    text_min = mois.text_c if text_min_annuel_c is None else text_min_annuel_c
    pertes_boucle = pertes_bouclage_kwh_j(installation, mois, text_min)
    besoins_ext = calc_besoin_etendu_solarisable(
        vecs_pro_jm_l_j=mois.vecs_l_j,
        tef_m_c=tef,
        tecs_pro_m_c=mois.tecs_prod_c,
        tmax_stock_solaire_c=installation.tmax_stock_c,
        eperte_boucle_jm_kwh_j=pertes_boucle,
        cp_ecs_wh_l_k=CP_ECS_WH_L_K,
    )
    besoin_ecs = float(besoins_ext["becs_pro_jm_kwh_j"])
    tecs_etendu = float(besoins_ext["tecs_etendu_m_c"])
    delta_t_eq_boucle = float(besoins_ext["delta_t_eq_boucle_c"])
    besoin_etendu = float(besoins_ext["betendu_jm_kwh_j"])
    besoin_total = float(besoins_ext["bth_total_jm_kwh_j"])
    if installation.type_bouclage == "apport_indirect" and pertes_boucle > 0:
        t_ref = max(mois.tecs_prod_c, tecs_etendu)
    else:
        t_ref = mois.tecs_prod_c
    r_dispo = rayonnement_disponible_kwh_m2_j(installation, mois)
    return calcul_solo2018_mois_core(
        installation=installation,
        mois=mois,
        text_min_annuel_c=text_min_annuel_c,
        t_ref_m_c=t_ref,
        tef_m_c=tef,
        r_disponible_kwh_m2_j=r_dispo,
        besoin_ecs_kwh_j=besoin_ecs,
        besoin_etendu_kwh_j=besoin_etendu,
        besoin_total_kwh_j=besoin_total,
        delta_t_eq_boucle_c=delta_t_eq_boucle,
        tecs_etendu_c=tecs_etendu,
    )


def calcul_solo2018_annee(
    installation: InstallationSoloV0,
    mois_data: Iterable[MoisSoloV0],
) -> list[ResultatMoisSoloV0]:
    mois_list = list(mois_data)
    text_min_annuel_c = min((m.text_c for m in mois_list), default=0.0)
    return [calcul_solo2018_mois(installation, m, text_min_annuel_c=text_min_annuel_c) for m in mois_list]


def calcul_solo2018_mois_cescet(
    installation: InstallationSoloV0,
    mois: MoisSoloV0,
    text_min_annuel_c: float | None,
    kget_w_k: float,
    pech_et1_w_k: float,
    debit_et_m3_h: float,
    ratio_ecs_max10_sur_j: float = 0.5,
) -> ResultatMoisSoloV0:
    res_base = calcul_solo2018_mois(
        installation=installation,
        mois=mois,
        text_min_annuel_c=text_min_annuel_c,
    )
    esol_cesc1 = res_base.production_solaire_kwh_j
    debit_ecs_max10 = max(0.0, ratio_ecs_max10_sur_j * mois.vecs_l_j / 1000.0)
    delta_t_corr_et = calc_delta_t_corr_et(
        pech_et1_w_k=pech_et1_w_k,
        debit_ecs_max10_m3_h=debit_ecs_max10,
        debit_et_m3_h=debit_et_m3_h,
        tef_c=mois.tef_c,
        vecs_pro_l_j=mois.vecs_l_j,
        esol_cesc_kwh_j=esol_cesc1,
    )
    text_min = mois.text_c if text_min_annuel_c is None else text_min_annuel_c
    pertes_boucle = pertes_bouclage_kwh_j(installation, mois, text_min)
    t_ref_base = (
        max(mois.tecs_prod_c, res_base.tecs_etendu_c)
        if installation.type_bouclage == "apport_indirect" and pertes_boucle > 0
        else mois.tecs_prod_c
    )
    tef_et = mois.tef_c + delta_t_corr_et
    t_ref_et = t_ref_base + delta_t_corr_et
    r_dispo = rayonnement_disponible_kwh_m2_j(installation, mois)
    res_proet = calcul_solo2018_mois_core(
        installation=installation,
        mois=mois,
        text_min_annuel_c=text_min_annuel_c,
        t_ref_m_c=t_ref_et,
        tef_m_c=tef_et,
        r_disponible_kwh_m2_j=r_dispo,
        besoin_ecs_kwh_j=res_base.besoin_ecs_kwh_j,
        besoin_etendu_kwh_j=res_base.besoin_etendu_kwh_j,
        besoin_total_kwh_j=res_base.besoin_total_kwh_j,
        delta_t_eq_boucle_c=res_base.delta_t_eq_boucle_c,
        tecs_etendu_c=res_base.tecs_etendu_c,
    )
    esol_proet = res_proet.production_solaire_kwh_j
    t_env_stock = (
        mois.t_env_stock_c
        if mois.t_env_stock_c is not None
        else installation.t_env_stock_c
    )
    eperte_et = calc_eperte_et_jm(
        kget_w_k=kget_w_k,
        vecs_pro_jm_l_j=mois.vecs_l_j,
        tef_m_c=mois.tef_c,
        esol_cesc_jm_kwh_j=esol_proet,
        t_env_stock_solaire_m_c=t_env_stock,
    )
    esol_final = max(0.0, esol_proet - eperte_et)
    primaire = calc_solo2018_primaire_m(
        tef_m_c=tef_et,
        t_ref_m_c=t_ref_et,
        t_env_stock_solaire_m_c=t_env_stock,
        v_stock_solaire_l=installation.volume_stock_l,
        cr_stock_solaire_wh_l_k_j=calc_cr_stock_solaire(installation),
        bref_jm_kwh_j=res_proet.besoin_ref_kwh_j,
        esol_jm_kwh_j=esol_proet,
    )
    taux_couv = esol_final / res_proet.besoin_ecs_kwh_j if res_proet.besoin_ecs_kwh_j > 0 else None
    taux_eco = esol_final / res_proet.besoin_total_kwh_j if res_proet.besoin_total_kwh_j > 0 else None
    return replace(
        res_proet,
        production_solaire_kwh_j=esol_final,
        production_solaire_kwh_mois=esol_final * res_proet.jours,
        productivite_kwh_m2_mois=(esol_final * res_proet.jours) / max(1e-9, installation.surface_capteurs_m2),
        t_sortie_stock_solaire_c=float(primaire["t_sortie_stock_solaire_c"]),
        pertes_stock_solaire_kwh_j=float(primaire["pertes_stock_solaire_kwh_j"]),
        production_primaire_kwh_j=float(primaire["production_primaire_kwh_j"]),
        besoin_primaire_kwh_j=float(primaire["besoin_primaire_kwh_j"]),
        prod_cesc_base_kwh_j=esol_cesc1,
        delta_t_corr_et_c=delta_t_corr_et,
        prod_cescet_avant_pertes_et_kwh_j=esol_proet,
        pertes_eau_technique_kwh_j=eperte_et,
        prod_cescet_finale_kwh_j=esol_final,
        taux_couverture_ecs=taux_couv,
        taux_economie_energie=taux_eco,
    )


def calcul_solo2018_annee_cescet(
    installation: InstallationSoloV0,
    mois_data: Iterable[MoisSoloV0],
    kget_w_k: float,
    pech_et1_w_k: float,
    debit_et_m3_h: float,
    ratio_ecs_max10_sur_j: float = 0.5,
) -> list[ResultatMoisSoloV0]:
    mois_list = list(mois_data)
    text_min_annuel_c = min((m.text_c for m in mois_list), default=0.0)
    return [
        calcul_solo2018_mois_cescet(
            installation=installation,
            mois=m,
            text_min_annuel_c=text_min_annuel_c,
            kget_w_k=kget_w_k,
            pech_et1_w_k=pech_et1_w_k,
            debit_et_m3_h=debit_et_m3_h,
            ratio_ecs_max10_sur_j=ratio_ecs_max10_sur_j,
        )
        for m in mois_list
    ]


