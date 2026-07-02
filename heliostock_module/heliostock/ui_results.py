from __future__ import annotations

import pandas as pd
import streamlit as st

from .charts import (
    _bar_chart,
    _line_chart,
    _multiyear_btes_flux_chart,
    _multiyear_btes_temperature_chart,
    _multiyear_btes_temperature_comparison_chart,
    _parametric_pac_chart,
    _parametric_surface_chart,
    _stacked_coverage_duration_chart,
    _temperature_chart,
)
from .postprocess import (
    _melt_monthly,
    _stacked_coverage_duration_dataframe,
)
from .scenarios import ScenarioResult
from .ui_economics import render_economics_tab
from .ui_formatting import display_dataframe, round_display_df


def render_hourly_results(
    *,
    scenario: ScenarioResult,
    parametric_pac_df: pd.DataFrame,
    parametric_surface_df: pd.DataFrame,
    calculation_id: str,
    peak_bt_power_kw: float,
    pac_nominal_power_kw: float,
    pac_power_fraction_pct: float,
    btes_backend_used: str,
    probe_power_ratio_w_m: float,
    hourly_profile_df: pd.DataFrame,
) -> pd.DataFrame:
    """Render all result panels for a completed HelioStock calculation."""

    hourly_df = scenario.hourly_df
    no_solar_hourly_df = scenario.no_solar_hourly_df
    multiyear_btes_df = scenario.multiyear_btes_df
    no_solar_multiyear_btes_df = scenario.no_solar_multiyear_btes_df
    annual_df = scenario.annual_df
    hourly_by_month_df = scenario.hourly_by_month_df

    total_ht = scenario.total_ht_kwh
    total_bt = scenario.total_bt_kwh
    total_preheat_ht = scenario.total_preheat_ht_kwh
    total_charge_buffer = scenario.total_charge_buffer_kwh
    total_to_btes = scenario.total_to_btes_kwh
    solar_productivity_valued = scenario.solar_productivity_valued_kwh_m2_year
    total_backup_ht = scenario.total_backup_ht_kwh
    total_backup_bt = scenario.total_backup_bt_kwh
    annual_ht_solar_coverage = scenario.annual_ht_solar_coverage
    total_pac = scenario.total_pac_kwh
    total_compressor = scenario.total_compressor_kwh
    total_auxiliaries = scenario.total_pac_auxiliaries_kwh
    total_standby = scenario.total_standby_kwh
    total_elec = scenario.total_elec_kwh
    mean_cop = scenario.mean_cop
    spf_pac_total = scenario.spf_pac_total
    spf_system = scenario.spf_system
    global_ren_rate = scenario.global_ren_rate
    no_solar_total_pac = scenario.no_solar_total_pac_kwh
    no_solar_total_elec = scenario.no_solar_total_elec_kwh
    no_solar_cop = scenario.no_solar_cop
    savings = scenario.savings
    backup_power_kw = scenario.backup_power_kw

    st.subheader("Resultats 8760 h")
    st.caption(
        f"Simulation technique champ : {scenario.simulation_years_total} an(s). "
        f"Annee affichee pour les resultats techniques : {scenario.simulation_year_displayed}. "
        f"Economie : trajectoire de {scenario.economic_years_used} an(s). "
        f"Tmin operationnelle PAC : {scenario.config.btes.t_min_c:.1f} C ; "
        f"critere GMI {'actif' if scenario.gmi_check_enabled else 'inactif'} "
        f"({scenario.config.btes.gmi_t_min_c:.1f} / {scenario.config.btes.gmi_t_max_c:.1f} C)."
    )
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Besoin total", f"{(total_ht + total_bt) / 1000:.0f} MWh")
    k2.metric("Prechauffage HT solaire", f"{total_preheat_ht / 1000:.0f} MWh")
    k3.metric("Charge ballon solaire", f"{total_charge_buffer / 1000:.0f} MWh")
    k4.metric("Injection BTES", f"{total_to_btes / 1000:.0f} MWh")

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Productivite solaire valorisee", f"{solar_productivity_valued:.0f} kWh/m2.an")
    k6.metric("Consommation appoint", f"{(total_backup_ht + total_backup_bt) / 1000:.0f} MWh")
    k7.metric("Couverture solaire HT", f"{annual_ht_solar_coverage * 100:.0f} %")
    k8.metric(
        "COP PAC avec solaire",
        f"{mean_cop:.1f}",
        delta=f"{mean_cop - no_solar_cop:+.1f} vs sans solaire" if no_solar_cop > 0.0 else None,
    )

    k9, k10, k11, k12 = st.columns(4)
    k9.metric("Taux EnR global", f"{global_ren_rate * 100:.0f} %")
    k10.metric("COP PAC sans solaire", f"{no_solar_cop:.1f}" if no_solar_cop > 0.0 else "non lance")
    k11.metric("Lineaire simule 8760 h", f"{scenario.full_borefield_length_m:.0f} ml")
    if bool(savings["found"]):
        k12.metric("Gain equivalent eco", f"{float(savings['saved_length_m']):.0f} ml")
    else:
        k12.metric("Gain equivalent eco", "non trouve")

    equivalent_full_power_hours = total_pac / pac_nominal_power_kw if pac_nominal_power_kw > 0.0 else 0.0
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Pmax besoin BT", f"{peak_bt_power_kw:.0f} kW")
    p2.metric("P PAC retenue", f"{pac_nominal_power_kw:.0f} kW", delta=f"{pac_power_fraction_pct:.0f} % Pmax")
    p3.metric("Heures pleine puissance PAC", f"{equivalent_full_power_hours:.0f} h/an")
    p4.metric("Pic appoint appele", f"{backup_power_kw:.0f} kW")
    gmi_hours_low = int((hourly_df["T_fluide_entree_echangeur_geo_C"] < scenario.config.btes.gmi_t_min_c - 1e-6).sum())
    gmi_hours_high = int((hourly_df["T_fluide_injection_C"] > scenario.config.btes.gmi_t_max_c + 1e-6).sum())
    source_limit_hours = int(hourly_df["Limite_temperature_source"].sum())
    source_limit_energy = float(hourly_df["BT_non_couvert_limite_source_kWh"].sum()) / 1000.0
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Heures sous Tmin operationnelle", f"{int((hourly_df['T_source_PAC_pour_COP_C'] <= scenario.config.btes.t_min_c + 1e-6).sum())} h")
    d2.metric("Heures hors GMI", f"{gmi_hours_low + gmi_hours_high} h")
    d3.metric("T fluide injection max", f"{float(hourly_df['T_fluide_injection_C'].max()):.1f} C")
    d4.metric("Limite source PAC", f"{source_limit_hours} h", delta=f"{source_limit_energy:.1f} MWh")

    _render_pac_electricity_summary(
        total_compressor=total_compressor,
        total_auxiliaries=total_auxiliaries,
        total_standby=total_standby,
        total_elec=total_elec,
        mean_cop=mean_cop,
        spf_pac_total=spf_pac_total,
        spf_system=spf_system,
    )
    _render_btes_warnings(
        scenario=scenario,
        hourly_df=hourly_df,
        btes_backend_used=btes_backend_used,
        probe_power_ratio_w_m=probe_power_ratio_w_m,
    )
    if no_solar_cop > 0.0:
        _render_borefield_savings_explanation(
            scenario=scenario,
            no_solar_cop=no_solar_cop,
            no_solar_total_pac=scenario.no_solar_total_pac_kwh,
        )

    tab_temp, tab_multi, tab_mono, tab_monthly, tab_economics, tab_parametric_pac, tab_parametric_solar, tab_detail = st.tabs(
        [
            "Températures horaires",
            "Multiannuel BTES",
            "Monotone horaire",
            "Analyses mensuelles",
            "Economie",
            "Paramétrique PAC",
            "Paramétrique solaire",
            "Données",
        ]
    )

    with tab_temp:
        st.markdown("### Température du ballon solaire et du champ BTES")
        st.altair_chart(_temperature_chart(hourly_df), width="stretch")
        st.markdown("### Rendement moyen capteur")
        _render_collector_efficiency_kpis(hourly_df)

    with tab_multi:
        _render_multiyear_tab(multiyear_btes_df, no_solar_multiyear_btes_df)

    with tab_mono:
        _render_duration_tab(hourly_df)

    with tab_monthly:
        _render_monthly_tab(
            annual_df=annual_df,
            hourly_by_month_df=hourly_by_month_df,
            total_pac=total_pac,
            no_solar_total_pac=no_solar_total_pac,
            total_elec=total_elec,
            no_solar_total_elec=no_solar_total_elec,
            mean_cop=mean_cop,
            no_solar_cop=no_solar_cop,
        )

    with tab_economics:
        render_economics_tab(
            economic_comparison_df=scenario.economic_comparison_df,
            economic_comparison_chart_df=scenario.economic_comparison_chart_df,
            economic_trajectory_df=scenario.economic_trajectory_df,
            recharge_value=scenario.recharge_value,
            heat_costs=scenario.heat_costs,
        )

    with tab_parametric_pac:
        _render_parametric_pac_tab(parametric_pac_df, calculation_id=calculation_id)

    with tab_parametric_solar:
        _render_parametric_solar_tab(parametric_surface_df, calculation_id=calculation_id)

    with tab_detail:
        _render_detail_tab(hourly_by_month_df, hourly_profile_df, hourly_df)

    return hourly_df


