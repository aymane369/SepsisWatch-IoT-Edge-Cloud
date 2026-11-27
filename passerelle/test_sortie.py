"""Tests de l'apprentissage dans la passerelle, sans MQTT ni Docker.
Le modèle et la liste des patients appris sont écrits dans un dossier temporaire."""
import json
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("SERVICE", "1")
os.environ["APPRENTISSAGE"] = "1"
os.environ["DOSSIER_ETAT"] = tempfile.mkdtemp()  # ne touche jamais au vrai dossier etat/
os.environ["DOSSIER_TAMPON"] = tempfile.mkdtemp()  # ni au vrai dossier tampon/

import passerelle
import tampon
from apprentissage import ModeleEnLigne


def sejour(patient, lit, nb_heures):
    """Envoie nb_heures messages de signes vitaux normaux pour un patient."""
    for h in range(1, nb_heures + 1):
        passerelle.traiter({"patient_id": patient, "service": 1, "lit": lit, "heure_sejour": h,
                            "hr": 80.0, "o2sat": 98.0, "temp": 37.0, "sbp": 120.0,
                            "map": 85.0, "dbp": 70.0, "resp": 16.0})


def test_le_message_indique_le_modele():
    m = passerelle.traiter({"patient_id": "pt-modele", "service": 1, "lit": 11, "heure_sejour": 1,
                            "hr": 80.0, "o2sat": 98.0, "temp": 37.0, "sbp": 120.0,
                            "map": 85.0, "dbp": 70.0, "resp": 16.0})
    assert m["modele"] == "en_ligne"
    assert m["schema_version"] == 4
    assert 0.0 < m["risque_edge"] < 1.0


def test_sortie_fait_apprendre():
    avant = passerelle.modele_en_ligne.nb_exemples
    sejour("pt-a", 12, 3)
    passerelle.traiter_sortie({"patient_id": "pt-a", "etiquettes": [0, 0, 1]})
    assert passerelle.modele_en_ligne.nb_exemples == avant + 3
    assert "pt-a" in passerelle.patients_appris
    assert "pt-a" not in passerelle.sejours  # séjour libéré de la mémoire


def test_meme_sortie_deux_fois():
    sejour("pt-b", 13, 2)
    passerelle.traiter_sortie({"patient_id": "pt-b", "etiquettes": [0, 0]})
    apres_premiere = passerelle.modele_en_ligne.nb_exemples
    deja = passerelle.stats["sorties_deja_apprises"]
    sejour("pt-b", 14, 2)  # le simulateur rejoue le même patient
    passerelle.traiter_sortie({"patient_id": "pt-b", "etiquettes": [0, 0]})
    assert passerelle.modele_en_ligne.nb_exemples == apres_premiere
    assert passerelle.stats["sorties_deja_apprises"] == deja + 1


def test_sortie_patient_inconnu():
    avant = passerelle.stats["sorties_inconnues"]
    passerelle.traiter_sortie({"patient_id": "pt-jamais-vu", "etiquettes": [0, 1]})
    assert passerelle.stats["sorties_inconnues"] == avant + 1


def test_reprise_apres_redemarrage():
    sejour("pt-c", 15, 2)
    passerelle.traiter_sortie({"patient_id": "pt-c", "etiquettes": [1, 1]})
    relu = ModeleEnLigne.charger(passerelle.CHEMIN_MODELE_EN_LIGNE)
    assert relu is not None
    assert relu.nb_exemples == passerelle.modele_en_ligne.nb_exemples
    assert "pt-c" in passerelle.charger_patients_appris()


def test_heures_hors_liste_ignorees():
    avant = passerelle.modele_en_ligne.nb_exemples
    sejour("pt-d", 16, 4)
    passerelle.traiter_sortie({"patient_id": "pt-d", "etiquettes": [0, 0]})  # liste plus courte
    assert passerelle.modele_en_ligne.nb_exemples == avant + 2

def test_memoire_sauvegardee_et_rechargee():
    sejour("pt-memo", 17, 3)
    passerelle.derniers[17]["alerte_niveau"] = "urgente"
    passerelle.sauvegarde_active = True
    passerelle.derniere_sauvegarde = 0.0
    passerelle.sauvegarder_memoire()
    passerelle.sauvegarde_active = False
    passerelle.derniers.clear()  # comme un redémarrage : la mémoire vive est vide
    passerelle.sejours.clear()
    passerelle.charger_memoire()
    assert passerelle.derniers[17]["alerte_niveau"] == "urgente"
    assert passerelle.derniers[17]["derniere_heure"] == 3
    assert sorted(passerelle.sejours["pt-memo"]) == [1, 2, 3]
    avant = passerelle.stats["doublons"]
    sejour("pt-memo", 17, 3)  # les heures 1 à 3 renvoyées : reconnues comme doublons
    assert passerelle.stats["doublons"] == avant + 3
def test_deux_sejours_par_lit():
    avant = passerelle.stats["sejours_oublies"]
    sejour("pt-lit-a", 18, 2)  # trois patients se suivent dans le lit 18, aucune sortie n'arrive
    sejour("pt-lit-b", 18, 2)
    assert "pt-lit-a" in passerelle.sejours  # sa sortie peut encore arriver
    sejour("pt-lit-c", 18, 2)
    assert "pt-lit-a" not in passerelle.sejours  # parti depuis deux admissions : oublié
    assert "pt-lit-b" in passerelle.sejours and "pt-lit-c" in passerelle.sejours
    assert passerelle.stats["sejours_oublies"] == avant + 1   


