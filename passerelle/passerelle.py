import json
import sys
import os
import paho.mqtt.client as mqtt
import time
from datetime import datetime
import math
from pathlib import Path
from features import BORNES, nettoyer, ajouter_mesure, calculer_variables, pressions_incoherentes
import tampon
from apprentissage import ModeleEnLigne, REGLAGES_RETENUS

SERVICE = int(os.environ.get("SERVICE") or (sys.argv[1] if len(sys.argv) > 1 else 1))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
SCHEMA_VERSION = 4 
AGE_MAX_HEURES = int(os.environ.get("AGE_MAX_HEURES", "6"))
RAPPEL_HEURES = int(os.environ.get("RAPPEL_HEURES", "6"))
FIN_HEURES = int(os.environ.get("FIN_HEURES", "3"))
PERSISTANCE_HEURES = int(os.environ.get("PERSISTANCE_HEURES", "1"))
PERSISTANCE_VIGILANCE = int(os.environ.get("PERSISTANCE_VIGILANCE", "1"))
ORDRE_PRIORITE = {"aucune": 0, "vigilance": 1, "urgente": 2, "critique": 3}
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
    """Risque de sepsis et les variables qui le font le plus monter (modèle fixe)."""
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


# ---------- Apprentissage en ligne ----------
# APPRENTISSAGE=0 pour revenir au modèle fixe sans toucher au code.
APPRENTISSAGE = os.environ.get("APPRENTISSAGE", "1") == "1" and modele is not None
DOSSIER_ETAT = Path(os.environ.get("DOSSIER_ETAT", Path(__file__).parent / "etat"))
CHEMIN_MODELE_EN_LIGNE = DOSSIER_ETAT / f"modele_en_ligne-{SERVICE}.json"
CHEMIN_PATIENTS_APPRIS = DOSSIER_ETAT / f"patients_appris-{SERVICE}.txt"
SEJOURS_MAX = 200  # séjours gardés en attente de leur message de sortie
CHEMIN_MEMOIRE = DOSSIER_ETAT / f"memoire-{SERVICE}.json"
SAUVEGARDE_SECONDES = int(os.environ.get("SAUVEGARDE_SECONDES", "10"))

def charger_patients_appris():
    if not CHEMIN_PATIENTS_APPRIS.exists():
        return set()
    return set(CHEMIN_PATIENTS_APPRIS.read_text(encoding="utf-8").split())


modele_en_ligne = None
patients_appris = set()
if APPRENTISSAGE:
    # modèle sauvegardé s'il existe et n'est pas abîmé, sinon départ depuis modele.json
    modele_en_ligne = ModeleEnLigne.charger(CHEMIN_MODELE_EN_LIGNE)
    if modele_en_ligne is None:
        modele_en_ligne = ModeleEnLigne.depuis_modele(modele, **REGLAGES_RETENUS)
    patients_appris = charger_patients_appris()

sejours = {}  # patient_id -> {heure: variables}, en attente du message de sortie


def predire_en_ligne(variables):
    """Risque de sepsis et explication, avec le modèle qui apprend."""
    risque = modele_en_ligne.predire(variables)
    contributions = modele_en_ligne.contributions(variables)
    plus_fortes = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return risque, [v for v, c in plus_fortes if c > 0]


def garder_variables(patient_id, heure, variables):
    """Garde les variables de chaque heure du patient jusqu'à son message de sortie."""
    if patient_id not in sejours:
        if len(sejours) >= SEJOURS_MAX:
            del sejours[next(iter(sejours))]  # le plus ancien : sa sortie n'est jamais arrivée
            stats["sejours_oublies"] += 1
        sejours[patient_id] = {}
    sejours[patient_id][heure] = variables


def traiter_sortie(s):
    """Fin de séjour : le modèle apprend des heures du patient que la passerelle a vues."""
    pid = s["patient_id"]
    heures = sejours.pop(pid, None)
    if modele_en_ligne is None:
        return
    if pid in patients_appris:
        stats["sorties_deja_apprises"] += 1  # patient rejoué : on n'apprend jamais deux fois
        return
    if not heures:
        stats["sorties_inconnues"] += 1  # aucune heure vue (passerelle démarrée après sa sortie, par exemple)
        return
    etiquettes = s["etiquettes"]
    n = 0
    for heure in sorted(heures):
        if 1 <= heure <= len(etiquettes):
            modele_en_ligne.apprendre(heures[heure], etiquettes[heure - 1])
            n += 1
    # on note le patient d'abord : après une coupure, on préfère perdre un patient que l'apprendre deux fois
    DOSSIER_ETAT.mkdir(parents=True, exist_ok=True)
    with open(CHEMIN_PATIENTS_APPRIS, "a", encoding="utf-8") as f:
        f.write(pid + "\n")
    patients_appris.add(pid)
    modele_en_ligne.sauvegarder(CHEMIN_MODELE_EN_LIGNE)
    stats["apprentissages"] += 1
    stats["heures_apprises"] += n



