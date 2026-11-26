"""Tests de l'apprentissage dans la passerelle, sans MQTT ni Docker.
Le modèle et la liste des patients appris sont écrits dans un dossier temporaire."""
import os
import tempfile

os.environ.setdefault("SERVICE", "1")
os.environ["APPRENTISSAGE"] = "1"
os.environ["DOSSIER_ETAT"] = tempfile.mkdtemp()  # ne touche jamais au vrai dossier etat/

import passerelle
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