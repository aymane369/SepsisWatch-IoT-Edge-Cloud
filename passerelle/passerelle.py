import json
import sys
import os
import paho.mqtt.client as mqtt
import time
from datetime import datetime
import math
from pathlib import Path
from features import BORNES, nettoyer, ajouter_mesure, calculer_variables

SERVICE = int(os.environ.get("SERVICE") or (sys.argv[1] if len(sys.argv) > 1 else 1))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
SCHEMA_VERSION = 2
AGE_MAX_HEURES = int(os.environ.get("AGE_MAX_HEURES", "6"))
PARAMS_NEWS2 = ["resp", "o2sat", "sbp", "hr", "temp"]


def points(param, v):
    """Points NEWS2 d'un paramètre."""
    if param == "resp":
        return 3 if v <= 8 else 1 if v <= 11 else 0 if v <= 20 else 2 if v <= 24 else 3
    if param == "o2sat":
        return 3 if v <= 91 else 2 if v <= 93 else 1 if v <= 95 else 0
    if param == "sbp":
        return 3 if v <= 90 else 2 if v <= 100 else 1 if v <= 110 else 0 if v <= 219 else 3
    if param == "hr":
        return (3 if v <= 40 else 1 if v <= 50 else 0 if v <= 90
                else 1 if v <= 110 else 2 if v <= 130 else 3)
    if param == "temp":
        return 3 if v <= 35.0 else 1 if v <= 36.0 else 0 if v <= 38.0 else 1 if v <= 39.0 else 2
    return 0

CHEMIN_MODELE = Path(__file__).parent / "modele.json"
modele = json.loads(CHEMIN_MODELE.read_text()) if CHEMIN_MODELE.exists() else None


def predire(variables):
    """Risque de sepsis et les variables qui le font le plus monter."""
    z = modele["intercept"]
    contributions = {}
    for v in modele["variables"]:
        x = variables.get(v)
        if x is None:
            x = modele["medianes"][v]
        c = modele["coefficients"][v] * (x - modele["moyennes"][v]) / modele["ecarts"][v]
        contributions[v] = c
        z += c
    risque = 1 / (1 + math.exp(-z))
    plus_fortes = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return risque, [v for v, c in plus_fortes if c > 0]


def priorite(niveau, alerte_modele):
    """Grille : NEWS2 élevé et modèle combinés, le modèle n'enlève jamais d'alerte."""
    if niveau == "eleve":
        return "critique" if alerte_modele else "urgente"
    return "vigilance" if alerte_modele else "aucune"



derniers = {}  # lit -> dernières valeurs connues du patient présent
stats = {"recus": 0, "invalides": 0, "vides": 0, "valeurs_rejetees": 0,
         "incoherents": 0, "doublons": 0, "kafka_envoyes": 0, "kafka_erreurs": 0}
cumul = {"reseau": 0.0, "traitement": 0.0}

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "vitals.enrichis")
producteur = None
if KAFKA_BOOTSTRAP:
    from confluent_kafka import Producer
    producteur = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP,
                           "linger.ms": 50,
                           "enable.idempotence": True})


def rapport_kafka(err, msg):
    if err is None:
        stats["kafka_envoyes"] += 1
    else:
        stats["kafka_erreurs"] += 1
