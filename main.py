import os
import shutil
import folium
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------

SITE = "site"             # output folder created by the program
RESOURCES = "ressources"  # files copied as they are (style.css, images/)

# Satellite background of the maps (the default OpenStreetMap tiles are blocked when the HTML is opened by double-click)
BASEMAP = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

YEAR = "2025"             # we only keep the installations put into service this year
CHART_COLOR = "#1F3A68"   # color of the bars

# The 6 territories. The key is the start of the INSEE code of the commune.
TERRITORIES = {
    "974": {"file": "reunion", "fr": "La Réunion", "en": "Réunion Island"},
    "971": {"file": "guadeloupe", "fr": "Guadeloupe", "en": "Guadeloupe"},
    "972": {"file": "martinique", "fr": "Martinique", "en": "Martinique"},
    "973": {"file": "guyane", "fr": "Guyane", "en": "French Guiana"},
    "976": {"file": "mayotte", "fr": "Mayotte", "en": "Mayotte"},
    "988": {"file": "nouvelle_caledonie", "fr": "Nouvelle-Calédonie", "en": "New Caledonia"},
}


# ---------------------------------------------------------------------------
# PART 1 - DATA: read the ANFR files and build one table
# ---------------------------------------------------------------------------

def read_table(folder, name, columns):
    """Read one ANFR file, keeping only the columns we need.
    The ID columns are read as text so that all tables can be joined."""
    return pd.read_csv(f"{folder}/{name}.txt", sep=";", encoding="utf-8",
                       usecols=columns, dtype={"STA_NM_ANFR": str, "COM_CD_INSEE": str})


def to_decimal(degrees, minutes, seconds, direction):
    """Convert degrees/minutes/seconds to decimal degrees (South and West are negative)."""
    value = degrees + minutes / 60 + seconds / 3600
    return value.where(~direction.isin(["S", "W"]), -value)


def load_stations():
    """Keep the installations put into service in YEAR (dates look like 04/09/2009)."""
    stations = read_table("data", "sup_station", ["STA_NM_ANFR", "ADM_ID", "DTE_EN_SERVICE"])
    return stations[stations["DTE_EN_SERVICE"].str[-4:] == YEAR]


def load_supports(stations):
    """Keep the supports of our 6 territories that carry these installations, and add decimal coordinates."""
    supports = read_table("data", "sup_support",
                          ["SUP_ID", "STA_NM_ANFR", "NAT_ID", "SUP_NM_HAUT", "COM_CD_INSEE",
                           "COR_NB_DG_LAT", "COR_NB_MN_LAT", "COR_NB_SC_LAT", "COR_CD_NS_LAT",
                           "COR_NB_DG_LON", "COR_NB_MN_LON", "COR_NB_SC_LON", "COR_CD_EW_LON"])
    supports["lat"] = to_decimal(supports["COR_NB_DG_LAT"], supports["COR_NB_MN_LAT"],
                                 supports["COR_NB_SC_LAT"], supports["COR_CD_NS_LAT"])
    supports["lon"] = to_decimal(supports["COR_NB_DG_LON"], supports["COR_NB_MN_LON"],
                                 supports["COR_NB_SC_LON"], supports["COR_CD_EW_LON"])

    supports["code"] = supports["COM_CD_INSEE"].str[:3]                          # territory code
    supports = supports[supports["code"].isin(list(TERRITORIES))]                # our 6 territories only
    supports = supports[supports["STA_NM_ANFR"].isin(stations["STA_NM_ANFR"])]   # installations of YEAR only
    return supports.dropna(subset=["lat", "lon"])                                # no coordinates = removed


def add_operator_and_nature(supports, stations):
    """Add the operator, the service date and the nature of each support."""
    operators = read_table("ref", "sup_exploitant", ["ADM_ID", "ADM_LB_NOM"])
    natures = read_table("ref", "sup_nature", ["NAT_ID", "NAT_LB_NOM"])
    return (supports
            .merge(stations, on="STA_NM_ANFR", how="left")
            .merge(operators, on="ADM_ID", how="left")
            .merge(natures, on="NAT_ID", how="left"))


