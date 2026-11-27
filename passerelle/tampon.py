import json
import os
from pathlib import Path

TAILLE_MAX_OCTETS = 50 * 1024 * 1024  # 50 Mo par passerelle, pour ne pas remplir le disque


def ecrire(chemin, cle, valeur):
    """Ajoute un message non livré à la fin du tampon. Renvoie False si le tampon est plein."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if chemin.exists() and chemin.stat().st_size >= TAILLE_MAX_OCTETS:
        return False
    with open(chemin, "a", encoding="utf-8") as f:
        f.write(json.dumps({"cle": cle, "valeur": valeur}) + "\n")
    return True


def _relire(fichier, envoyer):
    n = 0
    with open(fichier, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                m = json.loads(ligne)
            except json.JSONDecodeError:
                continue  # ligne coupée par un arrêt brutal
            envoyer(m["cle"], m["valeur"])
            n += 1
    return n


def vider(chemin, envoyer):
    """Renvoie chaque message du tampon avec envoyer(cle, valeur). Renvoie le nombre de messages relus.

    Le fichier .envoi n'est PAS supprimé ici : l'appelant appelle terminer_envoi()
    quand Kafka a répondu pour tous ses messages. Après un plantage, il est donc relu.
    """
    chemin = Path(chemin)
    en_cours = chemin.with_suffix(".envoi")
    if not en_cours.exists():
        if not chemin.exists():
            return 0
        # on renomme d'abord : les échecs pendant le renvoi repartent dans un nouveau tampon
        os.replace(chemin, en_cours)
    # sinon, un .envoi existe encore (renvoi précédent interrompu) : on le relit en premier
    return _relire(en_cours, envoyer)


def terminer_envoi(chemin):
    """Supprime le fichier .envoi : Kafka a répondu pour tous les messages renvoyés."""
    Path(chemin).with_suffix(".envoi").unlink(missing_ok=True)
    """Renvoie chaque message du tampon avec envoyer(cle, valeur). Renvoie le nombre de messages relus."""
    chemin = Path(chemin)
    en_cours = chemin.with_suffix(".envoi")
    n = 0
    # un fichier .envoi qui existe encore vient d'un arrêt pendant un renvoi précédent
    if en_cours.exists():
        n += _relire(en_cours, envoyer)
    if chemin.exists():
        # on renomme d'abord : les échecs pendant le renvoi repartent dans un nouveau tampon
        os.replace(chemin, en_cours)
        n += _relire(en_cours, envoyer)
    return n