# SAÉ 15 : Traiter des données — Supports antenne radio de l'ANFR

Génération automatique d'un site web bilingue (français / anglais) présentant des **cartes interactives** des supports radioélectriques mis en service en **2025** dans les territoires d'outre-mer français, à partir des données ouvertes de l'[ANFR](https://www.anfr.fr/) (Agence nationale des fréquences).

Projet réalisé dans le cadre de la SAÉ 15 à l'IUT de Rouen (département Réseaux & Télécommunications).

## Sommaire

- [Présentation](#présentation)
- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Données à fournir](#données-à-fournir)
- [Utilisation](#utilisation)
- [Structure du projet](#structure-du-projet)
- [Fonctionnement du programme](#fonctionnement-du-programme)
- [Configuration](#configuration)
- [Équipe](#équipe)

## Présentation

L'ANFR coordonne l'implantation des stations radioélectriques en France et veille au respect des limites d'exposition du public aux champs électromagnétiques. Depuis 2015, elle publie en open data les données des stations de plus de 5 W (hors Défense, aviation civile et Intérieur).

À partir de ce jeu de données réel, notre programme Python :

1. lit et croise plusieurs fichiers de l'ANFR (stations, supports, antennes, exploitants, natures de support) ;
2. ne conserve que les installations mises en service pendant l'année choisie ;
3. produit une carte interactive par territoire ;
4. génère un site web statique complet qui les présente.

## Fonctionnalités

- Lecture et jointure des tables ANFR avec **pandas**
- Conversion des coordonnées degrés / minutes / secondes en degrés décimaux
- Une carte satellite interactive par territoire avec **folium** : un marqueur par support, et au clic une fenêtre indiquant la nature, la hauteur, l'opérateur, les types d'antennes et la date de mise en service
- Site web statique de 3 pages (accueil, carte, contact) en **français et en anglais**
- Menu responsive et sélecteur de langue par drapeaux
- Le site généré s'ouvre par simple double-clic, sans serveur web

### Territoires couverts

| Code INSEE | Territoire |
|-----------|------------|
| 971 | Guadeloupe |
| 972 | Martinique |
| 973 | Guyane |
| 974 | La Réunion |
| 976 | Mayotte |
| 988 | Nouvelle-Calédonie |

## Prérequis

- [Python](https://www.python.org/) 3.8 ou supérieur
- Les bibliothèques Python `pandas`,`folium` et `Matplotlib`
- Une connexion Internet à l'ouverture du site : fond de carte satellite Esri, polices Google Fonts et drapeaux (flagcdn)

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/<votre-organisation>/<nom-du-depot>.git
cd <nom-du-depot>

# Installer les dépendances
pip install pandas
pip install folium
pip install matplotlib
## Données à fournir

Les fichiers de l'ANFR ne sont pas inclus dans le dépôt. Il faut les télécharger depuis le portail open data de l'ANFR et les placer dans deux dossiers à la racine du projet :

```
data/
├── sup_station.txt
├── sup_support.txt
└── sup_antenne.txt

ref/
├── sup_exploitant.txt
├── sup_nature.txt
└── sup_type_antenne.txt
```

Les fichiers sont au format texte, séparés par des points-virgules (`;`) et encodés en UTF-8. Si les dossiers `data/` ou `ref/` sont absents, le programme s'arrête avec un message d'erreur.

## Utilisation

```bash
python main.py
Cela va ouvrir le graphique. Ensuite,
il faudra taper site/index.html dans le terminal pour ouvrir le site avec les différentes cartes interactives.


## Structure du projet

```
.
├── main.py              # Programme principal (données, cartes, pages web)
├── assets/              # Fichiers fixes copiés tels quels dans le site
│   ├── style.css
│   └── images/          # map.png, logo.svg…
├── data/                # Fichiers ANFR (à fournir)
├── ref/                 # Tables de référence ANFR (à fournir)
└── site/                # Site généré par le programme
    ├── index.html       # Accueil (FR)
    ├── carte.html       # Carte interactive (FR)
    ├── contact.html     # Contact (FR)
    ├── index_en.html    # Accueil (EN)
    ├── carte_en.html    # Carte interactive (EN)
    ├── contact_en.html  # Contact (EN)
    ├── style.css
    ├── images/
    └── cartes/
        └── carte_<territoire>.html   # Une carte par territoire
```

Le dossier `site/` est régénéré à chaque exécution : ne modifiez pas ses fichiers à la main, modifiez plutôt `assets/` ou le programme.

## Fonctionnement du programme

Le script est organisé en trois parties, appelées dans cet ordre par `main()` :

1. **Données** : `load_installations()` lit les fichiers ANFR et construit un tableau avec une ligne par couple (support, installation), en joignant stations, supports, exploitants, natures et types d'antennes. Les valeurs manquantes sont affichées « inconnu ».
2. **Cartes** : `make_maps()` génère une carte par territoire dans `site/cartes/`. Si aucun support n'a été mis en service dans l'année pour un territoire, un court message remplace la carte.
3. **Pages web** : `write_pages()` écrit les 6 pages HTML à partir d'une mise en page commune (en-tête, pied de page) et de textes séparés par langue.

## Configuration

Les principaux paramètres se trouvent en haut du script :

| Variable | Rôle | Valeur par défaut |
|----------|------|-------------------|
| `YEAR` | Année de mise en service des installations conservées | `"2025"` |
| `TERRITORIES` | Territoires traités (code INSEE, nom de fichier, noms FR/EN) | 6 territoires d'outre-mer |
| `BASEMAP` | Fond de carte satellite (Esri) | World Imagery |
| `SITE` / `ASSETS` | Dossier de sortie / dossier des fichiers fixes | `site` / `assets` |

Les textes du site (pages FR et EN) et les coordonnées de l'équipe sont regroupés en bas du script, dans `TEXTS` et `PEOPLE`.

Le fond de carte OpenStreetMap par défaut n'est pas utilisé, car ses tuiles sont bloquées lorsque le fichier HTML est ouvert par double-clic.

## Équipe

| Nom | GitHub |
|-----|--------|
| Jayms Bouyer | [@jayms314](https://github.com/jayms314) |
| Maxence Dufourt | [@MaxenceDufourt](https://github.com/MaxenceDufourt) |
| Florian Adrast | [@florianadrast](https://github.com/florianadrast) |
| Thomas Choulant | [@Thomas-Ch-Dev](https://github.com/Thomas-Ch-Dev) |

Projet encadré dans le cadre du BUT R&T de l'[IUT de Rouen](https://iutrouen.univ-rouen.fr/).

## Source des données

Données ouvertes de l'[Agence nationale des fréquences (ANFR)](https://www.anfr.fr/) sur les stations radioélectriques de plus de 5 W.
