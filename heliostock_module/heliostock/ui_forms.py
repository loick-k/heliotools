from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from .app_service import ParametricRange
from .engine import HeatPumpConfig, MonthlyDemand, cop_from_source_temperature
from .epw_reader import read_epw_hourly_weather_from_zip
from .geothermal_design import BorefieldPreDesign, predimension_borefield
from .geocoding_service import GeocodingServiceError, search_addresses
from .gmi_service import GMIServiceError, WMS_URL, check_gmi_zoning, discover_gmi_layers, select_layer
from .hourly_engine import HourlyWeather
from .inputs import BtesInputs, EconomicsInputs, HeatPumpInputs, SolarInputs
from .load_profiles import (
    apply_demand_scope,
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
    WEATHER_STATION_LABEL_ALIASES,
)
from .ui_formatting import display_dataframe


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
PROCESS_TEMPLATE_XLSX = ASSETS_DIR / "modele_besoins_process_8760h.xlsx"


def _widget_default(key: str, value):
    """Avoid Streamlit's warning when a loaded project already set the widget state."""

    return {} if key in st.session_state else {"value": value}


@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_gmi_layers() -> list[dict[str, object]]:
    return discover_gmi_layers()


@st.cache_data(ttl=3_600, show_spinner=False)
def _cached_gmi_check(latitude: float, longitude: float, layer_name: str, layer_title: str) -> dict[str, object]:
    return check_gmi_zoning(
        latitude=latitude,
        longitude=longitude,
        layer_name=layer_name,
        layer_title=layer_title,
    )


@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_address_search(query: str) -> list[dict[str, object]]:
    return search_addresses(query=query, limit=5)


def _address_candidate_label(candidate: dict[str, object]) -> str:
    label = str(candidate.get("label") or "Adresse trouvée")
    context = str(candidate.get("context") or "")
    score = candidate.get("score")
    details = []
    if context and context.lower() not in label.lower():
        details.append(context)
    if isinstance(score, (float, int)):
        details.append(f"pertinence {score * 100:.0f} %")
    return f"{label} - {' · '.join(details)}" if details else label


def _build_gmi_map(
    *,
    latitude: float,
    longitude: float,
    address_label: str,
    result: dict[str, object] | None,
) -> folium.Map:
    zone = str(result.get("zone")) if isinstance(result, dict) else ""
    marker_colors = {"vert": "green", "orange": "orange", "rouge": "red"}
    marker_color = marker_colors.get(zone, "blue")

    map_object = folium.Map(
        location=[latitude, longitude],
        zoom_start=15,
        control_scale=True,
        tiles="OpenStreetMap",
    )

    if isinstance(result, dict) and result.get("wms_layer_name"):
        folium.WmsTileLayer(
            url=WMS_URL,
            layers=str(result["wms_layer_name"]),
            name="Zonage réglementaire GMI - BRGM",
            fmt="image/png",
            transparent=True,
            version="1.3.0",
            overlay=True,
            control=True,
            opacity=0.5,
            show=True,
        ).add_to(map_object)

    popup_lines = [address_label or "Point étudié"]
    popup_lines.append(f"Latitude : {latitude:.7f}")
    popup_lines.append(f"Longitude : {longitude:.7f}")
    if zone:
        popup_lines.append(f"Classement détecté : {zone}")

    folium.Marker(
        location=[latitude, longitude],
        tooltip=address_label or "Point étudié",
        popup="<br>".join(popup_lines),
        icon=folium.Icon(color=marker_color, icon="info-sign"),
    ).add_to(map_object)
    folium.Circle(
        location=[latitude, longitude],
        radius=12,
        color=marker_color,
        fill=True,
        fill_opacity=0.25,
        tooltip="Emplacement interrogé",
    ).add_to(map_object)
    if isinstance(result, dict) and result.get("wms_layer_name"):
        folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def _process_template_excel_bytes() -> bytes:
    if PROCESS_TEMPLATE_XLSX.exists():
        return PROCESS_TEMPLATE_XLSX.read_bytes()

    rows = []
    hour_index = 0
    month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for month, days in enumerate(month_days, start=1):
        for day in range(1, days + 1):
            for hour in range(1, 25):
                rows.append(
                    {
                        "hour_index": hour_index,
                        "month": month,
                        "day": day,
                        "hour": hour,
                        "E besoin HT kWh": 0.0,
                        "E besoin BT kWh": 0.0,
                    }
                )
                hour_index += 1

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="besoins_8760h")
        pd.DataFrame(
            [
                {
                    "Colonne": "E besoin HT kWh",
                    "Description": "Energie horaire du besoin process haute température, en kWh sur l'heure.",
                },
                {
                    "Colonne": "E besoin BT kWh",
                    "Description": "Energie horaire du besoin process basse température, en kWh sur l'heure.",
                },
                {
                    "Colonne": "P besoin HT kW / P besoin BT kW",
                    "Description": "Colonnes alternatives acceptées si vous préférez fournir des puissances moyennes horaires.",
                },
            ]
        ).to_excel(writer, index=False, sheet_name="notice")
    return buffer.getvalue()


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
    demand_scope: str = "ht_bt"
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
    savings_search_mode: str
    run_reduced_borefield: bool
    recharge_credit: float
    reduced_borefield_safety_factor: float


