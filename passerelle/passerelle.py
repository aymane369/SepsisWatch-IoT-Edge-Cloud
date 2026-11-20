import json
import sys
import os
import paho.mqtt.client as mqtt
import time
from datetime import datetime

SERVICE = int(os.environ.get("SERVICE") or (sys.argv[1] if len(sys.argv) > 1 else 1))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
SCHEMA_VERSION = 1

BORNES = {"hr": (20, 300), "o2sat": (50, 100), "temp": (25, 45),
          "sbp": (30, 300), "map": (20, 250), "dbp": (10, 200),
          "resp": (1, 80)}
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


derniers = {}  # lit -> dernières valeurs connues du patient présent
stats = {"recus": 0, "invalides": 0, "vides": 0, "valeurs_rejetees": 0,
         "incoherents": 0, "kafka_envoyes": 0, "kafka_erreurs": 0}
cumul = {"reseau": 0.0, "traitement": 0.0}
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "vitals.enrichis")
producteur = None
if KAFKA_BOOTSTRAP:
    from confluent_kafka import Producer
    producteur = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP,
                           "linger.ms": 50})


def rapport_kafka(err, msg):
    if err is None:
        stats["kafka_envoyes"] += 1
    else:
        stats["kafka_erreurs"] += 1
def traiter(m):
       # 1. Validation : une valeur hors bornes est écartée du calcul,
    #    mais le message d'origine n'est pas modifié
    valeurs_rejetees = []
    valeurs = {}
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
    memoire = derniers.get(m["lit"])
    if memoire is None or memoire["patient_id"] != m["patient_id"]:
        memoire = derniers[m["lit"]] = {"patient_id": m["patient_id"], "valeurs": {}}
    for param in PARAMS_NEWS2:
        if valeurs[param] is not None:
            memoire["valeurs"][param] = valeurs[param]

    # 3. Score NEWS2 partiel
    pts = [points(p, v) for p, v in memoire["valeurs"].items()]
    score = sum(pts)
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
    client.publish(topic, json.dumps(sortie), qos=1)
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