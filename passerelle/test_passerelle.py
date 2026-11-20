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
    traiter(message(heure_sejour=1, **{**NORMAL, "temp": 39.5}))
    r = traiter(message(heure_sejour=2, **{**NORMAL, "temp": None}))
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

def test_valeur_recente_reprise():
    """Une valeur de 3 heures est reprise et comptée comme reprise"""
    traiter(message(heure_sejour=1, **{**NORMAL, "temp": 39.5}))
    r = traiter(message(heure_sejour=4, **{**NORMAL, "temp": None}))
    assert r["news2"] == 2 and r["news2_nb_reprises"] == 1, (r["news2"], r["news2_nb_reprises"])


def test_valeur_trop_ancienne():
    """Une valeur de plus de 6 heures n'est plus utilisée"""
    traiter(message(heure_sejour=1, **{**NORMAL, "temp": 39.5}))
    r = traiter(message(heure_sejour=10, **{**NORMAL, "temp": None}))
    assert r["news2"] == 0 and r["news2_nb_params"] == 4, (r["news2"], r["news2_nb_params"])

def test_doublon_ignore():
    """Un second message à la même heure est ignoré et compté"""
    avant = stats["doublons"]
    traiter(message(heure_sejour=5, **NORMAL))
    r = traiter(message(heure_sejour=5, **NORMAL))
    assert r is None and stats["doublons"] == avant + 1, (r, stats["doublons"])


def test_message_en_retard():
    """Un message plus ancien que le dernier traité est ignoré"""
    traiter(message(heure_sejour=5, **NORMAL))
    r = traiter(message(heure_sejour=3, **NORMAL))
    assert r is None, r

TESTS = [test_valeur_hors_bornes, test_valeur_rejetee_exclue_du_score,
         test_pression_incoherente, test_pression_coherente,
         test_patient_sans_mesure, test_score_moyen, test_score_eleve,
         test_derniere_valeur_reprise, test_changement_de_patient,
         test_message_mal_forme, test_valeur_recente_reprise,
         test_valeur_trop_ancienne,test_doublon_ignore,
         test_message_en_retard]

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
        except Exception as e:
            print("ERREUR ", test.__doc__, "|", type(e).__name__, e)
    print(f"\n{reussis}/{len(TESTS)} tests réussis")