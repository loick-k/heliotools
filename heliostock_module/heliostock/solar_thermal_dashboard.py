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

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import folium
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from folium.plugins import MarkerCluster
from pyairtable import Api
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------

# IDs par défaut (base "BDD Atlansun Solaire thermique")
DEFAULT_BASE_ID = "appjauiOQySQq9PBz"
DEFAULT_TABLE_ID = "tblU1ec0gGyWq9YN8"  # table "BDD STH"

# Tables liées utilisées pour résoudre les champs de type "lien vers un
# enregistrement" (Ville, Secteurs, Type d'installation, Etat) en libellés
# lisibles plutôt que des IDs d'enregistrement Airtable.
LINKED_TABLES = {
    "Ville": "tbleBvECqENQREthB",
    "Secteurs": "tblKwrQ1LSFVS9NCK",
    "Type d'installation": "tblRFmyTCj3cFvYeZ",
    "Etat": "tblJj36Gj0YaanZNJ",
}

# ---------------------------------------------------------------------------
# Fonctions utilitaires de nettoyage
# ---------------------------------------------------------------------------
def to_float(value):
    """Extrait un nombre flottant d'une chaîne du type '5 000 L' ou '45%'."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d[\d\s]*(?:[.,]\d+)?", str(value))
    if not match:
        return None
    cleaned = match.group(0).replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def to_year(value):
    """Extrait une année à 4 chiffres (19xx ou 20xx) d'une chaîne."""
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def join_values(value):
    """Uniformise les valeurs de type liste (lookups) en chaîne lisible."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else None
    return value


def group_small_categories(
    counts: pd.DataFrame, label_col: str, value_col: str, seuil_pct: float = 3.0
) -> pd.DataFrame:
    """Regroupe les catégories représentant moins de `seuil_pct`% du total
    dans une catégorie 'Autres', pour éviter les graphiques illisibles avec
    de nombreuses petites tranches."""
    total = counts[value_col].sum()
    if total == 0 or counts.empty:
        return counts
    counts = counts.copy()
    counts["_pct"] = counts[value_col] / total * 100
    principales = counts[counts["_pct"] >= seuil_pct][[label_col, value_col]]
    petites = counts[counts["_pct"] < seuil_pct]
    if not petites.empty:
        ligne_autres = pd.DataFrame(
            {label_col: ["Autres"], value_col: [petites[value_col].sum()]}
        )
        principales = pd.concat([principales, ligne_autres], ignore_index=True)
    return principales.sort_values(value_col, ascending=False)


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


def build_search_query(row: pd.Series) -> str:
    """Construit une requête 'nom de l'application, ville, département,
    France' pour géocoder précisément une installation."""
    parts = [row.get("Application"), row.get("Ville"), row.get("Département")]
    parts = [str(p).strip() for p in parts if p]
    parts.append("France")
    return ", ".join(parts)


@st.cache_data(ttl=60 * 60 * 24 * 7, show_spinner=False)
def geocode_google(query: str, api_key: str):
    """Géocode précisément une installation via l'API Google Maps Geocoding.
    Renvoie (lat, lon, adresse_formatée, lien_google_maps) ou None."""
    if not query or not api_key:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": api_key, "region": "fr"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        result = data["results"][0]
        loc = result["geometry"]["location"]
        place_id = result.get("place_id")
        maps_url = (
            f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            if place_id
            else f"https://www.google.com/maps/search/?api=1&query={loc['lat']},{loc['lng']}"
        )
        return loc["lat"], loc["lng"], result.get("formatted_address"), maps_url
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