def _weighted_average_efficiency(hourly_df: pd.DataFrame, efficiency_column: str, energy_column: str) -> float:
    if efficiency_column not in hourly_df or energy_column not in hourly_df:
        return 0.0
    energy = pd.to_numeric(hourly_df[energy_column], errors="coerce").fillna(0.0).clip(lower=0.0)
    efficiency = pd.to_numeric(hourly_df[efficiency_column], errors="coerce").fillna(0.0).clip(lower=0.0)
    total_energy = float(energy.sum())
    if total_energy <= 1e-9:
        return 0.0
    return float((efficiency * energy).sum() / total_energy)


def _render_collector_efficiency_kpis(hourly_df: pd.DataFrame) -> None:
    ht_eff = _weighted_average_efficiency(hourly_df, "collector_eff_ht", "solar_ht_to_buffer_kwh")
    storage_eff = _weighted_average_efficiency(hourly_df, "collector_eff_storage", "solar_to_btes_kwh")
    ht_energy_mwh = float(hourly_df["solar_ht_to_buffer_kwh"].sum()) / 1000.0 if "solar_ht_to_buffer_kwh" in hourly_df else 0.0
    storage_energy_mwh = float(hourly_df["solar_to_btes_kwh"].sum()) / 1000.0 if "solar_to_btes_kwh" in hourly_df else 0.0

    k1, k2, k3 = st.columns(3)
    k1.metric("Charge ballon", f"{ht_eff * 100:.1f} %", delta=f"{ht_energy_mwh:.0f} MWh captés")
    k2.metric("Injection BTES", f"{storage_eff * 100:.1f} %", delta=f"{storage_energy_mwh:.0f} MWh injectés")
    if ht_energy_mwh + storage_energy_mwh > 1e-9:
        combined_eff = (
            ht_eff * ht_energy_mwh + storage_eff * storage_energy_mwh
        ) / max(1e-9, ht_energy_mwh + storage_energy_mwh)
        k3.metric("Moyenne pondérée", f"{combined_eff * 100:.1f} %")
    else:
        k3.metric("Moyenne pondérée", "non disponible")


