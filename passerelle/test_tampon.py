import tempfile
from pathlib import Path
import tampon


def nouveau_chemin():
    return Path(tempfile.mkdtemp()) / "tampon-1.jsonl"


def test_ecrire_puis_vider():
    chemin = nouveau_chemin()
    tampon.ecrire(chemin, "p1", '{"a": 1}')
    tampon.ecrire(chemin, "p2", '{"a": 2}')
    recus = []
    n = tampon.vider(chemin, lambda c, v: recus.append((c, v)))
    assert n == 2
    assert recus == [("p1", '{"a": 1}'), ("p2", '{"a": 2}')]  # ordre conservé
    assert not chemin.exists()


def test_tampon_absent():
    assert tampon.vider(nouveau_chemin(), lambda c, v: None) == 0


def test_ligne_coupee_ignoree():
    chemin = nouveau_chemin()
    tampon.ecrire(chemin, "p1", '{"a": 1}')
    with open(chemin, "a", encoding="utf-8") as f:
        f.write('{"cle": "p2", "val')  # arrêt brutal au milieu d'une écriture
    recus = []
    assert tampon.vider(chemin, lambda c, v: recus.append(c)) == 1
    assert recus == ["p1"]


def test_tampon_plein():
    chemin = nouveau_chemin()
    ancien = tampon.TAILLE_MAX_OCTETS
    tampon.TAILLE_MAX_OCTETS = 10
    try:
        assert tampon.ecrire(chemin, "p1", '{"a": 1}') is True
        assert tampon.ecrire(chemin, "p2", '{"a": 2}') is False
    finally:
        tampon.TAILLE_MAX_OCTETS = ancien


def test_renvoi_interrompu_relu():
    chemin = nouveau_chemin()
    tampon.ecrire(chemin, "ancien", '{"a": 0}')
    chemin.rename(chemin.with_suffix(".envoi"))  # simule un arrêt pendant un renvoi
    tampon.ecrire(chemin, "nouveau", '{"a": 1}')
    recus = []
    assert tampon.vider(chemin, lambda c, v: recus.append(c)) == 1  # d'abord l'ancien renvoi
    tampon.terminer_envoi(chemin)
    assert tampon.vider(chemin, lambda c, v: recus.append(c)) == 1  # puis le nouveau tampon
    assert recus == ["ancien", "nouveau"]


def test_echec_pendant_renvoi_garde_le_message():
    chemin = nouveau_chemin()
    tampon.ecrire(chemin, "p1", '{"a": 1}')
    # Kafka retombe pendant le renvoi : le message repart dans le tampon
    tampon.vider(chemin, lambda c, v: tampon.ecrire(chemin, c, v))
    tampon.terminer_envoi(chemin)
    recus = []
    assert tampon.vider(chemin, lambda c, v: recus.append(c)) == 1
    assert recus == ["p1"]

def test_envoi_garde_jusqu_a_confirmation():
    chemin = nouveau_chemin()
    tampon.ecrire(chemin, "p1", '{"a": 1}')
    tampon.vider(chemin, lambda c, v: None)
    envoi = chemin.with_suffix(".envoi")
    assert envoi.exists()  # renvoyé mais pas encore confirmé : le fichier reste
    tampon.terminer_envoi(chemin)
    assert not envoi.exists()
    
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