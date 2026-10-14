"""Génère une base SQLite bancaire fictive (banque de détail) avec Faker.

Usage : python seed_banque.py [chemin_db]   (par défaut : banque.db)
Toutes les données sont inventées : aucun lien avec une banque ou un client réels.
"""

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

DB_PATH = Path(__file__).resolve().parent / "banque.db"
NB_CLIENTS = 3_000
NB_TRANSACTIONS = 30_000
DEBUT, FIN = date(2025, 1, 1), date(2025, 12, 31)
SEED = 7

AGENCES = [
    ("Paris Opéra", "Paris", "Île-de-France"), ("Paris La Défense", "Puteaux", "Île-de-France"),
    ("Versailles", "Versailles", "Île-de-France"), ("Lyon Part-Dieu", "Lyon", "Auvergne-Rhône-Alpes"),
    ("Grenoble", "Grenoble", "Auvergne-Rhône-Alpes"), ("Marseille Prado", "Marseille", "Provence-Alpes-Côte d'Azur"),
    ("Nice", "Nice", "Provence-Alpes-Côte d'Azur"), ("Bordeaux", "Bordeaux", "Nouvelle-Aquitaine"),
    ("Toulouse Capitole", "Toulouse", "Occitanie"), ("Lille", "Lille", "Hauts-de-France"),
    ("Nantes", "Nantes", "Pays de la Loire"), ("Strasbourg", "Strasbourg", "Grand Est"),
]

# Segment : (poids, revenu annuel min-max, probabilité d'avoir un crédit)
SEGMENTS = {
    "Particulier": (70, (18_000, 65_000), 0.45),
    "Professionnel": (15, (30_000, 150_000), 0.60),
    "Entreprise": (8, (200_000, 5_000_000), 0.70),
    "Banque privée": (7, (150_000, 800_000), 0.50),
}

# Type de compte : (épargne ?, solde min-max)
TYPES_COMPTES = {
    "Compte courant": (False, (-500, 12_000)),
    "Livret A": (True, (100, 22_950)),
    "LDDS": (True, (50, 12_000)),
    "PEL": (True, (500, 61_200)),
    "Assurance-vie": (True, (2_000, 250_000)),
    "Compte à terme": (True, (5_000, 150_000)),
}

# Type de crédit : (montant min-max, durée en mois, taux min-max en %)
TYPES_CREDITS = {
    "Immobilier": ((80_000, 450_000), (180, 240, 300), (2.9, 4.1)),
    "Consommation": ((2_000, 35_000), (24, 48, 60), (4.5, 8.9)),
    "Auto": ((8_000, 45_000), (36, 48, 60, 72), (3.9, 6.9)),
    "Professionnel": ((20_000, 600_000), (36, 60, 84), (3.5, 6.5)),
}

POIDS_MOIS = {1: 0.9, 2: 0.9, 3: 1.05, 4: 1.0, 5: 1.0, 6: 1.1, 7: 0.95, 8: 0.7, 9: 1.1, 10: 1.05, 11: 1.0, 12: 1.15}

SCHEMA = """
CREATE TABLE agences (
    id INTEGER PRIMARY KEY, nom TEXT NOT NULL, ville TEXT NOT NULL, region TEXT NOT NULL
);
CREATE TABLE clients (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL,                -- donnée personnelle (colonne protégée)
    date_naissance TEXT,              -- donnée personnelle (colonne protégée)
    segment TEXT NOT NULL,
    agence_id INTEGER NOT NULL REFERENCES agences(id),
    date_entree TEXT NOT NULL,        -- format YYYY-MM-DD
    revenu_annuel REAL NOT NULL       -- en euros
);
CREATE TABLE comptes (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    type TEXT NOT NULL,
    iban TEXT NOT NULL,               -- donnée sensible (colonne protégée)
    date_ouverture TEXT NOT NULL,
    solde REAL NOT NULL               -- en euros, au 31/12/2025
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    compte_id INTEGER NOT NULL REFERENCES comptes(id),
    date TEXT NOT NULL,
    montant REAL NOT NULL,            -- positif = entrée, négatif = sortie
    categorie TEXT NOT NULL
);
CREATE TABLE credits (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    type TEXT NOT NULL,
    montant_initial REAL NOT NULL,
    encours REAL NOT NULL,            -- capital restant dû au 31/12/2025
    taux REAL NOT NULL,               -- taux nominal annuel en %
    duree_mois INTEGER NOT NULL,
    date_octroi TEXT NOT NULL,
    statut TEXT NOT NULL              -- 'Sain', 'Retard < 90 j' ou 'Défaut'
);
CREATE INDEX idx_transactions_date ON transactions(date);
"""


def jour_aleatoire(debut: date, fin: date) -> date:
    return debut + timedelta(days=random.randint(0, (fin - debut).days))


def jour_pondere() -> date:
    """Un jour de 2025, pondéré par la saisonnalité mensuelle."""
    mois = random.choices(list(POIDS_MOIS), weights=list(POIDS_MOIS.values()))[0]
    debut = date(2025, mois, 1)
    fin = date(2025, 12, 31) if mois == 12 else date(2025, mois + 1, 1) - timedelta(days=1)
    return jour_aleatoire(debut, fin)


