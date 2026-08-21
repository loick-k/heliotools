"""Interface de développement HelioCOP V2 — V1.

Cette interface est volontairement séparée de l'application historique. Elle
permet de valider la nouvelle couche fabricant et le screening énergétique V2
sans modifier la note d'opportunité V1.6.2.
"""
from __future__ import annotations
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st

from .hourly_profile import load_hourly_profile
from .manufacturer import ManufacturerRegistry
from .predim import (
    simulate_screening_v2,
    storage_capacity_kwh,
    evaluate_screening_configurations_v2,
    minimum_storage_for_each_pac_v2,
    pareto_screening_options_v2,
)
from .dynamic import ECS1DynamicConfig, read_dynamic_weather_epw_zip, simulate_ecs1_dynamic

ASSETS = Path(__file__).resolve().parent / "assets"
EXAMPLE_PROFILE = ASSETS / "profil_8760h_exemple_EHPAD.xlsx"


def _hp_label(product) -> str:
    return f"{product.manufacturer} — {product.model} ({product.nominal_power_kw:g} kW) [{product.data_quality.value}]"


def _manufacturer_table(registry: ManufacturerRegistry) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Fabricant": p.manufacturer,
                "Modèle": p.model,
                "Puissance nominale (kW)": p.nominal_power_kw,
                "Qualité données": p.data_quality.value,
                "Predim": "Oui" if p.predim_available else "Non",
                "Dynamique": "Oui" if p.dynamic_available else "Non",
                "T source min (°C)": p.source_temperature_min_C,
                "T source max (°C)": p.source_temperature_max_C,
                "T chaud max (°C)": p.sink_temperature_max_C,
                "Provenance": p.provenance,
            }
            for p in registry.heat_pumps
        ]
    )


def _render_registry(registry: ManufacturerRegistry) -> None:
    st.subheader("Bibliothèque fabricant stricte")
    st.caption(
        "Les PAC sans données suffisantes sont exclues du mode concerné. "
        "Les XML clairsemés seuls sont admis en prédimensionnement mais pas en dynamique annuelle ; "
        "une carte numérisée/reconstruite traçable peut les enrichir pour le dynamique."
    )
    st.dataframe(_manufacturer_table(registry), hide_index=True, width="stretch")
    dyn = registry.available_heat_pumps(mode="dynamic")
    if dyn:
        st.success("PAC disponibles en dynamique V1 : " + ", ".join(f"{p.manufacturer} {p.model}" for p in dyn))
    else:
        st.error("MISSING_HP_MAP — aucune PAC ne possède une carte dynamique exploitable.")

    st.markdown("#### Capteurs WISC catalogués")
    rows = []
    for c in registry.collectors:
        rows.append(
            {
                "Fabricant": c.manufacturer,
                "Modèle": c.model,
                "Certification": c.certification,
                "Surface unitaire (m²)": c.unit_area_m2,
                "η0": c.coefficients.get("eta0"),
                "a1": c.coefficients.get("a1"),
                "a7": c.coefficients.get("a7"),
                "a8": c.coefficients.get("a8"),
                "Mapping dynamique": c.equation_schema or "Non défini",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.info(
        "Les coefficients eta0/a1…a8/KT/KL sont conservés intégralement. "
        "Le module ECS1 dynamique utilise désormais le mapping quasi-dynamique QDT V1 documenté dans docs_v2/DYNAMIC_ECS1_V1.md."
    )


def _load_profile_from_ui(*, key_prefix: str):
    """Charge un profil avec des clés Streamlit propres à chaque vue.

    Streamlit exécute le contenu de tous les ``st.tabs`` à chaque rerun, même
    lorsque l'onglet n'est pas visible. Le prédimensionnement et l'ECS1
    dynamique appellent donc tous deux ce helper pendant le même run : leurs
    widgets doivent avoir des clés différentes.
    """
    uploaded = st.file_uploader(
        "Profil HelioTools 8760 h (.xlsx ou .csv)",
        type=["xlsx", "xls", "csv"],
        key=f"heliocop_v2_{key_prefix}_profile_upload",
    )
    use_example = st.checkbox(
        "Utiliser le profil EHPAD d'exemple fourni",
        value=uploaded is None,
        key=f"heliocop_v2_{key_prefix}_profile_example",
    )
    if uploaded is not None:
        return load_hourly_profile(uploaded, source_name=uploaded.name)
    if use_example and EXAMPLE_PROFILE.is_file():
        return load_hourly_profile(EXAMPLE_PROFILE)
    return None


def _screening_option_table(options) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Fabricant": o.manufacturer,
                "Configuration PAC": f"{o.unit_count} × {o.model}",
                "P PAC installée (kW)": o.installed_power_kw,
                "Stockage (L)": o.storage_volume_l,
                "Capacité stockage (kWh)": o.result.storage_capacity_kWh,
                "Couverture (%)": 100.0 * o.result.coverage_fraction,
                "Non servi (MWh)": o.result.unmet_energy_mwh,
                "SOC mini (%)": 100.0 * o.result.min_soc_fraction,
                "Équiv. pleine charge (h/an)": o.result.equivalent_full_load_hours,
                "Qualité données PAC": o.data_quality,
            }
            for o in options
        ]
    )


