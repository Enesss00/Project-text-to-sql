"""Banc d'essai de précision : questions réelles → pipeline complet → comparaison des résultats.

Critère (« execution accuracy ») : le résultat du SQL généré doit contenir exactement les mêmes
lignes que la requête de référence. Les noms et l'ordre des colonnes sont ignorés, les nombres
sont arrondis à 2 décimales et les lignes comparées sans tenir compte de leur ordre. Les colonnes
supplémentaires (ex. un nom en plus d'un identifiant) sont tolérées.

Usage : ANTHROPIC_API_KEY=... python evals/run_eval.py   (≈ 20 questions, quelques centimes)
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from text2sql import base, llm  # noqa: E402
from text2sql.config import DOSSIER_PROFILS, MODELE  # noqa: E402
from text2sql.profils import lire_profil  # noqa: E402

QUESTIONS = Path(__file__).with_name("questions.json")
PROFIL = lire_profil(DOSSIER_PROFILS / "retail.toml")   # les questions portent sur la base retail
DB_DEMO = PROFIL.base


def normaliser_valeur(v):
    """Arrondit les nombres pour neutraliser les écarts de calcul flottant."""
    if isinstance(v, float):
        return round(v, 2)
    return v


def lignes(df) -> Counter:
    """Multiensemble des lignes, chaque ligne vue comme un multiensemble de valeurs."""
    return Counter(tuple(sorted(map(str, map(normaliser_valeur, r)))) for r in df.itertuples(index=False))


def projeter(df_obtenu, df_ref):
    """Garde, dans le résultat obtenu, les colonnes qui correspondent à celles de la référence."""
    colonnes = []
    for col_ref in df_ref.columns:
        cible = sorted(map(str, map(normaliser_valeur, df_ref[col_ref])))
        for col in df_obtenu.columns:
            if col not in colonnes and sorted(map(str, map(normaliser_valeur, df_obtenu[col]))) == cible:
                colonnes.append(col)
                break
    return df_obtenu[colonnes] if len(colonnes) == len(df_ref.columns) else df_obtenu


def resultat_correct(df_obtenu, df_ref) -> bool:
    """Vrai si les lignes obtenues correspondent à la référence (colonnes en plus tolérées)."""
    if df_obtenu is None or len(df_obtenu) != len(df_ref):
        return False
    return lignes(projeter(df_obtenu, df_ref)) == lignes(df_ref)


def evaluer_cas(client, systeme: str, cas: dict) -> dict:
    """Joue la conversation du cas (questions de suivi incluses) et note la dernière réponse."""
    historique, res = [], None
    for question in cas["questions"]:
        res = llm.generer_et_executer(client, systeme, historique, question, DB_DEMO)
        if res.succes:
            historique += [{"role": "user", "content": question}, {"role": "assistant", "content": res.sql}]
    reference = base.executer_requete(DB_DEMO, cas["reference"])
    return {"id": cas["id"], "correct": resultat_correct(res.df, reference), "sql": res.sql,
            "erreur": res.erreur, "tentatives": res.tentatives, "cout_usd": res.consommation.cout()}


def main() -> None:
    cas = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    client = llm.creer_client()
    systeme = llm.construire_prompt_systeme(base.lire_schema(DB_DEMO), PROFIL)
    debut, resultats = time.monotonic(), []
    for c in cas:
        r = evaluer_cas(client, systeme, c)
        resultats.append(r)
        print(f"{'✅' if r['correct'] else '❌'} {r['id']:<24} tentatives={r['tentatives']}")
    score = sum(r["correct"] for r in resultats) / len(resultats)
    cout = sum(r["cout_usd"] for r in resultats)
    print(f"\nPrécision : {score:.0%} ({sum(r['correct'] for r in resultats)}/{len(resultats)}) · "
          f"modèle {MODELE} · coût ≈ {cout:.3f} $ · {time.monotonic() - debut:.0f} s")
    sortie = Path(__file__).with_name(f"resultats_{time.strftime('%Y%m%d_%H%M%S')}.json")
    sortie.write_text(json.dumps({"modele": MODELE, "precision": score, "cas": resultats},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Détails : {sortie}")


if __name__ == "__main__":
    main()
