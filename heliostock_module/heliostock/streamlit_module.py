from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from .app_service import HourlyCalculationRequest, run_hourly_calculation
from .ui_formatting import display_dataframe
from .ui_forms import (
    render_demand_form,
    render_calculation_selection_form,
    render_economics_form,
    render_geothermal_form,
    render_parametric_forms,
    render_solar_form,
    render_weather_form,
)
from .ui_results import render_hourly_results


def render_heliostock_hourly() -> pd.DataFrame:
    """Render the hourly-only HelioStock module."""

    st.header("HelioStock horaire")
    st.caption(
        "Resolution 8760 h EPW : capteurs -> ballon solaire journalier -> prechauffage HT, "
        "surplus vers BTES, PAC geothermique pour le process BT."
    )
    st.info(
        "Charge un fichier Excel de besoins horaires 8760 h pour lancer le calcul. "
        "Aucun profil mensuel de secours n'est utilise."
    )

    weather_form = render_weather_form()
    demand_form = render_demand_form(weather_form.hourly_weather)
    if not demand_form.valid:
        return pd.DataFrame()

    solar_form = render_solar_form()
    geothermal_form = render_geothermal_form(
        hourly_weather=weather_form.hourly_weather,
        demands=demand_form.demands,
        hourly_demand_override=demand_form.hourly_demand_override,
    )
    economics_inputs = render_economics_form()
    calculation_selection_form = render_calculation_selection_form()
    final_calculation_profile = calculation_selection_form.selection.calculation_profile == "calcul_final"
    if final_calculation_profile:
        parametric_forms = render_parametric_forms(solar_form.inputs.area_m2)
    else:
        st.info(
            "Les etudes parametriques PAC et solaire sont masquees pour ce profil. "
            "Selectionne `Calcul final complet - 25 ans, economie sondes et parametriques` pour les afficher et les lancer."
        )
        parametric_forms = render_parametric_forms(solar_form.inputs.area_m2, disabled=True)

    if not weather_form.hourly_weather:
        return pd.DataFrame()

    run_clicked = st.button("Lancer le profil de calcul selectionne", type="primary", width="stretch")
    if not run_clicked and "heliostock_last_result" not in st.session_state:
        st.info("Paramètres prêts. Clique sur **Lancer le calcul** pour exécuter la simulation horaire.")
        return pd.DataFrame()

    if run_clicked:
        st.session_state.pop("heliostock_last_result", None)
        progress = st.progress(0, text="Préparation des hypothèses de calcul...")
        try:
            calculation = run_hourly_calculation(
                HourlyCalculationRequest(
                    weather=weather_form.hourly_weather,
                    demands=demand_form.demands,
                    hourly_demand_override=demand_form.hourly_demand_override,
                    solar=solar_form.inputs,
                    btes=geothermal_form.btes,
                    heat_pump=geothermal_form.heat_pump,
                    economics=economics_inputs,
                    pac_power_fraction_pct=geothermal_form.pac_power_fraction_pct,
                    use_probe_predesign=geothermal_form.use_probe_predesign,
                    probe_power_ratio_w_m=geothermal_form.probe_power_ratio_w_m,
                    probe_energy_ratio_kwh_m=geothermal_form.probe_energy_ratio_kwh_m,
                    probe_unit_depth_m=geothermal_form.probe_unit_depth_m,
                    calculation_selection=calculation_selection_form.selection,
                    pac_parametric=parametric_forms.pac,
                    solar_parametric=parametric_forms.solar,
                ),
                progress=lambda value, text: progress.progress(value, text=text),
            )
        except (ImportError, RuntimeError) as exc:
            progress.empty()
            st.error(
                "Le calcul champ de sondes utilise pygfunction. Installe les dépendances avec "
                "`pip install -r requirements.txt`, puis relance le calcul."
            )
            st.caption(str(exc))
            return pd.DataFrame()
        except Exception as exc:
            progress.empty()
            st.error("Le calcul a échoué. Le détail technique est affiché ci-dessous pour faciliter le diagnostic.")
            st.exception(exc)
            return pd.DataFrame()
        for warning in calculation.warnings:
            st.warning(warning)
        progress.progress(100, text="Calcul terminé.")
        calculation_id = str(time.time_ns())
        st.session_state["heliostock_last_result"] = {
            "calculation_id": calculation_id,
            "scenario": calculation.scenario,
            "parametric_pac_df": calculation.parametric_pac_df.copy(),
            "parametric_surface_df": calculation.parametric_surface_df.copy(),
            "peak_bt_power_kw": calculation.peak_bt_power_kw,
            "pac_nominal_power_kw": calculation.pac_nominal_power_kw,
            "pac_power_fraction_pct": calculation.pac_power_fraction_pct,
            "btes_backend": calculation.btes_backend,
            "performance_log_df": calculation.performance_log_df.copy(),
        }
    else:
        st.info("Affichage du dernier calcul. Modifie les paramètres puis clique sur **Lancer le calcul** pour recalculer.")

    last_result = st.session_state["heliostock_last_result"]
    scenario = last_result["scenario"]
    render_started_at = time.perf_counter()
    hourly_df = render_hourly_results(
        scenario=scenario,
        parametric_pac_df=last_result["parametric_pac_df"],
        parametric_surface_df=last_result["parametric_surface_df"],
        calculation_id=str(last_result.get("calculation_id", "last")),
        peak_bt_power_kw=float(last_result["peak_bt_power_kw"]),
        pac_nominal_power_kw=float(last_result["pac_nominal_power_kw"]),
        pac_power_fraction_pct=float(last_result["pac_power_fraction_pct"]),
        btes_backend_used=str(last_result.get("btes_backend", scenario.config.btes.backend)),
        probe_power_ratio_w_m=geothermal_form.probe_power_ratio_w_m,
        hourly_profile_df=demand_form.hourly_profile_df,
    )
    render_elapsed = time.perf_counter() - render_started_at
    performance_log_df = last_result.get("performance_log_df", pd.DataFrame()).copy()
    if not performance_log_df.empty:
        previous_total = float(performance_log_df["Duree cumulee (s)"].iloc[-1])
        performance_log_df = pd.concat(
            [
                performance_log_df,
                pd.DataFrame(
                    [
                        {
                            "Etape": "render:results",
                            "Message": "Affichage Streamlit des resultats et graphiques",
                            "Progression (%)": None,
                            "Duree depuis etape precedente (s)": render_elapsed,
                            "Duree cumulee (s)": previous_total + render_elapsed,
                            "Duree rendu Streamlit (s)": render_elapsed,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    with st.expander("Journal performance du dernier calcul", expanded=False):
        if performance_log_df.empty:
            st.info("Aucun journal de performance disponible.")
        else:
            display_log = performance_log_df.copy()
            display_log["Etape"] = display_log["Etape"].astype("string")
            display_log["Message"] = display_log["Message"].astype("string")
            display_log["Progression (%)"] = pd.to_numeric(
                display_log["Progression (%)"],
                errors="coerce",
            ).astype("Float64")
            for column in ["Duree depuis etape precedente (s)", "Duree cumulee (s)"]:
                display_log[column] = display_log[column].astype(float).round(2)
            st.dataframe(display_dataframe(display_log), width="stretch", hide_index=True)
    return hourly_df


