"""Expérience hors ligne : des modèles qui apprennent patient après patient.
Chaque patient est prédit AVANT que les modèles apprennent de lui.

Usage : python entrainement/en_ligne.py [fichier.csv] [nb patients | tous] [pas1,pas2,...] [quart]
"""
import os
import sys
from pathlib import Path
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "passerelle"))
os.environ.setdefault("SERVICE", "1")  # sinon passerelle.py prend le 1er argument pour un numéro de service
from apprentissage import ModeleEnLigne
from passerelle import modele, predire

FICHIER = Path(sys.argv[1]) if len(sys.argv) > 1 else RACINE / "entrainement" / "jeu_hopital_b.csv"
NB = sys.argv[2] if len(sys.argv) > 2 else "6000"
PAS = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0.00003]
QUART = len(sys.argv) > 4 and sys.argv[4] == "quart"  # une seule passerelle : 1 patient sur 4
BLOC = 1000
SEUIL = modele["seuil"]

df = pd.read_csv(FICHIER)
ordre = df["patient_id"].drop_duplicates()
if NB != "tous":
    garder = set(ordre.iloc[: int(NB)])
    df = df[df["patient_id"].isin(garder)]
VARIABLES = modele["variables"]

# Deux versions qui partent du modèle actuel :
#   p10 : les heures sepsis comptent 10 fois plus dans l'apprentissage (réglage précédent)
#   p1  : toutes les heures comptent pareil, l'échelle des probabilités devrait rester celle du modèle actuel
modeles = {}
for p in PAS:
    modeles[f"chaud_{p:g}_p10"] = ModeleEnLigne.depuis_modele(modele, pas=p, poids_positif=10.0)
    modeles[f"chaud_{p:g}_p1"] = ModeleEnLigne.depuis_modele(modele, pas=p, poids_positif=1.0)

NOMS = ["fixe"] + list(modeles)
resultats = {n: [] for n in NOMS}  # (bloc, étiquette, risque)

traites = 0
for k, (pid, groupe) in enumerate(df.groupby("patient_id", sort=False)):
    if QUART and k % 4 != 0:
        continue
    bloc = traites // BLOC
    traites += 1

    tableau = groupe[VARIABLES]
    lignes = tableau.astype(object).where(tableau.notna(), None).to_dict("records")
    etiquettes = groupe["sepsis"].tolist()

    # 1) pendant le séjour : prédiction avec les modèles tels qu'ils sont avant ce patient
    for v, y in zip(lignes, etiquettes):
        resultats["fixe"].append((bloc, y, predire(v)[0]))
        for n, m in modeles.items():
            resultats[n].append((bloc, y, m.predire(v)))

    # 2) à la sortie : les étiquettes arrivent, les modèles apprennent
    for v, y in zip(lignes, etiquettes):
        for m in modeles.values():
            m.apprendre(v, y)

    if traites % 500 == 0:
        print(f"{traites} patients traités", flush=True)


def mesures(triplets):
    y = [t[1] for t in triplets]
    p = [t[2] for t in triplets]
    if len(set(y)) < 2:
        return None, None
    return roc_auc_score(y, p), average_precision_score(y, p)


def au_seuil(triplets):
    """Part des heures en alerte, sensibilité et précision au seuil du modèle actuel."""
    alertes = [t for t in triplets if t[2] >= SEUIL]
    positifs = sum(1 for t in triplets if t[1] == 1)
    vrais = sum(1 for t in alertes if t[1] == 1)
    taux = len(alertes) / len(triplets) if triplets else None
    sens = vrais / positifs if positifs else None
    prec = vrais / len(alertes) if alertes else None
    return taux, sens, prec


def pct(x):
    return f"{100 * x:6.1f}%" if x is not None else f"{'-':>7}"


L = 17
nb_blocs = max(t[0] for t in resultats["fixe"]) + 1
entete = "patients     " + "".join(f"{n:>{L}}" for n in NOMS)

print()
if QUART:
    print("Une seule passerelle : 1 patient sur 4")
print(f"AUROC par bloc de {BLOC} patients, dans l'ordre d'arrivée")
print(entete)
for b in range(nb_blocs):
    ligne = f"{b * BLOC + 1:>5}-{(b + 1) * BLOC:<7}"
    for n in NOMS:
        auroc, _ = mesures([t for t in resultats[n] if t[0] == b])
        ligne += f"{auroc:{L}.3f}" if auroc is not None else f"{'-':>{L}}"
    print(ligne)

print()
print(f"Part des heures en alerte (risque >= {SEUIL}) par bloc : doit rester stable")
print(entete)
for b in range(nb_blocs):
    ligne = f"{b * BLOC + 1:>5}-{(b + 1) * BLOC:<7}"
    for n in NOMS:
        taux, _, _ = au_seuil([t for t in resultats[n] if t[0] == b])
        ligne += f"{pct(taux):>{L}}"
    print(ligne)

print()
print(f"Sur l'ensemble (seuil {SEUIL})")
print(f"{'modele':<17}{'AUROC':>7}{'AUPRC':>8}{'en alerte':>11}{'sensibilite':>13}{'precision':>11}")
for n in NOMS:
    auroc, auprc = mesures(resultats[n])
    taux, sens, prec = au_seuil(resultats[n])
    print(f"{n:<17}{auroc:7.3f}{auprc:8.3f}{pct(taux):>11}{pct(sens):>13}{pct(prec):>11}")