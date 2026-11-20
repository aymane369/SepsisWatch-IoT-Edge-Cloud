"""Tests hors ligne du calcul des variables."""
from features import nettoyer, ajouter_mesure, calculer_variables, SIGNES


def mesure(**valeurs):
    """Fabrique une mesure, tous les signes absents par défaut."""
    m = {s: None for s in SIGNES}
    m.update(valeurs)
    return m


def historique_de(*heures_et_mesures):
    """Construit un historique à partir de couples (heure, mesure)."""
    h = []
    for heure, m in heures_et_mesures:
        ajouter_mesure(h, heure, nettoyer(m))
    return h


def test_nettoyer_hors_bornes():
    """Une valeur hors bornes devient None, la mesure d'origine reste intacte"""
    m = mesure(hr=900, resp=16)
    v = nettoyer(m)
    assert v["hr"] is None and v["resp"] == 16, v
    assert m["hr"] == 900, "la mesure d'origine a été modifiée"


def test_nettoyer_pressions_incoherentes():
    """Pressions incohérentes : MAP et DBP retirées, systolique gardée"""
    v = nettoyer(mesure(sbp=123, map=79, dbp=109))
    assert v["sbp"] == 123 and v["map"] is None and v["dbp"] is None, v


def test_fenetre_glissante():
    """L'historique ne garde que l'heure actuelle et les 6 précédentes"""
    h = historique_de(*[(heure, mesure(hr=80)) for heure in range(1, 11)])
    heures = [e["heure"] for e in h]
    assert heures == [4, 5, 6, 7, 8, 9, 10], heures


def test_statistiques():
    """HR 80, 90, 100 : dernier 100, moyenne 90, min 80, max 100, delta +10"""
    h = historique_de((1, mesure(hr=80)), (2, mesure(hr=90)), (3, mesure(hr=100)))
    v = calculer_variables(h, 3)
    obtenu = (v["hr_dernier"], v["hr_moy"], v["hr_min"], v["hr_max"],
              v["hr_delta"], v["hr_age"])
    assert obtenu == (100, 90, 80, 100, 10, 0), obtenu


def test_age_et_delta_manquant():
    """Température mesurée une seule fois à l'heure 1 : âge 3 à l'heure 4, pas de delta"""
    h = historique_de((1, mesure(temp=38.0)), (2, mesure()), (3, mesure()), (4, mesure()))
    v = calculer_variables(h, 4)
    assert v["temp_age"] == 3 and v["temp_delta"] is None, (v["temp_age"], v["temp_delta"])


def test_signe_jamais_mesure():
    """Signe jamais mesuré : valeurs None et âge à 7"""
    h = historique_de((1, mesure(hr=80)))
    v = calculer_variables(h, 1)
    assert v["dbp_dernier"] is None and v["dbp_age"] == 7, (v["dbp_dernier"], v["dbp_age"])


def test_variables_derivees():
    """HR 120 et SBP 100 : indice de choc 1,2 ; SBP 100 et DBP 60 : pression pulsée 40"""
    h = historique_de((1, mesure(hr=120, sbp=100, map=73, dbp=60)))
    v = calculer_variables(h, 1)
    assert v["indice_choc"] == 1.2 and v["pression_pulsee"] == 40, (v["indice_choc"], v["pression_pulsee"])


def test_nombre_de_variables():
    """Toujours 45 variables, même sans aucune mesure"""
    v = calculer_variables(historique_de((1, mesure())), 1)
    assert len(v) == 45, len(v)


TESTS = [test_nettoyer_hors_bornes, test_nettoyer_pressions_incoherentes,
         test_fenetre_glissante, test_statistiques, test_age_et_delta_manquant,
         test_signe_jamais_mesure, test_variables_derivees,
         test_nombre_de_variables]

if __name__ == "__main__":
    reussis = 0
    for test in TESTS:
        try:
            test()
            print("OK     ", test.__doc__)
            reussis += 1
        except AssertionError as e:
            print("ÉCHEC  ", test.__doc__, "| obtenu :", e)
        except Exception as e:
            print("ERREUR ", test.__doc__, "|", type(e).__name__, e)
    print(f"\n{reussis}/{len(TESTS)} tests réussis")