@st.cache_data(show_spinner=False)
def _scan_screening_cached(
    profile,
    product_specs,
    storage_choices,
    max_count: int,
    storage_temperature_c: float,
    reference_temperature_c: float,
):
    """Version cache-safe du balayage PAC / stockage.

    ``HeatPumpProduct`` contient des objets de carte/interpolation que Streamlit
    ne sait pas toujours hacher (notamment depuis l'ajout des cartes P-25/P-50).
    Le screening n'utilise pourtant que quatre champs simples du produit. On ne
    transmet donc au cache qu'un tuple de primitives totalement déterministe,
    puis on reconstruit des objets légers à l'intérieur de la fonction.
    """
    from types import SimpleNamespace

    products = tuple(
        SimpleNamespace(
            manufacturer=manufacturer,
            model=model,
            nominal_power_kw=float(nominal_power_kw),
            data_quality=data_quality,
        )
        for manufacturer, model, nominal_power_kw, data_quality in product_specs
    )
    return evaluate_screening_configurations_v2(
        profile,
        heat_pumps=products,
        storage_volumes_l=storage_choices,
        max_pac_count=max_count,
        storage_temperature_c=storage_temperature_c,
        reference_temperature_c=reference_temperature_c,
    )


def _render_screening(registry: ManufacturerRegistry) -> None:
    st.subheader("Predim V2 — configurations PAC / stockage sur 8 760 h")
    st.info(
        "Le calcul balaie automatiquement les gammes PAC fabricant et les volumes de stockage, comme dans HelioCOP V1. "
        "Il s'agit encore d'un screening capacité/stockage : puissance PAC constante, sans COP horaire ni contrainte WISC. "
        "Le SOC est exprimé en kWh à référence fixe et la cyclicité annuelle est contrôlée."
    )
    profile = _load_profile_from_ui(key_prefix="predim")
    if profile is None:
        st.info("Importez un profil 8760 h ou activez le profil d’exemple pour lancer le prédimensionnement.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Besoin annuel", f"{profile.annual_energy_mwh:.2f} MWh")
    c2.metric("Pointe horaire", f"{profile.peak_hourly_kw:.2f} kW")
    c3.metric("Heures non nulles", str(profile.nonzero_hours))

    products = registry.available_heat_pumps(mode="predim")
    if not products:
        st.error("MISSING_HP_MAP — aucune PAC avec données fabricant n'est disponible pour le prédimensionnement.")
        return

    st.markdown("#### Hypothèses communes du balayage")
    h1, h2, h3 = st.columns(3)
    t_storage = h1.number_input(
        "T stockage (°C)", min_value=35.0, max_value=75.0, value=60.0, step=1.0,
        key="heliocop_v2_predim_tstorage",
    )
    t_ref = h2.number_input(
        "T référence énergie (°C)", min_value=0.0, max_value=25.0, value=10.0, step=1.0,
        key="heliocop_v2_predim_tref",
    )
    max_count = h3.number_input(
        "Nombre maxi de PAC identiques", min_value=1, max_value=10, value=6, step=1,
        key="heliocop_v2_predim_max_count",
    )
    storage_choices = (1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000, 10000, 12000, 15000, 20000)
    st.caption(
        "Volumes testés : " + ", ".join(f"{v:g} L" for v in storage_choices) + ". "
        "Les Solerpac P-25 et P-50 sont incluses en prédimensionnement et en ECS1 dynamique ; "
        "leur COP provient des courbes fabricant numérisées et leur puissance dynamique est reconstruite avec traçabilité."
    )

    # Le cache reçoit uniquement les champs réellement utilisés par le screening.
    # Cela évite StreamlitDuplicate/UnhashableParamError avec les cartes fabricant
    # (interpolateurs, tableaux numpy, etc.) attachées aux objets PAC dynamiques.
    product_specs = tuple(
        (
            str(p.manufacturer),
            str(p.model),
            float(p.nominal_power_kw),
            str(getattr(p.data_quality, "value", p.data_quality)),
        )
        for p in products
    )

    with st.spinner("Test automatique des couples PAC / stockage sur 8 760 h…"):
        evaluated = _scan_screening_cached(
            profile,
            product_specs,
            storage_choices,
            int(max_count),
            float(t_storage),
            float(t_ref),
        )
    minimum_options = minimum_storage_for_each_pac_v2(evaluated)
    pareto_options = pareto_screening_options_v2(minimum_options)
    feasible_all = tuple(o for o in evaluated if o.result.is_feasible)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Configurations testées", f"{len(evaluated)}")
    m2.metric("Configurations faisables", f"{len(feasible_all)}")
    m3.metric("Configurations minimales", f"{len(minimum_options)}")
    m4.metric("Solutions Pareto", f"{len(pareto_options)}")

    if not feasible_all:
        st.error(
            "Aucune combinaison de la bibliothèque actuelle ne couvre 100 % du profil avec les volumes et le nombre de PAC testés."
        )
        partial = sorted(
            evaluated,
            key=lambda o: (-o.result.coverage_fraction, o.installed_power_kw, -o.storage_volume_l),
        )[:12]
        st.markdown("#### Meilleures configurations partielles")
        st.dataframe(_screening_option_table(partial), hide_index=True, width="stretch")
    else:
        st.markdown("#### Configurations minimales permettant de couvrir les besoins")
        st.caption(
            "Pour chaque modèle et nombre de PAC, HelioCOP conserve le plus petit stockage testé qui couvre le profil et retrouve son état annuel."
        )
        minimum_df = _screening_option_table(minimum_options)
        st.dataframe(minimum_df, hide_index=True, width="stretch")
        if not minimum_df.empty:
            try:
                import plotly.express as px
                fig = px.scatter(
                    minimum_df,
                    x="Stockage (L)",
                    y="P PAC installée (kW)",
                    color="Fabricant",
                    hover_name="Configuration PAC",
                    hover_data=["Couverture (%)", "SOC mini (%)", "Qualité données PAC"],
                    title="Configurations minimales couvrant le profil",
                )
                st.plotly_chart(fig, width="stretch", key="heliocop_v2_predim_configurations_scatter")
            except Exception:
                pass

        st.markdown("#### Front de Pareto — puissance PAC / stockage")
        st.caption(
            "Une solution du front de Pareto ne peut pas réduire simultanément la puissance PAC et le volume de stockage sans perdre la couverture."
        )
        st.dataframe(_screening_option_table(pareto_options), hide_index=True, width="stretch")

        if pareto_options:
            labels = [o.label for o in pareto_options]
            selected_label = st.selectbox(
                "Configuration PAC / stockage à examiner",
                labels,
                index=0,
                key="heliocop_v2_predim_pareto_choice",
            )
            selected = pareto_options[labels.index(selected_label)]
            detail, trace = simulate_screening_v2(
                profile,
                pac_power_kw=selected.installed_power_kw,
                storage_volume_l=selected.storage_volume_l,
                storage_temperature_c=float(t_storage),
                reference_temperature_c=float(t_ref),
                with_trace=True,
            )
            d1, d2, d3, d4, d5 = st.columns(5)
            d1.metric("PAC installée", f"{selected.installed_power_kw:.1f} kW")
            d2.metric("Stockage", f"{selected.storage_volume_l:g} L")
            d3.metric("Couverture", f"{100*detail.coverage_fraction:.2f} %")
            d4.metric("SOC mini", f"{100*detail.min_soc_fraction:.1f} %")
            d5.metric("Cyclique", "Oui" if detail.cyclic_ok else "NON")
            st.success(
                f"Configuration sélectionnée : {selected.unit_count} × {selected.model} ({selected.manufacturer}) "
                f"+ {selected.storage_volume_l:g} L."
            )
            trace_df = pd.DataFrame([row.__dict__ for row in trace])
            if not trace_df.empty:
                st.line_chart(trace_df[["storage_soc_fraction"]], height=240)
                st.caption("SOC horaire du stockage énergétique simplifié pour la configuration sélectionnée.")

        with st.expander("Toutes les configurations faisables", expanded=False):
            st.dataframe(_screening_option_table(feasible_all), hide_index=True, width="stretch")

    with st.expander("Test manuel d'une configuration", expanded=False):
        hp = st.selectbox("PAC", products, format_func=_hp_label, key="heliocop_v2_screen_hp")
        cols = st.columns(3)
        count = cols[0].number_input(
            "Nombre de PAC", min_value=1, max_value=10, value=1, step=1,
            key="heliocop_v2_hp_count",
        )
        storage_l = cols[1].selectbox(
            "Stockage total (L)", list(storage_choices), index=3,
            key="heliocop_v2_storage",
        )
        capacity_kwh = storage_capacity_kwh(
            float(storage_l), storage_temperature_c=float(t_storage), reference_temperature_c=float(t_ref)
        )
        cols[2].metric("Capacité stockage", f"{capacity_kwh:.1f} kWh")
        installed_kw = hp.nominal_power_kw * int(count)
        result, _ = simulate_screening_v2(
            profile,
            pac_power_kw=installed_kw,
            storage_volume_l=float(storage_l),
            storage_temperature_c=float(t_storage),
            reference_temperature_c=float(t_ref),
            with_trace=False,
        )
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("P installée", f"{installed_kw:.1f} kW")
        a2.metric("Couverture", f"{100*result.coverage_fraction:.2f} %")
        a3.metric("Non servi", f"{result.unmet_energy_mwh:.3f} MWh")
        a4.metric("SOC final", f"{100*result.final_soc_fraction:.1f} %")
        if result.is_feasible:
            st.success("Configuration faisable au sens du screening V2.")
        elif not result.cyclic_ok:
            st.error("NON_CYCLIC_ANNUAL_STATE — la configuration consomme une partie du stock initial sur l'année.")
        else:
            st.error(
                f"Configuration insuffisante — {result.unmet_energy_mwh:.2f} MWh non servis sur {result.unmet_hours} h. "
                "Augmentez la puissance PAC et/ou le stockage."
            )

