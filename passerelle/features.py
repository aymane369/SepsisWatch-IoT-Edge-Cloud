"""Nettoyage des mesures et calcul des variables du modèle.

Ce module est partagé par la passerelle (en direct) et par le script
d'entraînement (hors ligne), pour que les deux calculent exactement
les mêmes variables.
"""
from statistics import mean

SIGNES = ["hr", "o2sat", "temp", "sbp", "map", "dbp", "resp"]
BORNES = {"hr": (20, 300), "o2sat": (50, 100), "temp": (25, 45),
          "sbp": (30, 300), "map": (20, 250), "dbp": (10, 200),
          "resp": (1, 80)}
FENETRE_HEURES = 6
SUFFIXES = ("dernier", "moy", "min", "max", "delta", "age")


def nettoyer(mesure):
    """Renvoie les 7 signes utilisables : hors bornes et pressions incohérentes à None."""
    valeurs = {}
    for s in SIGNES:
        v = mesure.get(s)
        mini, maxi = BORNES[s]
        valeurs[s] = v if v is not None and mini <= v <= maxi else None
    sbp, pam, dbp = valeurs["sbp"], valeurs["map"], valeurs["dbp"]
    if ((dbp is not None and pam is not None and dbp > pam)
            or (pam is not None and sbp is not None and pam > sbp)
            or (dbp is not None and sbp is not None and dbp > sbp)):
        valeurs["map"] = None
        valeurs["dbp"] = None
    return valeurs


def ajouter_mesure(historique, heure, valeurs):
    """Ajoute une heure de mesures et oublie celles qui sortent de la fenêtre."""
    historique.append({"heure": heure, **valeurs})
    while heure - historique[0]["heure"] > FENETRE_HEURES:
        historique.pop(0)


def calculer_variables(historique, heure):
    """Calcule les 45 variables à partir de l'historique d'un patient."""
    variables = {"heure_sejour": heure}
    for s in SIGNES:
        points = [(e["heure"], e[s]) for e in historique if e[s] is not None]
        if points:
            valeurs = [v for _, v in points]
            h_der, v_der = points[-1]
            variables[f"{s}_dernier"] = v_der
            variables[f"{s}_moy"] = mean(valeurs)
            variables[f"{s}_min"] = min(valeurs)
            variables[f"{s}_max"] = max(valeurs)
            variables[f"{s}_delta"] = v_der - points[-2][1] if len(points) >= 2 else None
            variables[f"{s}_age"] = heure - h_der
        else:
            for suffixe in SUFFIXES:
                variables[f"{s}_{suffixe}"] = None
            variables[f"{s}_age"] = FENETRE_HEURES + 1
    hr = variables["hr_dernier"]
    sbp = variables["sbp_dernier"]
    dbp = variables["dbp_dernier"]
    variables["indice_choc"] = hr / sbp if hr is not None and sbp else None
    variables["pression_pulsee"] = sbp - dbp if sbp is not None and dbp is not None else None
    return variables