def _render_pac_electricity_summary(
    *,
    total_compressor: float,
    total_auxiliaries: float,
    total_standby: float,
    total_elec: float,
    mean_cop: float,
    spf_pac_total: float,
    spf_system: float,
) -> None:
    st.markdown("### Synthèse P1 électrique PAC/géothermie")
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Electricité compresseur PAC", f"{total_compressor / 1000.0:.1f} MWh/an")
    e2.metric("Forfait pompes + auxiliaires PAC", f"{total_auxiliaries / 1000.0:.1f} MWh/an")
    e3.metric("Veille/régulation", f"{total_standby / 1000.0:.1f} MWh/an")
    e4.metric("Electricité totale PAC", f"{total_elec / 1000.0:.1f} MWh/an")
    e5, e6, e7 = st.columns(3)
    e5.metric("COP machine", f"{mean_cop:.1f}")
    e6.metric("SPF PAC complet", f"{spf_pac_total:.1f}")
    e7.metric("SPF système simplifié", f"{spf_system:.1f}")


def _render_btes_warnings(
    *,
    scenario: ScenarioResult,
    hourly_df: pd.DataFrame,
    btes_backend_used: str,
    probe_power_ratio_w_m: float,
) -> None:
    max_extraction_w_m = float(hourly_df["q_extraction_w_m"].max())
    max_injection_w_m = float(hourly_df["q_injection_w_m"].max())
    hours_at_tmin = int((hourly_df["T_source_PAC_C"] <= scenario.config.btes.t_min_c + 1e-6).sum())
    warning_margin = 1.05
    if btes_backend_used == "pygfunction" and hours_at_tmin > 0:
        st.warning(
            f"Backend pygfunction : la température source atteint Tmin pendant {hours_at_tmin} h/an. "
            f"Ce diagnostic porte sur le champ complet simulé en 8760 h ({scenario.full_borefield_length_m:.0f} ml), "
            "pas sur le scénario économique à sondes réduites. Le champ est probablement trop sollicité ou trop court "
            "pour ce modèle ; le COP est alors borné à Tmin et la chaleur BT non couverte par la PAC bascule en appoint gaz."
        )
    if max_extraction_w_m > probe_power_ratio_w_m * warning_margin:
        st.warning(
            f"Puissance linéique d'extraction max = {max_extraction_w_m:.0f} W/ml, "
            f"au-dessus du ratio de prédimensionnement retenu ({probe_power_ratio_w_m:.0f} W/ml)."
        )
    if max_injection_w_m > probe_power_ratio_w_m * warning_margin:
        st.warning(
            f"Puissance linéique d'injection max = {max_injection_w_m:.0f} W/ml, "
            f"au-dessus du ratio de prédimensionnement retenu ({probe_power_ratio_w_m:.0f} W/ml). "
            "Vérifie la contrainte d'injection admissible dans les hypothèses géothermie."
        )


