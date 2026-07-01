from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from .app_service import CalculationSelection, ParametricRange
from .engine import HeatPumpConfig, MonthlyDemand, cop_from_source_temperature
from .epw_reader import read_epw_hourly_weather_from_zip
from .geothermal_design import BorefieldPreDesign, predimension_borefield
from .hourly_engine import HourlyWeather
from .inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, SolarInputs
from .load_profiles import (
    _estimate_capped_bt_heat_mwh,
    _hourly_demands_from_process_file,
    _peak_bt_power_kw,
)
from .ui_inputs import (
    COLLECTOR_LIBRARY,
    DEFAULT_EPW_REGIONS,
    FixedEconomicsAssumptions,
    FixedGeoAssumptions,
    FixedSolarAssumptions,
)


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
PROCESS_TEMPLATE_XLSX = ASSETS_DIR / "modele_besoins_process_8760h.xlsx"


@dataclass(frozen=True)
class WeatherFormResult:
    hourly_weather: list[HourlyWeather]


@dataclass(frozen=True)
class DemandFormResult:
    demands: list[MonthlyDemand]
    hourly_demand_override: dict[int, tuple[float, float]] | None
    hourly_profile_df: pd.DataFrame
    process_bt_target_c: float = 25.0
    process_ht_target_c: float = 60.0
    valid: bool = True


@dataclass(frozen=True)
class SolarFormResult:
    inputs: SolarInputs


@dataclass(frozen=True)
class GeothermalFormResult:
    btes: BtesInputs
    heat_pump: HeatPumpInputs
    pac_power_fraction_pct: float
    use_probe_predesign: bool
    probe_power_ratio_w_m: float
    probe_energy_ratio_kwh_m: float
    probe_unit_depth_m: float
    btes_backend: str
    predesign: BorefieldPreDesign


@dataclass(frozen=True)
class ParametricFormsResult:
    pac: ParametricRange
    solar: ParametricRange


@dataclass(frozen=True)
class CalculationSelectionFormResult:
    selection: CalculationSelection


def render_weather_form() -> WeatherFormResult:
    with st.expander("1) Météo", expanded=True):
        c1, c2, c3 = st.columns(3)
        tilt_deg = c1.number_input("Inclinaison capteurs (°)", min_value=0.0, max_value=90.0, value=35.0, step=1.0)
        azimuth_deg_south = c2.number_input("Azimut vs sud (°)", min_value=-180.0, max_value=180.0, value=0.0, step=5.0)
        albedo = c3.number_input(
            "Albédo du sol",
            min_value=0.0,
            max_value=1.0,
            value=0.2,
            step=0.05,
            help=(
                "Part du rayonnement solaire réfléchie par le sol vers les capteurs. "
                "0,20 correspond à un sol courant ; une surface claire ou enneigée peut être plus élevée."
            ),
        )
        st.caption(
            "Albédo : part du rayonnement solaire réfléchie par le sol vers les capteurs. "
            "La valeur courante de 0,20 convient à un environnement standard."
        )
        station_col, map_col = st.columns(2)
        region_names = list(DEFAULT_EPW_REGIONS.keys())
        with station_col:
            region_name = st.selectbox("Région météo", options=region_names, index=0)
            stations_by_label = DEFAULT_EPW_REGIONS[region_name]
            station_label = st.selectbox("Station météo", options=list(stations_by_label.keys()), index=0)
            station = stations_by_label[station_label]
            st.caption("La station sélectionnée fournit la température extérieure et l'irradiation horaire EPW/TMY.")
        with map_col:
            lat = float(station.latitude_deg)
            lon = float(station.longitude_deg)
            delta = 0.45
            station_title = html.escape(f"{region_name} - {station_label}", quote=True)
            components.html(
                f"""
                <div style="width:100%; aspect-ratio:1 / 1; overflow:hidden; border-radius:8px; border:1px solid #d7dce2;">
                  <iframe
                    title="Station météo {station_title}"
                    width="100%"
                    height="100%"
                    style="border:0;"
                    loading="lazy"
                    src="https://www.openstreetmap.org/export/embed.html?bbox={lon - delta}%2C{lat - delta}%2C{lon + delta}%2C{lat + delta}&layer=mapnik&marker={lat}%2C{lon}">
                  </iframe>
                </div>
                """,
                height=360,
            )

        if station.path.exists():
            _location, hourly_weather = read_epw_hourly_weather_from_zip(
                station.path,
                tilt_deg=tilt_deg,
                azimuth_deg_south=azimuth_deg_south,
                albedo=albedo,
            )
        else:
            hourly_weather = []
            st.error(f"Fichier météo introuvable pour la station {region_name} - {station_label}.")

    return WeatherFormResult(hourly_weather=hourly_weather)


