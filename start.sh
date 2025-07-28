#!/bin/sh

# Lance l'API Flask (gunicorn) en arrière-plan
echo "--- Démarrage de l'API Flask (Gunicorn)... ---"
gunicorn --bind 0.0.0.0:10000 app:app &

# Attend une seconde pour être sûr que l'API a démarré
sleep 1

# Lance le Bot Discord en avant-plan
echo "--- Démarrage du Bot Discord... ---"
python bot_runner.py