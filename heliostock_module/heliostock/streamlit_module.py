from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st

from .app_service import CalculationSelection, HourlyCalculationRequest, run_hourly_calculation
from .calculation_snapshot import build_calculation_snapshot, bytes_hash, stable_snapshot_hash, timestamp_now
from .ui_formatting import display_dataframe
from .ui_forms import (
    render_demand_form,
    render_economics_form,
    render_geothermal_form,
    render_parametric_forms,
    render_solar_form,
    render_weather_form,
)
from .ui_portal import render_project_save_controls


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
HELIOPILOT_LOGO = ASSETS_DIR / "logo_heliopilot_v5.png"
ATLANSUN_LOGO = ASSETS_DIR / "Logo_Atlansun.png"


def _snapshot_from_forms(
    *,
    weather_form,
    demand_form,
    solar_form,
    geothermal_form,
    economics_inputs,
    calculation_selection,
    parametric_forms,
) -> tuple[dict, str]:
    demand_file_bytes = st.session_state.get("heliostock_demand_file_bytes")
    snapshot = build_calculation_snapshot(
        weather_region=str(st.session_state.get("weather_region", "")),
        weather_station=str(st.session_state.get("weather_station", "")),
        weather_tilt_deg=st.session_state.get("weather_tilt_deg"),
        weather_azimuth_deg_south=st.session_state.get("weather_azimuth_deg_south"),
        weather_albedo=st.session_state.get("weather_albedo"),
        demand_file_name=str(st.session_state.get("heliostock_demand_file_name", "")),
        demand_file_hash=bytes_hash(demand_file_bytes if isinstance(demand_file_bytes, (bytes, bytearray)) else None),
        hourly_profile_df=demand_form.hourly_profile_df,
        process_bt_target_c=demand_form.process_bt_target_c,
        process_ht_target_c=demand_form.process_ht_target_c,
        demand_scope=demand_form.demand_scope,
        solar=solar_form.inputs,
        btes=geothermal_form.btes,
        heat_pump=geothermal_form.heat_pump,
        economics=economics_inputs,
        pac_power_fraction_pct=geothermal_form.pac_power_fraction_pct,
        use_probe_predesign=geothermal_form.use_probe_predesign,
        probe_power_ratio_w_m=geothermal_form.probe_power_ratio_w_m,
        probe_energy_ratio_kwh_m=geothermal_form.probe_energy_ratio_kwh_m,
        probe_unit_depth_m=geothermal_form.probe_unit_depth_m,
        calculation_selection=calculation_selection,
        pac_parametric=parametric_forms.pac,
        solar_parametric=parametric_forms.solar,
    )
    return snapshot, stable_snapshot_hash(snapshot)


