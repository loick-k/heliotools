from __future__ import annotations

import pandas as pd
import streamlit as st

from .charts import (
    _bar_chart,
    _line_chart,
    _multiyear_btes_annual_temperature_comparison_chart,
    _multiyear_btes_flux_chart,
    _multiyear_btes_temperature_chart,
    _multiyear_btes_temperature_comparison_chart,
    _parametric_pac_chart,
    _parametric_surface_chart,
    _percent_bar_chart,
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


EXTRACTION_WARNING_W_M = 50.0
EXTRACTION_STRONG_WARNING_W_M = 60.0
INJECTION_WARNING_W_M = 60.0
INJECTION_STRONG_WARNING_W_M = 80.0


def _render_kpi_styles() -> None:
    return None


def _render_kpi_section(
    title: str,
    metrics: list[tuple],
    *,
    caption: str | None = None,
    tone: str = "inputs",
) -> None:
    st.markdown(f"#### {title}")
    if caption:
        st.caption(caption)
    for start in range(0, len(metrics), 4):
        cols = st.columns(4)
        for col, metric in zip(cols, metrics[start : start + 4]):
            label = str(metric[0])
            value = str(metric[1])
            delta = str(metric[2]) if len(metric) > 2 and metric[2] else None
            help_text = str(metric[3]) if len(metric) > 3 and metric[3] else None
            col.metric(label, value, delta=delta, help=help_text)


def _scenario_economic_row(economic_comparison_df: pd.DataFrame, scenario_name: str) -> pd.Series | None:
    if economic_comparison_df.empty or "Scenario" not in economic_comparison_df:
        return None
    rows = economic_comparison_df[economic_comparison_df["Scenario"].astype(str) == scenario_name]
    if rows.empty:
        return None
    return rows.iloc[0]


def _row_float(row: pd.Series | None, column: str, default: float = 0.0) -> float:
    if row is None or column not in row:
        return default
    value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
    if pd.isna(value):
        return default
    return float(value)


def _trajectory_final_row(economic_trajectory_df: pd.DataFrame, scenario_name: str) -> pd.Series | None:
    if economic_trajectory_df.empty or "Scenario" not in economic_trajectory_df:
        return None
    rows = economic_trajectory_df[economic_trajectory_df["Scenario"].astype(str) == scenario_name]
    if rows.empty:
        return None
    if "Annee" in rows:
        return rows.sort_values("Annee").iloc[-1]
    return rows.iloc[-1]


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
    demand_scope: str = "ht_bt",
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
    normalized_demand_scope = str(demand_scope or "ht_bt").lower()
    show_solar_blocks = total_ht > 1e-6 and normalized_demand_scope != "bt_only"
    show_geothermal_blocks = total_bt > 1e-6 and normalized_demand_scope != "ht_only"
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
    geo_only_row = _scenario_economic_row(
        scenario.economic_comparison_df,
        "Geothermie seule",
    )
    same_borefield_row = _scenario_economic_row(
        scenario.economic_comparison_df,
        "Geothermie + solaire meme sondes",
    )
    reduced_borefield_row = _scenario_economic_row(
        scenario.economic_comparison_df,
        "Geothermie + solaire sondes reduites",
    )
    initial_borefield_cop = _row_float(same_borefield_row, "COP PAC moyen", mean_cop)
    initial_borefield_elec_mwh = _row_float(same_borefield_row, "Electricite PAC (MWh/an)", total_elec / 1000.0)
    reduced_borefield_available = (
        (bool(savings["found"]) or bool(savings.get("simulated", False)))
        and reduced_borefield_row is not None
    )
    reduced_borefield_length_m = _row_float(
        reduced_borefield_row,
        "Lineaire sondes (ml)",
        scenario.economic_borefield_length_m,
    )
    reduced_borefield_cop = _row_float(reduced_borefield_row, "COP PAC moyen", 0.0)
    reduced_borefield_elec_mwh = _row_float(reduced_borefield_row, "Electricite PAC (MWh/an)", 0.0)
    geo_only_final_row = _trajectory_final_row(scenario.economic_trajectory_df, "Geothermie seule")
    same_final_row = _trajectory_final_row(scenario.economic_trajectory_df, "Geothermie + solaire meme sondes")
    reduced_final_row = _trajectory_final_row(scenario.economic_trajectory_df, "Geothermie + solaire sondes reduites")

    st.subheader("Résumé technique")
    st.caption(
        f"Simulation technique champ : {scenario.simulation_years_total} an(s). "
        f"Année affichée pour les résultats techniques : {scenario.simulation_year_displayed}. "
        f"Économie : trajectoire de {scenario.economic_years_used} an(s). "
        f"Tmin opérationnelle PAC : {scenario.config.btes.t_min_c:.1f} °C ; "
        f"critère GMI {'actif' if scenario.gmi_check_enabled else 'inactif'} "
        f"({scenario.config.btes.gmi_t_min_c:.1f} / {scenario.config.btes.gmi_t_max_c:.1f} °C)."
    )
    equivalent_full_power_hours = total_pac / pac_nominal_power_kw if pac_nominal_power_kw > 0.0 else 0.0
    gmi_hours_low = int((hourly_df["T_fluide_entree_echangeur_geo_C"] < scenario.config.btes.gmi_t_min_c - 1e-6).sum())
    gmi_hours_high = int((hourly_df["T_fluide_injection_C"] > scenario.config.btes.gmi_t_max_c + 1e-6).sum())
    source_limit_hours = int(hourly_df["Limite_temperature_source"].sum())
    source_limit_energy = float(hourly_df["BT_non_couvert_limite_source_kWh"].sum()) / 1000.0
    solar_useful_kwh = total_preheat_ht + total_to_btes
    geothermal_renewable_kwh = max(total_pac - total_elec, 0.0)
    multiyear_years_count = scenario.simulation_years_total
    first_year_end_source_c = None
    final_year_end_source_c = None
    period_min_source_c = None
    if not multiyear_btes_df.empty:
        multiyear_years_count = int(multiyear_btes_df["Annee"].max())
        first_year_rows = multiyear_btes_df[multiyear_btes_df["Annee"] == 1]
        final_year_rows = multiyear_btes_df[multiyear_btes_df["Annee"] == multiyear_years_count]
        if not first_year_rows.empty:
            first_year_end_source_c = float(first_year_rows["T source PAC fin (C)"].iloc[-1])
        if not final_year_rows.empty:
            final_year_end_source_c = float(final_year_rows["T source PAC fin (C)"].iloc[-1])
        period_min_source_c = float(multiyear_btes_df["T source PAC min (C)"].min())
    final_btes_injection_mwh = 0.0
    final_btes_extraction_mwh = 0.0
    eta_btes_final = None
    if not multiyear_btes_df.empty and "Annee" in multiyear_btes_df:
        final_year_rows = multiyear_btes_df[multiyear_btes_df["Annee"] == int(multiyear_btes_df["Annee"].max())]
        final_btes_injection_mwh = float(final_year_rows.get("Injection BTES (MWh)", pd.Series(dtype=float)).sum())
        final_btes_extraction_mwh = float(final_year_rows.get("Extraction PAC (MWh)", pd.Series(dtype=float)).sum())
        if final_btes_injection_mwh > 1e-9:
            eta_btes_final = final_btes_extraction_mwh / final_btes_injection_mwh
    btes_diag = scenario.btes_diagnostics
    eta_btes_multi = btes_diag.get("eta_btes")
    ratio_injection_extraction = float(btes_diag.get("ratio_injection_extraction") or 0.0)
    geo_field_mode = str(btes_diag.get("geo_field_mode") or "GSHP_dominant")
    geo_field_mode_label = {
        "GSHP_dominant": "PAC dominante",
        "solar_recharged_borefield": "Champ recharge solaire",
        "BTES_like": "Fonctionnement proche BTES",
    }.get(geo_field_mode, geo_field_mode)
    solar_storage_volume_m3 = (
        float(scenario.config.collector.area_m2)
        * float(scenario.config.collector.daily_buffer_l_per_m2)
        / 1000.0
    )

    def _format_temp(value: float | None) -> str:
        if value is None:
            return "n.d."
        return f"{value:.1f} °C"

    _render_kpi_styles()
    ht_eff = _weighted_average_efficiency(hourly_df, "collector_eff_ht", "solar_ht_to_buffer_kwh")
    storage_eff = _weighted_average_efficiency(hourly_df, "collector_eff_storage", "solar_to_btes_kwh")
    ht_energy_mwh = float(hourly_df["solar_ht_to_buffer_kwh"].sum()) / 1000.0 if "solar_ht_to_buffer_kwh" in hourly_df else 0.0
    storage_energy_mwh = float(hourly_df["solar_to_btes_kwh"].sum()) / 1000.0 if "solar_to_btes_kwh" in hourly_df else 0.0
    combined_eff = (
        (ht_eff * ht_energy_mwh + storage_eff * storage_energy_mwh)
        / max(1e-9, ht_energy_mwh + storage_energy_mwh)
        if ht_energy_mwh + storage_energy_mwh > 1e-9
        else 0.0
    )

    input_metrics: list[tuple[str, str] | tuple[str, str, str | None]] = []
    if show_solar_blocks:
        input_metrics.extend(
            [
                ("Surface solaire", f"{scenario.config.collector.area_m2:.0f} m²"),
                ("Volume stockage solaire", f"{solar_storage_volume_m3:.0f} m³"),
            ]
        )
    if show_geothermal_blocks:
        input_metrics.extend(
            [
                ("P PAC géothermie retenue", f"{pac_nominal_power_kw:.0f} kW", f"{pac_power_fraction_pct:.0f} % Pmax"),
                ("Linéaire sondes", f"{scenario.full_borefield_length_m:.0f} ml"),
            ]
        )
    _render_kpi_section("Données d'entrée principales", input_metrics, tone="inputs")
    if not show_solar_blocks and not show_geothermal_blocks:
        st.warning("Aucun besoin HT ou BT actif dans le périmètre de calcul.")

    energy_metrics: list[tuple[str, str] | tuple[str, str, str | None]] = [
        ("Besoin total", f"{(total_ht + total_bt) / 1000:.0f} MWh")
    ]
    if show_solar_blocks:
        energy_metrics.extend(
            [
                ("Besoin haute température", f"{total_ht / 1000:.0f} MWh"),
                ("Production solaire ECS", f"{total_preheat_ht / 1000:.0f} MWh"),
            ]
        )
    if show_geothermal_blocks:
        energy_metrics.extend(
            [
                ("Besoin basse température", f"{total_bt / 1000:.0f} MWh"),
                ("Part EnR PAC géothermie", f"{geothermal_renewable_kwh / 1000:.0f} MWh"),
                ("Électricité PAC", f"{total_elec / 1000:.0f} MWh"),
            ]
        )
    energy_metrics.extend(
        [
            ("Consommation appoint gaz", f"{(total_backup_ht + total_backup_bt) / 1000:.0f} MWh"),
            ("Taux EnR global", f"{global_ren_rate * 100:.0f} %"),
        ]
    )
    _render_kpi_section(
        "Besoins et production par générateur",
        energy_metrics,
        caption="Lecture comptable limitée au périmètre actif : les blocs et KPI sans besoin associé sont masqués.",
        tone="energy",
    )
    if show_solar_blocks:
        _render_kpi_section(
            "Solaire thermique",
            [
                ("Production solaire totale", f"{solar_useful_kwh / 1000:.0f} MWh"),
                ("Production solaire ECS", f"{total_preheat_ht / 1000:.0f} MWh"),
                ("Production solaire injectée dans le BTES", f"{total_to_btes / 1000:.0f} MWh"),
                ("Productivité solaire valorisée", f"{solar_productivity_valued:.0f} kWh/m².an"),
                ("Taux de couverture solaire HT", f"{annual_ht_solar_coverage * 100:.0f} %"),
                ("η solaire ECS", f"{ht_eff * 100:.1f} %", f"{ht_energy_mwh:.0f} MWh captés"),
                ("η solaire BTES", f"{storage_eff * 100:.1f} %", f"{storage_energy_mwh:.0f} MWh injectés"),
                ("η solaire global", f"{combined_eff * 100:.1f} %" if combined_eff > 0.0 else "non disponible"),
            ],
            tone="solar",
        )

    def _scenario_pac_metrics(
        *,
        row: pd.Series | None,
        final_row: pd.Series | None,
        length_m: float,
        fallback_cop: float,
        fallback_elec_mwh: float,
        fallback_pac_mwh: float,
        available: bool = True,
    ) -> list[tuple]:
        if not available:
            return [
                ("Pmax besoin BT", f"{peak_bt_power_kw:.0f} kW"),
                ("Linéaire sondes", "non déterminé"),
                ("COP machine PAC", "n.d.", None, "Chaleur BT produite par la PAC divisée par l'électricité du compresseur uniquement."),
                ("SPF PAC avec auxiliaires", "n.d.", None, "Chaleur BT produite par la PAC divisée par l'électricité totale PAC : compresseur, pompes, auxiliaires et veille/régulation."),
                ("Électricité PAC", "n.d."),
                ("Chaleur PAC BT", "n.d."),
                ("Couverture PAC BT", "n.d."),
                ("Heures pleine puissance PAC", "n.d."),
                ("Appoint gaz année finale", "n.d."),
                ("T source min année finale", "n.d."),
                ("Heures limite source", "n.d."),
                ("Heures hors GMI", "n.d."),
                ("q extraction max", "n.d."),
                ("q injection max", "n.d."),
            ]

        cop = _row_float(final_row, "COP moyen", _row_float(row, "COP PAC moyen", fallback_cop))
        elec_mwh = _row_float(final_row, "Electricite PAC (MWh)", _row_float(row, "Electricite PAC (MWh/an)", fallback_elec_mwh))
        pac_mwh = _row_float(final_row, "Chaleur PAC BT (MWh)", fallback_pac_mwh)
        spf_pac = _row_float(
            final_row,
            "SPF PAC complet",
            pac_mwh / max(1e-9, elec_mwh) if elec_mwh > 0.0 else 0.0,
        )
        coverage_pct = _row_float(final_row, "Couverture PAC BT (%)", _row_float(row, "Couverture PAC BT (%)", 0.0))
        full_power_h = _row_float(final_row, "Heures equivalentes PAC BT", pac_mwh * 1000.0 / max(1e-9, pac_nominal_power_kw))
        backup_mwh = _row_float(final_row, "Appoint gaz total (MWh)", 0.0)
        t_source_min_c = _row_float(final_row, "T_source_PAC_min (C)", _row_float(row, "T source min annee finale (C)", 0.0))
        source_limited_h = _row_float(final_row, "Heures limite source", _row_float(row, "Heures limite source annee finale", 0.0))
        hours_gmi = _row_float(final_row, "Heures sous Tmin GMI", 0.0) + _row_float(final_row, "Heures sur Tmax GMI", 0.0)
        q_extract = _row_float(final_row, "q_extraction_W_m_max", 0.0)
        q_inject = _row_float(final_row, "q_injection_W_m_max", 0.0)
        return [
            ("Pmax besoin BT", f"{peak_bt_power_kw:.0f} kW"),
            ("Linéaire sondes", f"{length_m:.0f} ml"),
            (
                "COP machine PAC",
                f"{cop:.1f}" if cop > 0.0 else "n.d.",
                None,
                "Chaleur BT produite par la PAC divisée par l'électricité du compresseur uniquement.",
            ),
            (
                "SPF PAC avec auxiliaires",
                f"{spf_pac:.1f}" if spf_pac > 0.0 else "n.d.",
                None,
                "Chaleur BT produite par la PAC divisée par l'électricité totale PAC : compresseur, pompes, auxiliaires et veille/régulation.",
            ),
            ("Électricité PAC totale", f"{elec_mwh:.0f} MWh/an"),
            ("Chaleur PAC BT", f"{pac_mwh:.0f} MWh"),
            ("Couverture PAC BT", f"{coverage_pct:.0f} %"),
            ("Heures pleine puissance PAC", f"{full_power_h:.0f} h/an"),
            ("Appoint gaz année finale", f"{backup_mwh:.0f} MWh"),
            ("T source min année finale", f"{t_source_min_c:.1f} °C"),
            ("Heures limite source", f"{source_limited_h:.0f} h"),
            ("Heures hors GMI", f"{hours_gmi:.0f} h"),
            ("q extraction max", f"{q_extract:.0f} W/m"),
            ("q injection max", f"{q_inject:.0f} W/m"),
        ]

    if show_geothermal_blocks:
        st.markdown("#### PAC géothermie")
        geo_only_hours_gmi = _row_float(geo_only_final_row, "Heures sous Tmin GMI", 0.0) + _row_float(
            geo_only_final_row,
            "Heures sur Tmax GMI",
            0.0,
        )
        geo_only_t_source_min_c = _row_float(geo_only_final_row, "T_source_PAC_min (C)", 0.0)
        _render_kpi_section(
            "Géothermie seule",
            _scenario_pac_metrics(
                row=geo_only_row,
                final_row=geo_only_final_row,
                length_m=scenario.full_borefield_length_m,
                fallback_cop=no_solar_cop,
                fallback_elec_mwh=no_solar_total_elec / 1000.0,
                fallback_pac_mwh=no_solar_total_pac / 1000.0,
                available=no_solar_cop > 0.0,
            ),
            caption=(
                "Indicateurs techniques de l'année finale. COP machine PAC = chaleur BT produite par la PAC "
                "/ électricité du compresseur uniquement."
            ),
            tone="pac",
        )
        if geo_only_hours_gmi > 0.0:
            st.warning(
                "Référence géothermie seule non conforme au critère GMI "
                f"({geo_only_hours_gmi:.0f} h hors plage, T source min {geo_only_t_source_min_c:.1f} °C). "
                "L'économie de sondes du scénario C doit être lue avec prudence : le champ de référence est déjà "
                "trop sollicité. Conseil : augmenter le linéaire de sondes en priorité, ou réduire la puissance PAC "
                "appelée/sa couverture BT si le besoin peut accepter davantage d'appoint."
            )
        if show_solar_blocks:
            scenario_c_simulated = bool(savings.get("simulated", False))
            scenario_c_validated = bool(savings.get("found", False))
            scenario_c_candidate_length = float(
                savings.get("candidate_length_m", savings.get("equivalent_length_m", reduced_borefield_length_m))
                or 0.0
            )
            scenario_c_saved_retained = float(savings.get("saved_length_m", 0.0) or 0.0)
            _render_kpi_section(
                "Géothermie avec recharge solaire",
                _scenario_pac_metrics(
                    row=same_borefield_row,
                    final_row=same_final_row,
                    length_m=scenario.full_borefield_length_m,
                    fallback_cop=mean_cop,
                    fallback_elec_mwh=total_elec / 1000.0,
                    fallback_pac_mwh=total_pac / 1000.0,
                ),
                caption=(
                    "Indicateurs techniques de l'année finale. L'électricité PAC totale inclut compresseur, "
                    "pompes/auxiliaires et veille/régulation."
                ),
                tone="pac",
            )
            _render_kpi_section(
                "Géothermie avec recharge solaire et linéaire de sondes réduites",
                _scenario_pac_metrics(
                    row=reduced_borefield_row,
                    final_row=reduced_final_row,
                    length_m=reduced_borefield_length_m,
                    fallback_cop=reduced_borefield_cop,
                    fallback_elec_mwh=reduced_borefield_elec_mwh,
                    fallback_pac_mwh=0.0,
                    available=reduced_borefield_available,
                ),
                caption=(
                    "Indicateurs techniques de l'année finale pour le champ réduit simulé. "
                    "La réduction économique reste validée uniquement si les critères d'équivalence sont respectés."
                ),
                tone="pac",
            )
            if bool(savings.get("simulated", False)) and not bool(savings["found"]):
                st.caption(
                    "Scénario réduit affiché à titre exploratoire : le calcul physique a été réalisé, "
                    "mais l'économie de sondes n'est pas validée comme équivalente aux critères de référence."
                )
            if str(savings.get("message", "")).strip():
                st.caption(f"Statut économie de sondes : {savings['message']}")
            _render_kpi_section(
                "Statut scénario C - réduction de sondes",
                [
                    ("Calcul physique", "réalisé" if scenario_c_simulated else "non lancé"),
                    ("Réduction validée", "oui" if scenario_c_validated else "non"),
                    ("Linéaire testé", f"{scenario_c_candidate_length:.0f} ml" if scenario_c_simulated else "n.d."),
                    ("Gain économique retenu", f"{scenario_c_saved_retained:.0f} ml" if scenario_c_validated else "0 ml"),
                ],
                caption=(
                    "Le scénario C peut être calculé physiquement sans être retenu comme économie de sondes. "
                    "Le gain économique reste à 0 ml tant que les critères d'équivalence ne sont pas validés."
                ),
                tone="pac",
            )

        full_length_m = max(1e-9, float(scenario.full_borefield_length_m))
        extraction_kwh_per_m_year = final_btes_extraction_mwh * 1000.0 / full_length_m
        injection_kwh_per_m_year = final_btes_injection_mwh * 1000.0 / full_length_m
        q_extraction_max_year = float(hourly_df["q_extraction_w_m"].max()) if "q_extraction_w_m" in hourly_df else 0.0
        q_injection_max_year = float(hourly_df["q_injection_w_m"].max()) if "q_injection_w_m" in hourly_df else 0.0

        pac_security_metrics: list[tuple[str, str] | tuple[str, str, str | None]] = [
            ("Limite source PAC", f"{source_limit_hours} h", f"{source_limit_energy:.1f} MWh"),
            ("q extraction max année affichée", f"{q_extraction_max_year:.0f} W/ml"),
            ("q injection max année affichée", f"{q_injection_max_year:.0f} W/ml"),
            ("Énergie extraite sol", f"{extraction_kwh_per_m_year:.0f} kWh/ml.an"),
            ("Énergie injectée BTES", f"{injection_kwh_per_m_year:.0f} kWh/ml.an"),
            ("T source fin année 1", _format_temp(first_year_end_source_c)),
            (
                f"T source fin année {multiyear_years_count}",
                _format_temp(final_year_end_source_c),
                (
                    f"{final_year_end_source_c - first_year_end_source_c:+.1f} °C"
                    if final_year_end_source_c is not None and first_year_end_source_c is not None
                    else None
                ),
            ),
            ("T source min période", _format_temp(period_min_source_c)),
            (
                "Heures sous Tmin opérationnelle",
                f"{int((hourly_df['T_source_PAC_pour_COP_C'] <= scenario.config.btes.t_min_c + 1e-6).sum())} h",
            ),
            ("Heures hors GMI", f"{gmi_hours_low + gmi_hours_high} h"),
            ("T fluide injection max", f"{float(hourly_df['T_fluide_injection_C'].max()):.1f} °C"),
        ]
        if show_solar_blocks:
            pac_security_metrics.extend(
                [
                    ("Injection BTES année finale", f"{final_btes_injection_mwh:.0f} MWh"),
                    ("Extraction sol année finale", f"{final_btes_extraction_mwh:.0f} MWh"),
                    ("eta_BTES année finale", f"{eta_btes_final:.2f}" if eta_btes_final is not None else "non applicable"),
                    ("eta_BTES multiannuel", f"{float(eta_btes_multi):.2f}" if eta_btes_multi is not None else "non applicable"),
                    ("Ratio injection/extraction", f"{ratio_injection_extraction:.2f}"),
                ]
            )
        _render_kpi_section(
            "Champ de sondes et sécurité - scénario B",
            pac_security_metrics,
            caption="Ces indicateurs décrivent le scénario principal avec recharge solaire et linéaire initial.",
            tone="pac",
        )
        if btes_diag.get("geo_field_mode_comment"):
            st.caption(str(btes_diag["geo_field_mode_comment"]))
        if btes_diag.get("warning"):
            st.warning(str(btes_diag["warning"]))
        if btes_diag.get("surface_insulation_warning"):
            st.warning(str(btes_diag["surface_insulation_warning"]))

        _render_kpi_section(
            "Synthèse P1 électrique - géothermie" + (" avec recharge solaire" if show_solar_blocks else " seule"),
            [
                ("Électricité compresseur PAC", f"{total_compressor / 1000.0:.1f} MWh/an"),
                ("Forfait pompes + auxiliaires PAC", f"{total_auxiliaries / 1000.0:.1f} MWh/an"),
                ("Veille/régulation", f"{total_standby / 1000.0:.1f} MWh/an"),
                ("Électricité totale PAC", f"{total_elec / 1000.0:.1f} MWh/an"),
            ],
            caption=(
                "Ces indicateurs correspondent au scénario principal affiché : "
                + ("géothermie avec recharge solaire et linéaire initial." if show_solar_blocks else "géothermie seule sur le besoin BT.")
                + " Les indicateurs de performance COP/SPF sont affichés directement dans les blocs de scénarios."
            ),
            tone="pac",
        )

        _render_btes_warnings(
            scenario=scenario,
            hourly_df=hourly_df,
            btes_backend_used=btes_backend_used,
            probe_power_ratio_w_m=probe_power_ratio_w_m,
        )
        if show_solar_blocks and no_solar_cop > 0.0:
            _render_borefield_savings_explanation(
                scenario=scenario,
                no_solar_cop=no_solar_cop,
                no_solar_total_pac=scenario.no_solar_total_pac_kwh,
            )

    _render_kpi_section(
        "Appoint gaz",
        [("Pic appoint gaz appelé", f"{backup_power_kw:.0f} kW")],
        tone="gas",
    )

    result_sections = []
    if show_geothermal_blocks:
        result_sections.append("Analyse solaire et géothermie" if show_solar_blocks else "Analyse géothermie")
        result_sections.append("Multiannuel BTES")
    result_sections.extend(["Monotone horaire", "Analyses mensuelles", "Économie"])
    if show_geothermal_blocks:
        result_sections.append("Paramétrique PAC")
    if show_solar_blocks:
        result_sections.append("Paramétrique solaire")
    result_sections.append("Données")

    result_section = st.radio(
        "Section de résultats",
        result_sections,
        horizontal=True,
        key=f"result_section_{calculation_id}",
    )

    if result_section in {"Analyse solaire et géothermie", "Analyse géothermie"}:
        title = "Grandeurs solaires et géothermie horaire" if show_solar_blocks else "Grandeurs géothermie horaire"
        st.markdown(f"### {title} - année {scenario.simulation_year_displayed}")
        st.caption(
            "T source PAC n'est pas une température moyenne du sous-sol : c'est la température côté source géothermique "
            "vue par la PAC. La température de paroi forage est affichée séparément."
        )
        st.altair_chart(_temperature_chart(hourly_df), width="stretch")

    elif result_section == "Multiannuel BTES":
        _render_multiyear_tab(
            scenario,
            multiyear_btes_df,
            no_solar_multiyear_btes_df,
            scenario.reduced_multiyear_btes_df,
        )

    elif result_section == "Monotone horaire":
        _render_duration_tab(hourly_df)

    elif result_section == "Analyses mensuelles":
        _render_monthly_tab(
            annual_df=annual_df,
            hourly_by_month_df=hourly_by_month_df,
        )

    elif result_section.endswith("conomie"):
        render_economics_tab(
            economic_comparison_df=scenario.economic_comparison_df,
            economic_comparison_chart_df=scenario.economic_comparison_chart_df,
            economic_trajectory_df=scenario.economic_trajectory_df,
            recharge_value=scenario.recharge_value,
            heat_costs=scenario.heat_costs,
            total_compressor=total_compressor,
            total_auxiliaries=total_auxiliaries,
            total_standby=total_standby,
            total_elec=total_elec,
            mean_cop=mean_cop,
            spf_pac_total=spf_pac_total,
            spf_system=spf_system,
        )

    elif result_section.endswith("PAC"):
        _render_parametric_pac_tab(parametric_pac_df, calculation_id=calculation_id)

    elif result_section.endswith("solaire"):
        _render_parametric_solar_tab(parametric_surface_df, calculation_id=calculation_id)

    else:
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
    k1.metric("η solaire ECS", f"{ht_eff * 100:.1f} %", delta=f"{ht_energy_mwh:.0f} MWh captés")
    k2.metric("η solaire BTES", f"{storage_eff * 100:.1f} %", delta=f"{storage_energy_mwh:.0f} MWh injectés")
    if ht_energy_mwh + storage_energy_mwh > 1e-9:
        combined_eff = (
            ht_eff * ht_energy_mwh + storage_eff * storage_energy_mwh
        ) / max(1e-9, ht_energy_mwh + storage_energy_mwh)
        k3.metric("η solaire global", f"{combined_eff * 100:.1f} %")
    else:
        k3.metric("η solaire global", "non disponible")


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
    if btes_backend_used == "pygfunction" and hours_at_tmin > 0:
        st.warning(
            f"Backend pygfunction : la température source atteint Tmin pendant {hours_at_tmin} h/an. "
            f"Ce diagnostic porte sur le champ complet simulé en 8760 h ({scenario.full_borefield_length_m:.0f} ml), "
            "pas sur le scénario économique à sondes réduites. Le champ est probablement trop sollicité ou trop court "
            "pour ce modèle ; le COP est alors borné à Tmin et la chaleur BT non couverte par la PAC bascule en appoint gaz."
        )
    if max_extraction_w_m >= scenario.config.btes.max_extraction_w_m - 1e-6:
        st.warning(
            f"Limite dure d'extraction atteinte : {max_extraction_w_m:.0f} W/ml "
            f"pour une limite de {scenario.config.btes.max_extraction_w_m:.0f} W/ml. "
            "La puissance PAC peut être bridée par la limite horaire de simulation."
        )
    elif max_extraction_w_m > EXTRACTION_STRONG_WARNING_W_M:
        st.warning(
            f"Vigilance forte extraction : q extraction max = {max_extraction_w_m:.0f} W/ml, "
            f"au-dessus du seuil fort de {EXTRACTION_STRONG_WARNING_W_M:.0f} W/ml."
        )
    elif max_extraction_w_m > EXTRACTION_WARNING_W_M:
        st.warning(
            f"Vigilance extraction : q extraction max = {max_extraction_w_m:.0f} W/ml, "
            f"au-dessus du seuil de lecture de {EXTRACTION_WARNING_W_M:.0f} W/ml."
        )
    if max_injection_w_m >= scenario.config.btes.max_injection_w_m - 1e-6:
        st.warning(
            f"Limite dure d'injection atteinte : {max_injection_w_m:.0f} W/ml "
            f"pour une limite de {scenario.config.btes.max_injection_w_m:.0f} W/ml."
        )
    elif max_injection_w_m > INJECTION_STRONG_WARNING_W_M:
        st.warning(
            f"Vigilance forte injection : q injection max = {max_injection_w_m:.0f} W/ml, "
            f"au-dessus du seuil fort de {INJECTION_STRONG_WARNING_W_M:.0f} W/ml."
        )
    elif max_injection_w_m > INJECTION_WARNING_W_M:
        st.warning(
            f"Vigilance injection : q injection max = {max_injection_w_m:.0f} W/ml, "
            f"au-dessus du seuil de lecture de {INJECTION_WARNING_W_M:.0f} W/ml."
        )
    if max_extraction_w_m > EXTRACTION_WARNING_W_M or max_injection_w_m > INJECTION_WARNING_W_M:
        st.caption(
            "Les ratios de prédimensionnement ne sont pas des limites physiques instantanées. "
            "Les pointes horaires peuvent être supérieures si les températures restent compatibles "
            "avec les critères de fonctionnement et GMI."
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


def _render_multiyear_tab(
    scenario: ScenarioResult,
    multiyear_btes_df: pd.DataFrame,
    no_solar_multiyear_btes_df: pd.DataFrame,
    reduced_multiyear_btes_df: pd.DataFrame,
) -> None:
    st.markdown("### Évolution multiannuelle du champ de sondes")
    if multiyear_btes_df.empty:
        st.info("Projection multiannuelle indisponible.")
        return

    years_count = int(multiyear_btes_df["Annee"].max())
    st.caption(
        "Projection physique obtenue en répétant la même météo EPW et les mêmes besoins horaires "
        f"sur {years_count} ans. La comparaison mensuelle montre les fluctuations saisonnières ; "
        "la comparaison annuelle montre la dérive long terme des scénarios A, B et C."
    )

    monthly_frames = [
        no_solar_multiyear_btes_df.assign(Scenario="A - Géothermie seule")
        if not no_solar_multiyear_btes_df.empty
        else pd.DataFrame(),
        multiyear_btes_df.assign(Scenario="B - Géothermie avec recharge solaire"),
        reduced_multiyear_btes_df.assign(Scenario="C - Recharge solaire et linéaire réduit")
        if not reduced_multiyear_btes_df.empty
        else pd.DataFrame(),
    ]
    non_empty_monthly_frames = [frame for frame in monthly_frames if not frame.empty]
    monthly_comparison_df = (
        pd.concat(non_empty_monthly_frames, ignore_index=True)
        if non_empty_monthly_frames
        else pd.DataFrame()
    )

    annual_frames: list[pd.DataFrame] = []
    trajectory_df = scenario.economic_trajectory_df
    if not trajectory_df.empty and {"Scenario", "Annee", "T_source_PAC_min (C)"}.issubset(trajectory_df.columns):
        labels = {
            "Geothermie seule": "A - Géothermie seule",
            "Geothermie + solaire meme sondes": "B - Géothermie avec recharge solaire",
            "Geothermie + solaire sondes reduites": "C - Recharge solaire et linéaire réduit",
        }
        for raw_name, label in labels.items():
            rows = trajectory_df[trajectory_df["Scenario"].astype(str) == raw_name].copy()
            if rows.empty:
                continue
            annual_frames.append(
                pd.DataFrame(
                    {
                        "Annee": pd.to_numeric(rows["Annee"], errors="coerce"),
                        "Scenario": label,
                        "T source PAC min (C)": pd.to_numeric(rows["T_source_PAC_min (C)"], errors="coerce"),
                        "Heures limite source": pd.to_numeric(rows.get("Heures limite source", 0.0), errors="coerce"),
                    }
                )
            )
    non_empty_annual_frames = [frame for frame in annual_frames if not frame.empty]
    annual_comparison_df = (
        pd.concat(non_empty_annual_frames, ignore_index=True)
        if non_empty_annual_frames
        else pd.DataFrame()
    )

    chart_col_1, chart_col_2 = st.columns(2)
    if not monthly_comparison_df.empty:
        with chart_col_1:
            st.markdown("### Fluctuations mensuelles - scénarios A, B et C")
            st.altair_chart(_multiyear_btes_temperature_comparison_chart(monthly_comparison_df), width="stretch")
    else:
        with chart_col_1:
            st.markdown("### Fluctuations mensuelles - scénarios A, B et C")
            st.info("Comparaison mensuelle indisponible.")
    with chart_col_2:
        st.markdown("### Dérive annuelle - scénarios A, B et C")
        if annual_comparison_df.empty:
            st.info("Comparaison annuelle indisponible.")
        else:
            st.altair_chart(_multiyear_btes_annual_temperature_comparison_chart(annual_comparison_df), width="stretch")
    chart_col_3, chart_col_4 = st.columns(2)
    with chart_col_3:
        st.markdown("### Températures détaillées - scénario B")
        st.altair_chart(_multiyear_btes_temperature_chart(multiyear_btes_df), width="stretch")
    with chart_col_4:
        st.markdown("### Flux mensuels - scénario B")
        st.altair_chart(_multiyear_btes_flux_chart(multiyear_btes_df), width="stretch")
    with st.expander("Données mensuelles - scénario B", expanded=False):
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
) -> None:
    st.markdown("### Bilan annuel, calculé depuis les 8760 heures")
    st.dataframe(display_dataframe(annual_df[["Poste", "MWh/an"]]), width="stretch", hide_index=True)

    coverage_rate_df = hourly_by_month_df[["Mois", "Taux couverture solaire HT (%)"]].rename(
        columns={"Taux couverture solaire HT (%)": "Valeur"}
    )
    ground_flux_df = pd.concat(
        [
            hourly_by_month_df[["Mois", "Injection BTES (MWh)"]].rename(columns={"Injection BTES (MWh)": "Valeur"}).assign(Poste="Injection solaire BTES"),
            hourly_by_month_df[["Mois", "Extraction champ PAC (MWh)"]].rename(columns={"Extraction champ PAC (MWh)": "Valeur"}).assign(Poste="Extraction champ vers PAC"),
            hourly_by_month_df[["Mois", "Bilan net sol (MWh)"]].rename(columns={"Bilan net sol (MWh)": "Valeur"}).assign(Poste="Bilan net sol"),
        ],
        ignore_index=True,
    )
    ground_flux_df.loc[ground_flux_df["Poste"] == "Extraction champ vers PAC", "Valeur"] *= -1.0

    chart_a, chart_b = st.columns(2)
    with chart_a:
        st.markdown("### Couverture solaire HT")
        st.altair_chart(_percent_bar_chart(coverage_rate_df, y_title="Couverture solaire HT (%)"), width="stretch")
        st.caption(
            "La priorité HT est appliquée au pas horaire via le ballon solaire journalier. "
            "Une injection BTES mensuelle peut donc coexister avec un taux HT inférieur à 100 %."
        )
    with chart_b:
        st.markdown("### Flux sous-sol")
        st.altair_chart(_bar_chart(ground_flux_df), width="stretch")
        st.caption(
            "Les extractions PAC sont affichées négatives. Le bilan net sol correspond à extraction PAC - injection solaire."
        )

    chart_c, chart_d = st.columns(2)
    with chart_c:
        st.markdown("### Production solaire ECS et injection BTES")
        st.altair_chart(
            _bar_chart(_melt_monthly(hourly_by_month_df, ["Prechauffage HT solaire (MWh)", "Injection BTES (MWh)"])),
            width="stretch",
        )
    with chart_d:
        st.markdown("### Couverture besoin HT")
        st.altair_chart(
            _bar_chart(_melt_monthly(hourly_by_month_df, ["Prechauffage HT solaire (MWh)", "Appoint HT (MWh)"])),
            width="stretch",
        )

    chart_e, _chart_empty = st.columns(2)
    with chart_e:
        st.markdown("### Couverture besoin BT")
        st.altair_chart(_bar_chart(_melt_monthly(hourly_by_month_df, ["BT PAC (MWh)", "Appoint BT (MWh)"])), width="stretch")


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

    if not hourly_profile_df.empty and st.checkbox("Afficher le profil besoin horaire importe", value=False):
        st.dataframe(
            display_dataframe(hourly_profile_df[["hour_index", "month", "day", "hour", "demand_ht_kwh", "demand_bt_kwh"]]),
            width="stretch",
            hide_index=True,
        )

    if st.checkbox("Afficher la table horaire brute", value=False):
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

    with st.expander("Hypothèses restantes"):
        st.markdown(
            """
            - Les besoins process doivent venir d'un fichier Excel horaire 8760 h.
            - Les colonnes `E/P besoin HT` alimentent le besoin HT 60 °C.
            - Les colonnes `E/P besoin BT` alimentent le besoin BT 25 °C.
            - Le stockage solaire journalier est un volume d'eau equivalent.
            - Le solaire charge le ballon ; il ne va jamais directement au process.
            - Le ballon préchauffe le process HT jusqu'à sa température cible si son niveau de température le permet.
            - La ressource solaire restante part vers le BTES uniquement quand le ballon ne peut plus absorber, donc quand il atteint `Tmax ballon`.
            - Le champ de sondes utilise pygfunction pour calculer la température source PAC.
            """
        )