def fin_a_la_sortie(s):
    """Si le patient sort avec une alerte ouverte, la ferme et renvoie le message de fin à publier."""
    memoire = derniers.get(s.get("lit"))
    if (memoire is None or memoire["patient_id"] != s["patient_id"]
            or memoire["alerte_niveau"] == "aucune"):
        return None
    memoire.update(alerte_niveau="aucune", heures_calmes=0, heures_au_dessus=0)
    stats["alertes_fin"] += 1
    return {"patient_id": s["patient_id"], "service": SERVICE, "lit": s["lit"],
            "timestamp": s.get("timestamp"), "alerte": "fin", "raison_fin": "sortie",
            "priorite": "aucune", "alerte_niveau": "aucune",
            "passerelle": SERVICE, "schema_version": SCHEMA_VERSION}

def decider_alerte(memoire, prio, heure, fin_heures=FIN_HEURES,
                   persistance=PERSISTANCE_HEURES, rappel_heures=RAPPEL_HEURES, ecart=1,
                   news2_moyen=False, persistance_vigilance=PERSISTANCE_VIGILANCE):
    """Renvoie 'nouvelle', 'rappel', 'fin' ou None selon l'état de l'alerte du patient.

    ecart : nombre d'heures depuis le message précédent du patient (1 si aucune heure n'a été perdue).
    
    news2_moyen : vrai si le NEWS2 de l'heure est moyen. Une telle heure n'est pas « calme ».
    """
    # Des heures manquent : on ne sait pas si elles étaient calmes ou anormales,
    # donc les séries « de suite » repartent de zéro.
    if ecart > 1:
        memoire["heures_calmes"] = 0
        memoire["heures_au_dessus"] = 0
    active = memoire["alerte_niveau"]

    # La situation s'aggrave : alerte si elle dure assez longtemps (critique : immédiate)
    if ORDRE_PRIORITE[prio] > ORDRE_PRIORITE[active]:
        memoire["heures_au_dessus"] += 1
        memoire["heures_calmes"] = 0
        besoin = max(persistance, persistance_vigilance) if prio == "vigilance" else persistance
        if prio == "critique" or memoire["heures_au_dessus"] >= besoin:
            memoire.update(alerte_niveau=prio, alerte_depuis=heure, heures_au_dessus=0)
            return "nouvelle"
        return None
    memoire["heures_au_dessus"] = 0

    # Aucune alerte en cours et rien de nouveau
    if active == "aucune":
        return None

    # Alerte en cours, patient revenu au calme : fin après fin_heures heures calmes
    if prio == "aucune" and not news2_moyen:
        memoire["heures_calmes"] += 1
        if memoire["heures_calmes"] >= fin_heures:
            memoire.update(alerte_niveau="aucune", heures_calmes=0)
            return "fin"
        return None

    # Alerte en cours, situation toujours anormale : rappel toutes les rappel_heures heures
    memoire["heures_calmes"] = 0
    if heure - memoire["alerte_depuis"] >= rappel_heures:
        memoire["alerte_depuis"] = heure
        return "rappel"
    return None


def priorite(niveau, alerte_modele):
    """Grille : NEWS2 élevé et modèle combinés, le modèle n'enlève jamais d'alerte."""
    if niveau == "eleve":
        return "critique" if alerte_modele else "urgente"
    return "vigilance" if alerte_modele else "aucune"


derniers = {}  # lit -> dernières valeurs connues du patient présent
stats = {"recus": 0, "invalides": 0, "vides": 0, "valeurs_rejetees": 0,
         "incoherents": 0, "doublons": 0, "kafka_envoyes": 0, "kafka_erreurs": 0,
         "sans_memoire": 0, "alertes_nouvelle": 0, "alertes_rappel": 0, "alertes_fin": 0,
         "tampon_ecrits": 0, "tampon_renvoyes": 0, "tampon_perdus": 0,
         "apprentissages": 0, "heures_apprises": 0, "sorties_deja_apprises": 0,
         "sorties_inconnues": 0, "sorties_invalides": 0, "sejours_oublies": 0,"anciens_patients": 0,"heures_manquantes": 0}