@dataclass(frozen=True)
class ParametricFormsResult:
    pac: ParametricRange
    solar: ParametricRange


def render_weather_form() -> WeatherFormResult:
    with st.expander("1) Météo", expanded=True):
        c1, c2, c3 = st.columns(3)
        tilt_deg = c1.number_input(
            "Inclinaison capteurs (°)",
            min_value=0.0,
            max_value=90.0,
            step=1.0,
            key="weather_tilt_deg",
            **_widget_default("weather_tilt_deg", 35.0),
        )
        azimuth_deg_south = c2.number_input(
            "Azimut vs sud (°)",
            min_value=-180.0,
            max_value=180.0,
            step=5.0,
            key="weather_azimuth_deg_south",
            **_widget_default("weather_azimuth_deg_south", 0.0),
        )
        albedo = c3.number_input(
            "Albédo du sol",
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key="weather_albedo",
            **_widget_default("weather_albedo", 0.2),
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
        if st.session_state.get("weather_region") not in region_names:
            st.session_state["weather_region"] = region_names[0]
        with station_col:
            region_name = st.selectbox("Région météo", options=region_names, index=0, key="weather_region")
            stations_by_label = DEFAULT_EPW_REGIONS[region_name]
            legacy_station = st.session_state.get("weather_station")
            if legacy_station in WEATHER_STATION_LABEL_ALIASES:
                st.session_state["weather_station"] = WEATHER_STATION_LABEL_ALIASES[str(legacy_station)]
            if st.session_state.get("weather_station") not in stations_by_label:
                st.session_state["weather_station"] = list(stations_by_label.keys())[0]
            station_label = st.selectbox("Station météo", options=list(stations_by_label.keys()), index=0, key="weather_station")
            station = stations_by_label[station_label]
            st.caption("La station sélectionnée fournit la température extérieure et l'irradiation horaire EPW/TMY.")
        with map_col:
            region_stations = pd.DataFrame(
                [
                    {
                        "station": item.label,
                        "latitude": float(item.latitude_deg),
                        "longitude": float(item.longitude_deg),
                        "taille": 140 if item.label == station.label else 55,
                        "couleur": "#f59e0b" if item.label == station.label else "#64748b",
                    }
                    for item in stations_by_label.values()
                ]
            )
            st.map(
                region_stations,
                latitude="latitude",
                longitude="longitude",
                size="taille",
                color="couleur",
                zoom=6,
                width="stretch",
                height=360,
            )
            st.caption(f"Station affichée : {station.label}.")

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
            "température et une colonne pour le besoin basse température."
        )
        st.download_button(
            "Télécharger un modèle Excel vierge",
            data=_process_template_excel_bytes(),
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
            key="process_bt_target_c",
            help="Exemple : chauffage ou process basse température.",
        )
        process_ht_target_c = temp_ht_col.number_input(
            "Température process haute température (°C)",
            min_value=0.0,
            max_value=120.0,
            value=60.0,
            step=1.0,
            key="process_ht_target_c",
            help="Exemple : ECS ou process haute température.",
        )
        scope_options = {
            "HT + BT - scénario complet": "ht_bt",
            "BT seule - test géothermie/PAC": "bt_only",
            "HT seule - test solaire thermique": "ht_only",
        }
        scope_labels = list(scope_options.keys())
        if st.session_state.get("demand_scope_label") not in scope_labels:
            st.session_state["demand_scope_label"] = scope_labels[0]
        demand_scope_label = st.selectbox(
            "Périmètre de besoins actif",
            options=scope_labels,
            index=scope_labels.index(st.session_state["demand_scope_label"]),
            key="demand_scope_label",
            help=(
                "Permet de tester seulement la basse température ou seulement la haute température "
                "sans modifier le fichier Excel importé."
            ),
        )
        demand_scope = scope_options[str(demand_scope_label)]
        demand_file = st.file_uploader("Fichier Excel de besoins horaires", type=["xlsx", "xls"])
        if demand_file is not None:
            st.session_state["heliostock_demand_file_bytes"] = demand_file.getvalue()
            st.session_state["heliostock_demand_file_name"] = getattr(demand_file, "name", "besoins_process.xlsx")
        elif st.session_state.get("heliostock_demand_file_bytes"):
            demand_file = BytesIO(bytes(st.session_state["heliostock_demand_file_bytes"]))
            demand_file.name = str(st.session_state.get("heliostock_demand_file_name", "besoins_process.xlsx"))
            st.info(f"Fichier besoins chargé depuis le projet : {demand_file.name}")
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
                demand_scope=str(demand_scope),
                valid=False,
            )

        try:
            hourly_demand_override, demands, hourly_profile_df, demand_info = _hourly_demands_from_process_file(
                demand_file,
                hourly_weather,
            )
            raw_ht_kwh = float(demand_info["ht_kwh"])
            raw_bt_kwh = float(demand_info["bt_kwh"])
            demands, hourly_demand_override, hourly_profile_df = apply_demand_scope(
                scope=demand_scope,
                demands=demands,
                hourly_demand_override=hourly_demand_override,
                hourly_profile_df=hourly_profile_df,
            )
            active_ht_kwh = float(hourly_profile_df["demand_ht_kwh"].sum()) if "demand_ht_kwh" in hourly_profile_df else 0.0
            active_bt_kwh = float(hourly_profile_df["demand_bt_kwh"].sum()) if "demand_bt_kwh" in hourly_profile_df else 0.0
            st.success(
                "Profil process 8760 h chargé : "
                f"{demand_info['rows']:.0f} lignes, "
                f"HT active {active_ht_kwh / 1000:.0f} MWh/an, "
                f"BT active {active_bt_kwh / 1000:.0f} MWh/an."
            )
            if demand_scope != "ht_bt":
                st.info(
                    "Périmètre de test appliqué au calcul : "
                    f"HT importée {raw_ht_kwh / 1000:.0f} MWh/an, "
                    f"BT importée {raw_bt_kwh / 1000:.0f} MWh/an."
                )
        except Exception as exc:
            st.error(f"Lecture du fichier besoin impossible : {exc}")
            return DemandFormResult(
                [],
                None,
                pd.DataFrame(),
                process_bt_target_c=float(process_bt_target_c),
                process_ht_target_c=float(process_ht_target_c),
                demand_scope=str(demand_scope),
                valid=False,
            )

    return DemandFormResult(
        demands=demands,
        hourly_demand_override=hourly_demand_override,
        hourly_profile_df=hourly_profile_df,
        process_bt_target_c=float(process_bt_target_c),
        process_ht_target_c=float(process_ht_target_c),
        demand_scope=str(demand_scope),
    )