def make_antenna_table(supports):
    """One row per installation and support, with the antenna types in one text (e.g. "Panneau, Tube")."""
    antennas = read_table("data", "sup_antenne", ["STA_NM_ANFR", "SUP_ID", "TAE_ID"])
    antennas = antennas[antennas["STA_NM_ANFR"].isin(supports["STA_NM_ANFR"])]   # our installations only
    antenna_types = read_table("ref", "sup_type_antenne", ["TAE_ID", "TAE_LB"])
    antennas = antennas.merge(antenna_types, on="TAE_ID", how="left")
    antennas = antennas.dropna(subset=["TAE_LB"])                                # remove unknown types
    antennas = antennas.drop_duplicates(["STA_NM_ANFR", "SUP_ID", "TAE_LB"])     # each type only once
    antennas = antennas.sort_values("TAE_LB")                                    # alphabetical order
    return antennas.groupby(["STA_NM_ANFR", "SUP_ID"])["TAE_LB"].agg(", ".join).reset_index(name="antennas")


def load_installations():
    """Return one row per (support, installation) with all the data needed for the maps and the chart."""
    stations = load_stations()
    supports = load_supports(stations)
    installations = add_operator_and_nature(supports, stations)
    installations = installations.merge(make_antenna_table(supports), on=["STA_NM_ANFR", "SUP_ID"], how="left")
    installations = installations.fillna("inconnu")   # missing values are shown as "inconnu"

    print("Installations:", len(installations), "| Supports:", installations["SUP_ID"].nunique())
    print("Operateur inconnu:", (installations["ADM_LB_NOM"] == "inconnu").sum())   # check: the joins worked
    return installations


# ---------------------------------------------------------------------------
# PART 2 - MAPS: one interactive map per territory
# ---------------------------------------------------------------------------

def build_popup(first, group):
    """Popup text of one support: its own data, then one block per installation.
    "group" = rows of this support, "first" = its first row."""
    text = f"<b>Support {first['SUP_ID']}</b><br>Nature : {first['NAT_LB_NOM']}<br>Hauteur (m) : {first['SUP_NM_HAUT']}"
    for _, row in group.iterrows():
        text += (f"<hr>Opérateur : {row['ADM_LB_NOM']}"
                 f"<br>Antennes : {row['antennas']}"
                 f"<br>Mise en service : {row['DTE_EN_SERVICE']}")
    return text


def make_one_map(territory_data):
    """Build the map of one territory: one marker per support."""
    territory_map = folium.Map(tiles=BASEMAP, attr="Tiles © Esri")
    for _, group in territory_data.groupby("SUP_ID"):
        first = group.iloc[0]
        popup = folium.Popup(build_popup(first, group), max_width=300)
        folium.CircleMarker([first["lat"], first["lon"]], radius=3, popup=popup).add_to(territory_map)
    territory_map.fit_bounds([[territory_data["lat"].min(), territory_data["lon"].min()],
                              [territory_data["lat"].max(), territory_data["lon"].max()]])   # zoom on all markers
    return territory_map


def make_maps(installations):
    """Save one map per territory in site/cartes/."""
    for code, territory in TERRITORIES.items():
        territory_data = installations[installations["code"] == code]
        print(territory["file"], ":", territory_data["SUP_ID"].nunique(), "supports")
        path = f"{SITE}/cartes/carte_{territory['file']}.html"
        if territory_data.empty:   # no support this year: write a message instead of a map
            with open(path, "w", encoding="utf-8") as file:
                file.write(f"<meta charset='UTF-8'><p>Aucun support mis en service en {YEAR} pour ce territoire.</p>")
        else:
            make_one_map(territory_data).save(path)


# ---------------------------------------------------------------------------
# PART 3 - CHART: number of supports per territory (opens in its own window)
# ---------------------------------------------------------------------------

def show_chart(installations):
    """Show a bar chart in a separate window (not on the website). Same data as the maps."""
    # Count the different supports of each territory (one support can have several rows)
    counts = installations.groupby("code")["SUP_ID"].nunique()
    counts = counts.reindex(list(TERRITORIES), fill_value=0)   # territories with 0 support are shown too
    counts.index = [TERRITORIES[code]["fr"] for code in counts.index]
    counts = counts.sort_values(ascending=False)

    ax = counts.plot(kind="bar", color=CHART_COLOR, figsize=(8, 4))
    ax.bar_label(ax.containers[0])                              # number on top of each bar
    plt.title(f"Supports mis en service en {YEAR}")
    plt.ylabel("Nombre de supports")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.show()                                                  # waits until the window is closed


# ---------------------------------------------------------------------------
# PART 4 - WEB SITE: same layout for every page, only the texts change
# ---------------------------------------------------------------------------

def team_names(t):
    """Team names as "A, B, C and D" (in the language of the page)."""
    names = [person["name"] for person in PEOPLE]
    return f"{', '.join(names[:-1])} {t['and']} {names[-1]}"


