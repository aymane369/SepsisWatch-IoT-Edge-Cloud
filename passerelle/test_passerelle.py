"""Tests hors ligne de la passerelle : aucun MQTT, aucun Kafka."""
import json
from types import SimpleNamespace

from passerelle import traiter, on_message, derniers, stats


def message(lit=1, patient="ptest", **valeurs):
    """Fabrique un message de test, toutes les mesures absentes par défaut."""
    m = {"patient_id": patient, "service": 1, "lit": lit, "heure_sejour": 1,
         "timestamp": "2026-11-20T10:00:00+00:00",
         "hr": None, "o2sat": None, "temp": None, "sbp": None,
         "map": None, "dbp": None, "resp": None}
    m.update(valeurs)
    return m


NORMAL = {"resp": 16, "o2sat": 98, "sbp": 120, "hr": 80, "temp": 37.0}


def test_valeur_hors_bornes():
    """Une valeur impossible est signalée, sans modifier le message"""
    r = traiter(message(**{**NORMAL, "hr": 900}))
    assert "hr" in r["valeurs_rejetees"], r["valeurs_rejetees"]
    assert r["hr"] == 900, "la valeur d'origine a été modifiée"


def test_valeur_rejetee_exclue_du_score():
    """Une valeur rejetée ne compte pas dans NEWS2"""
    r = traiter(message(**{**NORMAL, "hr": 900}))
    assert r["news2"] == 0 and r["news2_nb_params"] == 4, (r["news2"], r["news2_nb_params"])


def test_pression_incoherente():
    """Pressions impossibles (DBP > MAP) signalées"""
    r = traiter(message(sbp=123, map=79, dbp=109))
    assert r["incoherences"] == ["pression"], r["incoherences"]


def test_pression_coherente():
    """Pressions normales non signalées"""
    r = traiter(message(sbp=120, map=93, dbp=80))
    assert r["incoherences"] == [], r["incoherences"]


def test_patient_sans_mesure():
    """Sans mesure, le niveau est indéterminé"""
    r = traiter(message())
    assert r["niveau"] == "indetermine" and r["news2_nb_params"] == 0, (r["niveau"], r["news2_nb_params"])


def test_score_moyen():
    """Score connu : 2 + 2 + 1 + 0 + 1 = 6, niveau moyen"""
    r = traiter(message(resp=22, o2sat=93, sbp=105, hr=88, temp=38.4))
    assert r["news2"] == 6 and r["niveau"] == "moyen", (r["news2"], r["niveau"])


def test_score_eleve():
    """Score connu : 3 + 1 + 2 + 2 = 8 sur 4 paramètres, niveau élevé"""
    r = traiter(message(hr=141, o2sat=94.5, temp=39.06, resp=21.5))
    assert r["news2"] == 8 and r["niveau"] == "eleve", (r["news2"], r["niveau"])


def test_derniere_valeur_reprise():
    """Une mesure absente reprend la dernière valeur du même patient"""
    traiter(message(**{**NORMAL, "temp": 39.5}))
    r = traiter(message(**{**NORMAL, "temp": None}))
    assert r["news2"] == 2, r["news2"]


def test_changement_de_patient():
    """Un nouveau patient dans le lit repart d'une mémoire vide"""
    traiter(message(patient="pA", **NORMAL))
    r = traiter(message(patient="pB"))
    assert r["niveau"] == "indetermine", r["niveau"]


def test_message_mal_forme():
    """Un JSON coupé est compté comme invalide, sans planter"""
    avant = stats["invalides"]
    texte = json.dumps(message(**NORMAL))[:-10]
    on_message(None, None, SimpleNamespace(payload=texte.encode()))
    assert stats["invalides"] == avant + 1, stats["invalides"]


TESTS = [test_valeur_hors_bornes, test_valeur_rejetee_exclue_du_score,
         test_pression_incoherente, test_pression_coherente,
         test_patient_sans_mesure, test_score_moyen, test_score_eleve,
         test_derniere_valeur_reprise, test_changement_de_patient,
         test_message_mal_forme]

if __name__ == "__main__":
    reussis = 0
    for test in TESTS:
        derniers.clear()
        try:
            test()
            print("OK     ", test.__doc__)
            reussis += 1
        except AssertionError as e:
            print("ÉCHEC  ", test.__doc__, "| obtenu :", e)
    print(f"\n{reussis}/{len(TESTS)} tests réussis")