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
    "#F2A000",
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#6B7280",
    "#E69F00",
    "#5B4AB0",
    "#8CB369",
]
MAP_POINT_COLORS = [
    "#0072B2",
    "#009E73",
    "#F2A000",
    "#CC79A7",
    "#D55E00",
    "#56B4E9",
    "#6B7280",
    "#7E57C2",
]
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


def _overview_export_tables(df_f: pd.DataFrame) -> dict[str, pd.DataFrame]:
    dep_counts = _counts_table(df_f, "Département")
    secteur_counts = group_small_categories(_counts_table(df_f, "Secteur"), "Secteur", "Nombre", seuil_pct=3.0)
    etat_counts = group_small_categories(_counts_table(df_f, "Etat"), "Etat", "Nombre", seuil_pct=3.0)
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
        "Répartition par secteur": secteur_counts,
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


def _pdf_short_label(value: object, max_chars: int = 26) -> str:
    try:
        if pd.notna(value) and float(value).is_integer():
            label = str(int(float(value)))
            return label if len(label) <= max_chars else f"{label[: max_chars - 1]}…"
    except (TypeError, ValueError):
        pass
    label = str(value or "Non renseigné")
    return label if len(label) <= max_chars else f"{label[: max_chars - 1]}…"


def _draw_pdf_header(canvas, *, title: str, subtitle: str, width: float, height: float) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(34, height - 38, title)
    canvas.setFont("Helvetica", 9)
    canvas.setFillColorRGB(0.47, 0.49, 0.55)
    canvas.drawString(34, height - 56, subtitle)
    canvas.setStrokeColorRGB(0.88, 0.9, 0.94)
    canvas.line(34, height - 68, width - 34, height - 68)


def _draw_pdf_footer(canvas, *, page_number: int, width: float) -> None:
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.55, 0.57, 0.64)
    canvas.drawRightString(width - 34, 24, f"Page {page_number}")


def _draw_wrapped_pdf_text(
    canvas,
    text: str,
    *,
    x: float,
    y: float,
    max_chars: int,
    leading: float = 11,
    font: str = "Helvetica",
    size: int = 8,
) -> float:
    canvas.setFont(font, size)
    for line in _wrap_text(text, width=max_chars):
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _draw_kpi_cards(canvas, metrics: list[tuple[str, str]], *, x: float, y: float, width: float) -> float:
    cols = min(4, max(1, len(metrics)))
    gap = 10
    card_w = (width - gap * (cols - 1)) / cols
    card_h = 54
    for idx, (label, value) in enumerate(metrics):
        col = idx % cols
        row = idx // cols
        cx = x + col * (card_w + gap)
        cy = y - row * (card_h + 10)
        canvas.setFillColorRGB(0.97, 0.98, 1.0)
        canvas.setStrokeColorRGB(0.86, 0.89, 0.94)
        canvas.roundRect(cx, cy - card_h, card_w, card_h, 7, fill=1, stroke=1)
        canvas.setFillColorRGB(0.45, 0.47, 0.53)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(cx + 10, cy - 16, label)
        canvas.setFillColorRGB(0.18, 0.19, 0.25)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(cx + 10, cy - 40, value)
    rows = math.ceil(len(metrics) / cols)
    return y - rows * (card_h + 10)


def _draw_bar_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    label_col: str,
    value_col: str,
    color: tuple[float, float, float],
    max_items: int = 10,
) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, title)
    chart = data[[label_col, value_col]].copy().head(max_items)
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart[value_col] = chart[value_col].map(_pdf_numeric)
    max_value = max(chart[value_col].max(), 1.0)
    canvas.setStrokeColorRGB(0.9, 0.92, 0.96)
    for step in range(5):
        gy = y + (height * step / 4)
        canvas.line(x + 28, gy, x + width, gy)
    bar_area_w = width - 36
    bar_w = min(22, max(8, bar_area_w / max(len(chart), 1) * 0.56))
    slot = bar_area_w / max(len(chart), 1)
    canvas.setFont("Helvetica", 7)
    for idx, row in chart.iterrows():
        value = _pdf_numeric(row[value_col])
        bx = x + 32 + idx * slot + (slot - bar_w) / 2
        bh = height * value / max_value
        canvas.setFillColorRGB(*color)
        canvas.rect(bx, y, bar_w, bh, fill=1, stroke=0)
        canvas.setFillColorRGB(0.38, 0.4, 0.48)
        canvas.drawCentredString(bx + bar_w / 2, y - 9, _pdf_short_label(row[label_col], 10))
        canvas.drawCentredString(bx + bar_w / 2, y + bh + 3, _fmt_number(value))


