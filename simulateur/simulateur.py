import json
import time
from datetime import datetime, timezone
from pathlib import Path
import os
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

CHEMIN_ETAT = Path("etat/simulateur.json")


def sauvegarder_etat():
    """Écrit, pour chaque lit, le patient et son heure, et le prochain fichier à admettre."""
    etat = {"prochain": prochain, "sorties": sorties,
            "lits": [{"patient_id": l["patient_id"], "heure": l["heure"]} for l in lits]}
    CHEMIN_ETAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHEMIN_ETAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(etat), encoding="utf-8")
    os.replace(tmp, CHEMIN_ETAT)


def charger_etat():
    """Relit l'état sauvegardé. Renvoie None si le fichier est absent ou abîmé."""
    try:
        etat = json.loads(CHEMIN_ETAT.read_text(encoding="utf-8"))
        lits = [{"patient_id": l["patient_id"],
                 "df": pd.read_csv(DOSSIER / f"{l['patient_id']}.psv", sep="|"),
                 "heure": l["heure"]} for l in etat["lits"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if len(lits) != NB_LITS:
        return None
    return etat, lits


def admettre(en_cours=False):
    """Charge le patient suivant dans un lit."""
    global prochain
    fichier = fichiers[prochain % len(fichiers)]
    prochain += 1
    df = pd.read_csv(fichier, sep="|")
    heure = random.randrange(len(df)) if en_cours else 0
    return {"patient_id": fichier.stem, "df": df, "heure": heure}


def publier_sortie(i, lit):
    """Fin de séjour : les étiquettes du patient partent sur un topic à part.
    Elles ne sont jamais envoyées avec les signes vitaux."""
    service = i // LITS_PAR_SERVICE + 1
    etiquettes = lit["df"]["SepsisLabel"].fillna(0).astype(int).tolist()
    message = {
        "patient_id": lit["patient_id"],
        "service": service,
        "lit": i + 1,
        "etiquettes": etiquettes,  # etiquettes[h - 1] correspond à heure_sejour = h
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    topic = f"hopital/service-{service}/lit-{i + 1:02d}/sortie"
    client.publish(topic, json.dumps(message), qos=1)

sorties = 0
reprise = charger_etat()
if reprise is None:
    lits = [admettre(en_cours=True) for _ in range(NB_LITS)]
    print(f"Démarrage : nouveaux patients dans les {NB_LITS} lits")
else:
    etat, lits = reprise
    prochain = etat["prochain"]
    sorties = etat["sorties"]
    print(f"Reprise : {NB_LITS} lits rechargés, prochain fichier {prochain}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulateur")
# Testament : si le simulateur disparaît sans prévenir, Mosquitto publie « hors ligne » à sa place
client.will_set("hopital/etat/simulateur", "hors ligne", qos=1, retain=True)
# À chaque connexion (et reconnexion), il annonce lui-même qu'il est là
client.on_connect = lambda c, u, f, rc, p: c.publish("hopital/etat/simulateur", "en ligne", qos=1, retain=True)
client.connect(os.environ.get("MQTT_HOST", "localhost"), 1883, keepalive=10)
client.loop_start()

tour = 0
while True:
    for i in range(NB_LITS):
        if lits[i]["heure"] >= len(lits[i]["df"]):
            publier_sortie(i, lits[i])  # le séjour est terminé : on publie ses étiquettes
            sorties += 1
            lits[i] = admettre()  # nouveau patient
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
    print(f"Tour {tour} : {NB_LITS} messages publiés, {sorties} sorties au total")
    sauvegarder_etat()  # après chaque tour : un redémarrage reprend les mêmes patients
    time.sleep(SECONDES_PAR_HEURE)
