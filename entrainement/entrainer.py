"""Entraîne la régression logistique Edge et mesure ses performances."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score

DOSSIER = Path(__file__).parent
table = pd.read_csv(DOSSIER / "jeu_entrainement.csv")
VARIABLES = [c for c in table.columns if c not in ("patient_id", "sepsis")]

# 1. Séparation par patient : 80 % pour apprendre, 20 % pour évaluer
patients = table["patient_id"].unique()
np.random.default_rng(42).shuffle(patients)
validation = set(patients[: len(patients) // 5])
est_val = table["patient_id"].isin(validation)
app, val = table[~est_val], table[est_val]

# 2. Préparation : manquants remplacés par la médiane, puis mise à l'échelle
medianes = app[VARIABLES].median()
X_app = app[VARIABLES].fillna(medianes)
moyennes, ecarts = X_app.mean(), X_app.std().replace(0, 1)


def preparer(df):
    return (df[VARIABLES].fillna(medianes) - moyennes) / ecarts


# 3. Entraînement
modele = LogisticRegression(max_iter=1000)
modele.fit(preparer(app), app["sepsis"])

# 4. Évaluation sur les patients jamais vus
proba = modele.predict_proba(preparer(val))[:, 1]
y = val["sepsis"].to_numpy()
auroc = roc_auc_score(y, proba)
print(f"Patients : {len(patients) - len(validation)} pour apprendre, {len(validation)} pour évaluer")
print(f"AUROC : {auroc:.3f}")
print(f"AUPRC : {average_precision_score(y, proba):.3f} (hasard : {y.mean():.3f})")

d = pd.DataFrame({"patient": val["patient_id"].to_numpy(), "y": y})
sepsis_patient = d.groupby("patient")["y"].max()
sans_sepsis = sepsis_patient[sepsis_patient == 0].index
print("\nSeuil | heures en alerte | sensibilité | précision | patients sepsis détectés | patients sans sepsis alertés")
for seuil in (0.05, 0.1, 0.2, 0.3, 0.5):
    d["alerte"] = proba >= seuil
    vp = (d["alerte"] & (d["y"] == 1)).sum()
    sens = vp / (d["y"] == 1).sum()
    prec = vp / d["alerte"].sum() if d["alerte"].sum() else 0
    detectes = d[d["y"] == 1].groupby("patient")["alerte"].any().mean()
    fausses = d.groupby("patient")["alerte"].any()[sans_sepsis].mean()
    print(f"{seuil:5.2f} | {d['alerte'].mean():15.1%} | {sens:10.1%} | {prec:8.1%} | "
          f"{detectes:23.1%} | {fausses:.1%}")

# 5. Variables les plus influentes
coefs = pd.Series(modele.coef_[0], index=VARIABLES)
print("\nVariables les plus influentes :")
print(coefs.reindex(coefs.abs().sort_values(ascending=False).index).head(10).round(3))

# 6. Export pour la passerelle
resultat = {
    "variables": VARIABLES,
    "medianes": {k: float(v) for k, v in medianes.items()},
    "moyennes": {k: float(v) for k, v in moyennes.items()},
    "ecarts": {k: float(v) for k, v in ecarts.items()},
    "coefficients": {k: float(v) for k, v in coefs.items()},
    "intercept": float(modele.intercept_[0]),
    "seuil": None,
    "auroc_validation": round(float(auroc), 4),
    "entrainement": "training_setA, 15 000 premiers patients, 80 % (separation par patient, graine 42)",
}
sortie = DOSSIER.parent / "passerelle" / "modele.json"
sortie.write_text(json.dumps(resultat, indent=2))
print(f"\nModèle enregistré dans {sortie}")