def _draw_horizontal_bar_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    label_col: str,
    value_col: str,
    colors: list[tuple[float, float, float]],
    value_suffix: str = "",
    max_items: int = 8,
) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, title)
    chart = data[[label_col, value_col]].copy().head(max_items)
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart[value_col] = chart[value_col].map(_pdf_numeric)
    max_value = max(chart[value_col].max(), 1.0)
    label_w = min(142, width * 0.43)
    bar_x = x + label_w + 8
    bar_w_max = width - label_w - 46
    row_h = min(18, height / max(len(chart), 1))
    canvas.setFont("Helvetica", 8)
    for row_idx, (_, row) in enumerate(chart.iterrows()):
        cy = y + height - (row_idx + 1) * row_h + 4
        value = _pdf_numeric(row[value_col])
        bar_w = bar_w_max * value / max_value
        canvas.setFillColorRGB(0.32, 0.34, 0.42)
        canvas.drawRightString(x + label_w, cy + 2, _pdf_short_label(row[label_col], 28))
        canvas.setFillColorRGB(*colors[row_idx % len(colors)])
        canvas.roundRect(bar_x, cy, bar_w, 8, 2, fill=1, stroke=0)
        canvas.setFillColorRGB(0.32, 0.34, 0.42)
        canvas.drawString(bar_x + bar_w + 4, cy + 1, _fmt_number(value, 0, value_suffix))


def _draw_line_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    x_col: str,
    y_col: str,
    y_axis_label: str = "",
) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, title)
    if x_col not in data.columns or y_col not in data.columns:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart = data[[x_col, y_col]].dropna().copy()
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart[x_col] = chart[x_col].map(_pdf_numeric)
    chart[y_col] = chart[y_col].map(_pdf_numeric)
    min_x, max_x = chart[x_col].min(), chart[x_col].max()
    max_y = max(chart[y_col].max(), 1.0)
    canvas.setStrokeColorRGB(0.9, 0.92, 0.96)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    for step in range(5):
        gy = y + (height * step / 4)
        canvas.line(x + 28, gy, x + width, gy)
        canvas.drawRightString(x + 24, gy - 3, _fmt_number(max_y * step / 4))
    points = []
    for _, row in chart.iterrows():
        px = x + 32 if max_x == min_x else x + 32 + (width - 36) * (row[x_col] - min_x) / (max_x - min_x)
        py = y + height * row[y_col] / max_y
        points.append((px, py))
    canvas.setStrokeColorRGB(0.0, 0.42, 0.8)
    canvas.setLineWidth(1.5)
    for start, end in zip(points, points[1:]):
        canvas.line(start[0], start[1], end[0], end[1])
    canvas.setFillColorRGB(0.0, 0.42, 0.8)
    for px, py in points:
        canvas.circle(px, py, 2.2, fill=1, stroke=0)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    if y_axis_label:
        canvas.drawString(x + 28, y + height + 3, y_axis_label)
    canvas.drawString(x + 28, y - 10, _fmt_number(min_x))
    canvas.drawRightString(x + width, y - 10, _fmt_number(max_x))