def _render_borefield_savings_explanation(
    *,
    scenario: ScenarioResult,
    no_solar_cop: float,
    no_solar_total_pac: float,
) -> None:
    with st.expander("Detail du calcul d'economie equivalente de sondes"):
        st.markdown(
            f"""
            Le cas de reference est le calcul **sans solaire** avec le champ complet :
            COP annuel PAC = `{no_solar_cop:.1f}` et chaleur BT PAC = `{no_solar_total_pac / 1000:.0f} MWh`.

            Le résultat 8760 h affiché au-dessus utilise le **champ complet prédimensionné** :
            `{scenario.full_borefield_length_m:.0f} ml`.

            Le calcul économique réduit ensuite le nombre de sondes avec solaire, puis relance le moteur pygfunction,
            jusqu'à retrouver au minimum ce COP et ce niveau de couverture BT. Cette réduction n'est utilisée que dans le scénario économique
            **Géothermie + solaire sondes réduites**.
            """
        )


def _render_multiyear_tab(multiyear_btes_df: pd.DataFrame, no_solar_multiyear_btes_df: pd.DataFrame) -> None:
    st.markdown("### Évolution multiannuelle du champ de sondes")
    if multiyear_btes_df.empty:
        st.info("Projection multiannuelle indisponible.")
        return

    years_count = int(multiyear_btes_df["Annee"].max())
    st.caption(
        "Projection physique obtenue en répétant la même météo EPW et les mêmes besoins horaires "
        f"sur {years_count} ans. Elle sert à visualiser la dérive thermique du champ ; "
        "les tableaux économiques restent calculés sur les indicateurs annuels."
    )
    first_year_end = float(multiyear_btes_df[multiyear_btes_df["Annee"] == 1]["T source PAC fin (C)"].iloc[-1])
    last_year_end = float(multiyear_btes_df[multiyear_btes_df["Annee"] == years_count]["T source PAC fin (C)"].iloc[-1])
    period_min = float(multiyear_btes_df["T source PAC min (C)"].min())
    hours_tmin = int(multiyear_btes_df["Heures sous Tmin source"].sum())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("T source fin an 1", f"{first_year_end:.0f} C")
    m2.metric(f"T source fin an {years_count}", f"{last_year_end:.0f} C", delta=f"{last_year_end - first_year_end:+.0f} C")
    m3.metric("T min période", f"{period_min:.0f} C")
    m4.metric("Heures source Tmin", f"{hours_tmin:.0f} h")
    chart_col_1, chart_col_2, chart_col_3 = st.columns(3)
    if not no_solar_multiyear_btes_df.empty:
        comparison_btes_df = pd.concat(
            [
                no_solar_multiyear_btes_df.assign(Scenario="Géothermie seule"),
                multiyear_btes_df.assign(Scenario="Géothermie + recharge solaire"),
            ],
            ignore_index=True,
        )
        with chart_col_1:
            st.markdown("### Comparaison")
            st.altair_chart(_multiyear_btes_temperature_comparison_chart(comparison_btes_df), width="stretch")
    else:
        with chart_col_1:
            st.markdown("### Comparaison")
            st.info("Comparaison géothermie seule indisponible.")
    with chart_col_2:
        st.markdown("### Température")
        st.altair_chart(_multiyear_btes_temperature_chart(multiyear_btes_df), width="stretch")
    with chart_col_3:
        st.markdown("### Flux mensuels")
        st.altair_chart(_multiyear_btes_flux_chart(multiyear_btes_df), width="stretch")
    st.dataframe(display_dataframe(multiyear_btes_df), width="stretch", hide_index=True)


