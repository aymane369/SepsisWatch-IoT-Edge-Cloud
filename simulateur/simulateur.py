import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import paho.mqtt.client as mqtt


import random
random.seed(42) 

DOSSIER = Path("data/training_setA")
NB_LITS = 80
LITS_PAR_SERVICE = 20
SECONDES_PAR_HEURE = 5  # 1 heure du dataset = 5 secondes réelles

VITAUX = {"HR": "hr", "O2Sat": "o2sat", "Temp": "temp", "SBP": "sbp",
          "MAP": "map", "DBP": "dbp", "Resp": "resp"}

fichiers = sorted(DOSSIER.glob("*.psv"))[15000:]
prochain = 0


def admettre(en_cours=False):
    """Charge le patient suivant dans un lit."""
    global prochain
    fichier = fichiers[prochain % len(fichiers)]
    prochain += 1
    df = pd.read_csv(fichier, sep="|")
    heure = random.randrange(len(df)) if en_cours else 0
    return {"patient_id": fichier.stem, "df": df, "heure": heure}


lits = [admettre(en_cours=True) for _ in range(NB_LITS)]

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulateur")
client.connect("localhost", 1883)
client.loop_start()

tour = 0
while True:
    for i in range(NB_LITS):
        if lits[i]["heure"] >= len(lits[i]["df"]):
            lits[i] = admettre()  # séjour terminé, nouveau patient
        lit = lits[i]
        ligne = lit["df"].iloc[lit["heure"]]
        service = i // LITS_PAR_SERVICE + 1

        message = {
            "patient_id": lit["patient_id"],
            "service": service,
            "lit": i + 1,
            "heure_sejour": lit["heure"] + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for colonne, nom in VITAUX.items():
            valeur = ligne[colonne]
            message[nom] = None if pd.isna(valeur) else float(valeur)

        topic = f"hopital/service-{service}/lit-{i + 1:02d}/vitals"
        client.publish(topic, json.dumps(message), qos=1)
        lit["heure"] += 1

    tour += 1
    print(f"Tour {tour} : {NB_LITS} messages publiés")
    time.sleep(SECONDES_PAR_HEURE)