def _render_hp_map(registry: ManufacturerRegistry) -> None:
    st.subheader("Cartographies PAC dynamiques")
    products = registry.available_heat_pumps(mode="dynamic")
    if not products:
        st.error("MISSING_HP_MAP — aucune carte dynamique disponible.")
        return
    hp = st.selectbox("PAC dynamique", products, format_func=_hp_label, key="heliocop_v2_dynamic_hp")
    hp_map = hp.performance_map
    assert hp_map is not None
    sb = hp_map.source_bounds_C
    hb = hp_map.sink_bounds_C
    st.caption(
        f"Convention : source = entrée glycol ; côté chaud = {hp_map.sink_temperature_convention}. "
        f"Domaine numérisé : source {sb[0]:g}…{sb[1]:g} °C ; chaud {hb[0]:g}…{hb[1]:g} °C."
    )
    c1, c2 = st.columns(2)
    ts = c1.slider("Température source entrée (°C)", float(sb[0]), float(sb[1]), min(10.0, float(sb[1])), 0.5, key="heliocop_v2_ts")
    sink_axis_label = "Température eau entrée côté chaud (°C)" if hp_map.sink_temperature_convention == "sink_in" else "Température eau sortie côté chaud (°C)"
    th = c2.slider(sink_axis_label, float(hb[0]), float(hb[1]), min(40.0, float(hb[1])), 0.5, key="heliocop_v2_th")
    point = hp_map.evaluate(T_source_in_C=ts, T_sink_C=th)
    if not point.valid:
        st.error("OUTSIDE_HP_MAP — aucune extrapolation n'est autorisée.")
        return
    cols = st.columns(4)
    cols[0].metric("P chaleur", f"{point.P_heat_kW:.2f} kW")
    cols[1].metric("P électrique", f"{point.P_el_kW:.2f} kW")
    cols[2].metric("COP", f"{point.COP:.2f}")
    cols[3].metric("P évaporateur", f"{point.P_evap_kW:.2f} kW")
    st.caption(f"Provenance : {point.provenance}. Incertitude de numérisation V1 : ±{point.uncertainty_pct:g} %." if point.uncertainty_pct else f"Provenance : {point.provenance}")

    # Tableau de courbes reconstituées sans extrapolation.
    source_grid = sorted({p.T_source_in_C for p in hp_map.points})
    sink_grid = sorted({p.T_sink_C for p in hp_map.points})
    curves = []
    for sink in sink_grid:
        for source in source_grid:
            p = hp_map.evaluate(T_source_in_C=source, T_sink_C=sink)
            if p.valid:
                curves.append({"T source (°C)": source, "T chaud (°C)": sink, "COP": p.COP})
    df = pd.DataFrame(curves)
    if not df.empty:
        try:
            import plotly.express as px
            fig = px.line(df, x="T source (°C)", y="COP", color="T chaud (°C)", markers=True, title=f"Carte COP numérisée — {hp.model}")
            st.plotly_chart(fig, width="stretch", key="heliocop_v2_cop_map")
        except Exception:
            st.dataframe(df, hide_index=True, width="stretch")