def _render_duration_tab(hourly_df: pd.DataFrame) -> None:
    st.markdown("### Monotones de charge")
    st.caption(
        "Les monotones sont triees par besoin decroissant et affichees en mix empile. "
        "La monotone synchronisee multi-courbes 8760 h a ete retiree pour accelerer l'affichage."
    )

    st.markdown("### Mix global trie par besoin total")
    global_stack_df = _stacked_coverage_duration_dataframe(hourly_df, mode="GLOBAL")
    st.altair_chart(
        _stacked_coverage_duration_chart(
            global_stack_df,
            title="Besoin total = solaire thermique + geothermie PAC + appoint gaz",
        ),
        width="stretch",
    )

    c_ht, c_bt = st.columns(2)
    with c_ht:
        st.markdown("### Mix HT trie par besoin HT")
        ht_stack_df = _stacked_coverage_duration_dataframe(hourly_df, mode="HT")
        st.altair_chart(
            _stacked_coverage_duration_chart(ht_stack_df, title="Besoin HT = solaire thermique + appoint"),
            width="stretch",
        )
    with c_bt:
        st.markdown("### Mix BT trie par besoin BT")
        bt_stack_df = _stacked_coverage_duration_dataframe(hourly_df, mode="BT")
        st.altair_chart(
            _stacked_coverage_duration_chart(bt_stack_df, title="Besoin BT = géothermie PAC + appoint"),
            width="stretch",
        )