def render_heliostock_hourly() -> pd.DataFrame:
    """Render the hourly-only HelioStock module."""

    logo_left, logo_right = st.columns([2, 1])
    if HELIOPILOT_LOGO.exists():
        logo_left.image(str(HELIOPILOT_LOGO), width=360)
    else:
        logo_left.header("HelioStock")
    if ATLANSUN_LOGO.exists():
        logo_right.image(str(ATLANSUN_LOGO), width=260)

    st.markdown(
        "HelioStock est un outil de pré-dimensionnement pour comparer des scénarios de chaleur renouvelable "
        "couplant solaire thermique, géothermie et stockage intersaisonnier par champ de sondes. "
        "Le calcul exploite un profil de besoins au pas de temps horaire, réalise par défaut une simulation 25 ans du champ "
        "de sondes avec pygfunction, puis propose une comparaison technico-économique des différents scénarios."
    )

    weather_form = render_weather_form()
    demand_form = render_demand_form(weather_form.hourly_weather)
    if not demand_form.valid:
        return pd.DataFrame()

    solar_form = render_solar_form(process_ht_target_c=demand_form.process_ht_target_c)
    geothermal_form = render_geothermal_form(
        hourly_weather=weather_form.hourly_weather,
        demands=demand_form.demands,
        hourly_demand_override=demand_form.hourly_demand_override,
        process_bt_target_c=demand_form.process_bt_target_c,
    )
    economics_inputs = render_economics_form()
    calculation_selection = CalculationSelection(
        calculation_profile="calcul_final",
        quick_preview=False,
        run_multiyear=True,
        technical_simulation_years=25,
        display_year_mode="finale",
        custom_display_year=25,
        run_geo_only=True,
        run_reduced_borefield=geothermal_form.run_reduced_borefield,
        savings_search_mode=geothermal_form.savings_search_mode,
        recharge_credit=geothermal_form.recharge_credit,
        reduced_borefield_safety_factor=geothermal_form.reduced_borefield_safety_factor,
    )
    parametric_forms = render_parametric_forms(solar_form.inputs.area_m2)
    render_project_save_controls()
    current_snapshot, current_snapshot_hash = _snapshot_from_forms(
        weather_form=weather_form,
        demand_form=demand_form,
        solar_form=solar_form,
        geothermal_form=geothermal_form,
        economics_inputs=economics_inputs,
        calculation_selection=calculation_selection,
        parametric_forms=parametric_forms,
    )

    if not weather_form.hourly_weather:
        return pd.DataFrame()

    run_clicked = st.button("Lancer le calcul final", type="primary", width="stretch")
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
                    calculation_selection=calculation_selection,
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
        calculated_at = timestamp_now()
        st.session_state["heliostock_last_result"] = {
            "calculation_id": calculation_id,
            "calculated_at": calculated_at,
            "input_snapshot": current_snapshot,
            "input_snapshot_hash": current_snapshot_hash,
            "scenario": calculation.scenario,
            "parametric_pac_df": calculation.parametric_pac_df.copy(),
            "parametric_surface_df": calculation.parametric_surface_df.copy(),
            "peak_bt_power_kw": calculation.peak_bt_power_kw,
            "pac_nominal_power_kw": calculation.pac_nominal_power_kw,
            "pac_power_fraction_pct": calculation.pac_power_fraction_pct,
            "btes_backend": calculation.btes_backend,
            "display_context": {
                "probe_power_ratio_w_m": geothermal_form.probe_power_ratio_w_m,
                "hourly_profile_df": demand_form.hourly_profile_df.copy(),
            },
            "performance_log_df": calculation.performance_log_df.copy(),
        }
    else:
        st.info("Affichage du dernier calcul. Modifie les paramètres puis clique sur **Lancer le calcul** pour recalculer.")

    last_result = st.session_state["heliostock_last_result"]
    result_hash = str(last_result.get("input_snapshot_hash", ""))
    calculated_at = str(last_result.get("calculated_at", "date inconnue"))
    calculation_id = str(last_result.get("calculation_id", "last"))
    st.caption(f"Dernier calcul affiche : {calculated_at} - identifiant {calculation_id}")
    if not result_hash:
        st.warning(
            "Les resultats affiches proviennent d'un ancien format de sauvegarde sans signature "
            "des hypotheses. Relance le calcul pour verrouiller la coherence parametres/resultats."
        )
    elif result_hash != current_snapshot_hash:
        st.warning(
            "Les resultats affiches correspondent au dernier calcul enregistre. "
            "Des parametres ont ete modifies depuis. Relance le calcul pour mettre a jour les resultats."
        )
    scenario = last_result["scenario"]
    display_context = last_result.get("display_context", {})
    stored_hourly_profile_df = display_context.get("hourly_profile_df", pd.DataFrame())
    if not isinstance(stored_hourly_profile_df, pd.DataFrame):
        stored_hourly_profile_df = pd.DataFrame()
    render_started_at = time.perf_counter()
    from .ui_results import render_hourly_results

    hourly_df = render_hourly_results(
        scenario=scenario,
        parametric_pac_df=last_result["parametric_pac_df"],
        parametric_surface_df=last_result["parametric_surface_df"],
        calculation_id=calculation_id,
        peak_bt_power_kw=float(last_result["peak_bt_power_kw"]),
        pac_nominal_power_kw=float(last_result["pac_nominal_power_kw"]),
        pac_power_fraction_pct=float(last_result["pac_power_fraction_pct"]),
        btes_backend_used=str(last_result.get("btes_backend", scenario.config.btes.backend)),
        probe_power_ratio_w_m=float(display_context.get("probe_power_ratio_w_m", geothermal_form.probe_power_ratio_w_m)),
        hourly_profile_df=stored_hourly_profile_df,
    )
    render_elapsed = time.perf_counter() - render_started_at
    performance_log_df = last_result.get("performance_log_df", pd.DataFrame()).copy()
    if not performance_log_df.empty:
        previous_total = float(performance_log_df["Duree cumulee (s)"].iloc[-1])
        render_row = {
            "Etape": "render:results",
            "Message": "Affichage Streamlit des resultats et graphiques",
            "Progression (%)": pd.NA,
            "Duree depuis etape precedente (s)": render_elapsed,
            "Duree cumulee (s)": previous_total + render_elapsed,
            "Duree rendu Streamlit (s)": render_elapsed,
        }
        for column in render_row:
            if column not in performance_log_df.columns:
                performance_log_df[column] = pd.NA
        performance_log_df.loc[len(performance_log_df)] = {
            column: render_row.get(column, pd.NA) for column in performance_log_df.columns
        }
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