def _draw_pie_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    radius: float,
    title: str,
    label_col: str,
    value_col: str,
    colors: list[tuple[float, float, float]],
    max_items: int = 7,
) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + radius * 2 + 16, title)
    chart = data[[label_col, value_col]].copy().head(max_items)
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + radius, "Aucune donnée.")
        return
    chart[value_col] = chart[value_col].map(_pdf_numeric)
    total = chart[value_col].sum()
    if total <= 0:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + radius, "Aucune donnée.")
        return
    start = 90
    for idx, row in chart.iterrows():
        extent = 360 * _pdf_numeric(row[value_col]) / total
        canvas.setFillColorRGB(*colors[idx % len(colors)])
        canvas.wedge(x, y, x + radius * 2, y + radius * 2, start, extent, fill=1, stroke=0)
        start += extent
    legend_x = x + radius * 2 + 18
    legend_y = y + radius * 2 - 4
    canvas.setFont("Helvetica", 8)
    for idx, row in chart.iterrows():
        pct = 100 * _pdf_numeric(row[value_col]) / total
        ly = legend_y - idx * 13
        canvas.setFillColorRGB(*colors[idx % len(colors)])
        canvas.rect(legend_x, ly - 7, 7, 7, fill=1, stroke=0)
        canvas.setFillColorRGB(0.32, 0.34, 0.42)
        canvas.drawString(legend_x + 10, ly - 7, f"{_pdf_short_label(row[label_col], 22)} - {pct:.0f} %")


