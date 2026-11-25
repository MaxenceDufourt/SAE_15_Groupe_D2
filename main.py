import os
import shutil

import folium
import pandas as pd

SITE = "site"      # folder created by the program
ASSETS = "assets"  # fixed files copied as they are: style.css and images/

# Satellite basemap (Esri). Default OpenStreetMap tiles are not used:
# they are blocked when the HTML file is opened by double-click.
BASEMAP = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

# Only the installations put into service in this year are kept (the others are not even loaded)
YEAR = "2025"

# The 6 territories. The key is the start of the commune INSEE code.
TERRITORIES = {
    "974": {"file": "reunion", "fr": "La Réunion", "en": "Réunion Island"},
    "971": {"file": "guadeloupe", "fr": "Guadeloupe", "en": "Guadeloupe"},
    "972": {"file": "martinique", "fr": "Martinique", "en": "Martinique"},
    "973": {"file": "guyane", "fr": "Guyane", "en": "French Guiana"},
    "976": {"file": "mayotte", "fr": "Mayotte", "en": "Mayotte"},
    "988": {"file": "nouvelle_caledonie", "fr": "Nouvelle-Calédonie", "en": "New Caledonia"},
}


# ---------------------------------------------------------------------------
# PART 1 - DATA: read the ANFR files and prepare one table with everything
# ---------------------------------------------------------------------------

def read_table(folder, name, columns):
    """Read one ANFR text file, keeping only the columns we need.
    STA_NM_ANFR and COM_CD_INSEE are read as text: some values (e.g. 0422750464)
    are not plain numbers, and all tables must use the same type to be joined."""
    return pd.read_csv(f"{folder}/{name}.txt", sep=";", encoding="utf-8",
                       usecols=columns, dtype={"STA_NM_ANFR": str, "COM_CD_INSEE": str})


def to_decimal(degrees, minutes, seconds, direction):
    """Degrees / minutes / seconds -> decimal degrees (South and West are negative)."""
    value = degrees + minutes / 60 + seconds / 3600
    return value.where(~direction.isin(["S", "W"]), -value)


def load_stations():
    """Installations put into service in YEAR. Service dates look like 04/09/2009, so the year is the last 4 characters."""
    station = read_table("data", "sup_station", ["STA_NM_ANFR", "ADM_ID", "DTE_EN_SERVICE"])
    return station[station["DTE_EN_SERVICE"].str[-4:] == YEAR]


def load_supports(station):
    """Supports of our 6 territories linked to the given installations, with decimal coordinates.
    The table has one row per support and per installation."""
    support = read_table("data", "sup_support",
                         ["SUP_ID", "STA_NM_ANFR", "NAT_ID", "SUP_NM_HAUT", "COM_CD_INSEE",
                          "COR_NB_DG_LAT", "COR_NB_MN_LAT", "COR_NB_SC_LAT", "COR_CD_NS_LAT",
                          "COR_NB_DG_LON", "COR_NB_MN_LON", "COR_NB_SC_LON", "COR_CD_EW_LON"])
    support["lat"] = to_decimal(support["COR_NB_DG_LAT"], support["COR_NB_MN_LAT"],
                                support["COR_NB_SC_LAT"], support["COR_CD_NS_LAT"])
    support["lon"] = to_decimal(support["COR_NB_DG_LON"], support["COR_NB_MN_LON"],
                                support["COR_NB_SC_LON"], support["COR_CD_EW_LON"])

    support["code"] = support["COM_CD_INSEE"].str[:3]      # territory = first 3 characters of the INSEE code
    support = support[support["code"].isin(list(TERRITORIES))]
    support = support[support["STA_NM_ANFR"].isin(station["STA_NM_ANFR"])]   # only the installations of YEAR
    return support.dropna(subset=["lat", "lon"])


def add_operator_and_nature(support, station):
    """Add the operator, the service date and the nature of each support."""
    exploitant = read_table("ref", "sup_exploitant", ["ADM_ID", "ADM_LB_NOM"])
    nature = read_table("ref", "sup_nature", ["NAT_ID", "NAT_LB_NOM"])
    return (support
            .merge(station, on="STA_NM_ANFR", how="left")
            .merge(exploitant, on="ADM_ID", how="left")
            .merge(nature, on="NAT_ID", how="left"))


