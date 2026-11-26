"""Garde une trace écrite de chaque exécution d'un script d'entraînement.

Tout ce que le script affiche est aussi ajouté à resultats/<nom du script>.txt,
précédé de la date et des arguments. Les résultats ne dépendent ainsi plus
d'une capture d'écran : ils sont dans le dépôt.
"""
import sys
from datetime import datetime
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent.parent / "resultats"


class _Double:
    """Écrit à la fois à l'écran et dans le fichier."""

    def __init__(self, ecran, fichier):
        self.ecran, self.fichier = ecran, fichier

    def write(self, texte):
        self.ecran.write(texte)
        self.fichier.write(texte)
        self.fichier.flush()

    def flush(self):
        self.ecran.flush()
        self.fichier.flush()


def enregistrer_sortie(chemin_script):
    """À appeler au début d'un script : enregistrer_sortie(__file__)."""
    DOSSIER.mkdir(exist_ok=True)
    nom = Path(chemin_script).stem
    fichier = open(DOSSIER / f"{nom}.txt", "a", encoding="utf-8")
    arguments = " ".join(sys.argv[1:]) or "(aucun)"
    fichier.write(f"\n{'=' * 70}\n{datetime.now():%Y-%m-%d %H:%M}  |  arguments : {arguments}\n{'=' * 70}\n")
    sys.stdout = _Double(sys.stdout, fichier)