def render_solar_form(*, process_ht_target_c: float) -> SolarFormResult:
    with st.expander("3) Champ solaire et ballon journalier", expanded=True):
        if st.session_state.get("solar_collector_name") not in COLLECTOR_LIBRARY:
            st.session_state["solar_collector_name"] = list(COLLECTOR_LIBRARY.keys())[0]
        collector_name = st.selectbox("Bibliothèque capteur", options=list(COLLECTOR_LIBRARY.keys()), index=0, key="solar_collector_name")
        collector_ref = COLLECTOR_LIBRARY[collector_name]
        st.caption(
            f"Capteur sélectionné : fabricant {collector_ref.manufacturer} - modèle {collector_ref.model}. "
            "Les coefficients restent modifiables ci-dessous."
        )
        c1, c2, c3, c4 = st.columns(4)
        area_m2 = c1.number_input("Surface capteurs (m²)", min_value=1.0, value=500.0, step=50.0, key="solar_area_m2")
        eta0 = c2.number_input("eta0", min_value=0.0, max_value=1.0, value=float(collector_ref.eta0), step=0.001, format="%.3f", key="solar_eta0")
        a1 = c3.number_input("a1 (W/m2.K)", min_value=0.0, value=float(collector_ref.a1_w_m2_k), step=0.001, format="%.3f", key="solar_a1")
        a2 = c4.number_input("a2 (W/m2.K2)", min_value=0.0, value=float(collector_ref.a2_w_m2_k2), step=0.001, format="%.3f", key="solar_a2")

        solar_fixed = FixedSolarAssumptions()
        c9, c10, c11 = st.columns(3)
        daily_buffer_ambient_temp_c = c9.number_input("T° ambiance ballon (°C)", min_value=0.0, max_value=40.0, value=20.0, step=1.0, key="solar_daily_buffer_ambient_temp_c")
        daily_buffer_max_temp_c = c10.number_input("Tmax ballon / bascule BTES (°C)", min_value=30.0, max_value=120.0, value=80.0, step=1.0, key="solar_daily_buffer_max_temp_c")
        daily_buffer_l_per_m2 = c11.number_input(
            "Ratio stockage solaire V/S (L/m²)",
            min_value=0.0,
            max_value=300.0,
            value=float(solar_fixed.daily_buffer_l_per_m2),
            step=5.0,
            key="solar_daily_buffer_l_per_m2",
            help="Volume de ballon journalier par m² de capteurs solaires. Par défaut : 60 L/m².",
        )
        solar_preheat_target_ht_c = float(process_ht_target_c)
        st.caption("Ratio stockage solaire V/S : par défaut 60 L/m².")

        with st.expander("Hypothèses solaires fixées", expanded=False):
            st.dataframe(display_dataframe(solar_fixed.to_table()), width="stretch", hide_index=True)
            st.caption(
                "Ces valeurs sont fixées pour réduire les degrés de liberté de l'interface. "
                "Le ratio V/S du stockage solaire est réglable dans le module solaire thermique."
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
            daily_buffer_l_per_m2=daily_buffer_l_per_m2,
            daily_buffer_ambient_temp_c=daily_buffer_ambient_temp_c,
            daily_buffer_max_temp_c=daily_buffer_max_temp_c,
            daily_buffer_loss_pct_per_day=0.0,
            daily_buffer_tank_count=solar_fixed.daily_buffer_tank_count,
            daily_buffer_insulation_thickness_cm=solar_fixed.daily_buffer_insulation_thickness_cm,
            daily_buffer_insulation_lambda_w_m_k=solar_fixed.daily_buffer_insulation_lambda_w_m_k,
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
    with st.expander("4) Géothermie PAC et champ de sondes", expanded=True):
        st.caption(
            "Bloc simplifié : la PAC est dimensionnée en % du Pmax BT. Le prédimensionnement propose un nombre de sondes, "
            "mais le nombre effectivement simulé reste modifiable ci-dessous."
        )
        use_probe_predesign = True
        geo_fixed = FixedGeoAssumptions(air_target_bt_c=float(process_bt_target_c))

        d1, d2 = st.columns(2)
        pac_power_fraction_pct = d1.number_input("P PAC (% Pmax BT)", min_value=1.0, max_value=150.0, value=100.0, step=5.0, key="geo_pac_power_fraction_pct")
        probe_unit_depth_m = d2.number_input("Profondeur unitaire sonde (m)", min_value=10.0, value=100.0, step=10.0, key="geo_probe_unit_depth_m")
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
            power_ratio_w_per_m=geo_fixed.predesign_power_ratio_w_m,
            energy_ratio_kwh_per_m_year=geo_fixed.predesign_energy_ratio_kwh_m_year,
            unit_depth_m=probe_unit_depth_m,
            safety_factor=geo_fixed.safety_factor,
        )

        g1, g2, g3, g4 = st.columns(4)
        g1.metric("P PAC retenue", f"{predesign.pac_power_kw:.0f} kW", delta=f"{pac_power_fraction_pct:.0f} % Pmax BT")
        g2.metric("COP de prédim.", f"{predesign.cop:.1f}")
        g3.metric("P sous-sol", f"{predesign.ground_power_kw:.0f} kW")
        g4.metric("Chaleur sous-sol", f"{predesign.ground_heat_mwh_year:.0f} MWh/an")

        g5, g6 = st.columns(2)
        g5.metric("Linéaire effectif", f"{predesign.effective_length_m:.0f} ml")
        g6.metric("Nombre de sondes prédim.", f"{predesign.boreholes}")

        boreholes = st.number_input(
            "Nombre de sondes à simuler",
            min_value=1,
            max_value=1000,
            value=int(predesign.boreholes),
            step=1,
            key="geo_boreholes",
            help="Valeur utilisée dans le calcul physique et économique. Le prédimensionnement reste seulement un repère.",
        )
        depth_m = predesign.unit_depth_m
        selected_borefield_length_m = float(boreholes) * float(depth_m)
        delta_boreholes = int(boreholes) - int(predesign.boreholes)
        st.caption(
            f"Champ simulé : {int(boreholes)} sondes x {depth_m:.0f} m = {selected_borefield_length_m:.0f} ml "
            f"({delta_boreholes:+d} sondes vs prédimensionnement)."
        )

        savings_options = ["désactivée", "rapide prédimensionnement", "experte détaillée"]
        savings_selectbox_kwargs = {
            "label": "Méthode économie de sondes",
            "options": savings_options,
            "key": "geo_savings_method",
            "help": (
                "Le mode rapide estime un linéaire réduit puis le vérifie avec quelques simulations pygfunction. "
                "Le mode expert lance une recherche plus détaillée et donc plus longue."
            ),
        }
        if "geo_savings_method" not in st.session_state:
            savings_selectbox_kwargs["index"] = 1
        elif st.session_state.get("geo_savings_method") not in savings_options:
            st.session_state["geo_savings_method"] = "rapide prédimensionnement"
        savings_method_label = st.selectbox(**savings_selectbox_kwargs)
        savings_mode_map = {
            "désactivée": "none",
            "rapide prédimensionnement": "fast",
            "experte détaillée": "expert",
        }
        savings_search_mode = savings_mode_map[str(savings_method_label)]
        run_reduced_borefield = savings_search_mode != "none"
        if savings_search_mode == "fast":
            st.caption(
                "Mode rapide : estimation du gain à partir de la recharge solaire, puis validation par un nombre limité "
                "de simulations pygfunction."
            )
        elif savings_search_mode == "expert":
            st.warning("Mode expert : calcul plus lourd, avec recherche itérative du linéaire de sondes.")

        with st.expander("Hypothèses géothermie fixées", expanded=False):
            st.dataframe(display_dataframe(geo_fixed.to_table()), width="stretch", hide_index=True)
            st.caption(
                "Ces valeurs sont fixées pour réduire les degrés de liberté de l'interface. "
                "Le COP horaire reste calculé dynamiquement avec la température du champ."
            )
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
            t_min_c=geo_fixed.t_min_c,
            t_max_c=geo_fixed.t_max_c,
            gmi_t_min_c=geo_fixed.gmi_t_min_c,
            gmi_t_max_c=geo_fixed.gmi_t_max_c,
            gmi_check_enabled=bool(geo_fixed.gmi_check_enabled),
            ground_conductivity_w_m_k=geo_fixed.ground_conductivity_w_m_k,
            ground_diffusivity_m2_s=geo_fixed.ground_diffusivity_m2_s,
            borehole_radius_m=geo_fixed.borehole_radius_m,
            borehole_buried_depth_m=geo_fixed.borehole_buried_depth_m,
            borehole_thermal_resistance_m_k_w=geo_fixed.borehole_thermal_resistance_m_k_w,
            max_extraction_w_m=geo_fixed.max_extraction_w_m,
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
        probe_power_ratio_w_m=geo_fixed.predesign_power_ratio_w_m,
        probe_energy_ratio_kwh_m=geo_fixed.predesign_energy_ratio_kwh_m_year,
        probe_unit_depth_m=float(probe_unit_depth_m),
        btes_backend=btes_backend,
        predesign=predesign,
        savings_search_mode=str(savings_search_mode),
        run_reduced_borefield=bool(run_reduced_borefield),
        recharge_credit=0.60,
        reduced_borefield_safety_factor=float(geo_fixed.reduced_borefield_safety_factor),
    )


