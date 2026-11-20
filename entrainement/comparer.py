"""Compare NEWS2, le modèle Edge et leur combinaison sur les patients de validation."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "passerelle"))
from passerelle import points

PARAMS_NEWS2 = ["resp", "o2sat", "sbp", "hr", "temp"]

# 1. Mêmes patients de validation que dans entrainer.py (même graine)
table = pd.read_csv(RACINE / "entrainement" / "jeu_entrainement.csv")
patients = table["patient_id"].unique()
np.random.default_rng(42).shuffle(patients)
validation = set(patients[: len(patients) // 5])
val = table[table["patient_id"].isin(validation)].reset_index(drop=True)

# 2. Risque du modèle, calculé avec modele.json comme le fera la passerelle
modele = json.loads((RACINE / "passerelle" / "modele.json").read_text())
V = modele["variables"]
X = (val[V].fillna(pd.Series(modele["medianes"])) - pd.Series(modele["moyennes"])) \
    / pd.Series(modele["ecarts"])
z = modele["intercept"] + X[V].to_numpy() @ np.array([modele["coefficients"][v] for v in V])
proba = 1 / (1 + np.exp(-z))

# 3. NEWS2 avec la fonction points de la passerelle
scores, niveaux = [], []
for ligne in val[[f"{p}_dernier" for p in PARAMS_NEWS2]].itertuples(index=False):
    pts = [points(p, v) for p, v in zip(PARAMS_NEWS2, ligne) if pd.notna(v)]
    s = sum(pts)
    scores.append(s)
    if len(pts) < 3:
        niveaux.append("indetermine")
    elif s >= 7:
        niveaux.append("eleve")
    elif s >= 5 or 3 in pts:
        niveaux.append("moyen")
    else:
        niveaux.append("faible")
val["news2"], val["niveau"] = scores, niveaux

# 4. Évaluation
y = val["sepsis"].to_numpy()
sepsis_patient = val.groupby("patient_id")["sepsis"].max()
sans_sepsis = sepsis_patient[sepsis_patient == 0].index


def evaluer(nom, alerte):
    d = pd.DataFrame({"patient": val["patient_id"], "y": y, "alerte": alerte})
    vp = (d["alerte"] & (d["y"] == 1)).sum()
    sens = vp / (d["y"] == 1).sum()
    prec = vp / d["alerte"].sum() if d["alerte"].sum() else 0
    detectes = d[d["y"] == 1].groupby("patient")["alerte"].any()
    fausses = d.groupby("patient")["alerte"].any()[sans_sepsis].mean()
    print(f"{nom:30} | {d['alerte'].mean():7.1%} | {sens:7.1%} | {prec:7.1%} | "
          f"{detectes.mean():9.1%} | {fausses:9.1%}")
    return detectes


print(f"AUROC modèle : {roc_auc_score(y, proba):.3f}  (doit redonner 0,736)")
print(f"AUROC NEWS2  : {roc_auc_score(y, val['news2']):.3f}\n")

eleve = (val["niveau"] == "eleve").to_numpy()
moyen_plus = val["niveau"].isin(["moyen", "eleve"]).to_numpy()
print(f"{'Stratégie':30} | alertes | sensib. | précis. | détectés | faux pat.")
det_news2 = evaluer("NEWS2 élevé", eleve)
evaluer("NEWS2 moyen ou élevé", moyen_plus)
det_m05 = evaluer("Modèle >= 0,05", proba >= 0.05)
det_m10 = evaluer("Modèle >= 0,10", proba >= 0.10)
evaluer("NEWS2 élevé OU modèle >= 0,05", eleve | (proba >= 0.05))
evaluer("NEWS2 élevé OU modèle >= 0,10", eleve | (proba >= 0.10))

print(f"\nPatients sepsis détectés par le modèle mais pas par NEWS2 élevé :")
print(f"  seuil 0,05 : {(det_m05 & ~det_news2).sum()} sur {len(det_news2)}")
print(f"  seuil 0,10 : {(det_m10 & ~det_news2).sum()} sur {len(det_news2)}")