def _month_label_series(values: pd.Series) -> pd.Series:
    labels = {
        1: "Jan", 2: "Fév", 3: "Mar", 4: "Avr", 5: "Mai", 6: "Juin",
        7: "Juil", 8: "Août", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Déc",
    }
    numeric = pd.to_numeric(values, errors="coerce").astype("Int64")
    return numeric.map(labels)


def _render_dynamic_result_charts(result) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = result.hourly.copy()
    df["month"] = pd.to_numeric(df["month"], errors="coerce")
    df["E_electric_total_kWh"] = (
        pd.to_numeric(df.get("E_HP_el_kWh"), errors="coerce").fillna(0.0)
        + pd.to_numeric(df.get("E_source_pump_kWh"), errors="coerce").fillna(0.0)
        + pd.to_numeric(df.get("E_sink_pump_kWh"), errors="coerce").fillna(0.0)
    )

    monthly = (
        df.groupby("month", dropna=False)
        .agg(
            E_demand_kWh=("E_demand_kWh", "sum"),
            E_renewable_kWh=("E_preheat_from_tank_kWh", "sum"),
            E_backup_kWh=("E_backup_kWh", "sum"),
            E_electric_kWh=("E_electric_total_kWh", "sum"),
            E_HP_heat_kWh=("E_HP_heat_kWh", "sum"),
            E_HP_el_kWh=("E_HP_el_kWh", "sum"),
            HP_runtime_h=("HP_runtime_h", "sum"),
        )
        .reset_index()
        .sort_values("month")
    )
    monthly["month_label"] = _month_label_series(monthly["month"])
    monthly["renewable_rate_pct"] = monthly.apply(
        lambda r: 100.0 * r["E_renewable_kWh"] / r["E_demand_kWh"] if r["E_demand_kWh"] > 1e-9 else 0.0,
        axis=1,
    )
    monthly["COP_month"] = monthly.apply(
        lambda r: r["E_HP_heat_kWh"] / r["E_HP_el_kWh"] if r["E_HP_el_kWh"] > 1e-9 else None,
        axis=1,
    )

    st.markdown("#### Graphiques d'analyse dynamique")
    fig_energy = make_subplots(specs=[[{"secondary_y": True}]])
    fig_energy.add_bar(x=monthly["month_label"], y=monthly["E_renewable_kWh"] / 1000.0, name="Part ENR utile", hovertemplate="%{y:.2f} MWh<extra></extra>")
    fig_energy.add_bar(x=monthly["month_label"], y=monthly["E_backup_kWh"] / 1000.0, name="Appoint", hovertemplate="%{y:.2f} MWh<extra></extra>")
    fig_energy.add_bar(x=monthly["month_label"], y=monthly["E_electric_kWh"] / 1000.0, name="Conso élec PAC + auxiliaires", hovertemplate="%{y:.2f} MWh<extra></extra>")
    fig_energy.add_scatter(
        x=monthly["month_label"], y=monthly["renewable_rate_pct"], name="Taux ENR", mode="lines+markers",
        line=dict(color="#ef553b"), secondary_y=True, hovertemplate="%{y:.1f} %<extra></extra>"
    )
    fig_energy.update_layout(
        barmode="stack",
        title="Apports énergétiques mensuels — appoint, part ENR et consommation électrique",
        legend_title_text="Contributions",
        xaxis_title="Mois",
        yaxis_title="Énergie (MWh/mois)",
        height=500,
    )
    fig_energy.update_yaxes(title_text="Taux ENR (%)", secondary_y=True)
    st.plotly_chart(fig_energy, width="stretch", key="heliocop_v2_dyn_monthly_energy")

    fig_cop = go.Figure()
    fig_cop.add_bar(x=monthly["month_label"], y=monthly["HP_runtime_h"], name="Heures de marche PAC", yaxis="y2", opacity=0.35)
    fig_cop.add_scatter(
        x=monthly["month_label"], y=monthly["COP_month"], name="COP mensuel", mode="lines+markers",
        hovertemplate="COP %{y:.2f}<extra></extra>"
    )
    fig_cop.update_layout(
        title="Évolution du COP mensuel",
        xaxis_title="Mois",
        yaxis=dict(title="COP (-)"),
        yaxis2=dict(title="Heures de marche PAC", overlaying="y", side="right", showgrid=False),
        height=420,
    )
    st.plotly_chart(fig_cop, width="stretch", key="heliocop_v2_dyn_monthly_cop")

    monotone = df[["hour_index", "E_demand_kWh", "E_preheat_from_tank_kWh", "E_backup_kWh"]].copy()
    monotone = monotone.sort_values("E_demand_kWh", ascending=False).reset_index(drop=True)
    monotone["rank"] = monotone.index + 1
    fig_monotone = go.Figure()
    fig_monotone.add_bar(x=monotone["rank"], y=monotone["E_preheat_from_tank_kWh"], name="Couverture ENR utile", hovertemplate="%{y:.2f} kWh<extra></extra>")
    fig_monotone.add_bar(x=monotone["rank"], y=monotone["E_backup_kWh"], name="Couverture appoint", hovertemplate="%{y:.2f} kWh<extra></extra>")
    fig_monotone.add_scatter(x=monotone["rank"], y=monotone["E_demand_kWh"], name="Besoin horaire monotone", mode="lines", line=dict(color="#111111", width=2), hovertemplate="%{y:.2f} kWh<extra></extra>")
    fig_monotone.update_layout(
        barmode="stack",
        title="Monotone horaire du besoin et couverture par générateur",
        xaxis_title="Heures classées par besoin décroissant",
        yaxis_title="Énergie horaire (kWh/h)",
        height=500,
    )
    st.plotly_chart(fig_monotone, width="stretch", key="heliocop_v2_dyn_monotone")

    with st.expander("Voir le tableau mensuel utilisé pour les graphiques"):
        shown = monthly[["month_label", "E_demand_kWh", "E_renewable_kWh", "E_backup_kWh", "E_electric_kWh", "renewable_rate_pct", "COP_month", "HP_runtime_h"]].copy()
        shown.columns = ["Mois", "Besoin (kWh)", "Part ENR utile (kWh)", "Appoint (kWh)", "Conso élec (kWh)", "Taux ENR (%)", "COP mensuel (-)", "Heures marche PAC"]
        st.dataframe(shown, hide_index=True, width="stretch")

