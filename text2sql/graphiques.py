"""Choix automatique et construction des graphiques (Altair).

Règles de forme :
- une seule valeur              → indicateur (pas de graphique)
- temps + valeur                → courbe
- temps + catégorie + valeur    → une courbe par catégorie (8 maximum, le reste dans « Autres »)
- catégorie + valeur            → barres horizontales triées
Palette catégorielle validée (daltonisme, contraste) en clair et en sombre.
"""

import re
from dataclasses import dataclass

import altair as alt
import pandas as pd

PALETTE = {
    "clair": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "sombre": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
ENCRE = {"clair": ("#0b0b0b", "#52514e", "#e6e5e1"), "sombre": ("#f0efec", "#c3c2b7", "#33332f")}
# Formats français pour les nombres et les dates (d3-format / d3-time-format)
LOCALE_FR = {
    "number": {"decimal": ",", "thousands": "\u202f", "grouping": [3], "currency": ["", "\u00a0€"]},
    "time": {
        "dateTime": "%A %e %B %Y à %X", "date": "%d/%m/%Y", "time": "%H:%M:%S",
        "periods": ["AM", "PM"],
        "days": ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"],
        "shortDays": ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."],
        "months": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                   "septembre", "octobre", "novembre", "décembre"],
        "shortMonths": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
                        "sept.", "oct.", "nov.", "déc."],
    },
}
MAX_SERIES = 8
MAX_BARRES_ETIQUETEES = 15
NOMS_TEMPORELS = ("date", "jour", "semaine", "mois", "trimestre", "annee", "année",
                  "month", "year", "day", "week", "periode", "période")
MOTIF_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?")


@dataclass
class ChoixGraphique:
    """Type de graphique retenu et colonnes à utiliser."""
    type: str                 # "kpi", "ligne", "lignes" ou "barres"
    x: str | None = None
    y: str | None = None
    serie: str | None = None


# --- Détection ----------------------------------------------------------------

def est_temporelle(colonne: pd.Series) -> bool:
    """Vrai si la colonne ressemble à une dimension de temps (nom ou format de date)."""
    if any(mot in str(colonne.name).lower() for mot in NOMS_TEMPORELS):
        return True
    valeurs = colonne.dropna().astype(str)
    return not valeurs.empty and bool(valeurs.str.match(MOTIF_DATE).all())


def choisir_graphique(df: pd.DataFrame | None) -> ChoixGraphique | None:
    """Choisit la forme adaptée aux données, ou None si aucun graphique n'a de sens."""
    if df is None or df.empty:
        return None
    numeriques = list(df.select_dtypes("number").columns)
    if df.shape == (1, 1) and numeriques:
        return ChoixGraphique("kpi", y=df.columns[0])
    if len(df) < 2 or len(df.columns) < 2:
        return None
    dimensions = [c for c in df.columns if c not in numeriques]
    x = dimensions[0] if dimensions else df.columns[0]
    mesures = [c for c in numeriques if c != x]
    if not mesures:
        return None
    if not est_temporelle(df[x]):
        return ChoixGraphique("barres", x=x, y=mesures[0])
    autres_dimensions = [c for c in dimensions if c != x]
    if autres_dimensions:
        return ChoixGraphique("lignes", x=x, y=mesures[0], serie=autres_dimensions[0])
    return ChoixGraphique("ligne", x=x, y=mesures[0])


# --- Construction -------------------------------------------------------------

def _type_axe_temps(colonne: pd.Series) -> str:
    """Encodage Altair de l'axe des temps : temporel si dates ISO, ordinal sinon."""
    valeurs = colonne.dropna().astype(str)
    return "T" if bool(valeurs.str.match(MOTIF_DATE).all()) else "O"


def _preparer_temps(df: pd.DataFrame, x: str) -> tuple[pd.DataFrame, str]:
    """Convertit l'axe des temps en dates si possible et renvoie son type Altair."""
    type_x = _type_axe_temps(df[x])
    if type_x == "T":
        df = df.assign(**{x: pd.to_datetime(df[x].astype(str))})
    return df.sort_values(x), type_x


def regrouper_series(df: pd.DataFrame, serie: str, y: str, maximum: int = MAX_SERIES) -> pd.DataFrame:
    """Garde les `maximum - 1` séries les plus fortes et regroupe le reste dans « Autres »."""
    if df[serie].nunique() <= maximum:
        return df
    principales = df.groupby(serie)[y].sum().nlargest(maximum - 1).index
    df = df.assign(**{serie: df[serie].where(df[serie].isin(principales), "Autres")})
    return df.groupby([c for c in df.columns if c != y], as_index=False)[y].sum()