def _render_monthly_tab(
    *,
    annual_df: pd.DataFrame,
    hourly_by_month_df: pd.DataFrame,
    total_pac: float,
    no_solar_total_pac: float,
    total_elec: float,
    no_solar_total_elec: float,
    mean_cop: float,
    no_solar_cop: float,
) -> None:
    st.markdown("### Bilan annuel, calcule depuis les 8760 heures")
    st.dataframe(display_dataframe(annual_df[["Poste", "MWh/an"]]), width="stretch", hide_index=True)

    st.markdown("### Taux de couverture solaire mensuel du besoin HT")
    coverage_rate_df = hourly_by_month_df[["Mois", "Taux couverture solaire HT (%)"]].rename(
        columns={"Taux couverture solaire HT (%)": "Valeur"}
    )
    st.altair_chart(_line_chart(coverage_rate_df, y_title="Couverture solaire HT (%)", y_domain=[0, 100]), width="stretch")
    st.caption(
        "La priorite HT est appliquee au pas horaire via le ballon solaire journalier : "
        "le solaire charge d'abord le ballon HT, le process HT soutire ensuite ce ballon, "
        "et le BTES ne recoit que le reliquat lorsque le ballon est sature. "
        "Une injection BTES mensuelle peut donc coexister avec un taux HT inferieur a 100 % "
        "si les heures de soleil, les heures d'appel HT ou la temperature utile du ballon ne coincident pas parfaitement."
    )

    st.markdown("### Flux sous-sol : energie injectee et extraite vers PAC")
    ground_flux_df = pd.concat(
        [
            hourly_by_month_df[["Mois", "Injection BTES (MWh)"]].rename(columns={"Injection BTES (MWh)": "Valeur"}).assign(Poste="Injection solaire BTES"),
            hourly_by_month_df[["Mois", "Extraction champ PAC (MWh)"]].rename(columns={"Extraction champ PAC (MWh)": "Valeur"}).assign(Poste="Extraction champ vers PAC"),
            hourly_by_month_df[["Mois", "Bilan net sol (MWh)"]].rename(columns={"Bilan net sol (MWh)": "Valeur"}).assign(Poste="Bilan net sol"),
        ],
        ignore_index=True,
    )
    ground_flux_df.loc[ground_flux_df["Poste"] == "Extraction champ vers PAC", "Valeur"] *= -1.0
    st.altair_chart(_bar_chart(ground_flux_df), width="stretch")
    st.caption(
        "Les extractions PAC sont affichées négatives. Le bilan net sol correspond à extraction PAC - injection solaire. "
        "La dérive thermique du champ est calculée par pygfunction à partir des charges linéiques horaires."
    )

    st.markdown("### Production solaire valorisee : prechauffage HT et injection BTES")
    st.altair_chart(_bar_chart(_melt_monthly(hourly_by_month_df, ["Prechauffage HT solaire (MWh)", "Injection BTES (MWh)"])), width="stretch")
    st.markdown("### Couverture mensuelle du besoin HT")
    st.altair_chart(_bar_chart(_melt_monthly(hourly_by_month_df, ["Prechauffage HT solaire (MWh)", "Appoint HT (MWh)"])), width="stretch")
    st.markdown("### Couverture mensuelle du besoin BT")
    st.altair_chart(_bar_chart(_melt_monthly(hourly_by_month_df, ["BT PAC (MWh)", "Appoint BT (MWh)"])), width="stretch")

    st.markdown("### Comparaison horaire sans solaire / avec solaire")
    if no_solar_cop <= 0.0:
        st.info("Comparaison sans solaire non lancee.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Gain BT PAC", f"{(total_pac - no_solar_total_pac) / 1000:.0f} MWh")
    c2.metric("Ecart electricite PAC", f"{(no_solar_total_elec - total_elec) / 1000:.0f} MWh")
    c3.metric("Gain COP", f"{mean_cop - no_solar_cop:+.1f}", delta=f"{mean_cop:.1f} vs {no_solar_cop:.1f}")


def _render_parametric_pac_tab(parametric_pac_df: pd.DataFrame, *, calculation_id: str) -> None:
    st.markdown("### Etude parametrique géothermie seule : puissance PAC")
    st.caption("Dans cette étude, la surface solaire est forcée à 0. Le gaz couvre le besoin HT et le complément BT.")
    if parametric_pac_df.empty:
        st.info("Active l'étude paramétrique dans l'expander `8) Etude parametrique PAC geothermie`, puis relance le calcul.")
        return

    pac_cost_column = "Coût chaleur géothermie + appoint gaz (EUR/MWh)"
    best_row = parametric_pac_df.sort_values(pac_cost_column, ascending=True).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Meilleur % Pmax coût", f"{best_row['P PAC (% Pmax BT)']:.0f} %")
    c2.metric("P PAC correspondante", f"{best_row['P PAC (kW)']:.0f} kW")
    c3.metric("Coût géothermie + appoint gaz min", f"{best_row[pac_cost_column]:.0f} EUR/MWh")
    c4.metric("Couverture PAC BT", f"{best_row['Couverture PAC BT (%)']:.0f} %")
    g1, g2 = st.columns(2)
    g1.metric("Besoin HT gaz", f"{best_row['Besoin HT gaz (MWh/an)']:.0f} MWh/an")
    g2.metric("Complément BT gaz", f"{best_row['Complément BT gaz (MWh/an)']:.0f} MWh/an")
    st.altair_chart(_parametric_pac_chart(parametric_pac_df), width="stretch", key=f"parametric_pac_chart_{calculation_id}")
    st.dataframe(
        display_dataframe(parametric_pac_df),
        width="stretch",
        hide_index=True,
        key=f"parametric_pac_table_{calculation_id}",
    )


