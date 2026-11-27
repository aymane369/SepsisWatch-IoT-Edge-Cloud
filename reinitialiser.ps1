# Remet tout le système à zéro avant une démonstration.
# Conservés : le modèle entraîné hors ligne (passerelle/modele.json) et le flux Node-RED (nodered/).
$compose = "-f", "docker-compose.yml", "-f", "docker-compose.kafka-dev.yml"

docker compose @compose down
docker volume rm sepsiswatch-iot-edge-cloud_mosquitto_data
docker volume rm sepsiswatch-iot-edge-cloud_etat sepsiswatch-iot-edge-cloud_tampon 2>$null
docker compose @compose up -d --build

Write-Host "Systeme remis a zero : tout repart comme au premier demarrage."