class FauxProducteur:
    """Remplace Kafka : garde les accusés de réception pour les déclencher à la main."""
    def __init__(self):
        self.envois = []

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.envois.append((on_delivery, key, value))
    def poll(self, delai):
        return 0

class FauxMessage:
    def __init__(self, cle, valeur):
        self.cle, self.valeur = cle, valeur

    def key(self):
        return self.cle.encode()

    def value(self):
        return self.valeur.encode()


def test_tampon_garde_jusqu_a_confirmation():
    faux = FauxProducteur()
    passerelle.producteur, passerelle.kafka_ok, passerelle.dernier_vidage = faux, True, 0.0
    try:
        tampon.ecrire(passerelle.CHEMIN_TAMPON, "p1", '{"a": 1}')
        tampon.ecrire(passerelle.CHEMIN_TAMPON, "p2", '{"a": 2}')
        passerelle.vider_tampon_si_possible()
        envoi = passerelle.CHEMIN_TAMPON.with_suffix(".envoi")
        assert len(faux.envois) == 2 and envoi.exists()  # renvoyés, pas encore confirmés : fichier gardé
        rapport, cle, valeur = faux.envois[0]
        rapport(None, FauxMessage(cle, valeur))  # Kafka confirme le premier
        assert envoi.exists()
        rapport, cle, valeur = faux.envois[1]
        rapport(None, FauxMessage(cle, valeur))  # puis le second
        assert not envoi.exists()  # tout est confirmé : fichier supprimé
    finally:
        passerelle.producteur = None


def test_journal_garde_jusqu_a_confirmation():
    faux = FauxProducteur()
    passerelle.producteur = faux
    try:
        passerelle.envoyer_kafka("p1", '{"a": 1}')
        morceau = next(iter(passerelle.journal_en_attente))
        assert morceau.exists()  # une copie sur le disque avant l'envoi
        passerelle.liberer_journal(tout=True)
        assert morceau.exists()  # pas encore confirmé : on la garde
        rapport, cle, valeur = faux.envois[0]
        rapport(None, FauxMessage(cle, valeur))  # Kafka confirme
        passerelle.liberer_journal(tout=True)
        assert not morceau.exists()  # confirmé : copie supprimée
    finally:
        passerelle.producteur = None
        passerelle.journal_en_attente.clear()


def test_journal_repris_au_demarrage():
    reste = passerelle.DOSSIER_TAMPON / f"journal-{passerelle.SERVICE}-1.jsonl"
    tampon.ecrire(reste, "p9", '{"a": 9}')  # morceau laissé par un plantage
    assert passerelle.reprendre_journal() == 1
    assert not reste.exists()
    recus = []
    tampon.vider(passerelle.CHEMIN_TAMPON, lambda c, v: recus.append(c))
    tampon.terminer_envoi(passerelle.CHEMIN_TAMPON)
    assert recus == ["p9"]  # il attend dans le tampon, prêt à être renvoyé

def test_pseudonyme_stable_et_secret():
    passerelle.PSEUDO_CLE = "cle-de-test"
    try:
        a = passerelle.pseudonyme("p015081")
        assert a == passerelle.pseudonyme("p015081")  # même patient : même pseudonyme
        assert a != "p015081" and a != passerelle.pseudonyme("p015082")
        passerelle.PSEUDO_CLE = "autre-cle"
        assert passerelle.pseudonyme("p015081") != a  # sans la bonne clé, impossible de le retrouver
    finally:
        passerelle.PSEUDO_CLE = ""


class FauxClient:
    """Remplace Mosquitto : garde les messages publiés."""
    def __init__(self):
        self.publies = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.publies.append((topic, payload))


def test_kafka_recoit_un_pseudonyme():
    faux, client = FauxProducteur(), FauxClient()
    passerelle.producteur, passerelle.PSEUDO_CLE = faux, "cle-de-test"
    try:
        m = {"patient_id": "pt-vrai", "service": 1, "lit": 19, "heure_sejour": 1,
             "timestamp": "2026-11-27T03:00:00+00:00",
             "hr": 80.0, "o2sat": 98.0, "temp": 37.0, "sbp": 120.0, "map": 85.0, "dbp": 70.0, "resp": 16.0}
        passerelle.on_message(client, None, SimpleNamespace(topic="hopital/service-1/lit-19/vitals",
                                                            payload=json.dumps(m).encode()))
        _, cle, valeur = faux.envois[-1]
        assert cle == passerelle.pseudonyme("pt-vrai") and json.loads(valeur)["patient_id"] == cle
        assert json.loads(client.publies[-1][1])["patient_id"] == "pt-vrai"  # Node-RED garde le vrai
    finally:
        passerelle.producteur, passerelle.PSEUDO_CLE = None, ""
        passerelle.journal_en_attente.clear()
if __name__ == "__main__":
    tests = [f for nom, f in list(globals().items()) if nom.startswith("test_")]
    reussis = 0
    for t in tests:
        try:
            t()
            print(f"OK      {t.__name__}")
            reussis += 1
        except AssertionError:
            print(f"ÉCHEC   {t.__name__}")
        except Exception as e:
            print(f"ERREUR  {t.__name__} : {e}")
    print(f"{reussis}/{len(tests)} réussis")