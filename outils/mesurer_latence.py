"""Mesure la latence en régime établi : écoute les décisions (news2) et les alertes pendant DUREE secondes.

À lancer depuis la racine du projet, dans le réseau Docker (même horloge que les conteneurs) :
  $mdp = ((Get-Content .env | Select-String "^MQTT_MDP_ADMIN=").Line -split "=", 2)[1]
  docker run --rm --network sepsiswatch-iot-edge-cloud_default -v ${PWD}/outils:/o -e MQTT_MDP=$mdp `
      sepsiswatch-iot-edge-cloud-passerelle-1 python /o/mesurer_latence.py 120
"""
import json
import os
import statistics
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

DUREE = int(sys.argv[1]) if len(sys.argv) > 1 else 120
reseau, traitement, bout_en_bout = [], [], []


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe([("hopital/+/+/news2", 0), ("hopital/alertes/#", 0)])


def on_message(client, userdata, msg):
    arrivee = time.time()
    try:
        m = json.loads(msg.payload)
    except ValueError:
        return
    if msg.topic.endswith("/news2"):
        if "latence_reseau_ms" in m:  # les fins spéciales (sortie, nouveau patient) n'ont pas ces champs
            reseau.append(m["latence_reseau_ms"])
            traitement.append(m["traitement_ms"])
    elif m.get("alerte") in ("nouvelle", "rappel") and m.get("timestamp"):
        # de l'envoi par le simulateur jusqu'à l'alerte lisible publiée par Node-RED
        bout_en_bout.append((arrivee - datetime.fromisoformat(m["timestamp"]).timestamp()) * 1000)


def resume(nom, valeurs):
    if not valeurs:
        print(f"{nom:34} aucune mesure")
        return
    v = sorted(valeurs)
    p95 = v[int(0.95 * (len(v) - 1))]
    print(f"{nom:34} n={len(v):5}  médiane {statistics.median(v):8.1f} ms"
          f"  p95 {p95:8.1f} ms  max {v[-1]:8.1f} ms")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mesure-latence")
client.username_pw_set("admin", os.environ.get("MQTT_MDP"))
client.on_connect, client.on_message = on_connect, on_message
client.connect(os.environ.get("MQTT_HOST", "mosquitto"), 1883)
client.loop_start()
print(f"Mesure pendant {DUREE} s...")
time.sleep(DUREE)
client.loop_stop()
resume("Réseau simulateur -> passerelle", reseau)
resume("Traitement dans la passerelle", traitement)
resume("Bout en bout capteur -> alerte", bout_en_bout)