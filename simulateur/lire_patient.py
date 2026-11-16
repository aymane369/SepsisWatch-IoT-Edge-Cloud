from pathlib import Path
import pandas as pd

VITAUX = ["HR", "O2Sat", "Temp", "SBP", "MAP", "DBP", "Resp"]

fichiers = sorted(Path("data/training_setA").glob("*.psv"))
print("Nombre de fichiers :", len(fichiers))

df = pd.read_csv(fichiers[0], sep="|")
print("Patient :", fichiers[0].stem)
print("Nombre d'heures :", len(df))
print(df[VITAUX].head(10))
print("Valeurs manquantes par colonne :")
print(df[VITAUX].isna().sum())