@st.cache_data(show_spinner=False)
def build_map_points(map_df: pd.DataFrame, google_api_key: str) -> list:
    """Construit la liste des points à afficher sur la carte.

    Le résultat est mis en cache dans son ensemble (tant que le sous-jeu de
    données filtré et la clé API ne changent pas), et les géocodages
    nécessaires sont lancés en parallèle plutôt qu'un par un : c'est ce qui
    évite à la carte d'être lente à charger, en particulier au premier
    affichage ou lorsqu'aucune coordonnée n'est encore stockée dans Airtable.
    """
    rows = map_df.to_dict("records")

    # Identifie les requêtes de géocodage réellement nécessaires (les
    # installations ayant déjà Latitude/Longitude n'en ont pas besoin), en
    # dédupliquant les requêtes identiques (ex. plusieurs installations dans
    # la même ville).
    google_queries, city_queries = set(), set()
    for row in rows:
        if pd.notna(row.get("Latitude")) and pd.notna(row.get("Longitude")):
            continue
        if google_api_key:
            google_queries.add(build_search_query(row))
        elif row.get("Ville"):
            city_queries.add(row["Ville"])

    google_cache, city_cache = {}, {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        google_futures = {
            executor.submit(geocode_google, q, google_api_key): q
            for q in google_queries
        }
        city_futures = {executor.submit(geocode_city, v): v for v in city_queries}
        for future, q in google_futures.items():
            google_cache[q] = future.result()
        for future, v in city_futures.items():
            city_cache[v] = future.result()

    points = []
    for row in rows:
        lat = lon = adresse = maps_url = None

        if pd.notna(row.get("Latitude")) and pd.notna(row.get("Longitude")):
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
            adresse = row.get("Ville")
            maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        elif google_api_key:
            result = google_cache.get(build_search_query(row))
            if result:
                lat, lon, adresse, maps_url = result

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

def render_solar_thermal_dashboard() -> None:

    # ---------------------------------------------------------------------------
    # Barre latérale - connexion & filtres
    # ---------------------------------------------------------------------------
    st.sidebar.header("🔌 Connexion Airtable")
    api_key = st.sidebar.text_input(
        "Personal Access Token Airtable",
        type="password",
        help=(
            "Créez un token sur airtable.com/create/tokens avec les scopes "
            "'data.records:read' et 'schema.bases:read', et donnez-lui accès "
            "à la base 'BDD Atlansun Solaire thermique'."
        ),
    )
    base_id = st.sidebar.text_input("Base ID", value=DEFAULT_BASE_ID)
    table_id = st.sidebar.text_input("Table ID (BDD STH)", value=DEFAULT_TABLE_ID)

    st.sidebar.header("🗺️ Google Maps (optionnel)")
    google_api_key = st.sidebar.text_input(
        "Clé API Google Maps",
        type="password",
        help=(
            "Utilisée seulement pour les installations sans Latitude/Longitude "
            "déjà renseignées dans Airtable. 💡 Astuce gratuite : géocodez vos "
            "installations une fois pour toutes avec le script Apps Script "
            "fourni (geocoder_airtable.gs), qui écrit Latitude/Longitude dans "
            "Airtable sans frais Google. Cette clé (payante au-delà d'un "
            "quota gratuit) n'est alors plus nécessaire."
        ),
    )

    if st.sidebar.button("🔄 Rafraîchir les données"):
        st.cache_data.clear()

    st.title("☀️ Installations Solaire Thermique")
    st.caption("Base Airtable : BDD Atlansun Solaire thermique — table BDD STH")

    if not api_key:
        st.info(
            "👈 Renseignez votre Personal Access Token Airtable dans la barre "
            "latérale pour charger les données."
        )
        st.stop()

    try:
        df = load_data(api_key, base_id, table_id)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Erreur lors du chargement des données Airtable : {exc}")
        st.stop()

    if df.empty:
        st.warning("Aucune installation trouvée dans cette table.")
        st.stop()

    # ---------------------------------------------------------------------------
    # Filtres
    # ---------------------------------------------------------------------------
    st.sidebar.header("🔎 Filtres")


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
        ["📊 Vue d'ensemble", "🗺️ Carte", "📋 Données"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # --- Vue d'ensemble --------------------------------------------------------
    if section == "📊 Vue d'ensemble":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Installations", f"{len(df_f):,}".replace(",", " "))
        c2.metric(
            "Superficie totale",
            f"{df_f['Superficie (m²)'].sum():,.0f} m²".replace(",", " "),
        )
        c3.metric(
            "Production annuelle totale",
            f"{df_f['Production annuelle (MWh)'].sum():,.0f} MWh".replace(",", " "),
        )
        c4.metric(
            "Aide ADEME totale",
            f"{df_f['Aide ADEME (€)'].sum():,.0f} €".replace(",", " "),
        )

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
            st.plotly_chart(fig_dep, use_container_width=True)

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
            st.plotly_chart(fig_secteur, use_container_width=True)

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
            st.plotly_chart(fig_etat, use_container_width=True)

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
                st.plotly_chart(fig_evol, use_container_width=True)
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
                st.plotly_chart(fig_annee, use_container_width=True)
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
                st.plotly_chart(fig_superficie_secteur, use_container_width=True)
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
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.info("Pas assez de données pour ce graphique.")

    # --- Carte -------------------------------------------------------------
    elif section == "🗺️ Carte":
        nb_avec_coords = df_f[["Latitude", "Longitude"]].dropna().shape[0]
        if nb_avec_coords > 0:
            st.caption(
                f"🎯 {nb_avec_coords} installation(s) localisée(s) précisément "
                "via les coordonnées stockées dans Airtable (géocodage gratuit "
                "Apps Script)."
            )
        elif google_api_key:
            st.caption(
                "🎯 Localisation précise via Google Maps (application, ville, "
                "département)."
            )
        else:
            st.caption(
                "📍 Localisation approximative au niveau de la ville "
                "(geo.api.gouv.fr, gratuit). Pour une localisation précise et "
                "gratuite, utilisez le script Apps Script fourni "
                "(geocoder_airtable.gs) pour écrire Latitude/Longitude dans "
                "Airtable — ou renseignez une clé API Google Maps ci-contre."
            )

        recherche = st.text_input(
            "🔍 Rechercher une installation (nom de l'application, ville ou département)"
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
                points = build_map_points(map_df, google_api_key)

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
                    type_installation = p.get("Type d'installation") or "—"
                    popup_html = (
                        f"<b>{p.get('Application') or 'Installation'}</b><br>"
                        f"Ville : {p.get('Ville') or '—'}<br>"
                        f"Département : {p.get('Département') or '—'}<br>"
                        f"Adresse estimée : {p.get('adresse') or '—'}<br>"
                        f"Secteur : {secteur}<br>"
                        f"Type : {type_installation}<br>"
                        f"Année de mise en service : {p.get('Année de mise en service') or '—'}<br>"
                        f"Superficie : {p.get('Superficie (m²)') or '—'} m²<br>"
                        f"Production annuelle : {p.get('Production annuelle (MWh)') or '—'} MWh<br>"
                        f"<a href='{p['maps_url']}' target='_blank'>📍 Voir sur Google Maps</a>"
                    )
                    if p.get("Lien internet"):
                        popup_html += (
                            f"<br><a href='{p['Lien internet']}' target='_blank'>"
                            "🔗 Lien du projet</a>"
                        )

                    folium.Marker(
                        location=[p["lat"], p["lon"]],
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=p.get("Application") or p.get("Ville"),
                        icon=folium.Icon(color=couleur_secteur[secteur]),
                    ).add_to(cluster)

                st_folium(
                    carte,
                    use_container_width=True,
                    height=550,
                    key="carte_installations",
                    returned_objects=[],
                )
                st.caption(
                    f"{len(points)} installation(s) localisée(s) sur "
                    f"{len(map_df)} affichée(s)."
                )
                if nb_avec_coords == 0 and not google_api_key:
                    st.caption(
                        "ℹ️ Localisation approximative : plusieurs installations "
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
            use_container_width=True,
            column_config={
                "Lien internet": st.column_config.LinkColumn("Lien internet"),
            },
            hide_index=True,
        )
        st.download_button(
            "⬇️ Télécharger en CSV",
            data=df_f.to_csv(index=False).encode("utf-8-sig"),
            file_name="installations_solaire_thermique.csv",
            mime="text/csv",
        )
