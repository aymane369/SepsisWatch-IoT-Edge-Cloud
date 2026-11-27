"""Crée les comptes MQTT : un mot de passe par client, gardé dans .env, et le fichier passwd de Mosquitto.
À lancer depuis la racine du projet : python mosquitto/creer_comptes.py"""
import secrets
import subprocess
from pathlib import Path

COMPTES = {
    "simulateur": "MQTT_MDP_SIMULATEUR",
    "passerelle-1": "MQTT_MDP_PASSERELLE_1",
    "passerelle-2": "MQTT_MDP_PASSERELLE_2",
    "passerelle-3": "MQTT_MDP_PASSERELLE_3",
    "passerelle-4": "MQTT_MDP_PASSERELLE_4",
    "nodered": "MQTT_MDP_NODERED",
    "sante": "MQTT_MDP_SANTE",
    "admin": "MQTT_MDP_ADMIN",
}

# 1. Un mot de passe par compte, ajouté à .env s'il n'existe pas encore
env = Path(".env")
lignes = env.read_text(encoding="utf-8-sig").splitlines() if env.exists() else []
valeurs = dict(l.split("=", 1) for l in lignes if "=" in l and not l.startswith("#"))
for var in COMPTES.values():
    if not valeurs.get(var):
        valeurs[var] = secrets.token_hex(16)
        lignes.append(f"{var}={valeurs[var]}")
env.write_text("\n".join(lignes) + "\n", encoding="utf-8")

# 2. Le fichier passwd de Mosquitto (mots de passe hachés), créé avec l'outil officiel mosquitto_passwd
dossier = Path("mosquitto/config").resolve()
commandes = " && ".join(
    f"mosquitto_passwd {'-c ' if i == 0 else ''}-b /m/passwd {nom} {valeurs[var]}"
    for i, (nom, var) in enumerate(COMPTES.items()))
# Mosquitto ne tourne pas en administrateur : les fichiers doivent appartenir à son utilisateur
commandes += " && chown mosquitto:mosquitto /m/passwd /m/acl && chmod 0700 /m/passwd /m/acl"
subprocess.run(["docker", "run", "--rm", "-v", f"{dossier}:/m", "eclipse-mosquitto:2", "sh", "-c", commandes],
               check=True)
print("Comptes créés :", ", ".join(COMPTES))