def make_antenna_table(support):
    """One row per installation and support, with the antenna types as one text (e.g. "Panneau, Tube")."""
    antenne = read_table("data", "sup_antenne", ["STA_NM_ANFR", "SUP_ID", "TAE_ID"])
    antenne = antenne[antenne["STA_NM_ANFR"].isin(support["STA_NM_ANFR"])]   # our territories only
    antenne = antenne.merge(read_table("ref", "sup_type_antenne", ["TAE_ID", "TAE_LB"]), on="TAE_ID", how="left")
    antenne = antenne.dropna(subset=["TAE_LB"]).drop_duplicates(["STA_NM_ANFR", "SUP_ID", "TAE_LB"]).sort_values("TAE_LB")
    return antenne.groupby(["STA_NM_ANFR", "SUP_ID"])["TAE_LB"].agg(", ".join).reset_index(name="antennes")


def load_installations():
    """Return one row per (support, installation) with all the data needed for the maps."""
    station = load_stations()
    support = load_supports(station)
    installations = add_operator_and_nature(support, station)
    installations = installations.merge(make_antenna_table(support), on=["STA_NM_ANFR", "SUP_ID"], how="left")
    installations = installations.fillna("inconnu")   # missing values are shown as "inconnu"

    print("Installations:", len(installations), "| Supports:", installations["SUP_ID"].nunique())
    print("Operateur inconnu:", (installations["ADM_LB_NOM"] == "inconnu").sum())   # check: joins worked
    return installations


# ---------------------------------------------------------------------------
# PART 2 - MAPS: one interactive map per territory
# ---------------------------------------------------------------------------

def build_popup(sup_id, group):
    """Text of the popup of one support: its own data, then one block per installation on it."""
    first = group.iloc[0]
    text = f"<b>Support {sup_id}</b><br>Nature : {first['NAT_LB_NOM']}<br>Hauteur (m) : {first['SUP_NM_HAUT']}"
    for _, row in group.iterrows():
        text += (f"<hr>Opérateur : {row['ADM_LB_NOM']}"
                 f"<br>Antennes : {row['antennes']}"
                 f"<br>Mise en service : {row['DTE_EN_SERVICE']}")
    return text


def make_one_map(data):
    """Map of one territory, with one marker per support."""
    carte = folium.Map(tiles=BASEMAP, attr="Tiles © Esri")
    for sup_id, group in data.groupby("SUP_ID"):
        first = group.iloc[0]
        folium.CircleMarker([first["lat"], first["lon"]], radius=3,
                            popup=folium.Popup(build_popup(sup_id, group), max_width=300)).add_to(carte)
    carte.fit_bounds([[data["lat"].min(), data["lon"].min()],
                      [data["lat"].max(), data["lon"].max()]])
    return carte


def make_maps(installations):
    """Save one map per territory in site/cartes/."""
    for code, territory in TERRITORIES.items():
        data = installations[installations["code"] == code]
        print(territory["file"], ":", data["SUP_ID"].nunique(), "supports")
        path = f"{SITE}/cartes/carte_{territory['file']}.html"
        if data.empty:                                 # no support this year: a short message instead of a map
            with open(path, "w", encoding="utf-8") as file:
                file.write(f"<meta charset='UTF-8'><p>Aucun support mis en service en {YEAR} pour ce territoire.</p>")
        else:
            make_one_map(data).save(path)


# ---------------------------------------------------------------------------
# PART 3 - WEB PAGES: the same layout for every page, only the text changes
# ---------------------------------------------------------------------------

def team_names(t):
    """'A, B, C and D' in the language of the page."""
    names = [person["name"] for person in PEOPLE]
    return f"{', '.join(names[:-1])} {t['and']} {names[-1]}"


def header(t, page):
    """Top of the page: logo, menu and the two language flags."""
    sfx = t["suffix"]
    return f"""    <header class="entete">
        <input type="checkbox" id="toggle">
        <label for="toggle" class="burger">☰</label>
        <a href="index{sfx}.html" class="logo">{t['logo']}</a>

        <nav class="menu">
            <a href="index{sfx}.html" class="button">{t['home']}</a>
            <a href="carte{sfx}.html" class="button">{t['map']}</a>
            <a href="contact{sfx}.html" class="button">{t['contact_menu']}</a>
        </nav>

        <div class="langues">
            <a href="{page}.html"><img src="https://flagcdn.com/fr.svg" alt="{t['flag_fr_alt']}"></a>
            <a href="{page}_en.html"><img src="https://flagcdn.com/gb.svg" alt="{t['flag_en_alt']}"></a>
        </div>
    </header>"""


def footer(t):
    """Bottom of the page: links and copyright."""
    sfx = t["suffix"]
    return f"""    <footer class="pied-de-page">
        <nav>
            <ul>
                <li><a href="index{sfx}.html">{t['home']}</a></li>
                <li><a href="carte{sfx}.html">{t['map']}</a></li>
                <li><a href="contact{sfx}.html">{t['contact_footer']}</a></li>
                <li><a href="https://iutrouen.univ-rouen.fr/" target="_blank" rel="noopener">{t['iut']}</a></li>
            </ul>
        </nav>
        <p class="copyright">© 2026 {team_names(t)}.</p>
    </footer>"""


