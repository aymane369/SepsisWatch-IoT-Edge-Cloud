# Remet tout le système à zéro avant une démonstration.
# Conservés : le modèle entraîné hors ligne (passerelle/modele.json) et le flux Node-RED (nodered/).
$compose = "-f", "docker-compose.yml", "-f", "docker-compose.kafka-dev.yml"

docker compose @compose down
docker volume rm sepsiswatch-iot-edge-cloud_mosquitto_data
Remove-Item etat\* -ErrorAction SilentlyContinue
Remove-Item tampon\* -ErrorAction SilentlyContinue
docker compose @compose up -d --build

Write-Host "Systeme remis a zero : tout repart comme au premier demarrage."