def _ordre_series(df: pd.DataFrame, serie: str, y: str) -> list:
    """Ordre stable des séries (par total décroissant, « Autres » en dernier)."""
    ordre = list(df.groupby(serie)[y].sum().sort_values(ascending=False).index)
    if "Autres" in ordre:
        ordre.remove("Autres")
        ordre.append("Autres")
    return ordre


def _infobulle(*colonnes: tuple[str, str]) -> list:
    """Champs d'infobulle avec format numérique lisible."""
    return [alt.Tooltip(f"{nom}:{t}", format=",.2f") if t == "Q" else alt.Tooltip(f"{nom}:{t}")
            for nom, t in colonnes]


def graphique_barres(df: pd.DataFrame, x: str, y: str, theme: str) -> alt.Chart:
    """Barres horizontales triées, fines, bout arrondi, valeur en bout de barre."""
    couleur, (_, encre_2, _) = PALETTE[theme][0], ENCRE[theme]
    hauteur = max(120, 28 * len(df))
    base = alt.Chart(df).encode(
        y=alt.Y(f"{x}:N", sort="-x", title=None),
        x=alt.X(f"{y}:Q", title=y.replace("_", " ")),
        tooltip=_infobulle((x, "N"), (y, "Q")),
    )
    barres = base.mark_bar(color=couleur, size=18, cornerRadiusEnd=4)
    if len(df) > MAX_BARRES_ETIQUETEES:
        return barres.properties(height=hauteur)
    valeurs = base.mark_text(align="left", dx=6, color=encre_2).encode(
        text=alt.Text(f"{y}:Q", format=",.0f"))
    return (barres + valeurs).properties(height=hauteur)


def graphique_lignes(df: pd.DataFrame, x: str, y: str, theme: str, serie: str | None = None) -> alt.Chart:
    """Courbe(s) de 2 px avec points, réticule et infobulle au survol."""
    df, type_x = _preparer_temps(df, x)
    palette = PALETTE[theme]
    survol = alt.selection_point(fields=[x], nearest=True, on="pointerover", empty=False)
    champs = [(x, type_x)] + ([(serie, "N")] if serie else []) + [(y, "Q")]
    encodage = {"x": alt.X(f"{x}:{type_x}", title=None), "y": alt.Y(f"{y}:Q", title=y.replace("_", " "))}
    if serie:
        df = regrouper_series(df, serie, y)
        ordre = _ordre_series(df, serie, y)
        encodage["color"] = alt.Color(f"{serie}:N", sort=ordre, title=serie.replace("_", " "),
                                      scale=alt.Scale(domain=ordre, range=palette[:len(ordre)]))
    else:
        encodage["color"] = alt.value(palette[0])
    base = alt.Chart(df).encode(**encodage)
    lignes = base.mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round")
    points = base.mark_point(filled=True, size=64).encode(
        opacity=alt.condition(survol, alt.value(1), alt.value(0)), tooltip=_infobulle(*champs))
    reticule = alt.Chart(df).mark_rule(color=ENCRE[theme][1], strokeWidth=1).encode(
        x=f"{x}:{type_x}", opacity=alt.condition(survol, alt.value(0.5), alt.value(0)),
    ).add_params(survol)
    return (lignes + points + reticule).properties(height=320)


def appliquer_style(graphique: alt.Chart, theme: str) -> alt.Chart:
    """Axes et grille discrets, texte dans les couleurs d'encre (jamais celle des données)."""
    encre_1, encre_2, grille = ENCRE[theme]
    return (graphique
            .configure(background="transparent", font="sans-serif", locale=LOCALE_FR)
            .configure_view(stroke=None)
            .configure_axis(gridColor=grille, gridWidth=1, domainColor=grille, tickColor=grille,
                            labelColor=encre_2, titleColor=encre_2, labelFontSize=12, titleFontWeight="normal")
            .configure_legend(labelColor=encre_1, titleColor=encre_2, orient="bottom", columns=4, symbolType="stroke",
                              symbolStrokeWidth=2)
            .configure_axisY(labelLimit=220))


def construire_graphique(df: pd.DataFrame, choix: ChoixGraphique, theme: str = "clair") -> alt.Chart:
    """Construit le graphique Altair correspondant au choix."""
    if choix.type == "barres":
        graphique = graphique_barres(df, choix.x, choix.y, theme)
    else:
        graphique = graphique_lignes(df, choix.x, choix.y, theme, serie=choix.serie)
    return appliquer_style(graphique, theme)