def _dynamic_station_options() -> list[Path]:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    return sorted(data_dir.glob("*.zip"), key=lambda p: p.name.lower())


def _station_label(path: Path) -> str:
    name = path.stem.replace("FRA_", "").replace("_TMYx", "").replace(".2011-2025", "")
    return name.replace(".", " ").replace("_", " — ")


def _collector_label(product) -> str:
    return f"{product.manufacturer} — {product.model} ({product.unit_area_m2:g} m²/unité)"


def _dynamic_excel_bytes(result) -> bytes:
    from io import BytesIO
    buffer = BytesIO()
    summary = pd.DataFrame([result.summary.__dict__])
    monthly = result.hourly.copy()
    monthly["month"] = pd.to_numeric(monthly["month"], errors="coerce")
    agg = monthly.groupby("month", dropna=False).agg(
        E_demand_kWh=("E_demand_kWh", "sum"),
        E_preheat_kWh=("E_preheat_from_tank_kWh", "sum"),
        E_backup_kWh=("E_backup_kWh", "sum"),
        E_HP_heat_kWh=("E_HP_heat_kWh", "sum"),
        E_HP_el_kWh=("E_HP_el_kWh", "sum"),
        E_collector_kWh=("E_collector_kWh", "sum"),
        HP_runtime_h=("HP_runtime_h", "sum"),
        T_source_mean_C=("T_source_in_C", "mean"),
        COP_mean=("COP_hour", "mean"),
    ).reset_index()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        result.hourly.to_excel(writer, sheet_name="resultats_8760h", index=False)
        agg.to_excel(writer, sheet_name="bilan_mensuel", index=False)
        summary.to_excel(writer, sheet_name="KPI", index=False)
    return buffer.getvalue()


