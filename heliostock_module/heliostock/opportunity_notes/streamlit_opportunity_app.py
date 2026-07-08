"""Outil d'aide à la note d'opportunité solaire thermique.

Lancement local :
    python -m streamlit run streamlit_opportunity_demo.py

Version V18 :
- suppression du champ "Type de bouclage" dans l'estimation des pertes ;
- le volume ECS de référence SOLO est déduit automatiquement de la conso ECS moyenne journalière divisée par le nombre d'unités ;
- conservation du bouclage SOLO complet, du collage Excel et du prédimensionnement.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:  # pragma: no cover
    go = None

from .cesc_economic_model import (
    ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY,
    CescEconomicInputs,
    TYPOLOGY_LABELS as ECONOMIC_SCENARIOS,
    build_yearly_cashflow_projection,
    compute_cesc_economic_model,
)
from .opportunity_model import (
    BUILDING_STATES,
    CAMPING_DEFAULT_L_PER_PERSON_NIGHT,
    DATA_SOURCES,
    DEFAULT_COLLECTOR_UNIT_AREA_M2,
    DEFAULT_LOOP_AMBIENT_TEMPERATURES_C,
    DEFAULT_MONTHLY_COEFFICIENTS,
    DEFAULT_PRODUCTIVITY_KWH_M2_YEAR,
    EHPAD_DEFAULT_L_PER_RESIDENT_DAY,
    HOSPITAL_DEFAULT_L_PER_BED_DAY,
    HOTEL_RATIOS_L_PER_ROOM_NIGHT,
    HOUSING_RATIOS_L_PER_DWELLING_DAY,
    LOOP_METHODS,
    MONTH_NAMES,
    SITE_TYPOLOGIES,
    SOLO_LOSS_INPUT_MODES,
    SOLO_LOOP_LOSS_MODE_LABELS,
    LoopInputs,
    NeedsInputs,
    SiteInputs,
    SizingInputs,
    compute_opportunity_results,
    dict_to_loop_inputs,
    dict_to_needs_inputs,
    dict_to_sizing_inputs,
    dict_to_site_inputs,
)

PROJECTS_DIR = Path.home() / ".heliotools" / "opportunity_notes" / "projects"


def eur(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f} €".replace(",", " ").replace(".", ",")


def eur_mwh(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f} €/MWh".replace(",", " ").replace(".", ",")


def number(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def parse_decimal(value: str) -> float | None:
    """Parse un nombre copié depuis Excel, avec virgule ou point décimal."""
    token = value.strip()
    if not token:
        return None
    token = token.replace("\u202f", " ").replace("\xa0", " ")
    token = re.sub(r"\s+", "", token)
    if "," in token and "." in token:
        # Format le plus courant en français : 1.234,56 ou 1 234,56.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    else:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def parse_pasted_numeric_values(text: str) -> list[float]:
    """Extrait des valeurs numériques depuis un collage Excel/LibreOffice.

    Formats acceptés :
    - une colonne de 12 valeurs ;
    - deux colonnes Mois + valeur ;
    - valeurs séparées par tabulation, point-virgule ou retour ligne.
    """
    values: list[float] = []
    header_words = (
        "mois",
        "conso",
        "consommation",
        "volume",
        "coefficient",
        "température",
        "temperature",
        "pertes",
        "perte",
        "facture",
        "facturée",
        "facturee",
        "nuitées",
        "nuitees",
        "l/j",
        "kwh",
        "mwh",
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(word in lower for word in header_words) and not any(month.lower() in lower for month in MONTH_NAMES):
            continue
        parts = [part.strip() for part in re.split(r"\t|;", line) if part.strip()]
        candidates: list[float] = []
        if len(parts) > 1:
            for part in parts:
                parsed = parse_decimal(part)
                if parsed is not None:
                    candidates.append(parsed)
        else:
            # Recherche les nombres dans la ligne. Compatible avec "Janvier 1 234,5".
            for match in re.finditer(r"[-+]?\d[\d\s\u202f\xa0.,]*", line):
                parsed = parse_decimal(match.group(0))
                if parsed is not None:
                    candidates.append(parsed)
        if candidates:
            # Si la ligne contient le mois puis la valeur, on retient la dernière valeur.
            values.append(candidates[-1])
    return values


def add_excel_paste_box(df: pd.DataFrame, value_column: str, key: str, label: str | None = None) -> pd.DataFrame:
    """Ajoute un bloc permettant de coller des valeurs Excel avant un data_editor.

    Important : ce composant n'utilise pas st.expander, car Streamlit interdit
    les expanders imbriqués. Il peut donc être appelé aussi bien dans une page
    simple que dans une section déjà repliable.
    """
    label = label or value_column
    st.markdown(f"**Coller des valeurs depuis Excel — {label}**")
    st.caption(
        "Colle soit une colonne de valeurs, soit deux colonnes Mois + valeur. "
        "Les 12 premières valeurs reconnues sont appliquées dans l'ordre des mois."
    )
    pasted = st.text_area(
        "Collage Excel / LibreOffice",
        key=f"{key}_paste_text",
        height=90,
        placeholder="Janvier\t1234\nFévrier\t1250\n...",
    )
    if st.button("Appliquer le collage", key=f"{key}_paste_button", use_container_width=True):
        values = parse_pasted_numeric_values(pasted)
        if not values:
            st.warning("Aucune valeur numérique reconnue dans le collage.")
        else:
            updated = df.copy()
            count = min(len(updated), len(values))
            for idx, value in enumerate(values[:count]):
                updated.loc[idx, value_column] = value
            st.success(f"{count} valeur(s) appliquée(s) dans le tableau.")
            return updated
    return df

def percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{100 * value:.{digits}f} %".replace(".", ",")


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9àâäéèêëïîôöùûüçñ]+", "-", text)
    text = text.strip("-")
    return text[:60] or "projet"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_projects_dir() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def empty_project_payload() -> dict[str, Any]:
    return {
        "project_id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "site": asdict(SiteInputs()),
        "needs": asdict(NeedsInputs()),
        "sizing": asdict(SizingInputs()),
        "loop": asdict(LoopInputs()),
        "economic": {},
    }


def project_file_path(project_id: str, project_name: str) -> Path:
    return PROJECTS_DIR / f"{slugify(project_name)}_{project_id[:8]}.json"


def list_project_files() -> list[Path]:
    ensure_projects_dir()
    return sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_project(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_project(payload: dict[str, Any]) -> Path:
    ensure_projects_dir()
    payload = dict(payload)
    payload["updated_at"] = now_iso()
    payload.setdefault("project_id", str(uuid.uuid4()))
    payload.setdefault("created_at", payload["updated_at"])
    site = payload.get("site", {})
    project_name = site.get("project_name") or "Nouveau projet"

    # Supprime les anciens fichiers du même projet si le nom a changé.
    for old_file in PROJECTS_DIR.glob(f"*_{payload['project_id'][:8]}.json"):
        old_file.unlink(missing_ok=True)

    path = project_file_path(payload["project_id"], project_name)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def init_session() -> None:
    if "project_payload" not in st.session_state:
        st.session_state.project_payload = empty_project_payload()


def monthly_needs_dataframe(results) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Mois": row.month,
                "Volume ECS 60°C (L/mois)": row.volume_l_60c,
                "Volume moyen (L/j)": row.average_l_day_60c,
                "Tef (°C)": row.cold_water_temperature_c,
                "Besoin utile (MWh)": row.useful_energy_mwh,
                "Bouclage sanitaire (MWh)": row.loop_losses_mwh,
                "Besoin total ECS + bouclage (MWh)": row.total_ecs_energy_mwh,
            }
            for row in results.monthly_needs
        ]
    )


def loop_dataframe(results) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Mois": row.month,
                "Jours": row.days,
                "Facture gaz talon estimée (kWh/mois)": row.gas_baseload_kwh,
                "Énergie ECS globale après rendement chaudière (kWh/mois)": row.global_ecs_after_boiler_kwh,
                "Besoin utile ECS (kWh/j)": row.useful_energy_kwh / row.days if row.days else 0.0,
                "Besoin utile ECS (kWh/mois)": row.useful_energy_kwh,
                "Bouclage sanitaire estimé (kWh/j)": row.loop_losses_kwh / row.days if row.days else 0.0,
                "Bouclage sanitaire estimé (kWh/mois)": row.loop_losses_kwh,
            }
            for row in results.monthly_needs
        ]
    )


def render_monthly_needs_chart(results):
    if go is None:
        return None
    rows = list(results.monthly_needs)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.average_l_day_60c for row in rows],
            name="Volume moyen ECS 60°C",
            hovertemplate="%{x}<br>%{y:,.0f} L/j à 60°C<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[row.month for row in rows],
            y=[row.useful_energy_mwh for row in rows],
            name="Besoin utile ECS",
            mode="lines+markers",
            yaxis="y2",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[row.month for row in rows],
            y=[row.total_ecs_energy_mwh for row in rows],
            name="ECS + bouclage",
            mode="lines+markers",
            yaxis="y2",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.update_layout(
        height=420,
        margin={"l": 10, "r": 20, "t": 45, "b": 40},
        xaxis_title="Mois",
        yaxis={"title": "Volume moyen (L/j à 60°C)"},
        yaxis2={"title": "Énergie (MWh/mois)", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
    )
    return fig


def render_loop_chart(results):
    if go is None:
        return None
    rows = list(results.monthly_needs)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.useful_energy_mwh for row in rows],
            name="Besoin utile ECS",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=[row.month for row in rows],
            y=[row.loop_losses_mwh for row in rows],
            name="Bouclage sanitaire",
            hovertemplate="%{x}<br>%{y:,.2f} MWh<extra></extra>",
        )
    )
    fig.update_layout(
        barmode="stack",
        height=360,
        margin={"l": 10, "r": 20, "t": 45, "b": 40},
        xaxis_title="Mois",
        yaxis_title="Besoin énergétique (MWh/mois)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
    )
    return fig


def render_ecs_loop_pie_chart(results):
    if go is None:
        return None
    useful = max(0.0, float(results.annual_useful_energy_mwh or 0.0))
    loop = max(0.0, float(results.annual_loop_losses_mwh or 0.0))
    if useful + loop <= 0:
        return None
    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Besoin utile ECS", "Bouclage sanitaire"],
                values=[useful, loop],
                hole=0.35,
                sort=False,
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.1f} MWh/an<br>%{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title="Répartition annuelle ECS utile / bouclage",
        height=340,
        margin={"l": 10, "r": 20, "t": 55, "b": 20},
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.05, "xanchor": "center", "x": 0.5},
    )
    return fig


def build_heat_cost_breakdown_rows(results) -> list[dict[str, float | str]]:
    return [
        {"Poste": "P1' - Auxiliaires électriques", "Famille": "P1'", "Coût chaleur (€/MWh)": results.heat_cost_p1_eur_mwh or 0.0},
        {"Poste": "P2 - Suivi et maintenance", "Famille": "P2", "Coût chaleur (€/MWh)": results.heat_cost_p2_eur_mwh or 0.0},
        {"Poste": "P4 - Investissement net aidé", "Famille": "P4", "Coût chaleur (€/MWh)": results.heat_cost_p4_eur_mwh or 0.0},
    ]


def render_heat_cost_breakdown_plotly(results):
    if go is None:
        return None
    rows = build_heat_cost_breakdown_rows(results)
    total_cost = results.solar_heat_cost_eur_mwh
    reference_cost = results.average_reference_energy_cost_eur_mwh
    x_max = max(total_cost, reference_cost, 1.0) * 1.25
    fig = go.Figure()
    for row in rows:
        value = float(row["Coût chaleur (€/MWh)"])
        fig.add_trace(
            go.Bar(
                y=["Coût chaleur solaire"],
                x=[value],
                name=str(row["Poste"]),
                orientation="h",
                text=[f"{value:.1f} €/MWh"],
                textposition="inside",
                hovertemplate="%{fullData.name}<br>%{x:.1f} €/MWh<extra></extra>",
            )
        )
    fig.add_vline(
        x=reference_cost,
        line_dash="dash",
        annotation_text=f"Référence moyenne : {reference_cost:.1f} €/MWh",
        annotation_position="top right",
    )
    fig.update_layout(
        barmode="stack",
        height=300,
        margin={"l": 10, "r": 20, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis_title="Coût de la chaleur (€/MWh utile)",
        yaxis_title=None,
    )
    fig.update_xaxes(range=[0, x_max], ticksuffix=" €/MWh")
    fig.update_yaxes(showticklabels=False)
    return fig


def first_positive_year(rows: list[dict[str, float | int]], cumulative_key: str) -> int | None:
    for row in rows:
        if float(row[cumulative_key]) >= 0:
            return int(row["Année"])
    return None


def render_cumulative_cashflow_plotly(cashflow_rows: list[dict[str, float | int]]):
    if go is None:
        return None
    years = [int(row["Année"]) for row in cashflow_rows]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[float(row["Flux cumulé moyen (€)"]) for row in cashflow_rows],
            name="Flux cumulé moyen/lissé",
            mode="lines+markers",
            hovertemplate="Année %{x}<br>%{y:,.0f} €<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=years,
            y=[float(row["Flux cumulé inflation annuelle (€)"]) for row in cashflow_rows],
            name="Flux cumulé avec inflation annuelle",
            mode="lines+markers",
            hovertemplate="Année %{x}<br>%{y:,.0f} €<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dash", annotation_text="Retour à zéro", annotation_position="bottom right")
    payback_avg = first_positive_year(cashflow_rows, "Flux cumulé moyen (€)")
    payback_inflation = first_positive_year(cashflow_rows, "Flux cumulé inflation annuelle (€)")
    if payback_avg is not None:
        fig.add_vline(x=payback_avg, line_dash="dot", annotation_text=f"Retour moyen : {payback_avg} ans")
    if payback_inflation is not None and payback_inflation != payback_avg:
        fig.add_vline(x=payback_inflation, line_dash="dot", annotation_text=f"Retour inflation : {payback_inflation} ans")
    fig.update_layout(
        height=390,
        margin={"l": 10, "r": 20, "t": 45, "b": 40},
        xaxis_title="Année",
        yaxis_title="Flux cumulé (€)",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    )
    fig.update_yaxes(ticksuffix=" €")
    return fig


def render_opportunity_notes_app() -> None:
    init_session()
    
    st.title("Note d'opportunité solaire thermique")
    st.caption(
        "Version de travail : estimation ECS, bouclage sanitaire, prédimensionnement CESC et raccord au modèle économique. "
        "La productivité est fixée par défaut à 500 kWh/m².an avant branchement du moteur SOLO 2018."
    )
    
    # ---------------------------------------------------------------------------
    # Barre latérale : gestion des projets.
    # ---------------------------------------------------------------------------
    with st.sidebar:
        st.header("Projets")
        if "save_notice" in st.session_state:
            st.success(st.session_state.pop("save_notice"))
    
        project_files = list_project_files()
        project_labels = []
        project_by_label: dict[str, Path] = {}
        for path in project_files:
            try:
                data = load_project(path)
                site = data.get("site", {})
                name = site.get("project_name", path.stem)
                airtable_id = site.get("airtable_id", "")
                updated = data.get("updated_at", "")
                label = f"{name}"
                if airtable_id:
                    label += f" | Airtable {airtable_id}"
                if updated:
                    label += f" — {updated}"
            except Exception:
                label = path.stem
            project_labels.append(label)
            project_by_label[label] = path
    
        selected_project_label = st.selectbox("Projet enregistré", options=["—"] + project_labels, index=0)
        col_load, col_new = st.columns(2)
        with col_load:
            if st.button("Charger", use_container_width=True, disabled=selected_project_label == "—"):
                st.session_state.project_payload = load_project(project_by_label[selected_project_label])
                st.rerun()
        with col_new:
            if st.button("Nouveau", use_container_width=True):
                st.session_state.project_payload = empty_project_payload()
                st.rerun()
    
    payload = st.session_state.project_payload
    site_default = dict_to_site_inputs(payload.get("site"))
    needs_default = dict_to_needs_inputs(payload.get("needs"))
    sizing_default = dict_to_sizing_inputs(payload.get("sizing"))
    loop_default = dict_to_loop_inputs(payload.get("loop"))
    economic_default = payload.get("economic", {}) or {}
    project_ui_key = str(payload.get("project_id", "projet"))[:8]
    
    # ---------------------------------------------------------------------------
    # Onglets de saisie et résultats.
    # ---------------------------------------------------------------------------
    tab_site, tab_needs, tab_energy, tab_loop, tab_sizing, tab_economics, tab_export = st.tabs(
        [
            "1. Projet",
            "2. Besoins ECS",
            "3. Eau froide & énergie",
            "4. Bouclage sanitaire",
            "5. Prédimensionnement",
            "6. Économie",
            "7. Synthèse / export",
        ]
    )
    
    with tab_site:
        st.subheader("Caractéristiques du site")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            project_name = st.text_input("Nom du projet", value=site_default.project_name)
            airtable_id = st.text_input("ID Airtable", value=site_default.airtable_id)
        with col_b:
            client_name = st.text_input("Maître d'ouvrage / client", value=site_default.client_name)
            city = st.text_input("Commune", value=site_default.city)
        with col_c:
            typology = st.selectbox(
                "Typologie d'établissement",
                options=list(SITE_TYPOLOGIES),
                index=list(SITE_TYPOLOGIES).index(site_default.typology) if site_default.typology in SITE_TYPOLOGIES else 0,
            )
            building_state = st.radio(
                "Nature du bâtiment",
                options=list(BUILDING_STATES),
                index=list(BUILDING_STATES).index(site_default.building_state)
                if site_default.building_state in BUILDING_STATES
                else 0,
            )
    
        data_source = st.radio(
            "Mode de détermination de la consommation ECS journalière",
            options=list(DATA_SOURCES),
            index=list(DATA_SOURCES).index(site_default.data_source) if site_default.data_source in DATA_SOURCES else 0,
            horizontal=True,
        )
    
        if building_state == "Bâtiment existant" and data_source != "Mesure de consommation ECS":
            st.warning(
                "Bâtiment existant : comptage ECS obligatoire / fortement attendu pour fiabiliser la note d'opportunité. "
                "Les ratios SOCOL peuvent servir à une première approche mais doivent être confrontés à des mesures."
            )
    
    site_inputs = SiteInputs(
        project_name=project_name,
        airtable_id=airtable_id,
        client_name=client_name,
        city=city,
        typology=typology,
        building_state=building_state,
        data_source=data_source,
    )
    
    # ---------------------------------------------------------------------------
    # Besoins ECS.
    # ---------------------------------------------------------------------------
    with tab_needs:
        st.subheader("Estimation des volumes ECS à 60 °C")
    
        housing_counts = dict(needs_default.housing_counts)
        housing_ratios = dict(needs_default.housing_ratios_l_day)
        residents_or_beds = needs_default.residents_or_beds
        liters_per_resident_or_bed_day = needs_default.liters_per_resident_or_bed_day
        monthly_occupancy = dict(needs_default.monthly_occupancy)
        liters_per_occupied_unit = needs_default.liters_per_occupied_unit
        hotel_category = needs_default.hotel_category
        measured_daily = dict(needs_default.measured_daily_l_60c_by_month)
        monthly_coefficients = dict(needs_default.monthly_coefficients)
    
        if data_source == "Mesure de consommation ECS":
            st.markdown("**Saisie d'une consommation mesurée ou estimée directement en L/j à 60 °C**")
            st.caption("Saisir la valeur moyenne journalière du mois. Le volume mensuel est calculé avec le nombre exact de jours du mois.")
            measured_rows = pd.DataFrame(
                [
                    {"Mois": month, "Conso mesurée ECS 60°C (L/j)": float(measured_daily.get(month, 0.0))}
                    for month in MONTH_NAMES
                ]
            )
            measured_rows = add_excel_paste_box(
                measured_rows,
                "Conso mesurée ECS 60°C (L/j)",
                key=f"{project_ui_key}_measured_daily",
                label="consommation ECS mesurée",
            )
            edited_measured = st.data_editor(
                measured_rows,
                hide_index=True,
                use_container_width=True,
                disabled=["Mois"],
                key=f"{project_ui_key}_measured_daily_editor",
            )
            measured_daily = {
                str(row["Mois"]): float(max(0.0, row["Conso mesurée ECS 60°C (L/j)"]))
                for _, row in edited_measured.iterrows()
            }
    
            st.markdown("**Unités de référence du site**")
            st.caption(
                "Ces unités ne servent pas à recalculer la consommation mesurée. "
                "Elles servent seulement à déduire le volume ECS de référence par unité utilisé dans le calcul SOLO du bouclage."
            )
            if typology == "Logement collectif":
                housing_unit_rows = pd.DataFrame(
                    [
                        {"Typologie": kind, "Nombre": int(housing_counts.get(kind, 0))}
                        for kind in HOUSING_RATIOS_L_PER_DWELLING_DAY
                    ]
                )
                edited_housing_units = st.data_editor(
                    housing_unit_rows,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Typologie"],
                    key=f"{project_ui_key}_measured_housing_units_editor",
                )
                housing_counts = {
                    str(row["Typologie"]): int(max(0, row["Nombre"])) for _, row in edited_housing_units.iterrows()
                }
            elif typology in {"EHPAD", "Hôpital"}:
                residents_or_beds = st.number_input(
                    "Nombre de résidents / lits",
                    min_value=0,
                    value=int(residents_or_beds),
                    step=1,
                    key=f"{project_ui_key}_measured_residents_or_beds",
                )
            elif typology == "Hôtel":
                st.caption("Renseigner les nuitées chambres si elles sont disponibles, pour calculer un volume de référence par chambre-nuitée.")
                occupancy_rows = pd.DataFrame(
                    [{"Mois": month, "Nuitées chambres": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
                )
                occupancy_rows = add_excel_paste_box(
                    occupancy_rows,
                    "Nuitées chambres",
                    key=f"{project_ui_key}_measured_hotel_occupancy",
                    label="nuitées chambres",
                )
                edited_occupancy = st.data_editor(
                    occupancy_rows,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Mois"],
                    key=f"{project_ui_key}_measured_hotel_occupancy_editor",
                )
                monthly_occupancy = {
                    str(row["Mois"]): float(max(0.0, row["Nuitées chambres"])) for _, row in edited_occupancy.iterrows()
                }
            elif typology == "Camping":
                st.caption("Renseigner les personnes-nuitées si elles sont disponibles, pour calculer un volume de référence par personne-nuitée.")
                occupancy_rows = pd.DataFrame(
                    [{"Mois": month, "Personnes-nuitées": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
                )
                occupancy_rows = add_excel_paste_box(
                    occupancy_rows,
                    "Personnes-nuitées",
                    key=f"{project_ui_key}_measured_camping_occupancy",
                    label="personnes-nuitées",
                )
                edited_occupancy = st.data_editor(
                    occupancy_rows,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Mois"],
                    key=f"{project_ui_key}_measured_camping_occupancy_editor",
                )
                monthly_occupancy = {
                    str(row["Mois"]): float(max(0.0, row["Personnes-nuitées"])) for _, row in edited_occupancy.iterrows()
                }
    
        elif typology == "Logement collectif":
            st.markdown("**Approche détaillée par typologie de logements**")
            housing_rows = pd.DataFrame(
                [
                    {
                        "Typologie": kind,
                        "Nombre": int(housing_counts.get(kind, 0)),
                        "L/logement/j à 60°C": float(housing_ratios.get(kind, default_ratio)),
                    }
                    for kind, default_ratio in HOUSING_RATIOS_L_PER_DWELLING_DAY.items()
                ]
            )
            edited_housing = st.data_editor(
                housing_rows,
                hide_index=True,
                use_container_width=True,
                disabled=["Typologie"],
                key=f"{project_ui_key}_housing_editor",
            )
            housing_counts = {str(row["Typologie"]): int(max(0, row["Nombre"])) for _, row in edited_housing.iterrows()}
            housing_ratios = {
                str(row["Typologie"]): float(max(0.0, row["L/logement/j à 60°C"]))
                for _, row in edited_housing.iterrows()
            }
    
        elif typology in {"EHPAD", "Hôpital"}:
            if typology == "Hôpital" and (
                site_default.typology != "Hôpital" or liters_per_resident_or_bed_day == EHPAD_DEFAULT_L_PER_RESIDENT_DAY
            ):
                default_ratio = HOSPITAL_DEFAULT_L_PER_BED_DAY
            elif typology == "EHPAD" and (
                site_default.typology != "EHPAD" or liters_per_resident_or_bed_day == HOSPITAL_DEFAULT_L_PER_BED_DAY
            ):
                default_ratio = EHPAD_DEFAULT_L_PER_RESIDENT_DAY
            else:
                default_ratio = liters_per_resident_or_bed_day
            col_a, col_b = st.columns(2)
            with col_a:
                residents_or_beds = st.number_input("Nombre de résidents / lits", min_value=0, value=int(residents_or_beds), step=1)
            with col_b:
                liters_per_resident_or_bed_day = st.number_input(
                    "Conso ECS à 60°C (L/résident ou lit/j)", min_value=0.0, value=float(default_ratio), step=1.0
                )
    
        elif typology == "Hôtel":
            col_a, col_b = st.columns(2)
            with col_a:
                hotel_category = st.selectbox(
                    "Catégorie hôtel",
                    options=list(HOTEL_RATIOS_L_PER_ROOM_NIGHT),
                    index=list(HOTEL_RATIOS_L_PER_ROOM_NIGHT).index(hotel_category)
                    if hotel_category in HOTEL_RATIOS_L_PER_ROOM_NIGHT
                    else 1,
                )
            with col_b:
                default_hotel_ratio = HOTEL_RATIOS_L_PER_ROOM_NIGHT[hotel_category]
                liters_per_occupied_unit = st.number_input(
                    "Conso ECS à 60°C (L/chambre-nuit)",
                    min_value=0.0,
                    value=float(liters_per_occupied_unit or default_hotel_ratio),
                    step=1.0,
                )
                st.caption(f"Valeur SOCOL proposée pour cette catégorie : {default_hotel_ratio:.0f} L/chambre-nuit.")
    
            occupancy_rows = pd.DataFrame(
                [{"Mois": month, "Nuitées chambres": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
            )
            occupancy_rows = add_excel_paste_box(
                occupancy_rows,
                "Nuitées chambres",
                key=f"{project_ui_key}_hotel_occupancy",
                label="nuitées chambres",
            )
            edited_occupancy = st.data_editor(
                occupancy_rows,
                hide_index=True,
                use_container_width=True,
                disabled=["Mois"],
                key=f"{project_ui_key}_hotel_occupancy_editor",
            )
            monthly_occupancy = {
                str(row["Mois"]): float(max(0.0, row["Nuitées chambres"])) for _, row in edited_occupancy.iterrows()
            }
    
        elif typology == "Camping":
            liters_per_occupied_unit = st.number_input(
                "Conso ECS à 60°C (L/personne-nuitée)",
                min_value=0.0,
                value=float(liters_per_occupied_unit or CAMPING_DEFAULT_L_PER_PERSON_NIGHT),
                step=1.0,
            )
            st.caption(f"Valeur proposée par défaut : {CAMPING_DEFAULT_L_PER_PERSON_NIGHT:.0f} L/personne-nuitée.")
            occupancy_rows = pd.DataFrame(
                [{"Mois": month, "Personnes-nuitées": float(monthly_occupancy.get(month, 0.0))} for month in MONTH_NAMES]
            )
            occupancy_rows = add_excel_paste_box(
                occupancy_rows,
                "Personnes-nuitées",
                key=f"{project_ui_key}_camping_occupancy",
                label="personnes-nuitées",
            )
            edited_occupancy = st.data_editor(
                occupancy_rows,
                hide_index=True,
                use_container_width=True,
                disabled=["Mois"],
                key=f"{project_ui_key}_camping_occupancy_editor",
            )
            monthly_occupancy = {
                str(row["Mois"]): float(max(0.0, row["Personnes-nuitées"])) for _, row in edited_occupancy.iterrows()
            }
    
        if data_source == "Ratio SOCOL" and typology in {"Logement collectif", "EHPAD", "Hôpital"}:
            with st.expander("Coefficient mensuel de modulation", expanded=False):
                coeff_rows = pd.DataFrame(
                    [
                        {"Mois": month, "Coefficient": float(monthly_coefficients.get(month, DEFAULT_MONTHLY_COEFFICIENTS[month]))}
                        for month in MONTH_NAMES
                    ]
                )
                coeff_rows = add_excel_paste_box(
                    coeff_rows,
                    "Coefficient",
                    key=f"{project_ui_key}_monthly_coeff",
                    label="coefficients mensuels",
                )
                edited_coeff = st.data_editor(
                    coeff_rows,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Mois"],
                    key=f"{project_ui_key}_monthly_coeff_editor",
                )
                monthly_coefficients = {
                    str(row["Mois"]): float(max(0.0, row["Coefficient"])) for _, row in edited_coeff.iterrows()
                }
    
    needs_inputs = NeedsInputs(
        housing_counts=housing_counts,
        housing_ratios_l_day=housing_ratios,
        residents_or_beds=int(residents_or_beds),
        liters_per_resident_or_bed_day=float(liters_per_resident_or_bed_day),
        monthly_occupancy=monthly_occupancy,
        liters_per_occupied_unit=float(liters_per_occupied_unit),
        hotel_category=hotel_category,
        measured_daily_l_60c_by_month=measured_daily,
        monthly_coefficients=monthly_coefficients,
    )
    
    # ---------------------------------------------------------------------------
    # Eau froide et paramètres de prédimensionnement.
    # ---------------------------------------------------------------------------
    with tab_energy:
        st.subheader("Température d'eau froide et besoins utiles")
        st.info(
            "La température d'eau froide est initialisée à 15 °C par défaut. "
            "Elle pourra être remplacée par le profil mensuel issu du module SOLO 2018."
        )
        tef_rows = pd.DataFrame(
            [
                {"Mois": month, "Température eau froide (°C)": float(sizing_default.cold_water_temperatures_c.get(month, 15.0))}
                for month in MONTH_NAMES
            ]
        )
        tef_rows = add_excel_paste_box(
            tef_rows,
            "Température eau froide (°C)",
            key=f"{project_ui_key}_cold_water",
            label="températures d'eau froide",
        )
        edited_tef = st.data_editor(
            tef_rows,
            hide_index=True,
            use_container_width=True,
            disabled=["Mois"],
            key=f"{project_ui_key}_cold_water_editor",
        )
        cold_water_temperatures = {
            str(row["Mois"]): float(row["Température eau froide (°C)"]) for _, row in edited_tef.iterrows()
        }
    
    # ---------------------------------------------------------------------------
    # Bouclage sanitaire.
    # ---------------------------------------------------------------------------
    with tab_loop:
        st.subheader("Bouclage sanitaire")
        loop_method = st.radio(
            "Méthode de calcul du bouclage",
            options=list(LOOP_METHODS),
            index=list(LOOP_METHODS).index(loop_default.method) if loop_default.method in LOOP_METHODS else 0,
            horizontal=True,
        )
    
        gas_monthly_kwh = dict(loop_default.gas_monthly_kwh)
        boiler_efficiency = loop_default.boiler_efficiency
    
        solo_type_bouclage_label = loop_default.solo_type_bouclage_label
        solo_loss_mode_label = loop_default.solo_loss_mode_label
        solo_losses_input_mode = loop_default.solo_losses_input_mode
        solo_losses_annual_kwh = loop_default.solo_losses_annual_kwh
        solo_losses_monthly_kwh_day = dict(loop_default.solo_losses_monthly_kwh_day)
        solo_debit_bouclage_l_h = loop_default.solo_debit_bouclage_l_h
        solo_delta_tmax_bouclage_k = loop_default.solo_delta_tmax_bouclage_k
        solo_long_bouclage_m = loop_default.solo_long_bouclage_m
        solo_kl_bouclage_w_m_k = loop_default.solo_kl_bouclage_w_m_k
        solo_long1_boucle_bon = loop_default.solo_long1_boucle_bon_m_per_unit
        solo_long1_boucle_moyen = loop_default.solo_long1_boucle_moyen_m_per_unit
        solo_long1_boucle_mauvais = loop_default.solo_long1_boucle_mauvais_m_per_unit
        solo_kl_boucle_bon = loop_default.solo_kl_boucle_bon_w_m_k
        solo_kl_boucle_moyen = loop_default.solo_kl_boucle_moyen_w_m_k
        solo_kl_boucle_mauvais = loop_default.solo_kl_boucle_mauvais_w_m_k
        solo_tref = loop_default.solo_tref_bouclage_c
        solo_tenv = loop_default.solo_tenv_bouclage_c
        solo_monthly_temperatures = dict(loop_default.solo_monthly_temperatures_c)
        solo_vecs_ref = loop_default.solo_vecs_unit_ref_l_day
        solo_active_ratio = loop_default.solo_active_ratio
    
        if loop_method == "Analyse factures gaz":
            st.caption(
                "Saisir les consommations gaz mensuelles. L'outil calcule le talon minimal journalier sur juin-septembre, "
                "applique le rendement chaudière, puis en déduit une perte de bouclage journalière constante. "
                "Le besoin utile ECS continue de varier chaque mois avec le coefficient de modulation et le nombre exact de jours."
            )
            boiler_efficiency = st.number_input(
                "Rendement chaudière gaz retenu",
                min_value=0.0,
                max_value=1.0,
                value=float(boiler_efficiency or 0.85),
                step=0.01,
            )
            gas_rows = pd.DataFrame(
                [{"Mois": month, "Conso gaz facturée (kWh/mois)": float(gas_monthly_kwh.get(month, 0.0))} for month in MONTH_NAMES]
            )
            gas_rows = add_excel_paste_box(
                gas_rows,
                "Conso gaz facturée (kWh/mois)",
                key=f"{project_ui_key}_gas_invoices",
                label="factures gaz mensuelles",
            )
            edited_gas = st.data_editor(
                gas_rows,
                hide_index=True,
                use_container_width=True,
                disabled=["Mois"],
                key=f"{project_ui_key}_gas_invoices_editor",
            )
            gas_monthly_kwh = {
                str(row["Mois"]): float(max(0.0, row["Conso gaz facturée (kWh/mois)"]))
                for _, row in edited_gas.iterrows()
            }
            st.markdown(
                "Calcul appliqué sur une base journalière : "
                "`Bbouclage_j = talon_gaz_j × rendement_chaudière - Becs_utile_j_du_mois_talon`. "
                "Puis `Bbouclage_mois = Bbouclage_j × nombre_de_jours_du_mois`."
            )
        else:
            st.caption(
                "Bloc bouclage repris du module SOLO 2018 fourni : mêmes modes de saisie, mêmes constantes par défaut "
                "et même logique de calcul des pertes journalières."
            )
    
            solo_loss_mode_label = st.selectbox(
                "Calcul des pertes de bouclage",
                options=list(SOLO_LOOP_LOSS_MODE_LABELS),
                index=list(SOLO_LOOP_LOSS_MODE_LABELS).index(solo_loss_mode_label)
                if solo_loss_mode_label in SOLO_LOOP_LOSS_MODE_LABELS
                else 5,
            )
            st.caption(
                "Le choix de valorisation du bouclage par le solaire n'est pas demandé ici : "
                "il servira plus tard pour le calcul SOLO/productivité, pas pour estimer les pertes de bouclage."
            )
    
            if solo_loss_mode_label == "Saisie pertes (kWh/j)":
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    solo_losses_input_mode = st.selectbox(
                        "Mode de saisie des pertes",
                        options=list(SOLO_LOSS_INPUT_MODES),
                        index=list(SOLO_LOSS_INPUT_MODES).index(solo_losses_input_mode)
                        if solo_losses_input_mode in SOLO_LOSS_INPUT_MODES
                        else 0,
                    )
                if solo_losses_input_mode == "Saisie annuelle":
                    with col_s2:
                        solo_losses_annual_kwh = st.number_input(
                            "Pertes bouclage annuelles (kWh/an)",
                            min_value=0.0,
                            value=float(solo_losses_annual_kwh or 0.0),
                            step=100.0,
                        )
                else:
                    losses_rows = pd.DataFrame(
                        [
                            {"Mois": month, "Pertes bouclage (kWh/j)": float(solo_losses_monthly_kwh_day.get(month, 0.0))}
                            for month in MONTH_NAMES
                        ]
                    )
                    losses_rows = add_excel_paste_box(
                        losses_rows,
                        "Pertes bouclage (kWh/j)",
                        key=f"{project_ui_key}_loop_losses",
                        label="pertes de bouclage mensuelles",
                    )
                    edited_losses = st.data_editor(
                        losses_rows,
                        hide_index=True,
                        use_container_width=True,
                        disabled=["Mois"],
                        key=f"{project_ui_key}_loop_losses_editor",
                    )
                    solo_losses_monthly_kwh_day = {
                        str(row["Mois"]): float(max(0.0, row["Pertes bouclage (kWh/j)"]))
                        for _, row in edited_losses.iterrows()
                    }
    
            elif solo_loss_mode_label == "Débit et delta T connus":
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    solo_debit_bouclage_l_h = st.number_input(
                        "Débit de bouclage (L/h)", min_value=0.0, value=float(solo_debit_bouclage_l_h or 300.0), step=10.0
                    )
                with col_d2:
                    solo_delta_tmax_bouclage_k = st.number_input(
                        "Delta T max bouclage (°C)", min_value=0.0, value=float(solo_delta_tmax_bouclage_k or 5.0), step=0.5
                    )
    
            elif solo_loss_mode_label == "Longueur et isolation connues":
                col_l1, col_l2 = st.columns(2)
                with col_l1:
                    solo_long_bouclage_m = st.number_input(
                        "Longueur de boucle (m)", min_value=0.0, value=float(solo_long_bouclage_m or 120.0), step=5.0
                    )
                with col_l2:
                    solo_kl_bouclage_w_m_k = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_bouclage_w_m_k or 0.3),
                        step=0.01,
                        format="%.2f",
                    )
    
            elif solo_loss_mode_label == "Boucle courte bien isolée":
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    solo_long1_boucle_bon = st.number_input(
                        "Longueur boucle par unité (m/unité)",
                        min_value=0.0,
                        value=float(solo_long1_boucle_bon or 6.0),
                        step=0.1,
                    )
                with col_b2:
                    solo_kl_boucle_bon = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_boucle_bon or 0.2),
                        step=0.01,
                        format="%.2f",
                    )
    
            elif solo_loss_mode_label == "Boucle qualité moyenne":
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    solo_long1_boucle_moyen = st.number_input(
                        "Longueur boucle par unité (m/unité)",
                        min_value=0.0,
                        value=float(solo_long1_boucle_moyen or 9.0),
                        step=0.1,
                    )
                with col_m2:
                    solo_kl_boucle_moyen = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_boucle_moyen or 0.3),
                        step=0.01,
                        format="%.2f",
                    )
    
            elif solo_loss_mode_label == "Boucle longue mal isolée":
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    solo_long1_boucle_mauvais = st.number_input(
                        "Longueur boucle par unité (m/unité)",
                        min_value=0.0,
                        value=float(solo_long1_boucle_mauvais or 12.0),
                        step=0.1,
                    )
                with col_v2:
                    solo_kl_boucle_mauvais = st.number_input(
                        "Perte linéique boucle (W/m/°C)",
                        min_value=0.0,
                        value=float(solo_kl_boucle_mauvais or 0.4),
                        step=0.01,
                        format="%.2f",
                    )
    
            with st.expander("Paramètres généraux SOLO 2018 du bouclage", expanded=False):
                st.caption(
                    "Le volume ECS de référence par unité n'est pas saisi ici : il est repris automatiquement "
                    "depuis la consommation ECS moyenne journalière calculée dans l'onglet Besoins ECS."
                )
                col_g1, col_g2, col_g3 = st.columns(3)
                with col_g1:
                    solo_tref = st.number_input("Température de référence bouclage (°C)", value=float(solo_tref or 55.0), step=1.0)
                with col_g2:
                    solo_tenv = st.number_input("Température environnement bouclage (°C)", value=float(solo_tenv or 20.0), step=1.0)
                with col_g3:
                    solo_active_ratio = st.number_input(
                        "Ratio bouclage actif",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(solo_active_ratio or 1.0),
                        step=0.05,
                    )
    
                loop_temp_rows = pd.DataFrame(
                    [
                        {"Mois": month, "Température mensuelle utilisée (°C)": float(solo_monthly_temperatures.get(month, 20.0))}
                        for month in MONTH_NAMES
                    ]
                )
                loop_temp_rows = add_excel_paste_box(
                    loop_temp_rows,
                    "Température mensuelle utilisée (°C)",
                    key=f"{project_ui_key}_loop_temps",
                    label="températures mensuelles bouclage",
                )
                edited_loop_temp = st.data_editor(
                    loop_temp_rows,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["Mois"],
                    key=f"{project_ui_key}_loop_temps_editor",
                )
                solo_monthly_temperatures = {
                    str(row["Mois"]): float(row["Température mensuelle utilisée (°C)"]) for _, row in edited_loop_temp.iterrows()
                }
    
    loop_inputs = LoopInputs(
        method=loop_method,
        gas_monthly_kwh=gas_monthly_kwh,
        boiler_efficiency=float(boiler_efficiency),
        solo_type_bouclage_label=solo_type_bouclage_label,
        solo_loss_mode_label=solo_loss_mode_label,
        solo_losses_input_mode=solo_losses_input_mode,
        solo_losses_annual_kwh=float(solo_losses_annual_kwh),
        solo_losses_monthly_kwh_day=solo_losses_monthly_kwh_day,
        solo_debit_bouclage_l_h=float(solo_debit_bouclage_l_h),
        solo_delta_tmax_bouclage_k=float(solo_delta_tmax_bouclage_k),
        solo_long_bouclage_m=float(solo_long_bouclage_m),
        solo_kl_bouclage_w_m_k=float(solo_kl_bouclage_w_m_k),
        solo_long1_boucle_bon_m_per_unit=float(solo_long1_boucle_bon),
        solo_long1_boucle_moyen_m_per_unit=float(solo_long1_boucle_moyen),
        solo_long1_boucle_mauvais_m_per_unit=float(solo_long1_boucle_mauvais),
        solo_kl_boucle_bon_w_m_k=float(solo_kl_boucle_bon),
        solo_kl_boucle_moyen_w_m_k=float(solo_kl_boucle_moyen),
        solo_kl_boucle_mauvais_w_m_k=float(solo_kl_boucle_mauvais),
        solo_tref_bouclage_c=float(solo_tref),
        solo_tenv_bouclage_c=float(solo_tenv),
        solo_monthly_temperatures_c=solo_monthly_temperatures,
        solo_vecs_unit_ref_l_day=float(solo_vecs_ref),
        solo_active_ratio=float(solo_active_ratio),
    )
    
    with tab_sizing:
        st.subheader("Paramètres de prédimensionnement")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            collector_unit_area = st.number_input(
                "Surface unitaire capteur (m²)",
                min_value=0.1,
                value=float(sizing_default.collector_unit_area_m2 or DEFAULT_COLLECTOR_UNIT_AREA_M2),
                step=0.01,
            )
        with col_b:
            target_ratio = st.number_input(
                "Ratio stockage cible (L/m²)",
                min_value=40.0,
                max_value=90.0,
                value=float(sizing_default.target_storage_ratio_l_m2),
                step=1.0,
            )
        with col_c:
            max_tank_count = st.number_input(
                "Nombre max. de ballons combinés", min_value=1, max_value=6, value=int(sizing_default.max_tank_count or 3), step=1
            )
            productivity_default = st.number_input(
                "Productivité par défaut (kWh/m².an)",
                min_value=0.0,
                value=float(sizing_default.productivity_kwh_m2_year or DEFAULT_PRODUCTIVITY_KWH_M2_YEAR),
                step=10.0,
            )
    
    sizing_inputs = SizingInputs(
        cold_water_temperatures_c=cold_water_temperatures,
        collector_unit_area_m2=float(collector_unit_area),
        target_storage_ratio_l_m2=float(target_ratio),
        max_tank_count=int(max_tank_count),
        productivity_kwh_m2_year=float(productivity_default),
    )
    
    try:
        opportunity_results = compute_opportunity_results(site_inputs, needs_inputs, sizing_inputs, loop_inputs)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    
    with tab_loop:
        st.markdown("### Résultat bouclage")
        col1, col2, col3 = st.columns(3)
        col1.metric("Besoin utile ECS", f"{number(opportunity_results.annual_useful_energy_mwh, 1)} MWh/an")
        col2.metric("Bouclage sanitaire", f"{number(opportunity_results.annual_loop_losses_mwh, 1)} MWh/an")
        col3.metric("Besoin ECS + bouclage", f"{number(opportunity_results.annual_total_ecs_energy_mwh, 1)} MWh/an")
        if loop_method == "Analyse factures gaz":
            loop_daily_kwh = opportunity_results.annual_loop_losses_mwh * 1000.0 / 365.0 if opportunity_results.annual_loop_losses_mwh > 0 else 0.0
            st.info(
                f"Talon gaz estival retenu : {number(opportunity_results.gas_summer_baseload_daily_kwh, 1)} kWh/j gaz, "
                f"avec un rendement chaudière de {number(loop_inputs.boiler_efficiency * 100, 0)} %. "
                f"Bouclage retenu : {number(loop_daily_kwh, 1)} kWh/j, soit une valeur journalière constante multipliée par le nombre de jours de chaque mois."
            )
        elif loop_method == "Hypothèses SOLO 2018":
            if opportunity_results.reference_unit_count > 0:
                st.info(
                    "Volume ECS de référence SOLO utilisé automatiquement : "
                    f"{number(opportunity_results.solo_reference_volume_l_day_per_unit, 1)} L/j/unité à 60 °C, "
                    f"calculé à partir de {number(opportunity_results.average_daily_volume_l_60c, 0)} L/j "
                    f"et {number(opportunity_results.reference_unit_count, 1)} unité(s)."
                )
            else:
                st.info(
                    "Volume ECS de référence SOLO utilisé automatiquement : "
                    f"{number(opportunity_results.solo_reference_volume_l_day_per_unit, 0)} L/j à 60 °C. "
                    "Aucune unité de référence n'est renseignée, donc l'outil utilise la consommation journalière totale comme valeur de repli."
                )
        fig_pie = render_ecs_loop_pie_chart(opportunity_results)
        if fig_pie is not None:
            st.plotly_chart(fig_pie, use_container_width=True)
    
        fig_loop = render_loop_chart(opportunity_results)
        if fig_loop is not None:
            st.plotly_chart(fig_loop, use_container_width=True)
        st.dataframe(loop_dataframe(opportunity_results), hide_index=True, use_container_width=True)
    
    with tab_sizing:
        st.markdown("### Proposition centrale")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Volume ECS moyen", f"{number(opportunity_results.average_daily_volume_l_60c, 0)} L/j à 60°C")
        col2.metric("Stockage proposé", f"{opportunity_results.storage.total_volume_l:,.0f} L".replace(",", " "))
        col3.metric("Surface proposée", f"{number(opportunity_results.collectors.surface_m2, 1)} m²")
        col4.metric("Ratio V/S", f"{number(opportunity_results.collectors.storage_ratio_l_m2, 1)} L/m²")
    
        st.write(f"**Ballons proposés :** {opportunity_results.storage.label}")
        st.write(
            "**Capteurs proposés :** "
            f"{opportunity_results.collectors.collector_count} capteurs × "
            f"{opportunity_results.collectors.collector_unit_area_m2:.2f} m² = "
            f"{opportunity_results.collectors.surface_m2:.2f} m²"
        )
        st.caption(
            "La surface est choisie pour être la plus proche possible de 60 L/m², "
            "avec un nombre de capteurs divisible par 2 ou par 3 lorsque c'est possible. "
            "Le stockage privilégie les multiples de ballons de même taille."
        )
        st.metric(
            "Production solaire provisoire",
            f"{number(opportunity_results.estimated_solar_production_mwh_year, 1)} MWh/an",
            f"{number(sizing_inputs.productivity_kwh_m2_year, 0)} kWh/m².an",
        )
    
    # ---------------------------------------------------------------------------
    # Modèle économique raccordé au pré-dimensionnement.
    # ---------------------------------------------------------------------------
    with tab_economics:
        st.subheader("Modèle économique")
        st.caption("Les valeurs sont préremplies avec le prédimensionnement et les hypothèses économiques par défaut de l'onglet CESC.")
    
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            economic_typology = st.selectbox(
                "Scénario d'aide ADEME",
                options=list(ECONOMIC_SCENARIOS),
                index=list(ECONOMIC_SCENARIOS).index(economic_default.get("typologie", "CESC"))
                if economic_default.get("typologie", "CESC") in ECONOMIC_SCENARIOS
                else 0,
            )
            economic_surface = st.number_input(
                "Surface économique (m²)",
                min_value=0.0,
                value=float(economic_default.get("surface_m2", opportunity_results.collectors.surface_m2)),
                step=1.0,
            )
            economic_productivity = st.number_input(
                "Productivité économique (kWh/m².an)",
                min_value=0.0,
                value=float(economic_default.get("productivity_kwh_m2_year", sizing_inputs.productivity_kwh_m2_year)),
                step=10.0,
            )
        with col_b:
            reference_energy_cost = st.number_input(
                "Coût énergie référence (€/MWh)",
                min_value=0.0,
                value=float(economic_default.get("reference_energy_cost_eur_mwh", 75.0)),
                step=5.0,
            )
            inflation = st.number_input(
                "Inflation énergie référence (%/an)",
                value=float(economic_default.get("reference_energy_inflation_percent", 3.0)),
                step=0.5,
            ) / 100.0
            years = st.number_input("Durée d'analyse (ans)", min_value=1, value=int(economic_default.get("years", 20)), step=1)
        with col_c:
            works_cost = st.number_input(
                "Coût travaux installation (€HT/m²)",
                min_value=0.0,
                value=float(economic_default.get("works_cost_eur_m2", 1563.0)),
                step=50.0,
            )
            eta_appoint = st.number_input(
                "Rendement appoint global",
                min_value=0.01,
                max_value=1.5,
                value=float(economic_default.get("eta_appoint", 0.82)),
                step=0.01,
            )
    
        with st.expander("Hypothèses économiques avancées", expanded=False):
            col_1, col_2, col_3 = st.columns(3)
            with col_1:
                auxiliary_ratio = st.number_input(
                    "Auxiliaires électriques (% prod.)", value=float(economic_default.get("auxiliary_ratio_percent", 3.0)), step=0.5
                ) / 100.0
                electricity_cost = st.number_input(
                    "Coût électricité auxiliaire (€/MWh)", value=float(economic_default.get("electricity_cost_eur_mwh", 200.0)), step=10.0
                )
            with col_2:
                maintenance_cost = st.number_input(
                    "Maintenance (€/m².an)", value=float(economic_default.get("maintenance_cost_eur_m2_year", 22.0)), step=1.0
                )
                fae_cost = st.number_input("FAE (€HT)", value=float(economic_default.get("fae_cost_eur", 4929.0)), step=100.0)
            with col_3:
                fae_aid_rate = st.number_input(
                    "Taux aide FAE (%)", value=float(economic_default.get("fae_aid_rate_percent", 70.0)), step=5.0
                ) / 100.0
                ademe_cap = st.number_input(
                    "Plafond aide travaux (% coût)", value=float(economic_default.get("ademe_cap_percent", 65.0)), step=5.0
                ) / 100.0
    
        economic_inputs = CescEconomicInputs(
            typologie=economic_typology,
            surface_m2=economic_surface,
            productivity_kwh_m2_year=economic_productivity,
            reference_energy_cost_eur_mwh=reference_energy_cost,
            reference_energy_inflation_rate=inflation,
            years=int(years),
            works_cost_eur_m2=works_cost,
            eta_appoint=eta_appoint,
            auxiliary_electricity_ratio=auxiliary_ratio,
            electricity_cost_eur_mwh=electricity_cost,
            maintenance_cost_eur_m2_year=maintenance_cost,
            fae_cost_eur=fae_cost,
            fae_aid_rate=fae_aid_rate,
            ademe_aid_max_rate_on_works=ademe_cap,
        )
        economic_results = compute_cesc_economic_model(economic_inputs)
    
        st.caption(
            f"Forfait ADEME appliqué : {ADEME_AID_EUR_PER_MWH_YEAR_BY_TYPOLOGY[economic_typology]:,.0f} €/MWh.an".replace(
                ",", " "
            )
        )
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Production solaire", f"{number(economic_results.annual_production_mwh, 1)} MWh/an")
        col2.metric("Investissement", eur(economic_results.investment_cost_eur, 0))
        col3.metric("Aides", eur(economic_results.aid_total_eur, 0), percent(economic_results.aid_rate))
        col4.metric("Reste à charge", eur(economic_results.net_investment_eur, 0))
    
        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Économies annuelles", eur(economic_results.annual_savings_eur, 0))
        col6.metric("Temps retour brut", f"{number(economic_results.raw_payback_years, 1)} ans")
        col7.metric("Coût chaleur solaire", eur_mwh(economic_results.solar_heat_cost_eur_mwh, 1))
        col8.metric(f"Économies sur {economic_inputs.years} ans", eur(economic_results.savings_over_period_eur, 0))
    
        fig_breakdown = render_heat_cost_breakdown_plotly(economic_results)
        if fig_breakdown is not None:
            st.plotly_chart(fig_breakdown, use_container_width=True)
    
        cashflow_rows = list(build_yearly_cashflow_projection(economic_inputs, economic_results))
        fig_cashflow = render_cumulative_cashflow_plotly(cashflow_rows)
        if fig_cashflow is not None:
            st.plotly_chart(fig_cashflow, use_container_width=True)
    
    # ---------------------------------------------------------------------------
    # Synthèse et export.
    # ---------------------------------------------------------------------------
    economic_payload = {
        "typologie": economic_typology,
        "surface_m2": economic_surface,
        "productivity_kwh_m2_year": economic_productivity,
        "reference_energy_cost_eur_mwh": reference_energy_cost,
        "reference_energy_inflation_percent": inflation * 100.0,
        "years": int(years),
        "works_cost_eur_m2": works_cost,
        "eta_appoint": eta_appoint,
        "auxiliary_ratio_percent": auxiliary_ratio * 100.0,
        "electricity_cost_eur_mwh": electricity_cost,
        "maintenance_cost_eur_m2_year": maintenance_cost,
        "fae_cost_eur": fae_cost,
        "fae_aid_rate_percent": fae_aid_rate * 100.0,
        "ademe_cap_percent": ademe_cap * 100.0,
    }
    
    current_payload = {
        "project_id": payload.get("project_id", str(uuid.uuid4())),
        "created_at": payload.get("created_at", now_iso()),
        "updated_at": now_iso(),
        "site": asdict(site_inputs),
        "needs": asdict(needs_inputs),
        "sizing": asdict(sizing_inputs),
        "loop": asdict(loop_inputs),
        "economic": economic_payload,
        "results": {"opportunity": opportunity_results.as_dict(), "economic": economic_results.as_dict()},
    }
    
    with tab_export:
        st.subheader("Synthèse")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Volume ECS annuel", f"{number(opportunity_results.annual_volume_l_60c / 1000.0, 1)} m³/an")
        col2.metric("Besoin utile ECS", f"{number(opportunity_results.annual_useful_energy_mwh, 1)} MWh/an")
        col3.metric("Bouclage", f"{number(opportunity_results.annual_loop_losses_mwh, 1)} MWh/an")
        col4.metric("Surface capteurs", f"{number(opportunity_results.collectors.surface_m2, 1)} m²")
    
        st.markdown(
            f"""
    **Projet :** {site_inputs.project_name}  
    **ID Airtable :** {site_inputs.airtable_id or "—"}  
    **Typologie :** {site_inputs.typology}  
    **Nature du bâtiment :** {site_inputs.building_state}  
    **Mode ECS :** {site_inputs.data_source}  
    **Méthode bouclage :** {loop_inputs.method}  
    
    **Besoin utile ECS :** {opportunity_results.annual_useful_energy_mwh:.1f} MWh/an.  
    **Bouclage sanitaire estimé :** {opportunity_results.annual_loop_losses_mwh:.1f} MWh/an.  
    **Besoin ECS total avec bouclage :** {opportunity_results.annual_total_ecs_energy_mwh:.1f} MWh/an.  
    
    **Prédimensionnement proposé :** {opportunity_results.storage.label}, avec {opportunity_results.collectors.collector_count} capteurs de {opportunity_results.collectors.collector_unit_area_m2:.2f} m², soit {opportunity_results.collectors.surface_m2:.2f} m².  
    **Ratio V/S :** {opportunity_results.collectors.storage_ratio_l_m2:.1f} L/m².  
    **Productivité provisoire :** {sizing_inputs.productivity_kwh_m2_year:.0f} kWh/m².an, à remplacer ensuite par le calcul SOLO 2018.
    """
        )
    
        st.download_button(
            "Télécharger le projet JSON",
            data=json.dumps(current_payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"{slugify(site_inputs.project_name)}.json",
            mime="application/json",
        )
        with st.expander("Voir le JSON complet", expanded=False):
            st.code(json.dumps(current_payload, ensure_ascii=False, indent=2), language="json")
    
    with st.sidebar:
        st.divider()
        if st.button("Enregistrer le projet", use_container_width=True):
            saved_path = save_project(current_payload)
            st.session_state.project_payload = current_payload
            st.session_state.save_notice = f"Projet enregistré : {saved_path.name}"
            st.rerun()
