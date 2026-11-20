"""Teste les versions A et B du modèle, et NEWS2, sur tous les patients de l'hôpital B.

Les modèles sont entraînés uniquement sur l'hôpital A (mêmes 12 000 patients que entrainer.py).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "passerelle"))
from passerelle import points

PARAMS_NEWS2 = ["resp", "o2sat", "sbp", "hr", "temp"]
table_a = pd.read_csv(RACINE / "entrainement" / "jeu_entrainement.csv")
table_b = pd.read_csv(RACINE / "entrainement" / "jeu_hopital_b.csv")

# Apprentissage : mêmes patients de l'hôpital A que dans entrainer.py
patients = table_a["patient_id"].unique()
np.random.default_rng(42).shuffle(patients)
validation = set(patients[: len(patients) // 5])
app = table_a[~table_a["patient_id"].isin(validation)]

TOUTES = [c for c in table_a.columns if c not in ("patient_id", "sepsis")]
VERSIONS = {"A : toutes": TOUTES,
            "B : sans heure_sejour": [c for c in TOUTES if c != "heure_sejour"]}

y = table_b["sepsis"].to_numpy()
sepsis_patient = table_b.groupby("patient_id")["sepsis"].max()
sans_sepsis = sepsis_patient[sepsis_patient == 0].index


def taux(alerte):
    d = pd.DataFrame({"patient": table_b["patient_id"], "y": y, "alerte": alerte})
    detectes = d[d["y"] == 1].groupby("patient")["alerte"].any().mean()
    fausses = d.groupby("patient")["alerte"].any()[sans_sepsis].mean()
    return detectes, fausses


print(f"Hôpital B : {table_b['patient_id'].nunique()} patients, AUPRC du hasard = {y.mean():.3f}\n")
print(f"{'Méthode':24} | AUROC | AUPRC | détectés 0,05 | faux 0,05 | détectés 0,10 | faux 0,10")

for nom, V in VERSIONS.items():
    medianes = app[V].median()
    X_app = app[V].fillna(medianes)
    moyennes, ecarts = X_app.mean(), X_app.std().replace(0, 1)
    modele = LogisticRegression(max_iter=1000).fit((X_app - moyennes) / ecarts, app["sepsis"])
    proba = modele.predict_proba((table_b[V].fillna(medianes) - moyennes) / ecarts)[:, 1]
    d05, f05 = taux(proba >= 0.05)
    d10, f10 = taux(proba >= 0.10)
    print(f"{nom:24} | {roc_auc_score(y, proba):.3f} | {average_precision_score(y, proba):.3f} | "
          f"{d05:13.1%} | {f05:9.1%} | {d10:13.1%} | {f10:9.1%}")

# NEWS2, avec la fonction de la passerelle
scores, eleve = [], []
for ligne in table_b[[f"{p}_dernier" for p in PARAMS_NEWS2]].itertuples(index=False):
    pts = [points(p, v) for p, v in zip(PARAMS_NEWS2, ligne) if pd.notna(v)]
    scores.append(sum(pts))
    eleve.append(len(pts) >= 3 and sum(pts) >= 7)
detectes, fausses = taux(np.array(eleve))
print(f"{'NEWS2 élevé':24} | {roc_auc_score(y, scores):.3f} | "
      f"{average_precision_score(y, scores):.3f} | {detectes:13.1%} | {fausses:9.1%} |")