def render_gmi_verification_block() -> None:
    with st.expander("4 bis) Vérification géothermie de minime importance (GMI)", expanded=False):
        st.caption(
            "Ce bloc interroge le zonage cartographique GMI du BRGM à partir d'une adresse ou de coordonnées. "
            "Il sert d'aide réglementaire préliminaire : il ne remplace pas l'analyse complète du projet, ni les autres critères GMI."
        )

        with st.form("heliostock_gmi_address_form", clear_on_submit=False):
            address_query = st.text_input(
                "Adresse du projet",
                placeholder="Ex. 10 rue de la Paix, 44000 Nantes",
                key="gmi_address_query",
            )
            search_submitted = st.form_submit_button("Rechercher l'adresse", width="stretch")

        if search_submitted:
            try:
                with st.spinner("Recherche dans la Base Adresse Nationale..."):
                    st.session_state["gmi_address_candidates"] = _cached_address_search(address_query)
            except (GeocodingServiceError, ValueError) as exc:
                st.session_state["gmi_address_candidates"] = []
                st.error(str(exc))
            else:
                if not st.session_state["gmi_address_candidates"]:
                    st.warning("Aucune adresse correspondante n'a été trouvée.")

        candidates = st.session_state.get("gmi_address_candidates", [])
        if candidates:
            selected_index = st.selectbox(
                "Adresse proposée",
                options=range(len(candidates)),
                format_func=lambda index: _address_candidate_label(candidates[index]),
                key="gmi_selected_address_candidate",
            )
            selected_candidate = candidates[int(selected_index)]
            if st.button("Utiliser cette adresse", width="stretch", key="gmi_use_selected_address"):
                st.session_state["gmi_latitude"] = float(selected_candidate["latitude"])
                st.session_state["gmi_longitude"] = float(selected_candidate["longitude"])
                st.session_state["gmi_selected_address_label"] = str(selected_candidate["label"])
                st.session_state.pop("gmi_result", None)
                st.rerun()

        if st.session_state.get("gmi_selected_address_label"):
            st.success(f"Adresse retenue : {st.session_state['gmi_selected_address_label']}")

        c1, c2 = st.columns(2)
        latitude = c1.number_input(
            "Latitude",
            min_value=-90.0,
            max_value=90.0,
            format="%.7f",
            key="gmi_latitude",
            **_widget_default("gmi_latitude", 47.2184),
        )
        longitude = c2.number_input(
            "Longitude",
            min_value=-180.0,
            max_value=180.0,
            format="%.7f",
            key="gmi_longitude",
            **_widget_default("gmi_longitude", -1.5536),
        )

        p1, p2 = st.columns(2)
        exchanger_label = p1.radio(
            "Type d'échangeur",
            options=("Fermé - sondes géothermiques", "Ouvert - nappe"),
            horizontal=True,
            key="gmi_exchanger_label",
        )
        exchanger_type = "ferme" if str(exchanger_label).startswith("Fermé") else "ouvert"
        depth_max_m = p2.selectbox(
            "Profondeur maximale étudiée",
            options=(50, 100, 200),
            format_func=lambda value: f"10 à {value} m",
            key="gmi_depth_max_m",
        )

        if st.button("Vérifier le zonage GMI", type="primary", width="stretch", key="gmi_check_button"):
            try:
                with st.spinner("Interrogation du service cartographique BRGM..."):
                    layers = _cached_gmi_layers()
                    selected_layer = select_layer(layers, exchanger_type=exchanger_type, depth_max_m=int(depth_max_m))
                    st.session_state["gmi_result"] = _cached_gmi_check(
                        round(float(latitude), 7),
                        round(float(longitude), 7),
                        str(selected_layer["name"]),
                        str(selected_layer["title"]),
                    )
            except (GMIServiceError, ValueError) as exc:
                st.error(str(exc))

        result = st.session_state.get("gmi_result")
        address_label = str(st.session_state.get("gmi_selected_address_label") or "Point étudié")
        st_folium(
            _build_gmi_map(
                latitude=float(latitude),
                longitude=float(longitude),
                address_label=address_label,
                result=result if isinstance(result, dict) else None,
            ),
            height=420,
            width="stretch",
            returned_objects=[],
            key="gmi_zoning_map",
        )
        if isinstance(result, dict):
            zone = str(result.get("zone") or "inconnu")
            zone_messages = {
                "vert": ("Zone verte", "success", "Le zonage cartographique ne signale pas de contrainte particulière GMI."),
                "orange": ("Zone orange", "warning", "Le projet nécessite une attention réglementaire renforcée et des vérifications complémentaires."),
                "rouge": ("Zone rouge", "error", "Le zonage cartographique indique une zone défavorable ou interdite selon la couche interrogée."),
                "aucune_donnee": ("Aucune donnée retournée", "warning", "Le service n'a pas renvoyé d'objet cartographique au point interrogé."),
                "inconnu": ("Classement non interprété", "warning", "Le service a répondu, mais HelioStock n'a pas pu interpréter automatiquement la classe."),
            }
            title, level, message = zone_messages.get(zone, zone_messages["inconnu"])
            getattr(st, level)(f"{title} - {message}")
            st.caption(
                f"Couche BRGM interrogée : {result.get('layer_title', result.get('layer_name', 'n.d.'))} ; "
                f"objets retournés : {result.get('feature_count', 'n.d.')}."
            )

        st.info(
            "Rappel : la GMI ne se limite pas au zonage cartographique. Les critères de profondeur, puissance, débit, "
            "températures, distance aux ouvrages sensibles et contexte hydrogéologique restent à vérifier."
        )