def _render_dynamic_ecs1(registry: ManufacturerRegistry) -> None:
    st.subheader("ECS1 dynamique — WISC → PAC → préchauffage → appoint")
    st.info(
        "Premier solveur physique annuel : météo EPW horaire, modèle WISC quasi-dynamique, "
        "équilibre champ/évaporateur, cartes PAC Heliopac numérisées/reconstruites et ballon 3 nœuds. "
        "La condensation, le givre et la pluie ne sont pas encore ajoutés séparément."
    )
    profile = _load_profile_from_ui(key_prefix="dynamic")
    if profile is None:
        st.info("Importez un profil 8760 h ou activez le profil d’exemple pour lancer l’ECS1 dynamique.")
        return
    stations = _dynamic_station_options()
    if not stations:
        st.error("Aucune météo EPW ZIP n'est disponible dans le package.")
        return
    dyn_hps = registry.available_heat_pumps(mode="dynamic")
    if not dyn_hps:
        st.error("MISSING_HP_MAP — aucune PAC dynamique disponible.")
        return
    if not registry.collectors:
        st.error("MISSING_COLLECTOR_DATA — aucun capteur WISC disponible.")
        return

    c1, c2 = st.columns(2)
    station = c1.selectbox("Station météo TMY", stations, format_func=_station_label, key="heliocop_v2_dyn_station")
    hp = c2.selectbox("PAC", dyn_hps, format_func=_hp_label, key="heliocop_v2_dyn_hp")
    if hp.data_quality.value == "DIGITIZED_COP_WITH_RECONSTRUCTED_POWER":
        st.warning(
            "Solerpac gamme P — dynamique V1 expérimentale : le COP est numérisé sur les courbes 25/35/45/55 °C. "
            "La puissance thermique 2D est reconstruite à partir de la courbe à 35 °C et de points FT1p/XML fabricant. "
            "Aucune extrapolation hors source -5…50 °C ni hors sortie eau 25…55 °C."
        )
    c3, c4, c5 = st.columns(3)
    collector = c3.selectbox("Capteur WISC", registry.collectors, format_func=_collector_label, key="heliocop_v2_dyn_collector")
    hp_count = c4.number_input("Nombre de PAC", min_value=1, max_value=12, value=1, step=1, key="heliocop_v2_dyn_hp_count")
    default_area = max(collector.unit_area_m2, round(hp.nominal_power_kw * int(hp_count) * 5.0 / collector.unit_area_m2) * collector.unit_area_m2)
    area = c5.number_input("Surface capteurs (m²)", min_value=float(collector.unit_area_m2), value=float(default_area), step=float(collector.unit_area_m2), key="heliocop_v2_dyn_area")

    st.markdown("#### Géométrie et météo")
    c1, c2, c3 = st.columns(3)
    tilt = c1.number_input("Inclinaison (°)", min_value=0.0, max_value=90.0, value=30.0, step=5.0, key="heliocop_v2_dyn_tilt")
    azimuth = c2.number_input("Azimut depuis le Sud (° ; Est négatif)", min_value=-180.0, max_value=180.0, value=0.0, step=5.0, key="heliocop_v2_dyn_azimuth")
    albedo = c3.number_input("Albédo", min_value=0.0, max_value=1.0, value=0.20, step=0.05, key="heliocop_v2_dyn_albedo")

    st.markdown("#### Ballon de préchauffage ECS1")
    c1, c2, c3, c4 = st.columns(4)
    tank_volume = c1.number_input("Volume ballon (L)", min_value=100.0, value=2000.0, step=100.0, key="heliocop_v2_dyn_tank")
    cold = c2.number_input("Eau froide (°C)", min_value=2.0, max_value=25.0, value=12.0, step=0.5, key="heliocop_v2_dyn_cold")
    service = c3.number_input("Température service (°C)", min_value=40.0, max_value=70.0, value=55.0, step=1.0, key="heliocop_v2_dyn_service")
    preheat = c4.number_input("Consigne préchauffage (°C)", min_value=22.0, max_value=55.0, value=45.0, step=1.0, key="heliocop_v2_dyn_preheat")
    c1, c2, c3, c4 = st.columns(4)
    hyst = c1.number_input("Hystérésis (K)", min_value=0.5, max_value=10.0, value=3.0, step=0.5, key="heliocop_v2_dyn_hyst")
    t_init = c2.number_input("T initiale ballon (°C)", min_value=22.0, max_value=55.0, value=35.0, step=1.0, key="heliocop_v2_dyn_tinit")
    ua = c3.number_input("UA ballon (W/K)", min_value=0.0, max_value=50.0, value=4.0, step=0.5, key="heliocop_v2_dyn_ua")
    g_inter = c4.number_input("Conductance inter-couches (W/K)", min_value=0.0, max_value=30.0, value=2.0, step=0.5, key="heliocop_v2_dyn_ginter")

    st.markdown("#### Régulation")
    c1, c2, c3, c4 = st.columns(4)
    schedule_mode = c1.selectbox("Plage PAC", ["24 h / 24", "Plage préférentielle"], key="heliocop_v2_dyn_schedule")
    start = c2.number_input("Début plage", min_value=0, max_value=23, value=10, step=1, key="heliocop_v2_dyn_start", disabled=schedule_mode == "24 h / 24")
    end = c3.number_input("Fin plage", min_value=1, max_value=24, value=18, step=1, key="heliocop_v2_dyn_end", disabled=schedule_mode == "24 h / 24")
    min_cop = c4.number_input("COP minimum de marche", min_value=0.0, max_value=10.0, value=0.0, step=0.1, key="heliocop_v2_dyn_mincop")
    c1, c2, c3, c4 = st.columns(4)
    source_flow_default = float(hp.source_flow_m3h or 0.0)
    sink_flow_default = float(hp.sink_flow_m3h or 0.0)
    source_pump_default = float(hp.source_pump_kW or 0.0)
    sink_pump_default = float(hp.sink_pump_kW or 0.0)
    source_flow = c1.number_input("Débit captage / PAC (m³/h)", min_value=0.0, value=source_flow_default, step=0.1, key="heliocop_v2_dyn_sourceflow")
    sink_flow = c2.number_input("Débit chauffage / PAC (m³/h)", min_value=0.0, value=sink_flow_default, step=0.1, key="heliocop_v2_dyn_sinkflow")
    source_pump = c3.number_input("Pompe source / PAC (kW)", min_value=0.0, value=source_pump_default, step=0.025, key="heliocop_v2_dyn_sourcepump")
    sink_pump = c4.number_input("Pompe chaud / PAC (kW)", min_value=0.0, value=sink_pump_default, step=0.025, key="heliocop_v2_dyn_sinkpump")
    if hp.source_pump_kW is None or hp.sink_pump_kW is None:
        st.caption("Un auxiliaire fabricant non renseigné reste à 0 dans cette V1 : vérifier le SPF système avant usage de référence.")

    st.markdown("#### Résolution temporelle")
    resolution_label = st.selectbox(
        "Pas de calcul de la régulation ECS1",
        ["Rapide — 1 pas/h", "Standard — 2 pas/h (30 min)", "Détaillé — 6 pas/h (10 min)"],
        index=2,
        key="heliocop_v2_dyn_resolution",
        help=(
            "La météo et le profil d'entrée restent horaires. Le ballon conserve ses sous-pas internes de 10 min. "
            "Le mode détaillé raffine surtout la régulation PAC/soutirage et sert à l'étude de sensibilité."
        ),
    )
    substeps_per_hour = {
        "Rapide — 1 pas/h": 1,
        "Standard — 2 pas/h (30 min)": 2,
        "Détaillé — 6 pas/h (10 min)": 6,
    }[resolution_label]
    st.caption(
        f"Charge numérique : {8760 * substeps_per_hour:,} sous-pas/an. "
        "Le mode Détaillé reste le calcul de référence ; Rapide sert uniquement au screening/sensibilité."
    )

    st.markdown("#### Gestion des limites de carte PAC côté chaud")
    c1, c2 = st.columns(2)
    clamp_low = c1.checkbox(
        "Verrouiller sous la T retour minimale de la carte",
        value=True,
        key="heliocop_v2_dyn_clamp_sink_low",
        help="Si T retour est inférieure à la borne fabricant numérisée, le COP et la puissance sont évalués à cette borne basse. La température réelle du circuit reste utilisée pour le bilan hydraulique.",
    )
    clamp_high = c2.checkbox(
        "Verrouiller au-dessus de la T retour maximale (sensibilité)",
        value=False,
        key="heliocop_v2_dyn_clamp_sink_high",
        help="Désactivé par défaut : le verrouillage haut peut être optimiste. À utiliser seulement en étude de sensibilité.",
    )
    sink_bounds = hp.performance_map.sink_bounds_C if hp.performance_map is not None else (None, None)
    if sink_bounds[0] is not None:
        st.caption(
            f"Carte sélectionnée : T retour documentée/numérisée de {sink_bounds[0]:.1f} à {sink_bounds[1]:.1f} °C. "
            f"Sous {sink_bounds[0]:.1f} °C, le calcul de référence peut verrouiller la lecture de carte à la borne basse (`SINK_CLAMPED_LOW`) au lieu d'arrêter la PAC. La borne haute reste bloquante par défaut."
        )

    st.warning(
        "Modèle capteur V1 : équation quasi-dynamique eta0/a1…a8 avec référence vent 3 m/s. "
        "IAM direct approché à partir de KT/KL. Condensation/givre/pluie exclus de cette itération."
    )
    if st.button("Lancer ECS1 dynamique 8760 h", type="primary", key="heliocop_v2_dyn_run"):
        try:
            with st.spinner("Lecture météo et simulation ECS1 dynamique…"):
                weather = read_dynamic_weather_epw_zip(station, tilt_deg=float(tilt), azimuth_deg_south=float(azimuth), albedo=float(albedo))
                cfg = ECS1DynamicConfig(
                    collector_area_m2=float(area),
                    hp_count=int(hp_count),
                    tank_volume_l=float(tank_volume),
                    service_temperature_c=float(service),
                    cold_water_temperature_c=float(cold),
                    tank_initial_temperature_c=float(t_init),
                    tank_preheat_setpoint_c=float(preheat),
                    tank_hysteresis_k=float(hyst),
                    tank_max_temperature_c=min(65.0, max(float(preheat) + 5.0, float(preheat))),
                    tank_ambient_temperature_c=20.0,
                    tank_ua_w_per_k=float(ua),
                    interlayer_w_per_k=float(g_inter),
                    preferred_start_hour=0 if schedule_mode == "24 h / 24" else int(start),
                    preferred_end_hour=24 if schedule_mode == "24 h / 24" else int(end),
                    min_cop_to_run=float(min_cop),
                    substeps_per_hour=int(substeps_per_hour),
                    source_flow_m3h_per_hp=float(source_flow),
                    sink_flow_m3h_per_hp=float(sink_flow),
                    source_pump_kw_per_hp=float(source_pump),
                    sink_pump_kw_per_hp=float(sink_pump),
                    clamp_sink_below_map=bool(clamp_low),
                    clamp_sink_above_map=bool(clamp_high),
                )
                progress = st.progress(0.0, text="Simulation annuelle : 0 %")
                started = perf_counter()

                def _update_progress(done: int, total: int) -> None:
                    frac = min(1.0, max(0.0, done / max(1, total)))
                    progress.progress(frac, text=f"Simulation annuelle : {100.0 * frac:.0f} %")

                result = simulate_ecs1_dynamic(
                    profile=profile, weather=weather, heat_pump=hp, collector=collector, config=cfg,
                    progress_callback=_update_progress,
                )
                elapsed_s = perf_counter() - started
                progress.progress(1.0, text=f"Simulation terminée en {elapsed_s:.1f} s")
                st.session_state["heliocop_v2_ecs1_dynamic_result"] = result
                st.session_state["heliocop_v2_ecs1_dynamic_meta"] = {
                    "station": _station_label(station), "hp": _hp_label(hp), "collector": _collector_label(collector), "area": area,
                    "resolution": resolution_label, "elapsed_s": elapsed_s,
                }
        except Exception as exc:
            st.exception(exc)

    result = st.session_state.get("heliocop_v2_ecs1_dynamic_result")
    if result is None:
        return
    s = result.summary
    st.markdown("#### Résultats annuels")
    c = st.columns(8)
    c[0].metric("Besoin", f"{s.demand_mwh:.1f} MWh")
    c[1].metric("Préchauffage", f"{s.preheat_from_tank_mwh:.1f} MWh")
    c[2].metric("Appoint", f"{s.backup_mwh:.1f} MWh")
    c[3].metric("Élec PAC", f"{s.hp_electric_mwh:.1f} MWh")
    c[4].metric("COP moyen", f"{s.mean_cop_running:.2f}")
    c[5].metric("SPF PAC", f"{s.spf_hp:.2f}")
    c[6].metric("SPF système", f"{s.spf_system:.2f}")
    c[7].metric("Marche PAC", f"{s.hp_runtime_h:.0f} h")
    c = st.columns(7)
    c[0].metric("Source min", "—" if s.source_temp_min_c is None else f"{s.source_temp_min_c:.1f} °C")
    c[1].metric("Source moy", "—" if s.source_temp_mean_c is None else f"{s.source_temp_mean_c:.1f} °C")
    c[2].metric("Source max", "—" if s.source_temp_max_c is None else f"{s.source_temp_max_c:.1f} °C")
    c[3].metric("Collecteur", f"{s.collector_mwh:.1f} MWh")
    c[4].metric("dont solaire", f"{s.collector_solar_mwh:.1f} MWh")
    c[5].metric("dont air + IR", f"{s.collector_atmospheric_ir_mwh:.1f} MWh")
    c[6].metric("Pertes ballon", f"{s.tank_losses_mwh:.1f} MWh")
    st.caption(
        f"Auxiliaires hydrauliques : source {s.source_pump_mwh:.3f} MWh/an | côté chaud {s.sink_pump_mwh:.3f} MWh/an."
    )

    diagnostics = {
        "Source insuffisante (sous-pas)": s.hours_source_insufficient,
        "Hors carte PAC": s.hours_outside_hp_map,
        "T retour chaud hors carte": s.hours_sink_outside_hp_map,
        "T retour verrouillée bas": s.hours_sink_clamped_low,
        "T retour verrouillée haut": s.hours_sink_clamped_high,
        "Équilibre source > carte": s.hours_source_above_hp_map,
    }
    st.caption("Diagnostics : " + " | ".join(f"{k}: {v}" for k, v in diagnostics.items()))
    df = result.hourly
    try:
        import plotly.express as px
        fig1 = px.line(df, x="hour_index", y=["T_tank_top_C", "T_tank_middle_C", "T_tank_bottom_C", "T_source_in_C", "T_sink_in_C", "T_sink_lookup_C"], title="Températures ballon, source et retour PAC (réel / utilisé par la carte)")
        st.plotly_chart(fig1, width="stretch", key="heliocop_v2_dyn_temperatures")
        fig2 = px.line(df, x="hour_index", y="COP_hour", title="COP horaire lorsque la PAC fonctionne")
        st.plotly_chart(fig2, width="stretch", key="heliocop_v2_dyn_cop")
        _render_dynamic_result_charts(result)
    except Exception:
        st.dataframe(df.head(500), hide_index=True, width="stretch")

    xlsx = _dynamic_excel_bytes(result)
    st.download_button(
        "Exporter résultats ECS1 dynamique (.xlsx)",
        data=xlsx,
        file_name="HelioCOP_ECS1_dynamique_8760h.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="heliocop_v2_dyn_export",
    )