def index_body(t):
    paragraphs = "\n".join(f"            <p>{p}</p>" for p in t["index_paragraphs"])
    return f"""    <main>
        <h1 class="centre">{t['index_title']}</h1>
        <h2 class="centre">{t['by']} {team_names(t)}</h2>

        <section class="cadre">
            <img src="images/map.png" alt="{t['index_alt']}">
            <h2 class="centre">{t['index_explanation']}</h2>
            <h3>{t['index_h3']}</h3>
{paragraphs}
        </section>
    </main>"""


def map_body(t):
    buttons = "\n".join(
        f'        <a href="cartes/carte_{territory["file"]}.html" target="carte-affichee" class="button">{territory[t["lang"]]}</a>'
        for territory in TERRITORIES.values())
    first_file = list(TERRITORIES.values())[0]["file"]   # the first territory is shown when the page opens
    return f"""    <h1 class="centre">{t['map_title']}</h1>
    <p class="centre intro-carte">{t['map_intro']}</p>

    <nav class="choix-carte" aria-label="{t['map_nav']}">
{buttons}
    </nav>

    <iframe name="carte-affichee" src="cartes/carte_{first_file}.html" class="carte" title="{t['map_iframe']}"></iframe>"""


def contact_body(t):
    sections = ""
    for p in PEOPLE:
        sections += f"""        <section class="contact-personne">
            <h2>{p['name']}</h2>
            <ul>
                <li>{t['mail_label']} : <a href="mailto:{p['mail']}">{p['mail']}</a></li>
                <li>LinkedIn : <a href="{p['linkedin_url']}" target="_blank" rel="noopener">{p['linkedin_text']}</a></li>
                <li>GitHub : <a href="{p['github_url']}" target="_blank" rel="noopener">{p['github_text']}</a></li>
            </ul>
        </section>
"""
    return f"""    <div class="cadre">
        <h1 class="centre">{t['contact_title']}</h1>
        <p><strong>{t['contact_intro']}</strong></p>
{sections}    </div>"""


BODIES = {"index": index_body, "carte": map_body, "contact": contact_body}


def write_pages():
    """Write the 6 pages: index, carte and contact, in French and English."""
    for t in TEXTS.values():
        for page, make_body in BODIES.items():
            html = f"""<!DOCTYPE html>
<html lang="{t['lang']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Asap:wght@400;700&family=Plus+Jakarta+Sans:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
    <link rel="icon" type="image/svg+xml" href="images/logo.svg">
    <title>{t['titles'][page]}</title>
</head>
<body>
{header(t, page)}

{make_body(t)}

{footer(t)}
</body>
</html>
"""
            with open(f"{SITE}/{page}{t['suffix']}.html", "w", encoding="utf-8") as file:
                file.write(html)


# ---------------------------------------------------------------------------
# MAIN: the 4 steps of the program
# ---------------------------------------------------------------------------

def main():
    if not os.path.isdir("data") or not os.path.isdir("ref"):
        raise SystemExit("Folders 'data/' and 'ref/' not found: put the ANFR files there (see README.md).")
    os.makedirs(f"{SITE}/cartes", exist_ok=True)
    shutil.copytree(ASSETS, SITE, dirs_exist_ok=True)   # 1. style.css and images/
    make_maps(load_installations())                     # 2. read the data, 3. make the maps
    write_pages()                                       # 4. write the web pages
    print(f"Site ready: open {SITE}/index.html")


# ---------------------------------------------------------------------------
# TEXTS OF THE SITE (placed here so that the code above comes first)
# ---------------------------------------------------------------------------

# Team members (contact page, home page and footer)
PEOPLE = [
    {"name": "Jayms Bouyer", "mail": "Jayms.bouyer@gmail.com",
     "linkedin_url": "https://www.linkedin.com/in/jayms-bouyer-874059438/", "linkedin_text": "Jayms Bouyer",
     "github_url": "https://github.com/jayms314", "github_text": "www.github.com/jayms314"},
    {"name": "Maxence Dufourt", "mail": "dufmax95@gmail.com",
     "linkedin_url": "https://www.linkedin.com/in/maxence-dufourt-b21541379",
     "linkedin_text": "www.linkedin.com/in/maxence-dufourt-b21541379",
     "github_url": "https://github.com/MaxenceDufourt", "github_text": "www.github.com/MaxenceDufourt"},
    {"name": "Florian Adrast", "mail": "florian.adrast@univ-rouen.fr",
     "linkedin_url": "https://www.linkedin.com/in/florian-a-b43359451/", "linkedin_text": "Florian Adrast",
     "github_url": "https://github.com/florianadrast", "github_text": "Florian Adrast"},
    {"name": "Thomas Choulant", "mail": "tchoulant@gmail.com",
     "linkedin_url": "https://www.linkedin.com/in/thomas-choulant/",
     "linkedin_text": "www.linkedin.com/in/thomas-choulant/",
     "github_url": "https://github.com/Thomas-Ch-Dev", "github_text": "www.github.com/Thomas-Ch-Dev"},
]

