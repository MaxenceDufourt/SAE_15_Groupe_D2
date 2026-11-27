#!/usr/bin/env python
# coding: utf-8

# In[8]:


import html as html_lib
import os
import folium
from folium.plugins import MarkerCluster
import numpy as np
import pandas as pd


#--------#

def convert_dms_series(deg, mn, sc, direction):
  """Convertit des colonnes de coordonnées DMS (Degrés, Minutes, Secondes)

  en degrés décimaux de manière vectorisée avec pandas/numpy.
  """
  d = pd.to_numeric(deg, errors="coerce").fillna(0.0)
  m = pd.to_numeric(mn, errors="coerce").fillna(0.0)
  s = pd.to_numeric(sc, errors="coerce").fillna(0.0)
  dec = d + (m / 60.0) + (s / 3600.0)

  # Applique un signe négatif pour le Sud (S) et l'Ouest (W)
  sign = np.where(
      direction.astype(str).str.strip().str.upper().isin(["S", "W"]), -1.0, 1.0
  )
  return dec * sign


def parse_alt(val):
  """Convertit la hauteur AER_NB_ALT_BAS en nombre flottant (float).

  Gère les virgules décimales, les espaces et les valeurs manquantes.
  """
  if pd.isna(val):
    return None
  s = str(val).strip().replace(",", ".")
  try:
    return float(s)
  except ValueError:
    return None


def add_legend(m, titre_carte, total_count, max_alt):
  """Ajoute un encadré de légende simplifié en bas à gauche de la carte Folium."""
  alt_txt = f"{max_alt:g} m" if max_alt is not None else "—"
  html = f"""
    <div style="
        position: fixed;
        bottom: 24px;
        left: 24px;
        z-index: 9999;
        background-color: white;
        padding: 10px 12px;
        border: 1px solid #ccc;
        border-radius: 6px;
        font-family: Arial, sans-serif;
        font-size: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
    ">
        <div style="font-weight: bold; margin-bottom: 3px;">{titre_carte} — 2026 ({total_count})</div>
        <div style="font-size: 11px; color: #dc2626; font-weight: bold;">
            <span style="display:inline-block;width:10px;height:10px;background:#dc2626;border-radius:50%;margin-right:4px;"></span>
            Plus haute : {alt_txt}
        </div>
    </div>
    """
  m.get_root().html.add_child(folium.Element(html))


def get_lieu(row):
  """Reconstitue l'adresse, le lieu-dit et le code postal sans doublons ni 'nan'."""
  morceaux = []
  for col in ["ADR_LB_ADD1", "ADR_LB_ADD2", "ADR_LB_ADD3", "ADR_LB_LIEU"]:
    val = str(row.get(col, "") or "").strip()
    if val and val.lower() != "nan" and val not in morceaux:
      morceaux.append(val)

  cp = str(row.get("ADR_NM_CP", "") or "").strip()
  if cp and cp.lower() != "nan":
    morceaux.append(cp)

  return " — ".join(morceaux) if morceaux else "Lieu non renseigné"


#--------#


