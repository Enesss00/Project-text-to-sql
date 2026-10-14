"""Génère une base SQLite de démonstration (commerce de détail) avec Faker.

Usage : python seed_db.py [chemin_db]   (par défaut : retail.db)
"""

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

# Paramètres de génération
DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("retail.db")
NB_MAGASINS = 10
NB_PRODUITS = 100
NB_CLIENTS = 500
NB_VENTES = 20_000
DEBUT = date(2025, 1, 1)  # 12 mois : janvier à décembre 2025
FIN = date(2025, 12, 31)
SEED = 42

# Villes des magasins avec leur région
VILLES = [
    ("Paris", "Île-de-France"), ("Versailles", "Île-de-France"),
    ("Lyon", "Auvergne-Rhône-Alpes"), ("Grenoble", "Auvergne-Rhône-Alpes"),
    ("Marseille", "Provence-Alpes-Côte d'Azur"), ("Nice", "Provence-Alpes-Côte d'Azur"),
    ("Bordeaux", "Nouvelle-Aquitaine"), ("Toulouse", "Occitanie"),
    ("Lille", "Hauts-de-France"), ("Nantes", "Pays de la Loire"),
]

# Catégories : (noms de base, fourchette de prix en euros)
CATEGORIES = {
    "Électronique": (["Casque audio", "Enceinte", "Chargeur", "Souris", "Clavier", "Écouteurs"], (15, 250)),
    "Maison": (["Lampe", "Coussin", "Vase", "Plaid", "Bougie", "Cadre photo"], (8, 90)),
    "Vêtements": (["T-shirt", "Pull", "Jean", "Veste", "Écharpe", "Chemise"], (12, 120)),
    "Alimentation": (["Café", "Thé", "Chocolat", "Miel", "Biscuits", "Confiture"], (2, 25)),
    "Sport": (["Ballon", "Tapis de yoga", "Gourde", "Haltères", "Raquette", "Sac de sport"], (10, 150)),
    "Beauté": (["Crème", "Parfum", "Shampoing", "Savon", "Rouge à lèvres", "Sérum"], (5, 80)),
}
ADJECTIFS = ["Classique", "Premium", "Eco", "Pro", "Mini", "Confort", "Essentiel", "Deluxe"]

# Saisonnalité : poids relatif des ventes par mois (pic en novembre/décembre)
POIDS_MOIS = {1: 0.8, 2: 0.75, 3: 0.9, 4: 0.95, 5: 1.0, 6: 1.05,
              7: 1.1, 8: 0.85, 9: 1.0, 10: 1.05, 11: 1.3, 12: 1.6}

SCHEMA = """
CREATE TABLE magasins (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL,
    ville TEXT NOT NULL,
    region TEXT NOT NULL
);
CREATE TABLE produits (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL,
    categorie TEXT NOT NULL,
    prix REAL NOT NULL
);
CREATE TABLE clients (
    id INTEGER PRIMARY KEY,
    ville TEXT NOT NULL,
    date_inscription TEXT NOT NULL  -- format YYYY-MM-DD
);
CREATE TABLE ventes (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,              -- format YYYY-MM-DD
    magasin_id INTEGER NOT NULL REFERENCES magasins(id),
    produit_id INTEGER NOT NULL REFERENCES produits(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    quantite INTEGER NOT NULL,
    montant REAL NOT NULL            -- quantite * prix, en euros
);
CREATE INDEX idx_ventes_date ON ventes(date);
"""


def generer_magasins():
    """Un magasin par ville, avec un nom d'enseigne."""
    return [(i, f"Boutique {ville}", ville, region) for i, (ville, region) in enumerate(VILLES, start=1)]


def generer_produits():
    """Produits répartis dans les catégories, prix tirés dans la fourchette de la catégorie."""
    produits, noms_vus = [], set()
    categories = list(CATEGORIES)
    while len(produits) < NB_PRODUITS:
        categorie = categories[len(produits) % len(categories)]
        bases, (prix_min, prix_max) = CATEGORIES[categorie]
        nom = f"{random.choice(bases)} {random.choice(ADJECTIFS)}"
        if nom in noms_vus:
            continue
        noms_vus.add(nom)
        prix = round(random.uniform(prix_min, prix_max), 2)
        produits.append((len(produits) + 1, nom, categorie, prix))
    return produits


def generer_clients(fake):
    """Clients majoritairement situés dans les villes des magasins."""
    villes = [v for v, _ in VILLES]
    clients = []
    for i in range(1, NB_CLIENTS + 1):
        ville = random.choice(villes) if random.random() < 0.8 else fake.city()
        inscription = fake.date_between(start_date=date(2021, 1, 1), end_date=FIN)
        clients.append((i, ville, inscription.isoformat()))
    return clients


def tirer_dates(n):
    """Tire n dates sur la période, pondérées par la saisonnalité et le week-end."""
    jours = [DEBUT + timedelta(days=d) for d in range((FIN - DEBUT).days + 1)]
    poids = [POIDS_MOIS[j.month] * (1.3 if j.weekday() >= 5 else 1.0) for j in jours]
    return random.choices(jours, weights=poids, k=n)


def generer_ventes(magasins, produits, clients):
    """Ventes : les grands magasins et les produits populaires pèsent davantage."""
    poids_magasins = [random.uniform(0.5, 2.0) for _ in magasins]
    poids_produits = [random.paretovariate(1.5) for _ in produits]
    dates = sorted(tirer_dates(NB_VENTES))
    ventes = []
    for i, jour in enumerate(dates, start=1):
        magasin = random.choices(magasins, weights=poids_magasins)[0]
        produit = random.choices(produits, weights=poids_produits)[0]
        client = random.choice(clients)
        quantite = random.choices([1, 2, 3, 4, 5], weights=[60, 22, 10, 5, 3])[0]
        montant = round(quantite * produit[3], 2)
        ventes.append((i, jour.isoformat(), magasin[0], produit[0], client[0], quantite, montant))
    return ventes


def main():
    random.seed(SEED)
    Faker.seed(SEED)
    fake = Faker("fr_FR")

    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    magasins = generer_magasins()
    produits = generer_produits()
    clients = generer_clients(fake)
    ventes = generer_ventes(magasins, produits, clients)

    conn.executemany("INSERT INTO magasins VALUES (?, ?, ?, ?)", magasins)
    conn.executemany("INSERT INTO produits VALUES (?, ?, ?, ?)", produits)
    conn.executemany("INSERT INTO clients VALUES (?, ?, ?)", clients)
    conn.executemany("INSERT INTO ventes VALUES (?, ?, ?, ?, ?, ?, ?)", ventes)
    conn.commit()
    conn.close()

    print(f"Base créée : {DB_PATH} — {len(magasins)} magasins, {len(produits)} produits, "
          f"{len(clients)} clients, {len(ventes)} ventes ({DEBUT} → {FIN})")


if __name__ == "__main__":
    main()
