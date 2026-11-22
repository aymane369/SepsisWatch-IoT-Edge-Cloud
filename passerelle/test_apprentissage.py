import math
import os
import tempfile
from pathlib import Path

os.environ.setdefault("SERVICE", "1")
from apprentissage import ModeleEnLigne, REGLAGES_RETENUS
from passerelle import modele, predire


def depart():
    return ModeleEnLigne.depuis_modele(modele, **REGLAGES_RETENUS)


def exemple_complet(m, decalage=0.5):
    """Toutes les variables présentes, chacune à moyenne + decalage × écart."""
    v = {}
    for i, nom in enumerate(m.variables):
        ecart = math.sqrt(m.m2[i] / (m.n_vus[i] - 1))
        v[nom] = m.moyennes[i] + decalage * ecart
    return v


def test_depart_identique_au_modele_actuel():
    m = depart()
    v = exemple_complet(m)
    assert abs(m.predire(v) - predire(v)[0]) < 1e-6


def test_sauvegarder_puis_charger():
    m = depart()
    v = exemple_complet(m)
    for _ in range(20):
        m.apprendre(v, 1)
    chemin = Path(tempfile.mkdtemp()) / "modele_en_ligne.json"
    m.sauvegarder(chemin)
    relu = ModeleEnLigne.charger(chemin)
    assert relu is not None
    assert abs(relu.predire(v) - m.predire(v)) < 1e-12
    assert relu.nb_exemples == 20
    assert not chemin.with_suffix(".tmp").exists()  # le fichier temporaire a été remplacé


def test_fichier_absent():
    chemin = Path(tempfile.mkdtemp()) / "absent.json"
    assert ModeleEnLigne.charger(chemin) is None


def test_fichier_abime():
    chemin = Path(tempfile.mkdtemp()) / "abime.json"
    chemin.write_text('{"variables": ["hr_dernier"], "coef": [0.1', encoding="utf-8")  # coupé en plein milieu
    assert ModeleEnLigne.charger(chemin) is None


def test_apprendre_un_positif_augmente_le_risque():
    m = depart()
    v = exemple_complet(m)
    avant = m.predire(v)
    m.apprendre(v, 1)
    assert m.predire(v) > avant


def test_apprendre_un_negatif_baisse_le_risque():
    m = depart()
    v = exemple_complet(m)
    avant = m.predire(v)
    m.apprendre(v, 0)
    assert m.predire(v) < avant


def test_valeurs_manquantes():
    m = depart()
    v = {nom: None for nom in m.variables}
    v[m.variables[0]] = float("nan")
    r = m.predire(v)
    m.apprendre(v, 0)
    assert 0.0 < r < 1.0


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