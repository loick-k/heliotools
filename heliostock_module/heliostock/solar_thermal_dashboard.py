"""
Dashboard Streamlit - Installations Solaire Thermique (Atlansun)
==================================================================
Connecte l'app à votre base Airtable "BDD Atlansun Solaire thermique"
(table "BDD STH") et affiche des KPI, graphiques et une carte des
installations.

Lancement local :
    pip install -r requirements.txt
    streamlit run app.py
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
import math
from urllib.parse import quote_plus

import folium
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from pyairtable import Api
from streamlit_folium import st_folium

from .dashboard_data_cleaning import group_small_categories, join_values, to_float, to_year
from .pdf_report import (
    draw_bar_chart as pdf_draw_bar_chart,
    draw_installation_map as pdf_draw_installation_map,
    draw_kpi_cards as pdf_draw_kpi_cards,
    draw_line_chart as pdf_draw_line_chart,
    draw_log_scatter_chart as pdf_draw_log_scatter_chart,
    draw_pie_chart as pdf_draw_pie_chart,
    draw_report_footer as pdf_draw_report_footer,
    draw_report_header as pdf_draw_report_header,
    draw_wrapped_text as pdf_draw_wrapped_text,
)

_draw_line_chart = pdf_draw_line_chart

# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------

# IDs par défaut (base "BDD Atlansun Solaire thermique")
DEFAULT_BASE_ID = "appjauiOQySQq9PBz"
DEFAULT_TABLE_ID = "tblU1ec0gGyWq9YN8"  # table "BDD STH"
GEOCODER_APPS_SCRIPT_URL = (
    "https://script.google.com/home/projects/"
    "1jDiVia7tT3dOoWIMxlypC2BxXWAAXz48x-pCneMn_w0730BT8fUVdxdZ/edit"
)
GEOCODING_MAX_WORKERS = 6
CHART_COLORS = [
    "#1F77B4",  # bleu
    "#2CA02C",  # vert
    "#D62728",  # rouge
    "#9467BD",  # violet
    "#FF7F0E",  # orange
    "#17BECF",  # cyan
    "#8C564B",  # brun
    "#E377C2",  # rose
    "#BCBD22",  # olive
    "#7F3C8D",  # prune
    "#11A579",  # vert emeraude
    "#3969AC",  # bleu profond
    "#F2B701",  # jaune
    "#E73F74",  # magenta
    "#80BA5A",  # vert clair
    "#E68310",  # orange fonce
    "#008695",  # bleu-vert
    "#CF1C90",  # fuchsia
    "#F97B72",  # corail
    "#4B4B8F",  # indigo
]
OTHER_CATEGORY_COLOR = "#6B7280"
MAP_POINT_COLORS = CHART_COLORS
PDF_CHART_COLORS = [
    (0.95, 0.63, 0.0),
    (0.0, 0.45, 0.7),
    (0.84, 0.37, 0.0),
    (0.0, 0.62, 0.45),
    (0.8, 0.47, 0.65),
    (0.34, 0.71, 0.91),
    (0.42, 0.45, 0.5),
    (0.9, 0.62, 0.0),
    (0.36, 0.29, 0.69),
    (0.55, 0.7, 0.41),
]

# Tables liées utilisées pour résoudre les champs de type "lien vers un
# enregistrement" (Ville, Secteurs, Type d'installation, Etat) en libellés
# lisibles plutôt que des IDs d'enregistrement Airtable.
LINKED_TABLES = {
    "Ville": "tbleBvECqENQREthB",
    "Secteurs": "tblKwrQ1LSFVS9NCK",
    "Type d'installation": "tblRFmyTCj3cFvYeZ",
    "Etat": "tblJj36Gj0YaanZNJ",
}


def _dashboard_secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Chargement des données depuis Airtable (avec cache)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def load_lookup(api_key: str, base_id: str, table_id: str) -> dict:
    """Charge une table liée et renvoie un dict {record_id: libellé}."""
    api = Api(api_key)
    table = api.table(base_id, table_id)
    records = table.all()
    lookup = {}
    for r in records:
        fields = r["fields"]
        # Le champ primaire s'appelle "Name" sur les tables liées de cette base.
        label = fields.get("Name") or next(iter(fields.values()), r["id"])
        lookup[r["id"]] = label
    return lookup


@st.cache_data(ttl=600, show_spinner="Chargement des données Airtable...")
def load_data(api_key: str, base_id: str, table_id: str) -> pd.DataFrame:
    api = Api(api_key)
    main_table = api.table(base_id, table_id)
    records = main_table.all()

    ville_map = load_lookup(api_key, base_id, LINKED_TABLES["Ville"])
    secteur_map = load_lookup(api_key, base_id, LINKED_TABLES["Secteurs"])
    type_map = load_lookup(api_key, base_id, LINKED_TABLES["Type d'installation"])
    etat_map = load_lookup(api_key, base_id, LINKED_TABLES["Etat"])

    def resolve(ids, mapping):
        if not ids:
            return None
        return ", ".join(mapping.get(i, i) for i in ids)

    rows = []
    for r in records:
        f = r["fields"]
        rows.append(
            {
                "ID": f.get("ID"),
                "Application": f.get("Application"),
                "Ville": resolve(f.get("Ville"), ville_map),
                "Secteur": resolve(f.get("Secteurs"), secteur_map),
                "Type d'installation": resolve(
                    f.get("Type d'installation"), type_map
                ),
                "Etat": resolve(f.get("Etat"), etat_map),
                "Département": join_values(f.get("Département")),
                "Année de mise en service": to_year(
                    f.get("Année de mise en service")
                ),
                "Volume stockage (L)": to_float(f.get("Volume Stockage (L)")),
                "Superficie (m²)": f.get("Superficie panneaux (m²)"),
                "Production annuelle (MWh)": f.get("Production annuelle (MWh)"),
                "Aide ADEME (€)": f.get("Montant aide ADEME"),
                "Taux de couverture (%)": to_float(
                    f.get("Taux de couverture solaire (%)")
                ),
                "Productivité (kWh/m².an)": to_float(
                    f.get("Productivité (kWh/m².an)")
                ),
                "Lien internet": f.get("Lien internet"),
                "Source": f.get("Source"),
                "Latitude": f.get("Latitude"),
                "Longitude": f.get("Longitude"),
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def geocode_city(nom_ville: str):
    """Géocodage simple d'une commune française via l'API officielle
    geo.api.gouv.fr (gratuite, sans clé)."""
    if not nom_ville:
        return None
    # On ne garde que le premier nom si plusieurs villes sont listées.
    premiere_ville = nom_ville.split(",")[0].strip()
    try:
        resp = requests.get(
            "https://geo.api.gouv.fr/communes",
            params={"nom": premiere_ville, "fields": "centre", "limit": 1},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            lon, lat = data[0]["centre"]["coordinates"]
            return lat, lon
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None
    return None


@st.cache_data(show_spinner=False)
def build_map_points(map_df: pd.DataFrame) -> list:
    """Construit la liste des points à afficher sur la carte.

    Le résultat est mis en cache dans son ensemble (tant que le sous-jeu de
    données filtré ne change pas), et les géocodages ville nécessaires sont
    lancés en parallèle plutôt qu'un par un. Les coordonnées Airtable restent
    prioritaires pour une localisation précise.
    """
    rows = map_df.to_dict("records")

    # Identifie les requêtes de géocodage réellement nécessaires (les
    # installations ayant déjà Latitude/Longitude n'en ont pas besoin), en
    # dédupliquant les requêtes identiques (ex. plusieurs installations dans
    # la même ville).
    city_queries = set()
    for row in rows:
        if pd.notna(row.get("Latitude")) and pd.notna(row.get("Longitude")):
            continue
        if row.get("Ville"):
            city_queries.add(row["Ville"])

    # Parallelism is limited to dashboard geocoding I/O. HelioStock physical
    # simulations and pygfunction calls remain sequential for Streamlit Cloud
    # robustness.
    city_cache = {}
    with ThreadPoolExecutor(max_workers=GEOCODING_MAX_WORKERS) as executor:
        city_futures = {executor.submit(geocode_city, v): v for v in city_queries}
        for future, v in city_futures.items():
            city_cache[v] = future.result()

    points = []
    for row in rows:
        lat = lon = adresse = maps_url = None

        if pd.notna(row.get("Latitude")) and pd.notna(row.get("Longitude")):
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
            adresse = row.get("Ville")
            maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

        if lat is None:
            ville = row.get("Ville")
            fallback = city_cache.get(ville) if ville else None
            if not fallback:
                continue
            lat, lon = fallback
            adresse = ville
            maps_url = (
                "https://www.google.com/maps/search/?api=1&query="
                f"{quote_plus(str(ville or ''))}"
            )

        point = dict(row)
        point.update({"lat": lat, "lon": lon, "adresse": adresse, "maps_url": maps_url})
        points.append(point)

    return points


def _fmt_number(value: float, decimals: int = 0, suffix: str = "") -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    formatted = f"{numeric:,.{decimals}f}".replace(",", " ")
    return f"{formatted} {suffix}".strip()


def _filtered_summary_metrics(df_f: pd.DataFrame) -> list[tuple[str, str]]:
    return [
        ("Installations", _fmt_number(len(df_f))),
        ("Superficie totale", _fmt_number(df_f["Superficie (m²)"].sum(), suffix="m²")),
        ("Production annuelle totale", _fmt_number(df_f["Production annuelle (MWh)"].sum(), suffix="MWh")),
        ("Aide ADEME totale", _fmt_number(df_f["Aide ADEME (€)"].sum(), suffix="€")),
    ]


def _counts_table(df_f: pd.DataFrame, column: str, value_label: str = "Nombre") -> pd.DataFrame:
    table = df_f[column].fillna("Non renseigné").value_counts().reset_index()
    table.columns = [column, value_label]
    return table


def _category_color_map(categories: list[str] | set[str], *, palette: list[str] | None = None) -> dict[str, str]:
    palette = palette or CHART_COLORS
    labels = sorted({str(category or "Non renseigné") for category in categories if str(category or "").strip()})
    color_map = {
        label: palette[index % len(palette)]
        for index, label in enumerate(label for label in labels if label != "Autres")
    }
    color_map["Autres"] = OTHER_CATEGORY_COLOR
    return color_map


def _sector_color_map(df_f: pd.DataFrame) -> dict[str, str]:
    if df_f.empty or "Secteur" not in df_f:
        return {"Autres": OTHER_CATEGORY_COLOR}
    sectors = set()
    for cell in df_f["Secteur"].fillna("Non renseigné"):
        cell_label = str(cell).strip() or "Non renseigné"
        sectors.add(cell_label)
        sectors.update(sector.strip() or "Non renseigné" for sector in cell_label.split(","))
    sectors.add("Autres")
    return _category_color_map(sectors)


def _surface_by_category(df_f: pd.DataFrame, column: str) -> pd.DataFrame:
    if df_f.empty or column not in df_f or "Superficie (m²)" not in df_f:
        return pd.DataFrame(columns=[column, "Superficie (m²)"])
    surface_df = df_f.dropna(subset=["Superficie (m²)"]).copy()
    if surface_df.empty:
        return pd.DataFrame(columns=[column, "Superficie (m²)"])
    surface_df[column] = surface_df[column].fillna("Non renseigné")
    return (
        surface_df.groupby(column)["Superficie (m²)"]
        .sum()
        .reset_index()
        .sort_values("Superficie (m²)", ascending=False)
    )


def _overview_export_tables(df_f: pd.DataFrame) -> dict[str, pd.DataFrame]:
    dep_counts = _counts_table(df_f, "Département")
    secteur_counts = group_small_categories(_counts_table(df_f, "Secteur"), "Secteur", "Nombre", seuil_pct=3.0)
    type_counts = group_small_categories(
        _counts_table(df_f, "Type d'installation"), "Type d'installation", "Nombre", seuil_pct=1.0
    )
    etat_counts = group_small_categories(_counts_table(df_f, "Etat"), "Etat", "Nombre", seuil_pct=3.0)
    superficie_departement = _surface_by_category(df_f, "Département")
    installations_par_annee = (
        df_f.dropna(subset=["Année de mise en service"])
        .groupby("Année de mise en service")
        .size()
        .reset_index(name="Nombre")
        .sort_values("Année de mise en service")
    )
    evolution_cumulee = installations_par_annee.copy()
    if not evolution_cumulee.empty:
        evolution_cumulee["Cumulé"] = evolution_cumulee["Nombre"].cumsum()
    elif "Cumulé" not in evolution_cumulee.columns:
        evolution_cumulee["Cumulé"] = pd.Series(dtype="float64")
    surface_par_annee = (
        df_f.dropna(subset=["Année de mise en service", "Superficie (m²)"])
        .groupby("Année de mise en service")["Superficie (m²)"]
        .sum()
        .reset_index()
        .sort_values("Année de mise en service")
    )
    surface_cumulee = surface_par_annee.copy()
    if not surface_cumulee.empty:
        surface_cumulee["Surface cumulée (m²)"] = surface_cumulee["Superficie (m²)"].cumsum()
    elif "Surface cumulée (m²)" not in surface_cumulee.columns:
        surface_cumulee["Surface cumulée (m²)"] = pd.Series(dtype="float64")
    superficie_secteur = df_f.dropna(subset=["Superficie (m²)"]).copy()
    if not superficie_secteur.empty:
        superficie_secteur["Secteur"] = superficie_secteur["Secteur"].fillna("Non renseigné")
        superficie_secteur = (
            superficie_secteur.groupby("Secteur")["Superficie (m²)"]
            .sum()
            .reset_index()
        )
        superficie_secteur = group_small_categories(
            superficie_secteur, "Secteur", "Superficie (m²)", seuil_pct=3.0
        )
    scatter_data = df_f.dropna(subset=["Superficie (m²)", "Production annuelle (MWh)"])[
        ["Application", "Ville", "Secteur", "Année de mise en service", "Superficie (m²)", "Production annuelle (MWh)"]
    ].copy()
    return {
        "Installations par département": dep_counts,
        "Superficie par département": superficie_departement,
        "Répartition par secteur": secteur_counts,
        "Répartition par typologie": type_counts,
        "Répartition par état": etat_counts,
        "Évolution cumulée": evolution_cumulee,
        "Nouvelles installations par année": installations_par_annee,
        "Surface installée par année": surface_par_annee,
        "Surface cumulée": surface_cumulee,
        "Superficie par secteur": superficie_secteur,
        "Superficie vs production annuelle": scatter_data,
    }


def _active_filters_summary(
    *,
    departements: list[str],
    secteurs: list[str],
    types: list[str],
    etats: list[str],
    annees: tuple[int, int] | None,
) -> list[tuple[str, str]]:
    def values(selected: list[str]) -> str:
        return ", ".join(selected) if selected else "Tous"

    return [
        ("Département", values(departements)),
        ("Secteur", values(secteurs)),
        ("Type d'installation", values(types)),
        ("Etat", values(etats)),
        ("Année de mise en service", f"{annees[0]} - {annees[1]}" if annees else "Toutes"),
    ]


def _overview_pdf_signature(df_f: pd.DataFrame, filters: list[tuple[str, str]]) -> tuple:
    return (
        len(df_f),
        tuple(filters),
        _fmt_number(df_f["Superficie (m²)"].sum(), 3),
        _fmt_number(df_f["Production annuelle (MWh)"].sum(), 3),
        _fmt_number(df_f["Aide ADEME (€)"].sum(), 3),
    )


def _wrap_text(text: str, width: int = 105) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _table_lines(df: pd.DataFrame, *, max_rows: int = 35) -> list[str]:
    if df.empty:
        return ["Aucune donnée."]
    export_df = df.head(max_rows).copy()
    for column in export_df.columns:
        if pd.api.types.is_numeric_dtype(export_df[column]):
            export_df[column] = export_df[column].map(lambda value: _fmt_number(value, 1 if float(value) % 1 else 0))
    lines = export_df.astype(str).to_string(index=False).splitlines()
    remaining = len(df) - len(export_df)
    if remaining > 0:
        lines.append(f"... {remaining} ligne(s) supplémentaire(s) non affichée(s) dans le PDF.")
    return lines


def _pdf_numeric(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _overview_pdf_bytes(
    *,
    df_f: pd.DataFrame,
    filters: list[tuple[str, str]],
) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas as pdf_canvas

    buffer = BytesIO()
    page_width, page_height = landscape(A4)
    canvas = pdf_canvas.Canvas(buffer, pagesize=(page_width, page_height), pageCompression=0)
    generated_at = datetime.now().strftime("%d/%m/%Y à %H:%M")
    chart_tables = _overview_export_tables(df_f)

    page = 1
    pdf_draw_report_header(
        canvas,
        title="Dashboard solaire thermique - vue d'ensemble",
        subtitle=f"Export généré le {generated_at} - données filtrées affichées dans la vue d'ensemble",
        width=page_width,
        height=page_height,
    )
    y = page_height - 92
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(34, y, "Filtres actifs")
    canvas.setFillColorRGB(0.42, 0.44, 0.52)
    fy = y - 16
    for label, value in filters:
        fy = pdf_draw_wrapped_text(canvas, f"{label} : {value}", x=34, y=fy, max_chars=80)
    y = min(y, fy) - 8

    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(34, y, "Indicateurs clés")
    y = pdf_draw_kpi_cards(canvas, _filtered_summary_metrics(df_f), x=34, y=y - 10, width=page_width - 68)

    pdf_draw_bar_chart(
        canvas,
        chart_tables["Installations par département"],
        x=34,
        y=92,
        width=360,
        height=175,
        title="Installations par département",
        label_col="Département",
        value_col="Nombre",
        color=(0.96, 0.64, 0.0),
    )
    pdf_draw_bar_chart(
        canvas,
        chart_tables["Superficie par département"],
        x=456,
        y=92,
        width=350,
        height=175,
        title="Surface installée par département",
        label_col="Département",
        value_col="Superficie (m²)",
        color=(0.0, 0.62, 0.45),
    )
    pdf_draw_report_footer(canvas, page_number=page, width=page_width)
    canvas.showPage()

    page += 1
    pdf_draw_report_header(
        canvas,
        title="Répartitions de la vue d'ensemble",
        subtitle="Secteur, typologie et état - mêmes filtres que l'écran",
        width=page_width,
        height=page_height,
    )
    pdf_draw_pie_chart(
        canvas,
        chart_tables["Répartition par secteur"],
        x=34,
        y=304,
        radius=58,
        title="Répartition par secteur",
        label_col="Secteur",
        value_col="Nombre",
        colors=PDF_CHART_COLORS,
    )
    pdf_draw_pie_chart(
        canvas,
        chart_tables["Répartition par typologie"],
        x=300,
        y=304,
        radius=58,
        title="Répartition par typologie",
        label_col="Type d'installation",
        value_col="Nombre",
        colors=PDF_CHART_COLORS,
    )
    pdf_draw_pie_chart(
        canvas,
        chart_tables["Répartition par état"],
        x=566,
        y=304,
        radius=58,
        title="Répartition par état",
        label_col="Etat",
        value_col="Nombre",
        colors=PDF_CHART_COLORS,
    )
    pdf_draw_line_chart(
        canvas,
        chart_tables["Évolution cumulée"],
        x=34,
        y=82,
        width=350,
        height=160,
        title="Évolution cumulée du nombre d'installations",
        x_col="Année de mise en service",
        y_col="Cumulé",
        y_axis_label="Nombre cumulé d'installations",
    )
    pdf_draw_bar_chart(
        canvas,
        chart_tables["Surface installée par année"],
        x=440,
        y=82,
        width=360,
        height=170,
        title="Surface installée par année",
        label_col="Année de mise en service",
        value_col="Superficie (m²)",
        color=(0.18, 0.53, 0.67),
        max_items=18,
    )
    pdf_draw_report_footer(canvas, page_number=page, width=page_width)
    canvas.showPage()

    page += 1
    pdf_draw_report_header(
        canvas,
        title="Surfaces et production",
        subtitle="Analyse des surfaces installées et de la production annuelle - mêmes filtres que l'écran",
        width=page_width,
        height=page_height,
    )
    pdf_draw_pie_chart(
        canvas,
        chart_tables["Superficie par secteur"],
        x=34,
        y=314,
        radius=74,
        title="Superficie par secteur",
        label_col="Secteur",
        value_col="Superficie (m²)",
        colors=PDF_CHART_COLORS,
    )
    pdf_draw_line_chart(
        canvas,
        chart_tables["Surface cumulée"],
        x=34,
        y=82,
        width=350,
        height=170,
        title="Surface cumulée installée",
        x_col="Année de mise en service",
        y_col="Surface cumulée (m²)",
        y_axis_label="Surface cumulée (m²)",
    )
    pdf_draw_log_scatter_chart(
        canvas,
        chart_tables["Superficie vs production annuelle"],
        x=440,
        y=312,
        width=350,
        height=190,
        title="Production annuelle selon la surface installée",
    )
    pdf_draw_report_footer(canvas, page_number=page, width=page_width)
    canvas.showPage()

    page += 1
    pdf_draw_report_header(
        canvas,
        title="Carte des installations",
        subtitle="Fond standard rues détaillées - cadrage automatique sur les installations filtrées",
        width=page_width,
        height=page_height,
    )
    pdf_draw_installation_map(
        canvas,
        df_f,
        x=48,
        y=86,
        width=page_width - 96,
        height=page_height - 178,
        colors=MAP_POINT_COLORS,
    )
    pdf_draw_report_footer(canvas, page_number=page, width=page_width)
    canvas.save()
    return buffer.getvalue()


def render_solar_thermal_dashboard() -> None:

    # ---------------------------------------------------------------------------
    # Barre latérale - connexion & filtres
    # ---------------------------------------------------------------------------
    st.sidebar.header("Connexion Airtable")
    api_key = _dashboard_secret("AIRTABLE_TOKEN")
    base_id = _dashboard_secret("AIRTABLE_BASE_ID", DEFAULT_BASE_ID)
    table_id = _dashboard_secret("AIRTABLE_TABLE_ID", DEFAULT_TABLE_ID)

    if st.sidebar.button("Rafraîchir les données"):
        st.cache_data.clear()

    st.title("Installations Solaire Thermique")
    st.caption("Base Airtable : BDD Atlansun Solaire thermique - table BDD STH")

    if not api_key:
        st.info(
            "Le token Airtable n'est pas configuré dans les secrets Streamlit."
        )
        st.stop()

    try:
        df = load_data(api_key, base_id, table_id)
    except Exception:  # noqa: BLE001
        st.error(
            "Erreur lors du chargement des données Airtable. Vérifie le token, "
            "le Base ID et le Table ID."
        )
        st.stop()

    if df.empty:
        st.warning("Aucune installation trouvée dans cette table.")
        st.stop()

    # ---------------------------------------------------------------------------
    # Filtres
    # ---------------------------------------------------------------------------
    st.sidebar.header("Filtres")


    def multiselect_filter(label, column):
        options = sorted(
            {v.strip() for cell in df[column].dropna() for v in str(cell).split(",")}
        )
        return st.sidebar.multiselect(label, options)


    f_departement = multiselect_filter("Département", "Département")
    f_secteur = multiselect_filter("Secteur", "Secteur")
    f_type = multiselect_filter("Type d'installation", "Type d'installation")
    f_etat = multiselect_filter("Etat", "Etat")

    annees = df["Année de mise en service"].dropna()
    if not annees.empty:
        min_a, max_a = int(annees.min()), int(annees.max())
        if min_a == max_a:
            f_annee = (min_a, max_a)
        else:
            f_annee = st.sidebar.slider(
                "Année de mise en service", min_a, max_a, (min_a, max_a)
            )
    else:
        f_annee = None


    def apply_filter(dataframe, column, selected):
        if not selected:
            return dataframe
        mask = dataframe[column].apply(
            lambda cell: bool(cell) and any(s in str(cell) for s in selected)
        )
        return dataframe[mask]


    df_f = df.copy()
    df_f = apply_filter(df_f, "Département", f_departement)
    df_f = apply_filter(df_f, "Secteur", f_secteur)
    df_f = apply_filter(df_f, "Type d'installation", f_type)
    df_f = apply_filter(df_f, "Etat", f_etat)
    if f_annee:
        df_f = df_f[
            df_f["Année de mise en service"].isna()
            | df_f["Année de mise en service"].between(f_annee[0], f_annee[1])
        ]
    active_filters = _active_filters_summary(
        departements=f_departement,
        secteurs=f_secteur,
        types=f_type,
        etats=f_etat,
        annees=f_annee,
    )

    st.sidebar.caption(f"{len(df_f)} installation(s) sur {len(df)} au total")

    # ---------------------------------------------------------------------------
    # Navigation
    # ---------------------------------------------------------------------------
    # Note : on utilise un st.radio plutôt que st.tabs. Avec st.tabs, Streamlit
    # masque les onglets inactifs en CSS (display:none) mais exécute quand même
    # leur code : Folium/Leaflet calcule alors la taille de la carte alors
    # qu'elle est cachée, ce qui la fait apparaître grisée/à moitié chargée.
    # Avec un radio, seule la section sélectionnée est exécutée et affichée,
    # donc la carte est toujours créée dans un conteneur réellement visible.
    section = st.radio(
        "Navigation",
        ["Vue d'ensemble", "Carte", "Données"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # --- Vue d'ensemble --------------------------------------------------------
    if section == "Vue d'ensemble":
        pdf_signature = _overview_pdf_signature(df_f, active_filters)
        if st.session_state.get("solar_dashboard_pdf_signature") != pdf_signature:
            st.session_state.pop("solar_dashboard_overview_pdf", None)
            st.session_state.pop("solar_dashboard_overview_pdf_name", None)
            st.session_state["solar_dashboard_pdf_signature"] = pdf_signature

        pdf_col_prepare, pdf_col_download = st.columns([1, 2])
        with pdf_col_prepare:
            if st.button("Préparer le PDF", help="Le PDF est généré uniquement à la demande pour éviter de ralentir l'ouverture du dashboard."):
                with st.spinner("Génération du PDF en cours..."):
                    st.session_state["solar_dashboard_overview_pdf"] = _overview_pdf_bytes(
                        df_f=df_f,
                        filters=active_filters,
                    )
                    st.session_state["solar_dashboard_overview_pdf_name"] = (
                        f"dashboard_solaire_thermique_vue_ensemble_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                    )
        with pdf_col_download:
            pdf_bytes = st.session_state.get("solar_dashboard_overview_pdf")
            if pdf_bytes:
                st.download_button(
                    "Télécharger la vue d'ensemble en PDF",
                    data=pdf_bytes,
                    file_name=st.session_state.get(
                        "solar_dashboard_overview_pdf_name",
                        "dashboard_solaire_thermique_vue_ensemble.pdf",
                    ),
                    mime="application/pdf",
                )
            else:
                st.caption("Le PDF n'est pas généré automatiquement : clique sur Préparer le PDF après avoir réglé les filtres.")

        c1, c2, c3, c4 = st.columns(4)
        summary_metrics = _filtered_summary_metrics(df_f)
        c1.metric(summary_metrics[0][0], summary_metrics[0][1])
        c2.metric(summary_metrics[1][0], summary_metrics[1][1])
        c3.metric(summary_metrics[2][0], summary_metrics[2][1])
        c4.metric(summary_metrics[3][0], summary_metrics[3][1])

        st.divider()

        overview_tables = _overview_export_tables(df_f)
        sector_color_map = _sector_color_map(df_f)

        col_a, col_b = st.columns(2)

        with col_a:
            dep_order = overview_tables["Installations par département"]["Département"].tolist()
            fig_dep = px.bar(
                overview_tables["Installations par département"],
                x="Département",
                y="Nombre",
                title="Installations par département",
                color_discrete_sequence=["#f4a300"],
                labels={"Nombre": "Nombre d'installations"},
                category_orders={"Département": dep_order},
            )
            fig_dep.update_layout(showlegend=False)
            st.plotly_chart(fig_dep, width="stretch")

        with col_b:
            surface_dep_order = overview_tables["Superficie par département"]["Département"].tolist()
            fig_surface_dep = px.bar(
                overview_tables["Superficie par département"],
                x="Département",
                y="Superficie (m²)",
                title="Surface installée par département",
                color_discrete_sequence=["#009E73"],
                labels={
                    "Département": "Département",
                    "Superficie (m²)": "Surface de capteurs installée (m²)",
                },
                category_orders={"Département": surface_dep_order},
            )
            fig_surface_dep.update_layout(showlegend=False)
            st.plotly_chart(fig_surface_dep, width="stretch")

        col_c, col_d = st.columns(2)

        with col_c:
            secteur_counts = overview_tables["Répartition par secteur"]
            fig_secteur = px.pie(
                secteur_counts,
                names="Secteur",
                values="Nombre",
                color="Secteur",
                title="Répartition par secteur",
                color_discrete_map=sector_color_map,
                labels={"Nombre": "Nombre d'installations", "Secteur": "Secteur"},
            )
            fig_secteur.update_traces(textposition="inside", textinfo="percent")
            fig_secteur.update_layout(legend_title_text="Secteur")
            st.plotly_chart(fig_secteur, width="stretch")

        with col_d:
            type_counts = overview_tables["Répartition par typologie"]
            fig_type = px.pie(
                type_counts,
                names="Type d'installation",
                values="Nombre",
                color="Type d'installation",
                title="Répartition par typologie d'installation",
                color_discrete_sequence=CHART_COLORS,
                labels={
                    "Nombre": "Nombre d'installations",
                    "Type d'installation": "Typologie d'installation",
                },
            )
            fig_type.update_traces(textposition="inside", textinfo="percent")
            fig_type.update_layout(legend_title_text="Typologie")
            st.plotly_chart(fig_type, width="stretch")

        col_e, col_f = st.columns(2)

        with col_e:
            etat_counts = overview_tables["Répartition par état"]
            fig_secteur = px.pie(
                etat_counts,
                names="Etat",
                values="Nombre",
                color="Etat",
                title="Répartition par état",
                color_discrete_sequence=CHART_COLORS,
                labels={"Nombre": "Nombre d'installations", "Etat": "État"},
            )
            fig_secteur.update_traces(textposition="inside", textinfo="percent")
            fig_secteur.update_layout(legend_title_text="État")
            st.plotly_chart(fig_secteur, width="stretch")

        with col_f:
            evol = overview_tables["Évolution cumulée"]
            if not evol.empty:
                fig_evol = px.line(
                    evol,
                    x="Année de mise en service",
                    y="Cumulé",
                    markers=True,
                    title="Évolution cumulée du nombre d'installations",
                    labels={
                        "Année de mise en service": "Année de mise en service",
                        "Cumulé": "Nombre cumulé d'installations",
                    },
                )
                st.plotly_chart(fig_evol, width="stretch")
            else:
                st.info("Pas assez de données d'année pour tracer l'évolution.")

        col_g, col_h = st.columns(2)

        with col_g:
            installations_par_annee = overview_tables["Nouvelles installations par année"]
            if not installations_par_annee.empty:
                fig_annee = px.bar(
                    installations_par_annee,
                    x="Année de mise en service",
                    y="Nombre",
                    title="Nouvelles installations par année",
                    color_discrete_sequence=["#2E86AB"],
                    labels={
                        "Année de mise en service": "Année de mise en service",
                        "Nombre": "Nombre de nouvelles installations",
                    },
                )
                fig_annee.update_layout(showlegend=False)
                st.plotly_chart(fig_annee, width="stretch")
            else:
                st.info("Pas assez de données d'année pour ce graphique.")

        with col_h:
            superficie_secteur = overview_tables["Superficie par secteur"]
            if not superficie_secteur.empty:
                fig_superficie_secteur = px.pie(
                    superficie_secteur,
                    names="Secteur",
                    values="Superficie (m²)",
                    color="Secteur",
                    title="Superficie (m²) par secteur",
                    color_discrete_map=sector_color_map,
                    labels={"Superficie (m²)": "Surface de capteurs installée (m²)", "Secteur": "Secteur"},
                )
                fig_superficie_secteur.update_traces(textposition="inside", textinfo="percent")
                fig_superficie_secteur.update_layout(legend_title_text="Secteur")
                st.plotly_chart(fig_superficie_secteur, width="stretch")
            else:
                st.info("Pas assez de données de superficie pour ce graphique.")

        col_i, col_j = st.columns(2)

        with col_i:
            surface_par_annee = overview_tables["Surface installée par année"]
            if not surface_par_annee.empty:
                fig_surface_annee = px.bar(
                    surface_par_annee,
                    x="Année de mise en service",
                    y="Superficie (m²)",
                    title="Surface installée par année",
                    color_discrete_sequence=["#009E73"],
                    labels={
                        "Année de mise en service": "Année de mise en service",
                        "Superficie (m²)": "Surface installée dans l'année (m²)",
                    },
                )
                fig_surface_annee.update_layout(showlegend=False)
                st.plotly_chart(fig_surface_annee, width="stretch")
            else:
                st.info("Pas assez de données de superficie annuelle pour ce graphique.")

        with col_j:
            surface_cumulee = overview_tables["Surface cumulée"]
            if not surface_cumulee.empty:
                fig_surface_cumulee = px.line(
                    surface_cumulee,
                    x="Année de mise en service",
                    y="Surface cumulée (m²)",
                    markers=True,
                    title="Surface cumulée installée",
                    labels={
                        "Année de mise en service": "Année de mise en service",
                        "Surface cumulée (m²)": "Surface cumulée de capteurs (m²)",
                    },
                )
                st.plotly_chart(fig_surface_cumulee, width="stretch")
            else:
                st.info("Pas assez de données de superficie annuelle pour tracer la surface cumulée.")

        st.subheader("Production annuelle selon la surface installée")
        scatter_df = df_f.dropna(subset=["Superficie (m²)", "Production annuelle (MWh)"])
        scatter_df = scatter_df[
            (scatter_df["Superficie (m²)"].map(to_float) > 0)
            & (scatter_df["Production annuelle (MWh)"].map(to_float) > 0)
        ].copy()
        if not scatter_df.empty:
            min_surface = max(float(scatter_df["Superficie (m²)"].map(to_float).min()), 1.0)
            max_surface = max(float(scatter_df["Superficie (m²)"].map(to_float).max()), min_surface)
            log_min = math.floor(math.log10(min_surface))
            log_max = math.ceil(math.log10(max_surface))
            surface_ticks = [10**power for power in range(log_min, log_max + 1)]
            min_production = max(float(scatter_df["Production annuelle (MWh)"].map(to_float).min()), 1.0)
            max_production = max(float(scatter_df["Production annuelle (MWh)"].map(to_float).max()), min_production)
            production_log_min = math.floor(math.log10(min_production))
            production_log_max = math.ceil(math.log10(max_production))
            production_ticks = [10**power for power in range(production_log_min, production_log_max + 1)]
            fig_scatter = px.scatter(
                scatter_df,
                x="Superficie (m²)",
                y="Production annuelle (MWh)",
                color="Secteur",
                log_x=True,
                log_y=True,
                color_discrete_map=sector_color_map,
                hover_name="Ville",
                hover_data=["Application", "Année de mise en service"],
                labels={
                    "Superficie (m²)": "Surface de capteurs installée (m², axe logarithmique)",
                    "Production annuelle (MWh)": "Production solaire annuelle (MWh/an, axe logarithmique)",
                    "Secteur": "Secteur",
                },
            )
            fig_scatter.update_xaxes(
                tickmode="array",
                tickvals=surface_ticks,
                ticktext=[f"{tick:g}" for tick in surface_ticks],
                title_text="Surface de capteurs installée (m², axe logarithmique)",
            )
            fig_scatter.update_yaxes(
                tickmode="array",
                tickvals=production_ticks,
                ticktext=[f"{tick:g}" for tick in production_ticks],
                title_text="Production solaire annuelle (MWh/an, axe logarithmique)",
            )
            st.plotly_chart(fig_scatter, width="stretch")
            st.caption(
                "Axes logarithmiques : chaque graduation correspond à un changement d'ordre de grandeur. "
                "Cela rend lisibles les petites, moyennes et très grandes installations sur le même graphique."
            )
        else:
            st.info("Pas assez de données avec une surface et une production strictement positives pour ce graphique.")

    # --- Carte -------------------------------------------------------------
    elif section == "Carte":
        nb_avec_coords = df_f[["Latitude", "Longitude"]].dropna().shape[0]
        if nb_avec_coords > 0:
            st.caption(
                f"{nb_avec_coords} installation(s) localisée(s) précisément "
                "via les coordonnées stockées dans Airtable (géocodage gratuit "
                "Apps Script)."
            )
        else:
            st.caption(
                "Localisation approximative au niveau de la ville "
                "(geo.api.gouv.fr, gratuit), car aucune coordonnée précise "
                "Latitude/Longitude n'est disponible dans les données filtrées."
            )
        st.info(
            "Pour recalculer les coordonnées précises, lance le projet Google Apps Script "
            "`Database Airtable Streamlit`, fonction `geocodeInstallationsAirtable`. "
            "Le script écrit les champs `Latitude` et `Longitude` dans Airtable. "
            "Après exécution, clique sur `Rafraîchir les données` dans HelioTools. "
            "Une copie du script est conservée dans `scripts/geocoder_airtable.gs`."
        )
        st.link_button(
            "Ouvrir le script de géolocalisation",
            GEOCODER_APPS_SCRIPT_URL,
            width="stretch",
        )

        recherche = st.text_input(
            "Rechercher une installation (nom de l'application, ville ou département)"
        )

        esri_attribution = "Tiles © Esri, TomTom, Garmin, FAO, NOAA, USGS, OpenStreetMap contributors"
        FONDS_DE_CARTE = {
            "Satellite (vue aérienne)": {
                "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "attr": "Tiles © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
            },
            "Standard (rues détaillées)": {"tiles": "OpenStreetMap", "attr": None},
            "Clair et épuré": {"tiles": "cartodbpositron", "attr": None},
        }
        fond_choisi = st.selectbox(
            "Fond de carte", list(FONDS_DE_CARTE.keys()), index=0
        )

        map_df = df_f.copy()
        if recherche:
            motif = recherche.lower()
            mask = (
                map_df["Application"].fillna("").str.lower().str.contains(motif)
                | map_df["Ville"].fillna("").str.lower().str.contains(motif)
                | map_df["Département"].fillna("").str.lower().str.contains(motif)
            )
            map_df = map_df[mask]
            if map_df.empty:
                st.warning("Aucune installation ne correspond à cette recherche.")

        if not map_df.empty:
            with st.spinner("Localisation des installations..."):
                points = build_map_points(map_df)

            if points:
                centre_lat = sum(p["lat"] for p in points) / len(points)
                centre_lon = sum(p["lon"] for p in points) / len(points)
                carte = folium.Map(
                    location=[centre_lat, centre_lon],
                    zoom_start=6 if len(points) > 1 else 12,
                    tiles=FONDS_DE_CARTE[fond_choisi]["tiles"],
                    attr=FONDS_DE_CARTE[fond_choisi]["attr"],
                )
                if fond_choisi == "Satellite (vue aérienne)":
                    folium.TileLayer(
                        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}",
                        attr=esri_attribution,
                        name="Routes et transports",
                        overlay=True,
                        control=True,
                    ).add_to(carte)
                    folium.TileLayer(
                        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                        attr=esri_attribution,
                        name="Noms des villes",
                        overlay=True,
                        control=True,
                    ).add_to(carte)
                    folium.LayerControl(collapsed=True).add_to(carte)
                couleur_secteur = _sector_color_map(df_f)

                for p in points:
                    secteur = p.get("Secteur") or "Non renseigné"
                    type_installation = p.get("Type d'installation") or "-"
                    popup_html = (
                        f"<b>{p.get('Application') or 'Installation'}</b><br>"
                        f"Ville : {p.get('Ville') or '-'}<br>"
                        f"Département : {p.get('Département') or '-'}<br>"
                        f"Adresse estimée : {p.get('adresse') or '-'}<br>"
                        f"Secteur : {secteur}<br>"
                        f"Type : {type_installation}<br>"
                        f"Année de mise en service : {p.get('Année de mise en service') or '-'}<br>"
                        f"Superficie : {p.get('Superficie (m²)') or '-'} m²<br>"
                        f"Production annuelle : {p.get('Production annuelle (MWh)') or '-'} MWh<br>"
                        f"<a href='{p['maps_url']}' target='_blank'>Voir sur Google Maps</a>"
                    )
                    if p.get("Lien internet"):
                        popup_html += (
                            f"<br><a href='{p['Lien internet']}' target='_blank'>"
                            "Lien du projet</a>"
                        )

                    folium.CircleMarker(
                        location=[p["lat"], p["lon"]],
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=p.get("Application") or p.get("Ville"),
                        radius=5,
                        color="#ffffff",
                        weight=1,
                        fill=True,
                        fill_color=couleur_secteur.get(secteur, OTHER_CATEGORY_COLOR),
                        fill_opacity=0.95,
                    ).add_to(carte)

                st_folium(
                    carte,
                    width="stretch",
                    height=550,
                    key="carte_installations",
                    returned_objects=[],
                )
                st.caption(
                    f"{len(points)} installation(s) localisée(s) sur "
                    f"{len(map_df)} affichée(s)."
                )
                if nb_avec_coords == 0:
                    st.caption(
                        "Info - Localisation approximative : plusieurs installations "
                        "d'une même ville apparaissent au même point (centre-ville)."
                    )
            else:
                st.info("Aucune installation n'a pu être localisée.")
        elif not recherche:
            st.info("Aucune ville renseignée pour les installations filtrées.")

    # --- Données -------------------------------------------------------------
    else:
        st.dataframe(
            df_f,
            width="stretch",
            column_config={
                "Lien internet": st.column_config.LinkColumn("Lien internet"),
            },
            hide_index=True,
        )
        st.download_button(
            "Télécharger en CSV",
            data=df_f.to_csv(index=False).encode("utf-8-sig"),
            file_name="installations_solaire_thermique.csv",
            mime="text/csv",
        )



