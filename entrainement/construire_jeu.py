"""Construit la table d'entraînement à partir des 15 000 premiers patients.

Les variables sont calculées avec features.py, le même code que la passerelle.
"""
import sys
from pathlib import Path

import pandas as pd
from journal import enregistrer_sortie 
enregistrer_sortie(__file__) 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "passerelle"))
from features import nettoyer, ajouter_mesure, calculer_variables

DOSSIER = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/training_setA")
NB_PATIENTS = 15000
if len(sys.argv) > 2:
    NB_PATIENTS = None if sys.argv[2] == "tous" else int(sys.argv[2])
SORTIE = sys.argv[3] if len(sys.argv) > 3 else "jeu_entrainement.csv"
COLONNES = {"HR": "hr", "O2Sat": "o2sat", "Temp": "temp", "SBP": "sbp",
            "MAP": "map", "DBP": "dbp", "Resp": "resp"}

fichiers = sorted(DOSSIER.glob("*.psv"))[:NB_PATIENTS]
lignes = []
for i, fichier in enumerate(fichiers, 1):
    df = pd.read_csv(fichier, sep="|", usecols=list(COLONNES) + ["SepsisLabel"])
    df = df.rename(columns=COLONNES)
    historique = []
    for heure, ligne in enumerate(df.itertuples(index=False), start=1):
        mesure = {s: getattr(ligne, s) for s in COLONNES.values()}
        mesure = {s: None if pd.isna(v) else float(v) for s, v in mesure.items()}
        ajouter_mesure(historique, heure, nettoyer(mesure))
        variables = calculer_variables(historique, heure)
        variables["patient_id"] = fichier.stem
        variables["sepsis"] = int(ligne.SepsisLabel)
        lignes.append(variables)
    if i % 1000 == 0:
        print(f"{i} patients traités")

table = pd.DataFrame(lignes)
table.to_csv(Path(__file__).parent / SORTIE, index=False)

patients_sepsis = table.groupby("patient_id")["sepsis"].max().sum()
print(f"\nLignes : {len(table)}")
print(f"Patients : {table['patient_id'].nunique()}, dont {patients_sepsis} avec sepsis")
print(f"Lignes avec sepsis = 1 : {table['sepsis'].mean():.2%}")