def render_demand_form(hourly_weather: list[HourlyWeather]) -> DemandFormResult:
    with st.expander("2) Besoins process", expanded=True):
        st.caption(
            "Importe un fichier Excel au pas de temps horaire pour charger le profil de besoin du site. "
            "Le fichier doit contenir 8760 lignes, soit une année complète, avec une colonne pour le besoin haute "
            "température et une colonne pour le besoin basse température. Le fichier reste local : aucun profil "
            "industriel n'est embarqué dans le dépôt public."
        )
        if PROCESS_TEMPLATE_XLSX.exists():
            st.download_button(
                "Télécharger un modèle Excel vierge",
                data=PROCESS_TEMPLATE_XLSX.read_bytes(),
                file_name="modele_besoins_process_8760h.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        temp_bt_col, temp_ht_col = st.columns(2)
        process_bt_target_c = temp_bt_col.number_input(
            "Température process basse température (°C)",
            min_value=0.0,
            max_value=120.0,
            value=25.0,
            step=1.0,
            help="Exemple : chauffage ou process basse température.",
        )
        process_ht_target_c = temp_ht_col.number_input(
            "Température process haute température (°C)",
            min_value=0.0,
            max_value=120.0,
            value=60.0,
            step=1.0,
            help="Exemple : ECS ou process haute température.",
        )
        demand_file = st.file_uploader("Fichier Excel de besoins horaires", type=["xlsx", "xls"])
        hourly_demand_override = None
        hourly_profile_df = pd.DataFrame()

        if demand_file is None:
            st.warning("Charge un fichier Excel horaire 8760 h pour activer le calcul.")
            return DemandFormResult(
                [],
                None,
                pd.DataFrame(),
                process_bt_target_c=float(process_bt_target_c),
                process_ht_target_c=float(process_ht_target_c),
                valid=False,
            )

        try:
            hourly_demand_override, demands, hourly_profile_df, demand_info = _hourly_demands_from_process_file(
                demand_file,
                hourly_weather,
            )
            st.success(
                "Profil process 8760 h charge : "
                f"{demand_info['rows']:.0f} lignes, "
                f"HT {demand_info['ht_kwh'] / 1000:.0f} MWh/an, "
                f"BT {demand_info['bt_kwh'] / 1000:.0f} MWh/an."
            )
            st.caption(
                f"Mapping appliqué : besoin HT -> process {process_ht_target_c:.0f} °C ; "
                f"besoin BT -> process {process_bt_target_c:.0f} °C. "
                "Les valeurs horaires recalées sont utilisées directement."
            )
        except Exception as exc:
            st.error(f"Lecture du fichier besoin impossible : {exc}")
            return DemandFormResult(
                [],
                None,
                pd.DataFrame(),
                process_bt_target_c=float(process_bt_target_c),
                process_ht_target_c=float(process_ht_target_c),
                valid=False,
            )

    return DemandFormResult(
        demands=demands,
        hourly_demand_override=hourly_demand_override,
        hourly_profile_df=hourly_profile_df,
        process_bt_target_c=float(process_bt_target_c),
        process_ht_target_c=float(process_ht_target_c),
    )


def render_solar_form(*, process_ht_target_c: float) -> SolarFormResult:
    with st.expander("3) Champ solaire et ballon journalier", expanded=True):
        collector_name = st.selectbox("Bibliotheque capteur", options=list(COLLECTOR_LIBRARY.keys()), index=0)
        collector_ref = COLLECTOR_LIBRARY[collector_name]
        st.caption(
            f"Capteur sélectionné : fabricant {collector_ref['manufacturer']} - modèle {collector_ref['model']}. "
            "Les coefficients restent modifiables ci-dessous."
        )
        c1, c2, c3, c4 = st.columns(4)
        area_m2 = c1.number_input("Surface capteurs (m2)", min_value=1.0, value=500.0, step=50.0)
        eta0 = c2.number_input("eta0", min_value=0.0, max_value=1.0, value=float(collector_ref["eta0"]), step=0.001, format="%.3f", key=f"eta0_{collector_name}")
        a1 = c3.number_input("a1 (W/m2.K)", min_value=0.0, value=float(collector_ref["a1_w_m2_k"]), step=0.001, format="%.3f", key=f"a1_{collector_name}")
        a2 = c4.number_input("a2 (W/m2.K2)", min_value=0.0, value=float(collector_ref["a2_w_m2_k2"]), step=0.001, format="%.3f", key=f"a2_{collector_name}")

        solar_fixed = FixedSolarAssumptions()
        c9, c10, c11 = st.columns(3)
        daily_buffer_ambient_temp_c = c9.number_input("Ambiance ballon (C)", min_value=0.0, max_value=40.0, value=20.0, step=1.0)
        daily_buffer_max_temp_c = c10.number_input("Tmax ballon / bascule BTES (C)", min_value=30.0, max_value=120.0, value=80.0, step=1.0)
        solar_preheat_target_ht_c = c11.number_input(
            "Cible max préchauffage HT solaire (°C)",
            min_value=0.0,
            max_value=120.0,
            value=float(process_ht_target_c),
            step=1.0,
        )

        with st.expander("Hypotheses solaires fixees", expanded=False):
            st.dataframe(solar_fixed.to_table(), width="stretch", hide_index=True)
            st.caption(
                "Ces valeurs sont fixees pour reduire les degres de liberte de l'interface. "
                "Le volume ballon est force a 60 L/m2 de capteurs."
            )

    return SolarFormResult(
        inputs=SolarInputs(
            area_m2=area_m2,
            eta0=eta0,
            a1_w_m2_k=a1,
            a2_w_m2_k2=a2,
            process_ht_target_c=float(process_ht_target_c),
            system_efficiency=solar_fixed.system_efficiency,
            daily_buffer_charge_factor_ht=solar_fixed.daily_buffer_charge_factor_ht,
            daily_buffer_l_per_m2=solar_fixed.daily_buffer_l_per_m2,
            daily_buffer_ambient_temp_c=daily_buffer_ambient_temp_c,
            daily_buffer_max_temp_c=daily_buffer_max_temp_c,
            daily_buffer_loss_pct_per_day=solar_fixed.daily_buffer_loss_pct,
            solar_preheat_target_ht_c=solar_preheat_target_ht_c,
            solar_buffer_hx_approach_k=solar_fixed.solar_buffer_hx_approach_k,
            solar_buffer_collector_approach_k=solar_fixed.solar_buffer_collector_approach_k,
        )
    )


def render_geothermal_form(
    *,
    hourly_weather: list[HourlyWeather],
    demands: list[MonthlyDemand],
    hourly_demand_override: dict[int, tuple[float, float]] | None,
    process_bt_target_c: float,
) -> GeothermalFormResult:
    pre_peak_bt_power_kw = _peak_bt_power_kw(hourly_weather, demands, hourly_demand_override)
    with st.expander("4) Geothermie PAC et champ de sondes", expanded=True):
        st.caption(
            "Bloc simplifie : la PAC est dimensionnee en % du Pmax BT. Le predimensionnement propose un nombre de sondes, "
            "mais le nombre effectivement simule reste modifiable ci-dessous."
        )
        use_probe_predesign = True
        geo_fixed = FixedGeoAssumptions(air_target_bt_c=float(process_bt_target_c))

        d1, d2 = st.columns(2)
        pac_power_fraction_pct = d1.number_input("P PAC (% Pmax BT)", min_value=1.0, max_value=150.0, value=100.0, step=5.0)
        probe_unit_depth_m = d2.number_input("Profondeur unitaire sonde (m)", min_value=10.0, value=100.0, step=10.0)
        btes_backend = "pygfunction"
        st.caption(
            "Calcul champ de sondes : modèle horaire 8760 h avec température source PAC calculée par pygfunction. "
            "Les besoins horaires viennent obligatoirement de l'upload Excel 8760 h."
        )

        pre_pac_nominal_power_kw = pre_peak_bt_power_kw * max(0.0, pac_power_fraction_pct) / 100.0
        pre_hp_for_design = HeatPumpConfig(
            air_target_bt_c=float(process_bt_target_c),
            condenser_approach_k=geo_fixed.condenser_approach_k,
            evaporator_approach_k=geo_fixed.evaporator_approach_k,
            carnot_efficiency=geo_fixed.carnot_efficiency,
            cop_min=geo_fixed.cop_min,
            cop_max=geo_fixed.cop_max,
            max_thermal_power_kw=pre_pac_nominal_power_kw,
        )
        pre_design_cop = cop_from_source_temperature(geo_fixed.t_initial_c, pre_hp_for_design)
        pre_pac_heat_mwh = _estimate_capped_bt_heat_mwh(
            hourly_weather,
            demands,
            hourly_demand_override,
            pre_pac_nominal_power_kw,
        )
        predesign = predimension_borefield(
            pac_power_kw=pre_pac_nominal_power_kw,
            cop=pre_design_cop,
            heat_pac_mwh_year=pre_pac_heat_mwh,
            power_ratio_w_per_m=geo_fixed.probe_power_ratio_w_m,
            max_extraction_kwh_per_m_year=geo_fixed.max_extraction_kwh_per_m_year,
            unit_depth_m=probe_unit_depth_m,
            safety_factor=geo_fixed.safety_factor,
        )

        g1, g2, g3, g4 = st.columns(4)
        g1.metric("P PAC retenue", f"{predesign.pac_power_kw:.0f} kW", delta=f"{pac_power_fraction_pct:.0f} % Pmax BT")
        g2.metric("COP de predim", f"{predesign.cop:.1f}")
        g3.metric("P sous-sol", f"{predesign.ground_power_kw:.0f} kW")
        g4.metric("Chaleur sous-sol", f"{predesign.ground_heat_mwh_year:.0f} MWh/an")

        g5, g6, g7 = st.columns(3)
        g5.metric("Longueur requise", f"{predesign.required_length_m:.0f} ml")
        g6.metric("Nombre de sondes predim", f"{predesign.boreholes}")
        g7.metric("Lineaire effectif", f"{predesign.effective_length_m:.0f} ml")

        boreholes = st.number_input(
            "Nombre de sondes a simuler",
            min_value=1,
            max_value=1000,
            value=int(predesign.boreholes),
            step=1,
            help="Valeur utilisee dans le calcul physique et economique. Le predimensionnement reste seulement un repere.",
        )
        depth_m = predesign.unit_depth_m
        selected_borefield_length_m = float(boreholes) * float(depth_m)
        delta_boreholes = int(boreholes) - int(predesign.boreholes)
        st.caption(
            f"Champ simule : {int(boreholes)} sondes x {depth_m:.0f} m = {selected_borefield_length_m:.0f} ml "
            f"({delta_boreholes:+d} sondes vs predimensionnement)."
        )

        with st.expander("Hypotheses geothermie fixees", expanded=False):
            st.dataframe(geo_fixed.to_table(), width="stretch", hide_index=True)
            st.caption(
                "Ces valeurs sont fixees pour reduire les degres de liberte de l'interface. "
                "Le COP horaire reste calcule dynamiquement avec la temperature du champ."
            )
        with st.expander("Seuils source PAC et critere GMI", expanded=True):
            s1, s2, s3 = st.columns(3)
            t_min_operation_c = s1.number_input(
                "Tmin source PAC operationnelle (C)",
                min_value=-10.0,
                max_value=20.0,
                value=geo_fixed.t_min_c,
                step=1.0,
            )
            gmi_t_min_c = s2.number_input("Tmin GMI (C)", min_value=-10.0, max_value=10.0, value=geo_fixed.gmi_t_min_c, step=1.0)
            gmi_t_max_c = s3.number_input("Tmax GMI (C)", min_value=20.0, max_value=60.0, value=geo_fixed.gmi_t_max_c, step=1.0)
            gmi_check_enabled = st.checkbox("Afficher la conformite GMI", value=geo_fixed.gmi_check_enabled)
            if t_min_operation_c > gmi_t_min_c:
                st.warning("La Tmin operationnelle PAC est plus restrictive que le critere GMI bas.")
        with st.expander("Hypothèses avancées P1 électrique", expanded=False):
            st.markdown(
                f"""
                - Forfait pompes + auxiliaires PAC/géothermie : `{geo_fixed.aux_pac_ratio * 100:.0f} %` de l'électricité compresseur.
                - Veille/régulation PAC : `{geo_fixed.standby_power_kw:.2f} kW` à chaque heure.
                - Le P1' solaire reste séparé dans l'onglet économie.
                - Les pompes de transfert solaire vers BTES ne sont pas ajoutées dans cette V0.
                """
            )

    return GeothermalFormResult(
        btes=BtesInputs(
            boreholes=int(boreholes),
            depth_m=depth_m,
            spacing_m=geo_fixed.spacing_m,
            t_initial_c=geo_fixed.t_initial_c,
            t_min_c=t_min_operation_c,
            t_max_c=geo_fixed.t_max_c,
            gmi_t_min_c=gmi_t_min_c,
            gmi_t_max_c=gmi_t_max_c,
            gmi_check_enabled=bool(gmi_check_enabled),
            ground_conductivity_w_m_k=geo_fixed.ground_conductivity_w_m_k,
            ground_diffusivity_m2_s=geo_fixed.ground_diffusivity_m2_s,
            borehole_radius_m=geo_fixed.borehole_radius_m,
            borehole_buried_depth_m=geo_fixed.borehole_buried_depth_m,
            borehole_thermal_resistance_m_k_w=geo_fixed.borehole_thermal_resistance_m_k_w,
            max_extraction_w_m=geo_fixed.probe_power_ratio_w_m,
            max_injection_w_m=geo_fixed.max_injection_w_m,
            backend=btes_backend,
        ),
        heat_pump=HeatPumpInputs(
            air_target_bt_c=float(process_bt_target_c),
            condenser_approach_k=geo_fixed.condenser_approach_k,
            evaporator_approach_k=geo_fixed.evaporator_approach_k,
            carnot_efficiency=geo_fixed.carnot_efficiency,
            cop_min=geo_fixed.cop_min,
            cop_max=geo_fixed.cop_max,
            pac_power_fraction_pct=pac_power_fraction_pct,
            peak_bt_power_kw=0.0,
            aux_pac_ratio=geo_fixed.aux_pac_ratio,
            standby_power_kw=geo_fixed.standby_power_kw,
        ),
        pac_power_fraction_pct=float(pac_power_fraction_pct),
        use_probe_predesign=use_probe_predesign,
        probe_power_ratio_w_m=geo_fixed.probe_power_ratio_w_m,
        probe_energy_ratio_kwh_m=geo_fixed.max_extraction_kwh_per_m_year,
        probe_unit_depth_m=float(probe_unit_depth_m),
        btes_backend=btes_backend,
        predesign=predesign,
    )


def render_economics_form() -> EconomicsInputs:
    with st.expander("5) Economie", expanded=False):
        st.caption(
            "Reference de chaleur evitee : appoint gaz. Les couts sont decomposes par generateur : "
            "solaire thermique, geothermie PAC et appoint gaz."
        )
        economics_fixed = FixedEconomicsAssumptions()
        c1, c2 = st.columns(2)
        eta_appoint_eco = c1.number_input("Rendement appoint gaz", min_value=0.01, max_value=1.50, value=0.82, step=0.01)
        reference_energy_inflation_pct = c2.number_input("Inflation gaz reference (%/an)", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
        st.caption("Duree d'analyse economique par defaut : 25 ans. Aucune autre aide publique deja acquise n'est appliquee.")

        st.markdown("#### P1 - Energies")
        p1a, p1b, p1c = st.columns(3)
        reference_energy_cost_eur_mwh = p1a.number_input("P1 gaz reference (EUR/MWh PCI)", min_value=0.0, value=70.0, step=5.0)
        electricity_cost_eur_mwh = p1b.number_input("P1 electricite auxiliaires/PAC (EUR/MWh)", min_value=0.0, value=200.0, step=10.0)
        auxiliary_electricity_ratio_pct = p1c.number_input("P1' auxiliaires solaires (% prod.)", min_value=0.0, max_value=20.0, value=3.0, step=0.5)
        st.caption("Le P1' solaire ne couvre pas les pompes de transfert solaire vers BTES.")

        st.markdown("#### P2 - Maintenance")
        p2a, p2b = st.columns(2)
        p2a.info("P2 solaire fixe : 1 % du CAPEX solaire brut par an, soit P2 = 0.01 x CAPEX solaire / production solaire totale.")
        backup_p2_eur_kw_year = p2b.number_input("P2 appoint gaz (EUR/kW.an)", min_value=0.0, max_value=100.0, value=10.0, step=1.0)

        st.markdown("#### P4 - Investissements")
        st.dataframe(economics_fixed.p4_table(), width="stretch", hide_index=True)
        st.caption(
            "CAPEX = S x cout unitaire(S). Aide ADEME solaire plafonnee a 65 % du CAPEX. "
            "Les autres aides publiques sont forcees a 0 EUR."
        )

    return EconomicsInputs(
        reference_energy_cost_eur_mwh=reference_energy_cost_eur_mwh,
        reference_energy_inflation_pct=reference_energy_inflation_pct,
        eta_appoint_eco=eta_appoint_eco,
        analysis_years=int(economics_fixed.analysis_years),
        auxiliary_electricity_ratio_pct=auxiliary_electricity_ratio_pct,
        electricity_cost_eur_mwh=electricity_cost_eur_mwh,
        maintenance_cost_eur_m2_year=0.0,
        ademe_eur_mwh_year=economics_fixed.ademe_eur_mwh_year,
        other_public_aid_eur=economics_fixed.other_public_aid_eur,
        backup_p2_eur_kw_year=backup_p2_eur_kw_year,
    )


def render_calculation_selection_form() -> CalculationSelectionFormResult:
    with st.expander("6) Profil de calcul et calculs a lancer", expanded=True):
        profile_label = st.radio(
            "Profil de calcul",
            options=[
                "Previsualisation rapide - 1 an, scenario principal uniquement",
                "Dimensionnement technique - 25 ans, sans parametriques",
                "Calcul final complet - 25 ans, economie sondes et parametriques",
            ],
            index=1,
            horizontal=True,
        )
        profile_map = {
            "Previsualisation rapide - 1 an, scenario principal uniquement": "previsualisation_rapide",
            "Dimensionnement technique - 25 ans, sans parametriques": "dimensionnement_25_ans",
            "Calcul final complet - 25 ans, economie sondes et parametriques": "calcul_final",
        }
        calculation_profile = profile_map[str(profile_label)]
        quick_preview = calculation_profile == "previsualisation_rapide"
        final_profile = calculation_profile == "calcul_final"
        if quick_preview:
            st.info(
                "Profil rapide : simulation 1 an du scenario principal uniquement. "
                "Geothermie seule, economie de sondes et etudes parametriques sont masquees/desactivees."
            )
        elif calculation_profile == "dimensionnement_25_ans":
            st.info(
                "Profil dimensionnement : simulation technique 25 ans avec comparaison geothermie seule. "
                "Les etudes parametriques et l'economie de sondes restent desactivees."
            )
        else:
            st.info(
                "Profil final complet : simulation 25 ans avec options avancees. "
                "Les etudes parametriques PAC/solaire et l'economie de sondes sont disponibles ci-dessous."
            )
        run_multiyear = st.checkbox("Projection technique multiannuelle", value=not quick_preview, disabled=quick_preview)
        technical_simulation_years = st.number_input(
            "Duree simulation technique champ (ans)",
            min_value=1,
            max_value=50,
            value=1 if quick_preview else 25,
            step=1,
            disabled=quick_preview or not run_multiyear,
        )
        display_year_mode = st.radio(
            "Annee technique affichee",
            options=["finale", "annee 1", "personnalisee"],
            index=0,
            horizontal=True,
            disabled=quick_preview,
        )
        custom_display_year = st.number_input(
            "Annee personnalisee",
            min_value=1,
            max_value=int(technical_simulation_years),
            value=int(technical_simulation_years),
            step=1,
            disabled=quick_preview or display_year_mode != "personnalisee",
        )
        run_geo_only = st.checkbox(
            "Scenario geothermie seule",
            value=not quick_preview,
            disabled=calculation_profile == "dimensionnement_25_ans",
        )
        savings_method_label = st.selectbox(
            "Methode economie de sondes",
            options=["desactivee", "rapide predimensionnement", "experte detaillee"],
            index=1 if final_profile else 0,
            disabled=not final_profile or not run_geo_only,
        )
        savings_mode_map = {
            "desactivee": "none",
            "rapide predimensionnement": "fast",
            "experte detaillee": "expert",
        }
        savings_search_mode = savings_mode_map[str(savings_method_label)]
        if quick_preview:
            run_multiyear = False
            technical_simulation_years = 1
            display_year_mode = "finale"
            custom_display_year = 1
            run_geo_only = False
            savings_search_mode = "none"
        elif calculation_profile == "dimensionnement_25_ans":
            run_multiyear = True
            run_geo_only = True
            savings_search_mode = "none"
        run_reduced_borefield = savings_search_mode != "none" and bool(run_geo_only)
        recharge_credit = st.number_input("Credit recharge solaire", min_value=0.0, max_value=1.0, value=0.60, step=0.05)
        reduced_borefield_safety_factor = st.number_input(
            "Marge securite sondes reduites",
            min_value=1.0,
            max_value=2.0,
            value=1.10,
            step=0.05,
            disabled=not final_profile or savings_search_mode == "none",
        )
        if not run_geo_only and run_reduced_borefield:
            run_reduced_borefield = False
            savings_search_mode = "none"
        st.caption(
            "Important : les etudes parametriques ne sont affichees et lancees que dans le profil "
            "`Calcul final complet - 25 ans, economie sondes et parametriques`."
        )
    return CalculationSelectionFormResult(
        selection=CalculationSelection(
            calculation_profile=str(calculation_profile),
            quick_preview=bool(quick_preview),
            run_multiyear=bool(run_multiyear),
            technical_simulation_years=int(technical_simulation_years) if run_multiyear else 1,
            display_year_mode=str(display_year_mode),
            custom_display_year=int(custom_display_year),
            run_geo_only=bool(run_geo_only),
            run_reduced_borefield=bool(run_reduced_borefield),
            savings_search_mode=str(savings_search_mode),
            recharge_credit=float(recharge_credit),
            reduced_borefield_safety_factor=float(reduced_borefield_safety_factor),
        )
    )


def render_parametric_forms(area_m2: float, *, disabled: bool = False) -> ParametricFormsResult:
    if disabled:
        return ParametricFormsResult(
            pac=ParametricRange(False, 50.0, 100.0, 10.0),
            solar=ParametricRange(False, max(0.0, float(area_m2) * 0.5), max(50.0, float(area_m2) * 1.5), 250.0),
        )

    with st.expander("7) Etude parametrique PAC - Calcul final uniquement", expanded=False):
        enable_pac_power_parametric = st.checkbox("Activer l'étude paramétrique sur la puissance PAC", value=False)
        pp1, pp2, pp3 = st.columns(3)
        param_pac_fraction_min_pct = pp1.number_input("P PAC min (% Pmax BT)", min_value=1.0, max_value=150.0, value=50.0, step=5.0)
        param_pac_fraction_max_pct = pp2.number_input("P PAC max (% Pmax BT)", min_value=1.0, max_value=150.0, value=100.0, step=5.0)
        param_pac_fraction_step_pct = pp3.number_input("Pas PAC (% Pmax BT)", min_value=1.0, max_value=50.0, value=10.0, step=5.0)
        st.caption(
            "Chaque point relance la simulation 8760 h en désactivant le solaire thermique. "
            "L'appoint gaz couvre tout le besoin HT et le complément BT non couvert par PAC. "
            "Si le prédimensionnement sondes est activé, le nombre de sondes est recalculé pour chaque puissance PAC. "
            "Limite de sécurité : 25 points."
        )

    with st.expander("8) Etude parametrique solaire + injection BTES - Calcul final uniquement", expanded=False):
        enable_solar_surface_parametric = st.checkbox("Activer l'étude paramétrique sur la surface solaire", value=False)
        p1, p2, p3 = st.columns(3)
        param_surface_min_m2 = p1.number_input("Surface min étudiée (m²)", min_value=0.0, value=max(0.0, float(area_m2) * 0.5), step=50.0)
        param_surface_max_m2 = p2.number_input("Surface max étudiée (m²)", min_value=0.0, value=max(50.0, float(area_m2) * 1.5), step=50.0)
        param_surface_step_m2 = p3.number_input("Pas de surface (m²)", min_value=1.0, value=250.0, step=50.0)
        st.caption(
            "Chaque point relance la simulation 8760 h et recalcule le coût Mix EnR, "
            "le taux EnR global et la couverture solaire HT. Limite de sécurité : 25 points."
        )

    return ParametricFormsResult(
        pac=ParametricRange(
            enabled=bool(enable_pac_power_parametric) and not disabled,
            minimum=float(param_pac_fraction_min_pct),
            maximum=float(param_pac_fraction_max_pct),
            step=float(param_pac_fraction_step_pct),
        ),
        solar=ParametricRange(
            enabled=bool(enable_solar_surface_parametric) and not disabled,
            minimum=float(param_surface_min_m2),
            maximum=float(param_surface_max_m2),
            step=float(param_surface_step_m2),
        ),
    )