def render_economics_form() -> EconomicsInputs:
    with st.expander("5) Économie", expanded=False):
        st.caption(
            "Référence de chaleur évitée : appoint gaz. Les coûts sont décomposés par générateur : "
            "solaire thermique, géothermie PAC et appoint gaz."
        )
        economics_fixed = FixedEconomicsAssumptions()
        c1, c2 = st.columns(2)
        eta_appoint_eco = c1.number_input("Rendement appoint gaz", min_value=0.01, max_value=1.50, value=0.82, step=0.01, key="eco_eta_appoint")
        reference_energy_inflation_pct = c2.number_input("Inflation gaz référence (%/an)", min_value=0.0, max_value=20.0, value=3.0, step=0.5, key="eco_reference_energy_inflation_pct")
        st.caption("Durée d'analyse économique par défaut : 20 ans. Aucune autre aide publique déjà acquise n'est appliquée.")

        st.markdown("#### P1 - Énergies")
        p1a, p1b, p1c = st.columns(3)
        reference_energy_cost_eur_mwh = p1a.number_input("P1 gaz référence (EUR/MWh PCI)", min_value=0.0, value=70.0, step=5.0, key="eco_reference_energy_cost_eur_mwh")
        electricity_cost_eur_mwh = p1b.number_input("P1 électricité auxiliaires/PAC (EUR/MWh)", min_value=0.0, value=200.0, step=10.0, key="eco_electricity_cost_eur_mwh")
        auxiliary_electricity_ratio_pct = p1c.number_input("P1' auxiliaires solaires (% prod.)", min_value=0.0, max_value=20.0, value=3.0, step=0.5, key="eco_auxiliary_electricity_ratio_pct")
        st.caption("Le P1' solaire ne couvre pas les pompes de transfert solaire vers BTES.")

        st.markdown("#### P2 - Maintenance")
        p2a, p2b = st.columns(2)
        p2a.info("P2 solaire fixe : 1 % du CAPEX solaire brut par an, soit P2 = 0.01 x CAPEX solaire / production solaire totale.")
        backup_p2_eur_kw_year = p2b.number_input("P2 appoint gaz (EUR/kW.an)", min_value=0.0, max_value=100.0, value=10.0, step=1.0, key="eco_backup_p2_eur_kw_year")

        st.markdown("#### P4 - Investissements")
        st.dataframe(display_dataframe(economics_fixed.p4_table()), width="stretch", hide_index=True)
        st.caption(
            "CAPEX = S x coût unitaire(S). Aide ADEME solaire plafonnée à 65 % du CAPEX. "
            "Les autres aides publiques sont forcées à 0 EUR."
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


def render_parametric_forms(area_m2: float, *, disabled: bool = False) -> ParametricFormsResult:
    if disabled:
        return ParametricFormsResult(
            pac=ParametricRange(False, 50.0, 100.0, 10.0),
            solar=ParametricRange(False, max(0.0, float(area_m2) * 0.5), max(50.0, float(area_m2) * 1.5), 250.0),
        )

    with st.expander("6) Étude paramétrique PAC", expanded=False):
        enable_pac_power_parametric = st.checkbox("Activer l'étude paramétrique sur la puissance PAC", value=False, key="param_pac_enabled")
        pp1, pp2, pp3 = st.columns(3)
        param_pac_fraction_min_pct = pp1.number_input("P PAC min (% Pmax BT)", min_value=1.0, max_value=150.0, value=50.0, step=5.0, key="param_pac_min_pct")
        param_pac_fraction_max_pct = pp2.number_input("P PAC max (% Pmax BT)", min_value=1.0, max_value=150.0, value=100.0, step=5.0, key="param_pac_max_pct")
        param_pac_fraction_step_pct = pp3.number_input("Pas PAC (% Pmax BT)", min_value=1.0, max_value=50.0, value=10.0, step=5.0, key="param_pac_step_pct")
        st.caption(
            "Chaque point relance la simulation 8760 h en désactivant le solaire thermique. "
            "L'appoint gaz couvre tout le besoin HT et le complément BT non couvert par PAC. "
            "Si le prédimensionnement sondes est activé, le nombre de sondes est recalculé pour chaque puissance PAC. "
            "Limite de sécurité : 25 points."
        )

    with st.expander("7) Étude paramétrique solaire + injection BTES", expanded=False):
        enable_solar_surface_parametric = st.checkbox("Activer l'étude paramétrique sur la surface solaire", value=False, key="param_solar_enabled")
        p1, p2, p3 = st.columns(3)
        param_surface_min_m2 = p1.number_input("Surface min étudiée (m²)", min_value=0.0, value=max(0.0, float(area_m2) * 0.5), step=50.0, key="param_surface_min_m2")
        param_surface_max_m2 = p2.number_input("Surface max étudiée (m²)", min_value=0.0, value=max(50.0, float(area_m2) * 1.5), step=50.0, key="param_surface_max_m2")
        param_surface_step_m2 = p3.number_input("Pas de surface (m²)", min_value=1.0, value=250.0, step=50.0, key="param_surface_step_m2")
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

