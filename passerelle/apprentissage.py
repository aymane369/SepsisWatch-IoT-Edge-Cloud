import json
import math
import os
from pathlib import Path

BORNE_Z = 5.0  # une valeur standardisée est limitée à ±5 : une valeur extrême au début ne fait pas exploser les coefficients

# Réglages retenus dans l'expérience hors ligne (entrainement/en_ligne.py, hôpital B) :
# départ depuis modele.json, pas de 0,00003, poids de 1 pour garder l'échelle des probabilités
# (avec un poids de 10, la part d'heures en alerte dérivait de 10 % à 27 %).
REGLAGES_RETENUS = {"pas": 0.00003, "poids_positif": 1.0}


def _manquant(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _sigmoide(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class ModeleEnLigne:
    """Régression logistique mise à jour exemple par exemple (descente de gradient stochastique)."""

    CHAMPS = ["variables", "coef", "intercept", "n_vus", "moyennes", "m2",
              "pas", "poids_positif", "l2", "nb_exemples"]

    def __init__(self, variables, pas=0.01, poids_positif=10.0, l2=1e-4):
        self.variables = list(variables)
        n = len(self.variables)
        self.coef = [0.0] * n
        self.intercept = 0.0
        # moyennes et écarts calculés au fil de l'eau (méthode de Welford)
        self.n_vus = [0] * n
        self.moyennes = [0.0] * n
        self.m2 = [0.0] * n
        self.pas = pas
        self.poids_positif = poids_positif  # poids des heures sepsis dans l'apprentissage
        self.l2 = l2
        self.nb_exemples = 0

    @classmethod
    def depuis_modele(cls, modele, pseudo_effectif=1000, **reglages):
        """Démarre à partir du modèle entraîné hors ligne (modele.json)."""
        m = cls(modele["variables"], **reglages)

        def liste(champ):
            v = modele[champ]
            return [float(v[nom]) for nom in m.variables] if isinstance(v, dict) else [float(x) for x in v]

        m.coef = liste("coefficients")
        i = modele["intercept"]
        m.intercept = float(i[0] if isinstance(i, list) else i)
        m.moyennes = liste("moyennes")
        m.n_vus = [pseudo_effectif] * len(m.variables)
        m.m2 = [e * e * (pseudo_effectif - 1) for e in liste("ecarts")]
        return m

    # ---------- sauvegarde et chargement ----------

    def vers_dict(self):
        return {champ: getattr(self, champ) for champ in self.CHAMPS}

    @classmethod
    def depuis_dict(cls, d):
        m = cls(d["variables"])
        for champ in cls.CHAMPS:
            setattr(m, champ, d[champ])
        return m

    def sauvegarder(self, chemin):
        """Écrit d'abord un fichier temporaire puis le met à la place de l'ancien :
        une coupure pendant l'écriture ne laisse jamais un fichier à moitié écrit."""
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_suffix(".tmp")
        with open(temporaire, "w", encoding="utf-8") as f:
            json.dump(self.vers_dict(), f)
        os.replace(temporaire, chemin)

    @classmethod
    def charger(cls, chemin):
        """Renvoie le modèle sauvegardé, ou None si le fichier est absent ou abîmé."""
        chemin = Path(chemin)
        if not chemin.exists():
            return None
        try:
            with open(chemin, encoding="utf-8") as f:
                return cls.depuis_dict(json.load(f))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    # ---------- prédiction et apprentissage ----------

    def _vecteur(self, variables):
        xs = []
        for i, nom in enumerate(self.variables):
            x = variables.get(nom)
            if _manquant(x) or self.n_vus[i] == 0:
                xs.append(0.0)  # manquant : remplacé par la moyenne, soit 0 une fois standardisé
                continue
            ecart = math.sqrt(self.m2[i] / (self.n_vus[i] - 1)) if self.n_vus[i] > 1 else 0.0
            if ecart == 0.0:
                ecart = 1.0
            z = (float(x) - self.moyennes[i]) / ecart
            xs.append(max(-BORNE_Z, min(BORNE_Z, z)))
        return xs

    def predire(self, variables):
        xs = self._vecteur(variables)
        return _sigmoide(self.intercept + sum(c * x for c, x in zip(self.coef, xs)))

    def apprendre(self, variables, etiquette):
        # 1) mise à jour des moyennes et des écarts avec les valeurs présentes
        for i, nom in enumerate(self.variables):
            x = variables.get(nom)
            if _manquant(x):
                continue
            x = float(x)
            self.n_vus[i] += 1
            d = x - self.moyennes[i]
            self.moyennes[i] += d / self.n_vus[i]
            self.m2[i] += d * (x - self.moyennes[i])
        # 2) un pas de gradient
        xs = self._vecteur(variables)
        p = _sigmoide(self.intercept + sum(c * x for c, x in zip(self.coef, xs)))
        g = (p - etiquette) * (self.poids_positif if etiquette else 1.0)
        for i in range(len(xs)):
            self.coef[i] -= self.pas * (g * xs[i] + self.l2 * self.coef[i])
        self.intercept -= self.pas * g
        self.nb_exemples += 1