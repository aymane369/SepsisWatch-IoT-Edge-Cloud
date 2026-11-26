"""Teste plusieurs réglages des alertes sur les 3 000 patients de validation, hors ligne.

Utilise les fonctions priorite et decider_alerte de la passerelle elle-même.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from journal import enregistrer_sortie 
enregistrer_sortie(__file__) 
RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "passerelle"))
from passerelle import points, priorite, decider_alerte

PARAMS_NEWS2 = ["resp", "o2sat", "sbp", "hr", "temp"]

# 1. Mêmes patients de validation que entrainer.py
table = pd.read_csv(RACINE / "entrainement" / "jeu_entrainement.csv")
patients = table["patient_id"].unique()
np.random.default_rng(42).shuffle(patients)
validation = set(patients[: len(patients) // 5])
val = table[table["patient_id"].isin(validation)].reset_index(drop=True)

# 2. Priorité de chaque heure, calculée comme dans la passerelle
modele = json.loads((RACINE / "passerelle" / "modele.json").read_text())
V = modele["variables"]
X = (val[V].fillna(pd.Series(modele["medianes"])) - pd.Series(modele["moyennes"])) \
    / pd.Series(modele["ecarts"])
z = modele["intercept"] + X[V].to_numpy() @ np.array([modele["coefficients"][v] for v in V])
proba = 1 / (1 + np.exp(-z))

prios = []
niveaux = []
for ligne, p in zip(val[[f"{x}_dernier" for x in PARAMS_NEWS2]].itertuples(index=False), proba):
    pts = [points(n, v) for n, v in zip(PARAMS_NEWS2, ligne) if pd.notna(v)]
    s = sum(pts)
    niveau = ("indetermine" if len(pts) < 3 else "eleve" if s >= 7
              else "moyen" if s >= 5 or 3 in pts else "faible")
    niveaux.append(niveau)
    prios.append(priorite(niveau, p >= modele["seuil"]))
val["prio"] = prios
val["niveau"] = niveaux

groupes = [(g["heure_sejour"].to_numpy(), g["prio"].to_numpy(), g["sepsis"].to_numpy(),
            g["niveau"].to_numpy())
           for _, g in val.groupby("patient_id", sort=False)]
jours = len(val) / 24


# 3. Rejouer chaque patient heure par heure avec un réglage donné
def rejouer(persistance, fin, avec_memoire=True, nouvelles_regles=True, pers_vig=1):
    alertes = fins = 0
    sepsis_total = sepsis_detectes = sans_sepsis = faux = 0
    retards = []
    for heures, prs, ys, nivs in groupes:
        memoire = {"alerte_niveau": "aucune", "alerte_depuis": 0,
                   "heures_calmes": 0, "heures_au_dessus": 0}
        detecte = alerte_patient = False
        premiere_prio = premiere_alerte = None
        precedente = 0
        for h, pr, y, nv in zip(heures, prs, ys, nivs):
            ecart = int(h) - precedente if precedente > 0 else 1
            precedente = int(h)
            if avec_memoire:
                if nouvelles_regles:
                    d = decider_alerte(memoire, pr, int(h), fin_heures=fin, persistance=persistance,
                                       ecart=ecart, news2_moyen=(nv == "moyen"),
                                       persistance_vigilance=pers_vig)
                else:
                    d = decider_alerte(memoire, pr, int(h), fin_heures=fin, persistance=persistance)
                en_alerte = memoire["alerte_niveau"] != "aucune"
                envoyee = d in ("nouvelle", "rappel")
                fins += d == "fin"
            else:
                en_alerte = envoyee = pr != "aucune"
            alertes += envoyee
            alerte_patient = alerte_patient or envoyee
            if pr != "aucune" and premiere_prio is None:
                premiere_prio = h
            if en_alerte and premiere_alerte is None:
                premiere_alerte = h
            if y == 1 and en_alerte:
                detecte = True
        if ys.max() == 1:
            sepsis_total += 1
            sepsis_detectes += detecte
            if premiere_prio is not None and premiere_alerte is not None:
                retards.append(premiere_alerte - premiere_prio)
        else:
            sans_sepsis += 1
            faux += alerte_patient
    return (alertes / jours, fins / jours, sepsis_detectes / sepsis_total,
            faux / sans_sepsis, np.mean(retards) if retards else 0.0)


def afficher(nom, r):
    print(f"{nom:26} | {r[0]:9.2f} | {r[1]:7.2f} | {r[2]:9.1%} | {r[3]:12.1%} | {r[4]:6.2f}")


print(f"{'Réglage':26} | alertes/j | fins/j  | sepsis    | sans sepsis  | retard")
print(f"{'':26} | par pat.  | par pat.| détectés  | alertés      | (h)")
afficher("Sans mémoire", rejouer(1, 2, avec_memoire=False))
afficher("ancien : pers. 1, fin 3 h", rejouer(1, 3, nouvelles_regles=False))
afficher("vigilance 2 h, fin 3 h", rejouer(1, 3, pers_vig=2))
afficher("vigilance 3 h, fin 3 h", rejouer(1, 3, pers_vig=3))
for persistance in (1, 2):
    for fin in (2, 3, 4):
        afficher(f"persistance {persistance}, fin {fin} h", rejouer(persistance, fin))