cumul = {"reseau": 0.0, "traitement": 0.0}

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "vitals.enrichis")
producteur = None
if KAFKA_BOOTSTRAP:
    from confluent_kafka import Producer
    producteur = Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "linger.ms": 50,
        "enable.idempotence": True,
        "message.timeout.ms": 30000,
    })
DOSSIER_TAMPON = Path(os.environ.get("DOSSIER_TAMPON", Path(__file__).parent / "tampon"))
CHEMIN_TAMPON = DOSSIER_TAMPON / f"tampon-{SERVICE}.jsonl"
kafka_ok = False       # devient True dès qu'un message est confirmé par Kafka
dernier_vidage = 0.0


def rapport_kafka(err, msg):
    global kafka_ok
    if err is None:
        stats["kafka_envoyes"] += 1
        kafka_ok = True
        return
    stats["kafka_erreurs"] += 1
    kafka_ok = False
    cle = msg.key().decode() if msg.key() else None
    mettre_en_tampon(cle, msg.value().decode())


def mettre_en_tampon(cle, valeur):
    if tampon.ecrire(CHEMIN_TAMPON, cle, valeur):
        stats["tampon_ecrits"] += 1
    else:
        stats["tampon_perdus"] += 1   # tampon plein


def envoyer_kafka(cle, valeur):
    try:
        producteur.produce(KAFKA_TOPIC, key=cle, value=valeur, on_delivery=rapport_kafka)
    except BufferError:
        # file d'attente du producteur pleine : directement sur disque
        mettre_en_tampon(cle, valeur)


def vider_tampon_si_possible():
    global dernier_vidage
    if not kafka_ok or time.time() - dernier_vidage < 5:
        return
    dernier_vidage = time.time()
    n = tampon.vider(CHEMIN_TAMPON, envoyer_kafka)
    if n:
        stats["tampon_renvoyes"] += n
        print(f"[passerelle-{SERVICE}] {n} messages du tampon renvoyés à Kafka")

derniere_sauvegarde = 0.0
sauvegarde_active = False  # mise à True seulement quand la passerelle tourne vraiment (pas pendant les tests)


def sauvegarder_memoire():
    """Écrit la mémoire des lits et des séjours dans etat/, au plus toutes les SAUVEGARDE_SECONDES secondes."""
    global derniere_sauvegarde
    if not sauvegarde_active or time.time() - derniere_sauvegarde < SAUVEGARDE_SECONDES:
        return
    derniere_sauvegarde = time.time()
    DOSSIER_ETAT.mkdir(parents=True, exist_ok=True)
    tmp = CHEMIN_MEMOIRE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"derniers": derniers, "sejours": sejours}), encoding="utf-8")
    os.replace(tmp, CHEMIN_MEMOIRE)


def charger_memoire():
    """Relit la mémoire sauvegardée. Fichier absent ou abîmé : on garde une mémoire vide."""
    try:
        contenu = json.loads(CHEMIN_MEMOIRE.read_text(encoding="utf-8"))
        # JSON écrit les clés numériques en texte : on les remet en nombres
        lits = {int(lit): fiche for lit, fiche in contenu["derniers"].items()}
        attente = {pid: {int(h): v for h, v in heures.items()}
                   for pid, heures in contenu["sejours"].items()}
    except (OSError, ValueError, KeyError, AttributeError):
        return
    derniers.update(lits)
    sejours.update(attente)