def build_island_map(df_ile, cfg, idx_plus_haute, max_alt):
  """Crée une carte Folium verrouillée sur l'emprise du territoire."""
  lat_min, lon_min, lat_max, lon_max = cfg["bbox"]
  center = [(lat_min + lat_max) / 2.0, (lon_min + lon_max) / 2.0]

  # Verrouille le zoom et les bornes géographiques sur la zone
  m = folium.Map(
      location=center,
      zoom_start=cfg["min_zoom"],
      min_zoom=cfg["min_zoom"],
      max_zoom=cfg["max_zoom"],
      max_bounds=True,
      min_lat=lat_min,
      max_lat=lat_max,
      min_lon=lon_min,
      max_lon=lon_max,
      tiles=None,
  )
  m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]])

  # Ajout du fond de carte Esri
  for name, url in [
      (
          "Esri Topo Map",
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
      ),
  ]:
    folium.TileLayer(
        tiles=url,
        attr="Esri",
        name=name,
        min_zoom=cfg["min_zoom"],
        max_zoom=cfg["max_zoom"],
    ).add_to(m)

  add_legend(m, cfg["nom"], len(df_ile), max_alt)

  # Groupe principal regroupé (cluster) + groupe séparé pour l'antenne la plus haute
  cluster = MarkerCluster(name=f"{cfg['nom']} — 2026").add_to(m)
  groupe_plus_haute = folium.FeatureGroup(
      name=f"Plus haute ({cfg['nom']})", show=True
  ).add_to(m)

  for idx, r in df_ile.iterrows():
    est_plus_haute = idx == idx_plus_haute
    date_val = r.get("Mise en service")
    date_str = (
        date_val.strftime("%Y-%m-%d")
        if pd.notna(date_val)
        else "Non renseignée"
    )

    # Prépare les informations affichées dans l'infobulle et le popup
    alt_val = r.get("alt_bas")
    alt_str = f"{alt_val:g} m" if pd.notna(alt_val) else "—"
    lieu = get_lieu(r)
    territoire = cfg["nom"]

    etiquette_info = (
        f"Lieu : {lieu} | Territoire : {territoire} | Hauteur : {alt_str} | "
        f"Mise en service : {date_str}"
    )

    popup_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 12px; min-width: 230px;">
            <strong>Lieu :</strong> {lieu}<br>
            <strong>Territoire :</strong> {territoire}<br>
            <strong>Hauteur :</strong> <b>{alt_str}</b><br>
            <strong>Mise en service :</strong> {date_str}
        </div>
        """

    if est_plus_haute:
      # Marqueur rouge distinctif pour l'antenne la plus haute
      folium.Marker(
          location=[r["latitude"], r["longitude"]],
          icon=folium.Icon(color="red", icon="arrow-up", prefix="fa"),
          tooltip=etiquette_info,
          popup=folium.Popup(popup_html, max_width=320),
      ).add_to(groupe_plus_haute)
    else:
      # Cercle de couleur uniforme (bleu) pour les autres antennes
      folium.CircleMarker(
          location=[r["latitude"], r["longitude"]],
          radius=6,
          color="#3186cc",
          weight=1.5,
          fill=True,
          fill_color="#3186cc",
          fill_opacity=0.85,
          tooltip=etiquette_info,
          popup=folium.Popup(popup_html, max_width=320),
      ).add_to(cluster)

  folium.LayerControl().add_to(m)
  return m.get_root().render()


#--------#

DATA_DIR = r"C:\Users\bouyejay\Desktop\data\data"
SUPPORT_FILE = os.path.join(DATA_DIR, "sup_support.txt")
STATION_FILE = os.path.join(DATA_DIR, "sup_station.txt")
ANTENNE_FILE = os.path.join(DATA_DIR, "sup_antenne.txt")
OUTPUT_GALLERY_HTML = os.path.join(DATA_DIR, "cartes_iles_2026_galerie.html")

# Liste des territoires (avec la Guyane ajoutée)
ILES_2026 = [
    {
        "cle": "guadeloupe",
        "prefix": "971",
        "nom": "Guadeloupe",
        "bbox": [15.80, -61.85, 16.55, -61.00],
        "min_zoom": 10,
        "max_zoom": 17,
    },
    {
        "cle": "martinique",
        "prefix": "972",
        "nom": "Martinique",
        "bbox": [14.35, -61.25, 14.90, -60.75],
        "min_zoom": 10,
        "max_zoom": 17,
    },
    {
        "cle": "guyane",
        "prefix": "973",
        "nom": "Guyane",
        "bbox": [2.10, -54.60, 5.80, -51.60],
        "min_zoom": 7,
        "max_zoom": 17,
    },
    {
        "cle": "reunion",
        "prefix": "974",
        "nom": "La Réunion",
        "bbox": [-21.40, 55.20, -20.85, 55.85],
        "min_zoom": 10,
        "max_zoom": 17,
    },
    {
        "cle": "mayotte",
        "prefix": "976",
        "nom": "Mayotte",
        "bbox": [-13.05, 45.00, -12.60, 45.32],
        "min_zoom": 11,
        "max_zoom": 17,
    },
    {
        "cle": "nouvelle_caledonie",
        "prefix": "988",
        "nom": "Nouvelle-Calédonie",
        "bbox": [-22.75, 163.50, -19.50, 168.10],
        "min_zoom": 7,
        "max_zoom": 17,
    },
]

#--------#

try:
  print("1. Chargement des fichiers ANFR...")
  df_support = pd.read_csv(
      SUPPORT_FILE,
      sep=";",
      encoding="latin-1",
      dtype={"STA_NM_ANFR": str, "ADR_NM_CP": str},
  )
  df_station = pd.read_csv(
      STATION_FILE, sep=";", encoding="latin-1", dtype={"STA_NM_ANFR": str}
  )
  df_antenne = pd.read_csv(
      ANTENNE_FILE, sep=";", encoding="latin-1", dtype={"STA_NM_ANFR": str}
  )

  print("2. Conversion des coordonnées et nettoyage...")
  df_support["latitude"] = convert_dms_series(
      df_support["COR_NB_DG_LAT"],
      df_support["COR_NB_MN_LAT"],
      df_support["COR_NB_SC_LAT"],
      df_support["COR_CD_NS_LAT"],
  )
  df_support["longitude"] = convert_dms_series(
      df_support["COR_NB_DG_LON"],
      df_support["COR_NB_MN_LON"],
      df_support["COR_NB_SC_LON"],
      df_support["COR_CD_EW_LON"],
  )

  mask_coords_valides = (
      df_support["latitude"].between(-90.0, 90.0)
      & df_support["longitude"].between(-180.0, 180.0)
      & ~(
          (df_support["latitude"] == 0.0) & (df_support["longitude"] == 0.0)
      )
  )
  df_support = df_support[mask_coords_valides].copy()
  df_support["cp_clean"] = (
      df_support["ADR_NM_CP"].astype(str).str.strip().str.zfill(5)
  )

  print("3. Fusion des tables, hauteur AER_NB_ALT_BAS et filtre 2026...")
  for df, col in [
      (df_support, "SUP_ID"),
      (df_antenne, "SUP_ID"),
      (df_support, "STA_NM_ANFR"),
      (df_station, "STA_NM_ANFR"),
  ]:
    df[col] = df[col].astype(str).str.strip()

  df_base = pd.merge(
      df_antenne,
      df_support.drop_duplicates("SUP_ID"),
      on=["SUP_ID", "STA_NM_ANFR"],
  )
  df_base = pd.merge(df_base, df_station, on="STA_NM_ANFR", how="left")

  df_base["alt_bas"] = (
      df_base["AER_NB_ALT_BAS"].apply(parse_alt)
      if "AER_NB_ALT_BAS" in df_base.columns
      else np.nan
  )
  df_base["Mise en service"] = pd.to_datetime(
      df_base["DTE_EN_SERVICE"], format="%d/%m/%Y", errors="coerce"
  )
  df_base_2026 = df_base[df_base["Mise en service"].dt.year == 2026].copy()

  print("4. Génération de la page HTML contenant toutes les cartes...")
  sections_html = []
  nav_links = []

  for cfg in ILES_2026:
    lat_min, lon_min, lat_max, lon_max = cfg["bbox"]

    df_ile = df_base_2026[
        df_base_2026["cp_clean"].str.startswith(cfg["prefix"])
        & df_base_2026["latitude"].between(lat_min, lat_max)
        & df_base_2026["longitude"].between(lon_min, lon_max)
    ].copy()

    alts_valides = df_ile["alt_bas"].dropna()
    max_alt = float(alts_valides.max()) if not alts_valides.empty else None
    idx_plus_haute = (
        alts_valides.idxmax() if not alts_valides.empty else None
    )

    alt_resume = f" | Hauteur max : {max_alt:g} m" if max_alt is not None else ""
    print(
        f"   - {cfg['nom']} ({cfg['prefix']}) : {len(df_ile)} antennes en"
        f" 2026{alt_resume}"
    )

    map_html = build_island_map(df_ile, cfg, idx_plus_haute, max_alt)
    escaped_srcdoc = html_lib.escape(map_html, quote=True)

    nav_links.append(
        f'<a href="#{cfg["cle"]}">{cfg["nom"]} ({len(df_ile)})</a>'
    )
    sections_html.append(f"""
        <section id="{cfg["cle"]}" class="island-card">
            <div class="island-header">
                <h2>{cfg["nom"]} — 2026</h2>
                <div class="island-meta">
                    {f'<span class="max-alt">Hauteur max : {max_alt:g} m</span>' if max_alt is not None else ''}
                    <span>{len(df_ile)} antennes</span>
                </div>
            </div>
            <iframe
                srcdoc="{escaped_srcdoc}"
                loading="lazy"
                title="Carte {cfg["nom"]} 2026">
            </iframe>
        </section>
        """)

  page_html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Antennes 2026 — Territoires (Galerie)</title>
    <style>
        body {{
            margin: 0;
            padding: 24px 16px 60px;
            background: #f0f2f5;
            font-family: Arial, sans-serif;
            color: #222;
        }}
        .top-bar {{
            max-width: 1100px;
            margin: 0 auto 24px;
            background: #fff;
            padding: 16px 20px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .top-bar h1 {{
            margin: 0 0 10px;
            font-size: 20px;
        }}
        .nav {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .nav a {{
            text-decoration: none;
            background: #e8eef5;
            color: #1a3b5d;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: bold;
        }}
        .nav a:hover {{
            background: #3186cc;
            color: #fff;
        }}
        .gallery {{
            max-width: 1100px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 28px;
        }}
        .island-card {{
            background: #fff;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 3px 12px rgba(0,0,0,0.1);
        }}
        .island-header {{
            display: flex;
            justify-content: span-between;
            align-items: center;
            padding: 12px 18px;
            border-bottom: 1px solid #e5e7eb;
            gap: 12px;
        }}
        .island-header h2 {{
            margin: 0;
            font-size: 16px;
        }}
        .island-meta {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 13px;
            color: #555;
            font-weight: bold;
        }}
        .max-alt {{
            background: #fee2e2;
            color: #dc2626;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
        }}
        iframe {{
            width: 100%;
            height: 560px;
            border: 0;
            display: block;
        }}
    </style>
</head>
<body>
    <div class="top-bar">
        <h1>Antennes mises en service en 2026 — Territoires</h1>
        <div class="nav">
            {"".join(nav_links)}
        </div>
    </div>
    <main class="gallery">
        {"".join(sections_html)}
    </main>
</body>
</html>
"""

  with open(OUTPUT_GALLERY_HTML, "w", encoding="utf-8") as f:
    f.write(page_html)

  print(f"5. Terminé ! Galerie enregistrée : {OUTPUT_GALLERY_HTML}")

except Exception as e:
  print("Erreur rencontrée :", e)


# In[ ]:




