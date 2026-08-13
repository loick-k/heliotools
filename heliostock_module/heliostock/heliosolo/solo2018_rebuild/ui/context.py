from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DescriptionState:
    project_name: Any
    mode_meteo_label: Any
    mode_meteo_verification: Any
    ville_ref: Any
    cas_verification_meteo: Any
    profil_hz: Any
    ville_ref_effective: Any
    zip_path: Any
    site_lat_deg: Any
    site_lon_deg: Any
    site_tz_h: Any
    rdispo_monthly_map: Any
    meteo_impose_map: Any
    mode_rayonnement_label: Any
    mode_rdispo_impose: Any
    typologie_label: Any
    categorie_hotellerie: Any
    unite_label: Any
    mode_nb_unites: Any
    nb_unites_batiment: Any
    nb_logements_mix: Any
    vecs_total_mix_l_j: Any
    default_vecs_unitaire_l_j: Any
    vecs_total_ref_l_j: Any
    vecs_unite_ref_l_j: Any


@dataclass(slots=True)
class ModelisationContext:
    description: DescriptionState
    app_config: Any


@dataclass(slots=True)
class CapteursState:
    surface_unitaire_capteur_m2: Any
    nb_capteurs: Any
    surface_capteurs_m2: Any
    n0: Any
    a1: Any
    a2: Any
    b_capteur: Any
    k_capteur: Any
    inclinaison_deg: Any
    azimut_deg_sud: Any


@dataclass(slots=True)
class StockageState:
    nb_ballons_stock: Any
    v1_stock_solaire_l: Any
    volume_stock_l: Any
    modele_stock_label: Any
    modele_stock_solaire: Any
    tenv_mode: Any
    tenv_base_c: Any
    tenv_monthly_map: Any
    cr_stock_wh_l_k_j: Any
    tmax_stock_c: Any
    epais_iso_stock_solaire_cm: Any
    lambda_iso_stock_solaire_w_m_k: Any
    modele_geometrie_ballon: Any
    algo_sballon: Any
    cr_stock_effectif_ui: Any
    t_env_stock_used_c: Any


@dataclass(slots=True)
class HydrauliqueState:
    mode_schema_label: Any
    mode_schema: Any
    ratio_pointe_ecs_profile: Any
    ratio_ecs_max10_sur_j: Any
    mode_kt_primaire: Any
    long_primaire_m: Any
    kl_primaire_w_m_k: Any
    type_installation_label: Any
    type_circulation: Any
    type_echangeur: Any
    type_circulation_label: Any
    type_echangeur_label: Any
    pech11_w_m2_k: Any
    kget_w_k: Any
    pech_et1_w_m2_k: Any
    mode_debit_et_label: Any
    debit1_et_l_h_m2: Any
    debit_et_total_m3_h_manual: Any


@dataclass(slots=True)
class BouclageState:
    type_bouclage_label: Any
    type_bouclage: Any
    mode_pertes_boucle_label: Any
    mode_pertes_boucle: Any
    debit_bouclage_l_h: Any
    delta_tmax_bouclage_k: Any
    long_bouclage_m: Any
    kl_bouclage_w_m_k: Any
    long1_boucle_bon_m_par_unite: Any
    long1_boucle_moyen_m_par_unite: Any
    long1_boucle_mauvais_m_par_unite: Any
    kl_boucle_bon_w_m_k: Any
    kl_boucle_moyen_w_m_k: Any
    kl_boucle_mauvais_w_m_k: Any
    pertes_boucle_monthly_map: Any
    pertes_boucle_kwh_j: Any
    bouclage_pertes_placeholder: Any


@dataclass(slots=True)
class BesoinsState:
    conso_mode: Any
    tef_mode_label: Any
    tef_mode: Any
    tef_monthly_map: Any
    vecs_monthly_map: Any
    tecs_mode: Any
    tecs_const_c: Any
    tecs_monthly_map: Any
    tef_manual_c: Any
    modele_v_eau_chaude: Any
    vecs_const_l_j: Any
    tecs_dis_mode: Any
    tecs_dis_const_c: Any
    tecs_dis_monthly_map: Any


@dataclass(slots=True)
class ResultatsSettings:
    algo_corr_incidence: Any
    appliquer_corr_incidence: Any
    coeff0_ci: Any
    coeff1_ci: Any
    coeff3_ci: Any
    debit_et_m3_h: Any
    pech_et1_w_k: Any


@dataclass(slots=True)
class ResultatsContext:
    description: DescriptionState
    besoins: BesoinsState
    hydraulique: HydrauliqueState
    bouclage: BouclageState
    stockage: StockageState
    capteurs: CapteursState
    settings: ResultatsSettings
    app_config: Any