def _render_parametric_solar_tab(parametric_surface_df: pd.DataFrame, *, calculation_id: str) -> None:
    st.markdown("### Etude parametrique sur la surface solaire thermique")
    if parametric_surface_df.empty:
        st.info("Active l'étude paramétrique dans l'expander `9) Etude parametrique surface solaire`, puis relance le calcul.")
        return

    best_cost_column = "Coût chaleur Mix ENR (EUR/MWh)"
    best_row = parametric_surface_df.sort_values(best_cost_column, ascending=True).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Meilleure surface coût", f"{best_row['Surface solaire (m²)']:.0f} m²")
    c2.metric("Coût Mix EnR min", f"{best_row[best_cost_column]:.0f} EUR/MWh")
    c3.metric("Taux EnR global", f"{best_row['Taux EnR global (%)']:.0f} %")
    c4.metric("Couverture solaire HT", f"{best_row['Couverture solaire HT (%)']:.0f} %")
    if "Simulations economie sondes" in parametric_surface_df:
        s1, s2, s3 = st.columns(3)
        s1.metric("Linéaire estimé", f"{best_row.get('Lineaire estime (ml)', 0.0):.0f} ml")
        s2.metric("Linéaire vérifié", f"{best_row.get('Lineaire verifie (ml)', 0.0):.0f} ml")
        s3.metric("Simulations économie sondes", f"{int(best_row.get('Simulations economie sondes', 0))}")
    st.altair_chart(
        _parametric_surface_chart(parametric_surface_df),
        width="stretch",
        key=f"parametric_solar_chart_{calculation_id}",
    )
    st.dataframe(
        display_dataframe(parametric_surface_df),
        width="stretch",
        hide_index=True,
        key=f"parametric_solar_table_{calculation_id}",
    )


def _render_detail_tab(hourly_by_month_df: pd.DataFrame, hourly_profile_df: pd.DataFrame, hourly_df: pd.DataFrame) -> None:
    st.markdown("### Agregation par mois des resultats horaires")
    st.dataframe(display_dataframe(hourly_by_month_df), width="stretch", hide_index=True)

    if not hourly_profile_df.empty:
        with st.expander("Profil besoin horaire importe"):
            st.dataframe(
                display_dataframe(hourly_profile_df[["hour_index", "month", "day", "hour", "demand_ht_kwh", "demand_bt_kwh"]]),
                width="stretch",
                hide_index=True,
            )

    with st.expander("Table horaire brute"):
        st.dataframe(
            display_dataframe(
                hourly_df[
                    [
                        "Heure annee",
                        "month",
                        "day",
                        "hour",
                        "tair_c",
                        "demand_ht_kwh",
                        "solar_ht_to_buffer_kwh",
                        "solar_ht_from_buffer_kwh",
                        "unmet_ht_kwh",
                        "solar_to_btes_kwh",
                        "demand_bt_kwh",
                        "heat_bt_from_pac_kwh",
                        "electricity_compressor_kwh",
                        "electricity_pac_auxiliaries_kwh",
                        "electricity_standby_kwh",
                        "electricity_pac_total_kwh",
                        "electricity_system_total_kwh",
                        "electricity_pac_kwh",
                        "solar_ht_buffer_temp_end_c",
                        "T_paroi_forage_C",
                        "T_source_PAC_C",
                        "T_evaporateur_PAC_C",
                        "T_fluide_injection_C",
                        "q_extraction_W_m",
                        "q_injection_W_m",
                        "q_net_W_m",
                        "cop_pac",
                    ]
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with st.expander("Hypotheses restantes"):
        st.markdown(
            """
            - Les besoins process doivent venir d'un fichier Excel horaire 8760 h.
            - Les colonnes `E/P besoin HT` alimentent le besoin HT 60 C.
            - Les colonnes `E/P besoin BT` alimentent le besoin BT 25 C.
            - Le stockage solaire journalier est un volume d'eau equivalent.
            - Le solaire charge le ballon ; il ne va jamais directement au process.
            - Le ballon prechauffe le process HT jusqu'a 60 C si son niveau de temperature le permet.
            - La ressource solaire restante part vers le BTES uniquement quand le ballon ne peut plus absorber, donc quand il atteint `Tmax ballon`.
            - Le champ de sondes utilise pygfunction pour calculer la temperature source PAC.
            """
        )