def traiter(m):
    valeurs_rejetees = []
    valeurs = {}

    memoire = derniers.get(m["lit"])
    if memoire is None or memoire["patient_id"] != m["patient_id"]:
        memoire = derniers[m["lit"]] = {"patient_id": m["patient_id"],"valeurs": {}, "derniere_heure": 0,"historique": []}
    heure = m["heure_sejour"]
    if heure <= memoire["derniere_heure"]:
        stats["doublons"] += 1
        return None
    memoire["derniere_heure"] = heure

    for param, (mini, maxi) in BORNES.items():
        v = m.get(param)
        if v is not None and not (mini <= v <= maxi):
            valeurs_rejetees.append(param)
            v = None
        valeurs[param] = v
    if valeurs_rejetees:
        stats["valeurs_rejetees"] += 1
    if all(v is None for v in valeurs.values()):
        stats["vides"] += 1
    # 1 bis. Cohérence entre pressions : DBP <= MAP <= SBP
    incoherences = []
    sbp, pam, dbp = valeurs["sbp"], valeurs["map"], valeurs["dbp"]
    if ((dbp is not None and pam is not None and dbp > pam)
            or (pam is not None and sbp is not None and pam > sbp)
            or (dbp is not None and sbp is not None and dbp > sbp)):
        incoherences.append("pression")
        stats["incoherents"] += 1

    # 2. Dernières valeurs connues (remises à zéro si le patient change)
    for param in PARAMS_NEWS2:
        if valeurs[param] is not None:
            memoire["valeurs"][param] = (valeurs[param], heure)
    # 3. Score NEWS2 partiel
    utilisables = {p: (v, h) for p, (v, h) in memoire["valeurs"].items() if heure - h <= AGE_MAX_HEURES}
    pts = [points(p, v) for p, (v, h) in utilisables.items()]
    score = sum(pts)
    nb_reprises = sum(1 for v, h in utilisables.values() if h < heure)
    if len(pts) < 3:
        niveau = "indetermine"
    elif score >= 7:
        niveau = "eleve"
    elif score >= 5 or 3 in pts:
        niveau = "moyen"
    else:
        niveau = "faible"

    m["news2"] = score
    m["news2_nb_params"] = len(pts)
    m["niveau"] = niveau
    m["valeurs_rejetees"] = valeurs_rejetees
    m["passerelle"] = SERVICE
    m["incoherences"] = incoherences
    m["schema_version"] = SCHEMA_VERSION
    m["news2_nb_reprises"] = nb_reprises
        # 4. Modèle Edge : risque de sepsis
    ajouter_mesure(memoire["historique"], heure, nettoyer(m))
    alerte_modele = False
    if modele is not None:
        risque, explication = predire(calculer_variables(memoire["historique"], heure))
        alerte_modele = risque >= modele["seuil"]
        m["risque_edge"] = round(risque, 4)
        m["risque_alerte"] = alerte_modele
        m["risque_explication"] = explication

    # 5. Priorité selon la grille
    m["priorite"] = priorite(niveau, alerte_modele)
    return m


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(f"hopital/service-{SERVICE}/+/vitals", qos=1)
    print(f"Passerelle {SERVICE} connectée")


def on_message(client, userdata, msg):
    arrivee = time.time()
    stats["recus"] += 1
    try:
        m = json.loads(msg.payload)
        sortie = traiter(m)
        if sortie is None:
            return
        emission = datetime.fromisoformat(sortie["timestamp"]).timestamp()
    except (ValueError, KeyError, TypeError):
        stats["invalides"] += 1
        return
    depart = time.time()
    sortie["latence_reseau_ms"] = round((arrivee - emission) * 1000, 2)
    sortie["traitement_ms"] = round((depart - arrivee) * 1000, 3)
    cumul["reseau"] += sortie["latence_reseau_ms"]
    cumul["traitement"] += sortie["traitement_ms"]

    topic = f"hopital/service-{SERVICE}/lit-{sortie['lit']:02d}/news2"
    client.publish(topic, json.dumps(sortie), qos=2)
    if producteur is not None:
        try:
            producteur.produce(KAFKA_TOPIC, key=sortie["patient_id"],
                               value=json.dumps(sortie),
                               on_delivery=rapport_kafka)
            producteur.poll(0)
        except BufferError:
            stats["kafka_erreurs"] += 1
    if stats["recus"] % 100 == 0:
        n = stats["recus"] - stats["invalides"]
        print(stats, f"latence moy {cumul['reseau'] / n:.1f} ms,",
              f"traitement moy {cumul['traitement'] / n:.3f} ms")


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"passerelle-{SERVICE}")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883)
    client.loop_forever()