# All the texts of the pages, one block per language
TEXTS = {
    "fr": {
        "lang": "fr",
        "suffix": "",                       # file names: index.html, carte.html, contact.html
        "logo": "SAÉ 15 : Traiter des données",
        "home": "Accueil", "map": "Carte Interactive",
        "contact_menu": "Contactez-nous", "contact_footer": "Contact",
        "iut": "IUT de Rouen – R&amp;T",
        "flag_fr_alt": "Français", "flag_en_alt": "Anglais",
        "by": "Par", "and": "et",
        "titles": {"index": "SAÉ 15 : Accueil", "carte": "SAÉ 15 : Carte Interactive",
                   "contact": "SAÉ 15 : Contact"},
        "index_title": "Présentation du projet",
        "index_alt": "Photo d'accueil Unsplash",
        "index_explanation": "Explication",
        "index_h3": "Projet SAE 15 : données ouvertes de l’ANFR.",
        "index_paragraphs": [
            "L’Agence nationale des fréquences (ANFR) coordonne l’implantation des stations radioélectriques en France et veille au respect des limites d’exposition du public aux champs électromagnétiques. Depuis 2015, elle publie en open data les données des stations de plus de 5 W (hors Défense, aviation civile et Intérieur).",
            "Notre objectif : à partir de ce jeu de données réel, caractériser les installations en France : répartition géographique, technologies et leur évolution, exploitants. Les résultats sont présentés sur une carte interactive.",
            "Outils : Python pour le traitement et la visualisation, Git/GitHub pour le versionnage et la programmation, Trello pour l’organisation.",
            "Livrables : dépôt GitHub (code commenté + README), bilan de l’étude, carte interactive.",
        ],
        "map_title": "Carte Interactive",
        "map_intro": "Choisissez un territoire pour afficher la carte des supports radioélectriques de l’ANFR. Cliquez sur un point pour voir ses détails.",
        "map_nav": "Choix du territoire",
        "map_iframe": "Carte interactive des supports radioélectriques du territoire choisi",
        "contact_title": "Contactez-nous",
        "contact_intro": "Vous trouverez ici toutes les informations concernant nos coordonnées.",
        "mail_label": "Adresse mail",
    },
    "en": {
        "lang": "en",
        "suffix": "_en",                    # file names: index_en.html, carte_en.html, contact_en.html
        "logo": "SAÉ 15: Processing data",
        "home": "Home", "map": "Interactive Map",
        "contact_menu": "Contact", "contact_footer": "Contact",
        "iut": "IUT Rouen – R&amp;T",
        "flag_fr_alt": "French", "flag_en_alt": "English",
        "by": "By", "and": "and",
        "titles": {"index": "SAÉ 15: Home", "carte": "SAÉ 15: Interactive Map",
                   "contact": "SAÉ 15: Contact"},
        "index_title": "Project Overview",
        "index_alt": "Unsplash homepage photo",
        "index_explanation": "Explanation",
        "index_h3": "SAE 15 Project: ANFR open data.",
        "index_paragraphs": [
            "The French National Frequency Agency (ANFR) coordinates the deployment of radio stations across France and ensures that public exposure to electromagnetic fields stays within legal limits. Since 2015, it has published open data on stations above 5 W (excluding the Ministry of Defence, civil aviation and the Ministry of the Interior).",
            "Our goal: using this real-world dataset, to characterize radio installations in France: geographic distribution, technologies and how they have evolved, and operators. The results are presented on an interactive map.",
            "Tools: Python for data processing and visualization, Git/GitHub for version control and coding, Trello for project organization.",
            "Deliverables: GitHub repository (commented code + README), study report, interactive map.",
        ],
        "map_title": "Interactive Map",
        "map_intro": "Choose a territory to display the map of ANFR radio supports. Click a point to see its details.",
        "map_nav": "Choose a territory",
        "map_iframe": "Interactive map of the radio supports of the selected territory",
        "contact_title": "Contact",
        "contact_intro": "Here you will find all our contact information.",
        "mail_label": "Mail",
    },
}


main()