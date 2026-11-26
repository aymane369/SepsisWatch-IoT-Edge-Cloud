"""Compare plusieurs jeux de variables pour le modèle Edge (hôpital A, validation)."""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score
from journal import enregistrer_sortie 
enregistrer_sortie(__file__) 
DOSSIER = Path(__file__).parent
table = pd.read_csv(DOSSIER / "jeu_entrainement.csv")
TOUTES = [c for c in table.columns if c not in ("patient_id", "sepsis")]
AGES = [c for c in TOUTES if c.endswith("_age")]
VARIANTES = {
    "A : toutes": TOUTES,
    "B : sans heure_sejour": [c for c in TOUTES if c != "heure_sejour"],
    "C : physiologie seule": [c for c in TOUTES if c != "heure_sejour" and c not in AGES],
}

# Même séparation par patient que entrainer.py
patients = table["patient_id"].unique()
np.random.default_rng(42).shuffle(patients)
validation = set(patients[: len(patients) // 5])
est_val = table["patient_id"].isin(validation)
app, val = table[~est_val], table[est_val]
y = val["sepsis"].to_numpy()
sepsis_patient = val.groupby("patient_id")["sepsis"].max()
sans_sepsis = sepsis_patient[sepsis_patient == 0].index

print(f"{'Version':24} | var. | AUROC | AUPRC | détectés 0,05 | faux 0,05 | détectés 0,10 | faux 0,10")
for nom, V in VARIANTES.items():
    medianes = app[V].median()
    X_app = app[V].fillna(medianes)
    moyennes, ecarts = X_app.mean(), X_app.std().replace(0, 1)
    modele = LogisticRegression(max_iter=1000).fit((X_app - moyennes) / ecarts, app["sepsis"])
    proba = modele.predict_proba((val[V].fillna(medianes) - moyennes) / ecarts)[:, 1]

    resultats = []
    for seuil in (0.05, 0.10):
        d = pd.DataFrame({"patient": val["patient_id"], "y": y, "alerte": proba >= seuil})
        detectes = d[d["y"] == 1].groupby("patient")["alerte"].any().mean()
        fausses = d.groupby("patient")["alerte"].any()[sans_sepsis].mean()
        resultats += [detectes, fausses]
    print(f"{nom:24} | {len(V):4} | {roc_auc_score(y, proba):.3f} | "
          f"{average_precision_score(y, proba):.3f} | {resultats[0]:13.1%} | "
          f"{resultats[1]:9.1%} | {resultats[2]:13.1%} | {resultats[3]:9.1%}")

    coefs = pd.Series(modele.coef_[0], index=V)
    top = coefs.reindex(coefs.abs().sort_values(ascending=False).index).head(3)
    print("   principales :", ", ".join(f"{k} ({v:+.2f})" for k, v in top.items()))