def traiter(m):
    valeurs_rejetees = []
    valeurs = {}

    memoire = derniers.get(m["lit"])
    if (memoire is not None and memoire["patient_id"] != m["patient_id"]
            and est_plus_ancien(m.get("timestamp"), memoire["dernier_timestamp"])):
        stats["anciens_patients"] += 1
        return None
    if memoire is None or memoire["patient_id"] != m["patient_id"]:
        memoire = derniers[m["lit"]] = {"patient_id": m["patient_id"],
                                        "valeurs": {}, "derniere_heure": 0,
                                        "historique": [],
                                        "alerte_niveau": "aucune",
                                        "alerte_depuis": 0, "heures_calmes": 0,
                                        "heures_au_dessus": 0, "dernier_timestamp": None}
    heure = m["heure_sejour"]
    if heure <= memoire["derniere_heure"]:
        stats["doublons"] += 1
        return None
    ecart = heure - memoire["derniere_heure"] if memoire["derniere_heure"] > 0 else 1
    memoire["derniere_heure"] = heure
    memoire["dernier_timestamp"] = m.get("timestamp")
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
    if pressions_incoherentes(valeurs["sbp"], valeurs["map"], valeurs["dbp"]):
        incoherences.append("pression")

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
    m["heures_manquantes"] = ecart - 1
    stats["heures_manquantes"] += ecart - 1

    # 4. Modèle Edge : risque de sepsis
    ajouter_mesure(memoire["historique"], heure, nettoyer(m))
    alerte_modele = False
    if modele is not None:
        variables = calculer_variables(memoire["historique"], heure)
        if modele_en_ligne is not None:
            risque, explication = predire_en_ligne(variables)
            garder_variables(m["patient_id"], heure, variables)
            m["modele"] = "en_ligne"
            m["modele_nb_patients"] = len(patients_appris)
        else:
            risque, explication = predire(variables)
            m["modele"] = "fixe"
            m["modele_nb_patients"] = 0
        alerte_modele = risque >= modele["seuil"]
        m["risque_edge"] = round(risque, 4)
        m["risque_alerte"] = alerte_modele
        m["risque_explication"] = explication

    # 5. Priorité selon la grille
    m["priorite"] = priorite(niveau, alerte_modele)
    m["alerte"] = decider_alerte(memoire, m["priorite"], heure, ecart=ecart,
                                 news2_moyen=(niveau == "moyen"))
    m["alerte_niveau"] = memoire["alerte_niveau"]  
    if m["priorite"] != "aucune":
        stats["sans_memoire"] += 1
    if m["alerte"] is not None:
        stats["alertes_" + m["alerte"]] += 1
    return m

def est_plus_ancien(t1, t2):
    """Vrai si l'horodatage t1 est antérieur à t2 (faux si l'un des deux manque ou est illisible)."""
    try:
        return datetime.fromisoformat(t1) < datetime.fromisoformat(t2)
    except (TypeError, ValueError):
        return False

    
def on_connect(client, userdata, flags, reason_code, properties):
    if flags.session_present:
        print(f"[passerelle-{SERVICE}] session reprise : les messages en attente vont arriver")
    client.subscribe([(f"hopital/service-{SERVICE}/+/vitals", 1),
                      (f"hopital/service-{SERVICE}/+/sortie", 1)])
    client.publish(f"hopital/etat/passerelle-{SERVICE}", "en ligne", qos=1, retain=True)
    print(f"Passerelle {SERVICE} connectée")

def on_message(client, userdata, msg):
    sauvegarder_memoire()
    # Message de sortie : apprentissage, rien à republier
    if msg.topic.endswith("/sortie"):
        fin = None
        try:
            s = json.loads(msg.payload)
            fin = fin_a_la_sortie(s)
            traiter_sortie(s)
        except (ValueError, KeyError, TypeError):
            stats["sorties_invalides"] += 1
        if fin is not None:
            # alerte fermée parce que le patient est sorti : seulement pour Node-RED, pas pour Kafka
            client.publish(f"hopital/service-{SERVICE}/lit-{fin['lit']:02d}/news2", json.dumps(fin), qos=2)
        return
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
        envoyer_kafka(sortie["patient_id"], json.dumps(sortie))
        producteur.poll(0)
        vider_tampon_si_possible()
    if stats["recus"] % 100 == 0:
        n = stats["recus"] - stats["invalides"]
        print(stats, f"latence moy {cumul['reseau'] / n:.1f} ms,",
              f"traitement moy {cumul['traitement'] / n:.3f} ms")


if __name__ == "__main__":
    if modele_en_ligne is not None:
        print(f"[passerelle-{SERVICE}] apprentissage en ligne actif : "
              f"{len(patients_appris)} patients déjà appris, {modele_en_ligne.nb_exemples} heures")
    else:
        print(f"[passerelle-{SERVICE}] modèle fixe")
    
    charger_memoire()
    sauvegarde_active = True
    print(f"[passerelle-{SERVICE}] mémoire rechargée : {len(derniers)} lits, {len(sejours)} séjours en cours")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"passerelle-{SERVICE}",
                         clean_session=False)
    client.will_set(f"hopital/etat/passerelle-{SERVICE}", "hors ligne", qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883, keepalive=10)
    client.loop_forever()