def header(t, page):
    """Top of the page: logo, menu and the two language flags."""
    suffix = t["suffix"]
    return f"""    <header class="entete">
        <input type="checkbox" id="toggle">
        <label for="toggle" class="burger">☰</label>
        <a href="index{suffix}.html" class="logo">{t['logo']}</a>

        <nav class="menu">
            <a href="index{suffix}.html" class="button">{t['home']}</a>
            <a href="carte{suffix}.html" class="button">{t['map']}</a>
            <a href="contact{suffix}.html" class="button">{t['contact_menu']}</a>
        </nav>

        <div class="langues">
            <a href="{page}.html"><img src="https://flagcdn.com/fr.svg" alt="{t['flag_fr_alt']}"></a>
            <a href="{page}_en.html"><img src="https://flagcdn.com/gb.svg" alt="{t['flag_en_alt']}"></a>
        </div>
    </header>"""


def footer(t):
    """Bottom of the page: links and copyright."""
    suffix = t["suffix"]
    return f"""    <footer class="pied-de-page">
        <nav>
            <ul>
                <li><a href="index{suffix}.html">{t['home']}</a></li>
                <li><a href="carte{suffix}.html">{t['map']}</a></li>
                <li><a href="contact{suffix}.html">{t['contact_footer']}</a></li>
                <li><a href="https://iutrouen.univ-rouen.fr/" target="_blank" rel="noopener">{t['iut']}</a></li>
            </ul>
        </nav>
        <p class="copyright">© 2026 {team_names(t)}.</p>
    </footer>"""


def index_body(t):
    """Content of the home page."""
    paragraphs = "\n".join(f"            <p>{paragraph}</p>" for paragraph in t["index_paragraphs"])
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
    """Content of the map page: one button per territory and a frame that shows the chosen map."""
    buttons = "\n".join(
        f'        <a href="cartes/carte_{territory["file"]}.html" target="carte-affichee" class="button">{territory[t["lang"]]}</a>'
        for territory in TERRITORIES.values())
    first_file = list(TERRITORIES.values())[0]["file"]   # first territory = shown when the page opens
    return f"""    <h1 class="centre">{t['map_title']}</h1>
    <p class="centre intro-carte">{t['map_intro']}</p>

    <nav class="choix-carte" aria-label="{t['map_nav']}">
{buttons}
    </nav>

    <iframe name="carte-affichee" src="cartes/carte_{first_file}.html" class="carte" title="{t['map_iframe']}"></iframe>"""


def contact_body(t):
    """Content of the contact page: one block per team member."""
    sections = ""
    for person in PEOPLE:
        sections += f"""        <section class="contact-personne">
            <h2>{person['name']}</h2>
            <ul>
                <li>{t['mail_label']} : <a href="mailto:{person['mail']}">{person['mail']}</a></li>
                <li>LinkedIn : <a href="{person['linkedin_url']}" target="_blank" rel="noopener">{person['linkedin_text']}</a></li>
                <li>GitHub : <a href="{person['github_url']}" target="_blank" rel="noopener">{person['github_text']}</a></li>
            </ul>
        </section>
"""
    return f"""    <div class="cadre">
        <h1 class="centre">{t['contact_title']}</h1>
        <p><strong>{t['contact_intro']}</strong></p>
{sections}    </div>"""


BODIES = {"index": index_body, "carte": map_body, "contact": contact_body}


def write_pages():
    """Write the 6 pages (index, carte, contact) in French and English."""
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


# Team members (used in the contact page, the home page and the footer)
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
        "suffix": "",                       # files: index.html, carte.html, contact.html
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
        "suffix": "_en",                    # files: index_en.html, carte_en.html, contact_en.html
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


# ---------------------------------------------------------------------------
# MAIN: the steps of the program
# ---------------------------------------------------------------------------

def main():
    if not os.path.isdir("data") or not os.path.isdir("ref"):
        raise SystemExit("Folders 'data/' and 'ref/' not found: put the ANFR files there (see README.md).")
    os.makedirs(f"{SITE}/cartes", exist_ok=True)
    shutil.copytree(RESOURCES, SITE, dirs_exist_ok=True)   # 1. copy style.css and images/
    installations = load_installations()                   # 2. read the data (only once)
    make_maps(installations)                               # 3. make the maps
    write_pages()                                          # 4. write the web pages
    print(f"Site ready: open {SITE}/index.html")
    show_chart(installations)                              # 5. chart, last because the window blocks the program


main()