def _draw_scatter_chart(
    canvas,
    data: pd.DataFrame,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
) -> None:
    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(x, y + height + 16, title)
    chart = data.dropna(subset=["Superficie (m²)", "Production annuelle (MWh)"]).copy()
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée.")
        return
    chart = chart[
        (chart["Superficie (m²)"].map(_pdf_numeric) > 0)
        & (chart["Production annuelle (MWh)"].map(_pdf_numeric) > 0)
    ].copy()
    if chart.empty:
        canvas.setFont("Helvetica", 9)
        canvas.drawString(x, y + height / 2, "Aucune donnée avec surface et production strictement positives.")
        return
    min_x = max(chart["Superficie (m²)"].map(_pdf_numeric).min(), 1.0)
    max_x = max(chart["Superficie (m²)"].map(_pdf_numeric).max(), min_x)
    log_min = math.floor(math.log10(min_x))
    log_max = math.ceil(math.log10(max_x))
    tick_values = [10**power for power in range(log_min, log_max + 1)]
    if not tick_values:
        tick_values = [min_x, max_x]
    min_y = max(chart["Production annuelle (MWh)"].map(_pdf_numeric).min(), 1.0)
    max_y = max(chart["Production annuelle (MWh)"].map(_pdf_numeric).max(), min_y)
    log_y_min = math.floor(math.log10(min_y))
    log_y_max = math.ceil(math.log10(max_y))
    y_tick_values = [10**power for power in range(log_y_min, log_y_max + 1)]
    if not y_tick_values:
        y_tick_values = [min_y, max_y]
    canvas.setStrokeColorRGB(0.9, 0.92, 0.96)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    log_y_span = max(log_y_max - log_y_min, 1e-9)
    for tick in y_tick_values:
        gy = y + height * (math.log10(tick) - log_y_min) / log_y_span
        canvas.line(x + 28, gy, x + width, gy)
        canvas.drawRightString(x + 24, gy - 3, _fmt_number(tick))
    log_span = max(log_max - log_min, 1e-9)
    for tick in tick_values:
        gx = x + 28 + (width - 36) * (math.log10(tick) - log_min) / log_span
        canvas.line(gx, y, gx, y + height)
        canvas.drawCentredString(gx, y - 11, _fmt_number(tick))
    canvas.setFillColorRGB(0.0, 0.7, 0.62)
    for _, row in chart.head(120).iterrows():
        surface = max(_pdf_numeric(row["Superficie (m²)"]), min_x)
        px = x + 28 + (width - 36) * (math.log10(surface) - log_min) / log_span
        production = max(_pdf_numeric(row["Production annuelle (MWh)"]), min_y)
        py = y + height * (math.log10(production) - log_y_min) / log_y_span
        canvas.circle(px, py, 2.4, fill=1, stroke=0)
    canvas.setFillColorRGB(0.38, 0.4, 0.48)
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(x + width / 2, y - 24, "Surface de capteurs installée (m², axe logarithmique)")
    canvas.drawString(x + 28, y + height + 3, "Production annuelle (MWh/an, axe logarithmique)")
    canvas.setFillColorRGB(0.5, 0.52, 0.58)
    canvas.drawString(x + 28, y - 36, "Axes log : comparaison lisible des petites, moyennes et grandes installations.")


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
    _draw_pdf_header(
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
        fy = _draw_wrapped_pdf_text(canvas, f"{label} : {value}", x=34, y=fy, max_chars=80)
    y = min(y, fy) - 8

    canvas.setFillColorRGB(0.18, 0.19, 0.25)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(34, y, "Indicateurs clés")
    y = _draw_kpi_cards(canvas, _filtered_summary_metrics(df_f), x=34, y=y - 10, width=page_width - 68)

    _draw_bar_chart(
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
    _draw_pie_chart(
        canvas,
        chart_tables["Répartition par secteur"],
        x=456,
        y=92,
        radius=74,
        title="Répartition par secteur",
        label_col="Secteur",
        value_col="Nombre",
        colors=PDF_CHART_COLORS,
    )
    _draw_pdf_footer(canvas, page_number=page, width=page_width)
    canvas.showPage()

    page += 1
    _draw_pdf_header(
        canvas,
        title="Graphiques de la vue d'ensemble",
        subtitle="Répartition, évolution temporelle et surfaces - mêmes filtres que l'écran",
        width=page_width,
        height=page_height,
    )
    _draw_pie_chart(
        canvas,
        chart_tables["Répartition par état"],
        x=34,
        y=322,
        radius=70,
        title="Répartition par état",
        label_col="Etat",
        value_col="Nombre",
        colors=PDF_CHART_COLORS,
    )
    _draw_line_chart(
        canvas,
        chart_tables["Évolution cumulée"],
        x=440,
        y=330,
        width=350,
        height=160,
        title="Évolution cumulée du nombre d'installations",
        x_col="Année de mise en service",
        y_col="Cumulé",
        y_axis_label="Nombre cumulé d'installations",
    )
    _draw_bar_chart(
        canvas,
        chart_tables["Surface installée par année"],
        x=34,
        y=82,
        width=360,
        height=170,
        title="Surface installée par année",
        label_col="Année de mise en service",
        value_col="Superficie (m²)",
        color=(0.18, 0.53, 0.67),
        max_items=18,
    )
    _draw_line_chart(
        canvas,
        chart_tables["Surface cumulée"],
        x=440,
        y=82,
        width=350,
        height=170,
        title="Surface cumulée installée",
        x_col="Année de mise en service",
        y_col="Surface cumulée (m²)",
        y_axis_label="Surface cumulée (m²)",
    )
    _draw_pdf_footer(canvas, page_number=page, width=page_width)
    canvas.showPage()

    page += 1
    _draw_pdf_header(
        canvas,
        title="Surfaces et production",
        subtitle="Analyse des surfaces installées et de la production annuelle - mêmes filtres que l'écran",
        width=page_width,
        height=page_height,
    )
    _draw_pie_chart(
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
    _draw_scatter_chart(
        canvas,
        chart_tables["Superficie vs production annuelle"],
        x=440,
        y=312,
        width=350,
        height=190,
        title="Production annuelle selon la surface installée",
    )
    _draw_pdf_footer(canvas, page_number=page, width=page_width)
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
        pdf_bytes = _overview_pdf_bytes(df_f=df_f, filters=active_filters)
        st.download_button(
            "Télécharger la vue d'ensemble en PDF",
            data=pdf_bytes,
            file_name=f"dashboard_solaire_thermique_vue_ensemble_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
        )

        c1, c2, c3, c4 = st.columns(4)
        summary_metrics = _filtered_summary_metrics(df_f)
        c1.metric(summary_metrics[0][0], summary_metrics[0][1])
        c2.metric(summary_metrics[1][0], summary_metrics[1][1])
        c3.metric(summary_metrics[2][0], summary_metrics[2][1])
        c4.metric(summary_metrics[3][0], summary_metrics[3][1])

        st.divider()

        col_a, col_b = st.columns(2)

        with col_a:
            dep_counts = (
                df_f["Département"].fillna("Non renseigné").value_counts().reset_index()
            )
            dep_counts.columns = ["Département", "Nombre"]
            fig_dep = px.bar(
                dep_counts,
                x="Département",
                y="Nombre",
                title="Installations par département",
                color_discrete_sequence=["#f4a300"],
                labels={"Nombre": "Nombre d'installations"},
            )
            fig_dep.update_layout(showlegend=False)
            st.plotly_chart(fig_dep, width="stretch")

        with col_b:
            secteur_counts = (
                df_f["Secteur"].fillna("Non renseigné").value_counts().reset_index()
            )
            secteur_counts.columns = ["Secteur", "Nombre"]
            secteur_counts = group_small_categories(
                secteur_counts, "Secteur", "Nombre", seuil_pct=3.0
            )
            fig_secteur = px.pie(
                secteur_counts,
                names="Secteur",
                values="Nombre",
                color="Secteur",
                title="Répartition par secteur",
                color_discrete_sequence=CHART_COLORS,
                labels={"Nombre": "Nombre d'installations", "Secteur": "Secteur"},
            )
            fig_secteur.update_traces(textposition="inside", textinfo="percent")
            fig_secteur.update_layout(legend_title_text="Secteur")
            st.plotly_chart(fig_secteur, width="stretch")

        col_e, col_f = st.columns(2)

        with col_e:
            etat_counts = (
                df_f["Etat"].fillna("Non renseigné").value_counts().reset_index()
            )
            etat_counts.columns = ["Etat", "Nombre"]
            etat_counts = group_small_categories(
                etat_counts, "Etat", "Nombre", seuil_pct=3.0
            )
            fig_etat = px.pie(
                etat_counts,
                names="Etat",
                values="Nombre",
                color="Etat",
                title="Répartition par état",
                color_discrete_sequence=CHART_COLORS,
                labels={"Nombre": "Nombre d'installations", "Etat": "État"},
            )
            fig_etat.update_traces(textposition="inside", textinfo="percent")
            fig_etat.update_layout(legend_title_text="État")
            st.plotly_chart(fig_etat, width="stretch")

        with col_f:
            evol = (
                df_f.dropna(subset=["Année de mise en service"])
                .groupby("Année de mise en service")
                .size()
                .reset_index(name="Nombre")
                .sort_values("Année de mise en service")
            )
            if not evol.empty:
                evol["Cumulé"] = evol["Nombre"].cumsum()
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
            installations_par_annee = (
                df_f.dropna(subset=["Année de mise en service"])
                .groupby("Année de mise en service")
                .size()
                .reset_index(name="Nombre")
                .sort_values("Année de mise en service")
            )
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
            superficie_df = df_f.dropna(subset=["Superficie (m²)"]).copy()
            if not superficie_df.empty:
                superficie_df["Secteur"] = superficie_df["Secteur"].fillna(
                    "Non renseigné"
                )
                superficie_secteur = (
                    superficie_df.groupby("Secteur")["Superficie (m²)"]
                    .sum()
                    .reset_index()
                )
                superficie_secteur = group_small_categories(
                    superficie_secteur, "Secteur", "Superficie (m²)", seuil_pct=3.0
                )
                fig_superficie_secteur = px.pie(
                    superficie_secteur,
                    names="Secteur",
                    values="Superficie (m²)",
                    color="Secteur",
                    title="Superficie (m²) par secteur",
                    color_discrete_sequence=CHART_COLORS,
                    labels={"Superficie (m²)": "Surface de capteurs installée (m²)", "Secteur": "Secteur"},
                )
                fig_superficie_secteur.update_traces(textposition="inside", textinfo="percent")
                fig_superficie_secteur.update_layout(legend_title_text="Secteur")
                st.plotly_chart(fig_superficie_secteur, width="stretch")
            else:
                st.info("Pas assez de données de superficie pour ce graphique.")

        col_i, col_j = st.columns(2)

        with col_i:
            surface_par_annee = (
                df_f.dropna(subset=["Année de mise en service", "Superficie (m²)"])
                .groupby("Année de mise en service")["Superficie (m²)"]
                .sum()
                .reset_index()
                .sort_values("Année de mise en service")
            )
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
            surface_cumulee = surface_par_annee.copy() if "surface_par_annee" in locals() else pd.DataFrame()
            if not surface_cumulee.empty:
                surface_cumulee["Surface cumulée (m²)"] = surface_cumulee["Superficie (m²)"].cumsum()
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
                secteurs_uniques = sorted(
                    {p.get("Secteur") or "Non renseigné" for p in points}
                )
                couleur_secteur = {
                    s: MAP_POINT_COLORS[i % len(MAP_POINT_COLORS)] for i, s in enumerate(secteurs_uniques)
                }

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
                        fill_color=couleur_secteur[secteur],
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



