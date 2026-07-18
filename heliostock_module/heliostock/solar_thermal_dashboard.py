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
from urllib.parse import quote_plus

import folium
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from folium.plugins import MarkerCluster
from pyairtable import Api
from streamlit_folium import st_folium

from .dashboard_data_cleaning import group_small_categories, join_values, to_float, to_year

# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------

# IDs par défaut (base "BDD Atlansun Solaire thermique")
DEFAULT_BASE_ID = "appjauiOQySQq9PBz"
DEFAULT_TABLE_ID = "tblU1ec0gGyWq9YN8"  # table "BDD STH"
GEOCODING_MAX_WORKERS = 6

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


def _pdf_escape(value: object) -> bytes:
    raw = str(value).encode("cp1252", errors="replace")
    escaped = bytearray()
    for byte in raw:
        if byte in (40, 41, 92):
            escaped.extend(b"\\" + bytes([byte]))
        elif byte < 32 or byte > 126:
            escaped.extend(f"\\{byte:03o}".encode("ascii"))
        else:
            escaped.append(byte)
    return bytes(escaped)


def _pdf_line_command(text: str, *, x: int, y: int, size: int = 9, bold: bool = False) -> bytes:
    font = "F2" if bold else "F1"
    return b"BT /" + font.encode("ascii") + b" " + str(size).encode("ascii") + b" Tf " + str(x).encode("ascii") + b" " + str(y).encode("ascii") + b" Td (" + _pdf_escape(text) + b") Tj ET\n"


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


def _simple_pdf_from_lines(lines: list[tuple[str, int, bool]]) -> bytes:
    page_width, page_height = 595, 842
    pages: list[bytes] = []
    current: list[bytes] = []
    y = 800
    for text, size, bold in lines:
        if y < 46:
            pages.append(b"".join(current))
            current = []
            y = 800
        current.append(_pdf_line_command(text, x=42, y=y, size=size, bold=bold))
        y -= max(11, size + 4)
    if current:
        pages.append(b"".join(current))

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    page_object_ids: list[int] = []
    for content in pages:
        page_id = len(objects) + 1
        content_id = len(objects) + 2
        page_object_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode("ascii")

    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{object_id} 0 obj\n".encode("ascii"))
        payload.extend(obj)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(payload)


def _overview_pdf_bytes(
    *,
    df_f: pd.DataFrame,
    filters: list[tuple[str, str]],
) -> bytes:
    lines: list[tuple[str, int, bool]] = [
        ("Dashboard solaire thermique - vue d'ensemble", 16, True),
        (f"Export généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", 9, False),
        ("", 9, False),
        ("Filtres actifs", 12, True),
    ]
    for label, value in filters:
        for wrapped in _wrap_text(f"{label} : {value}", width=95):
            lines.append((wrapped, 9, False))

    lines.extend([("", 9, False), ("Indicateurs clés", 12, True)])
    for label, value in _filtered_summary_metrics(df_f):
        lines.append((f"{label} : {value}", 10, False))

    for title, table in _overview_export_tables(df_f).items():
        lines.extend([("", 9, False), (title, 12, True)])
        for line in _table_lines(table):
            for wrapped in _wrap_text(line, width=105):
                lines.append((wrapped, 8, False))

    return _simple_pdf_from_lines(lines)


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
    st.sidebar.header("ðŸ”Ž Filtres")


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
        ["ðŸ“Š Vue d'ensemble", "ðŸ—ºï¸ Carte", "ðŸ“‹ Données"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # --- Vue d'ensemble --------------------------------------------------------
    if section == "ðŸ“Š Vue d'ensemble":
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
            )
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
                title="Répartition par secteur",
                hole=0.4,
            )
            fig_secteur.update_traces(textposition="inside", textinfo="percent+label")
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
                title="Répartition par état",
                hole=0.4,
            )
            fig_etat.update_traces(textposition="inside", textinfo="percent+label")
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
                )
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
                    title="Superficie (m²) par secteur",
                    hole=0.4,
                )
                fig_superficie_secteur.update_traces(
                    textposition="inside", textinfo="percent+label"
                )
                st.plotly_chart(fig_superficie_secteur, width="stretch")
            else:
                st.info("Pas assez de données de superficie pour ce graphique.")

        st.subheader("Superficie vs Production annuelle")
        scatter_df = df_f.dropna(subset=["Superficie (m²)", "Production annuelle (MWh)"])
        if not scatter_df.empty:
            fig_scatter = px.scatter(
                scatter_df,
                x="Superficie (m²)",
                y="Production annuelle (MWh)",
                color="Secteur",
                hover_name="Ville",
                hover_data=["Application", "Année de mise en service"],
            )
            st.plotly_chart(fig_scatter, width="stretch")
        else:
            st.info("Pas assez de données pour ce graphique.")

    # --- Carte -------------------------------------------------------------
    elif section == "ðŸ—ºï¸ Carte":
        nb_avec_coords = df_f[["Latitude", "Longitude"]].dropna().shape[0]
        if nb_avec_coords > 0:
            st.caption(
                f"ðŸŽ¯ {nb_avec_coords} installation(s) localisée(s) précisément "
                "via les coordonnées stockées dans Airtable (géocodage gratuit "
                "Apps Script)."
            )
        else:
            st.caption(
                "ðŸ“ Localisation approximative au niveau de la ville "
                "(geo.api.gouv.fr, gratuit). Pour une localisation précise et "
                "gratuite, utilisez le script Apps Script fourni "
                "(geocoder_airtable.gs) pour écrire Latitude/Longitude dans "
                "Airtable."
            )

        recherche = st.text_input(
            "ðŸ” Rechercher une installation (nom de l'application, ville ou département)"
        )

        FONDS_DE_CARTE = {
            "Satellite (vue aérienne)": "Esri.WorldImagery",
            "Standard (rues détaillées)": "OpenStreetMap",
            "Clair et épuré": "cartodbpositron",
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
                    tiles=FONDS_DE_CARTE[fond_choisi],
                )
                cluster = MarkerCluster().add_to(carte)

                palette = [
                    "blue", "green", "orange", "purple", "darkred",
                    "cadetblue", "darkgreen", "pink", "gray",
                ]
                secteurs_uniques = sorted(
                    {p.get("Secteur") or "Non renseigné" for p in points}
                )
                couleur_secteur = {
                    s: palette[i % len(palette)] for i, s in enumerate(secteurs_uniques)
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
                        f"<a href='{p['maps_url']}' target='_blank'>ðŸ“ Voir sur Google Maps</a>"
                    )
                    if p.get("Lien internet"):
                        popup_html += (
                            f"<br><a href='{p['Lien internet']}' target='_blank'>"
                            "ðŸ”— Lien du projet</a>"
                        )

                    folium.Marker(
                        location=[p["lat"], p["lon"]],
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=p.get("Application") or p.get("Ville"),
                        icon=folium.Icon(color=couleur_secteur[secteur]),
                    ).add_to(cluster)

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