def generer_clients(fake):
    clients = []
    poids_agences = [random.uniform(0.6, 1.8) for _ in AGENCES]
    for i in range(1, NB_CLIENTS + 1):
        segment = random.choices(list(SEGMENTS), weights=[s[0] for s in SEGMENTS.values()])[0]
        rev_min, rev_max = SEGMENTS[segment][1]
        nom = fake.company() if segment == "Entreprise" else fake.name()
        naissance = None if segment == "Entreprise" else fake.date_of_birth(minimum_age=19, maximum_age=88).isoformat()
        agence = random.choices(range(1, len(AGENCES) + 1), weights=poids_agences)[0]
        entree = jour_aleatoire(date(2005, 1, 1), FIN).isoformat()
        revenu = round(random.uniform(rev_min, rev_max), 2)
        clients.append((i, nom, naissance, segment, agence, entree, revenu))
    return clients


def generer_comptes(fake, clients):
    comptes = []
    for client in clients:
        types = ["Compte courant"] + random.sample(list(TYPES_COMPTES)[1:], k=random.randint(0, 3))
        for type_compte in types:
            bas, haut = TYPES_COMPTES[type_compte][1]
            facteur = 3 if client[3] in ("Entreprise", "Banque privée") else 1
            solde = round(random.uniform(bas, haut) * facteur, 2)
            ouverture = max(client[5], jour_aleatoire(date(2005, 1, 1), FIN).isoformat())
            comptes.append((len(comptes) + 1, client[0], type_compte, fake.iban(), ouverture, solde))
    return comptes


def generer_transactions(comptes):
    transactions = []
    for i in range(1, NB_TRANSACTIONS + 1):
        compte = random.choice(comptes)
        if TYPES_COMPTES[compte[2]][0]:   # épargne : versements et retraits
            categorie = random.choices(["Versement", "Retrait épargne", "Intérêts"], weights=[60, 35, 5])[0]
            montant = {"Versement": random.uniform(50, 3_000), "Retrait épargne": -random.uniform(50, 4_000),
                       "Intérêts": random.uniform(5, 400)}[categorie]
        else:
            categorie = random.choices(["Salaire", "Virement reçu", "Carte", "Prélèvement", "Retrait DAB", "Frais"],
                                       weights=[10, 10, 40, 22, 12, 6])[0]
            montant = {"Salaire": random.uniform(1_500, 4_500), "Virement reçu": random.uniform(20, 2_500),
                       "Carte": -random.uniform(3, 250), "Prélèvement": -random.uniform(15, 1_200),
                       "Retrait DAB": -random.choice([20, 40, 50, 60, 100, 200]),
                       "Frais": -random.uniform(1, 30)}[categorie]
        transactions.append((i, compte[0], jour_pondere().isoformat(), round(montant, 2), categorie))
    transactions.sort(key=lambda t: t[2])
    return [(i, *t[1:]) for i, t in enumerate(transactions, start=1)]


def statut_credit(segment: str, taux_endettement: float) -> str:
    """Statut tiré au sort, plus risqué pour un endettement élevé."""
    p_defaut = {"Particulier": 0.025, "Professionnel": 0.045, "Entreprise": 0.035, "Banque privée": 0.008}[segment]
    p_defaut *= 1 + 0.3 * min(taux_endettement, 3)
    tirage = random.random()
    if tirage < p_defaut:
        return "Défaut"
    return "Retard < 90 j" if tirage < p_defaut * 2.5 else "Sain"


def generer_credits(clients):
    credits = []
    for client in clients:
        segment, revenu = client[3], client[6]
        if random.random() > SEGMENTS[segment][2]:
            continue
        pro = segment in ("Professionnel", "Entreprise")
        types = ["Professionnel"] if pro else ["Immobilier", "Consommation", "Auto"]
        type_credit = random.choices(types, weights=[1] if len(types) == 1 else [45, 35, 20])[0]
        (m_min, m_max), durees, (t_min, t_max) = TYPES_CREDITS[type_credit]
        montant = round(random.uniform(m_min, m_max) * (2 if segment == "Entreprise" else 1), 2)
        duree = random.choice(durees)
        octroi = jour_aleatoire(date(2015, 1, 1), FIN) if random.random() > 0.25 else jour_pondere()
        mois_ecoules = (FIN.year - octroi.year) * 12 + FIN.month - octroi.month
        encours = round(max(0.0, montant * (1 - mois_ecoules / duree)), 2)
        if encours == 0:
            continue
        taux = round(random.uniform(t_min, t_max) + (0.6 if octroi.year >= 2023 else 0), 2)
        statut = statut_credit(segment, montant / max(revenu, 1) / 5)
        credits.append((len(credits) + 1, client[0], type_credit, montant, encours, taux, duree,
                        octroi.isoformat(), statut))
    return credits


def main(chemin: Path = DB_PATH) -> None:
    random.seed(SEED)
    Faker.seed(SEED)
    fake = Faker("fr_FR")
    chemin.unlink(missing_ok=True)
    conn = sqlite3.connect(chemin)
    conn.executescript(SCHEMA)

    agences = [(i, *a) for i, a in enumerate(AGENCES, start=1)]
    clients = generer_clients(fake)
    comptes = generer_comptes(fake, clients)
    transactions = generer_transactions(comptes)
    credits = generer_credits(clients)

    conn.executemany("INSERT INTO agences VALUES (?, ?, ?, ?)", agences)
    conn.executemany("INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?, ?)", clients)
    conn.executemany("INSERT INTO comptes VALUES (?, ?, ?, ?, ?, ?)", comptes)
    conn.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?)", transactions)
    conn.executemany("INSERT INTO credits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", credits)
    conn.commit()
    conn.close()
    print(f"Base créée : {chemin} — {len(agences)} agences, {len(clients)} clients, {len(comptes)} comptes, "
          f"{len(transactions)} transactions, {len(credits)} crédits")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH)
