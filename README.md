# Text-to-SQL avec Claude et Streamlit

Posez une question en français (« CA par magasin en septembre ? »), l'application génère
une requête SQL avec l'API Claude, l'exécute sur une base SQLite de démonstration et affiche
le SQL, le tableau de résultats et un graphique choisi automatiquement.

## Installation et lancement

```bash
pip install -r requirements.txt
python seed_db.py
ANTHROPIC_API_KEY="sk-ant-..." streamlit run app.py
```

L'application s'ouvre sur http://localhost:8501.

## Fichiers

| Fichier | Rôle |
|---|---|
| `seed_db.py` | Crée `retail.db` : 10 magasins, 100 produits, 500 clients, 20 000 ventes sur 2025 |
| `app.py` | Application Streamlit (chat, génération SQL, exécution, graphiques) |
| `test_security.py` | Tests pytest du filtre de sécurité SQL |

## Fonctionnement

- Le schéma est lu via `PRAGMA table_info` et injecté dans le prompt système, avec 4 exemples
  question/SQL et les valeurs possibles des petites colonnes texte (catégories, régions…).
- Les échanges réussis (question → SQL) sont renvoyés au modèle : les questions de suivi
  comme « et pour octobre ? » fonctionnent.
- En cas d'erreur (SQL invalide ou refusé), l'erreur est renvoyée au modèle pour correction,
  2 fois au maximum ; sinon un message clair est affiché.
- Graphique : ligne si la première colonne est temporelle (date, mois…), barres pour
  catégorie/valeur, rien pour une valeur unique.

## Sécurité

- Base ouverte en lecture seule (`mode=ro`).
- Seules les requêtes commençant par `SELECT` ou `WITH` sont acceptées ; `;`, les commentaires
  et les mots-clés `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `PRAGMA`, `CREATE`, `ATTACH`…
  sont refusés (y compris à l'intérieur de littéraux texte : filtre volontairement strict).
- `LIMIT 500` est ajouté si la requête n'a pas de LIMIT final.

## Tests

```bash
python -m pytest -q
```