def render_heliocop_v2_app() -> None:
    st.title("HelioCOP V2 — ECS1 dynamique V1.0.7")
    st.caption("Predimensionnement + premier solveur dynamique WISC / PAC / ballon de préchauffage ECS1 — avec graphiques mensuels et monotone horaire.")
    registry = ManufacturerRegistry.from_package_data()
    tabs = st.tabs(["Données fabricant", "Predim 8760 h", "Carte PAC", "ECS1 dynamique", "Limites V1"])
    with tabs[0]:
        _render_registry(registry)
    with tabs[1]:
        _render_screening(registry)
    with tabs[2]:
        _render_hp_map(registry)
    with tabs[3]:
        _render_dynamic_ecs1(registry)
    with tabs[4]:
        st.subheader("Limites scientifiques de l'ECS1 dynamique V1")
        st.markdown(
            """
            - Le modèle WISC utilise la structure quasi-dynamique `eta0 / a1…a8` du XML produit.
            - La condensation, le givre et la pluie ne sont pas encore ajoutés séparément.
            - Les IAM KT/KL sont ramenés à un IAM direct équivalent à partir de l'angle global.
            - Les cartes PAC Heliopac i-10/i-15 sont numérisées depuis la fiche fabricant.
            - Les Solerpac P-25/P-50 sont disponibles en dynamique V1.0.4 : COP numérisé sur les courbes de sortie 25/35/45/55 °C ; puissance thermique reconstruite à partir de la courbe à 35 °C et de points FT1p/XML. Cette reconstruction est explicitement étiquetée et ne doit pas être confondue avec une table fabricant complète.
            - Pour les cartes `sink_out` P-25/P-50, le solveur résout la température de sortie compatible avec le retour ballon et le débit condenseur. Aucune extrapolation continue n'est autorisée hors du domaine numérisé.
            - En dessous de la borne basse côté chaud (22 °C sur les courbes Heliopac i), la V1.0.2 peut **verrouiller** l'évaluation à la borne basse : `T_sink_lookup = T_sink_min`, avec statut `SINK_CLAMPED_LOW`. La température réelle du retour reste utilisée pour calculer la température de sortie et le bilan hydraulique.
            - Au-dessus de la borne haute, le calcul reste bloquant par défaut (`SINK_OUTSIDE_HP_MAP`). Un verrouillage haut existe uniquement comme option de sensibilité et est explicitement signalé `SINK_CLAMPED_HIGH`.
            - Le ballon ECS1 est le modèle 3 nœuds existant de HelioTools ; ECS2 nécessitera plusieurs ports et une hydraulique de charge dédiée.
            - Le pas externe est 1 h avec 6 sous-pas de 10 min par défaut. Le profil de besoin reste horaire.
            - Le bouclage ECS n'est pas intégré dans ECS1 V1 ; l'appoint est considéré en aval du préchauffage.
            """
        )
