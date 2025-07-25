#!/bin/bash

# Lancer le processus du bot en arrière-plan
echo "--- Démarrage du Bot Discord en arrière-plan... ---"
python3 bot_runner.py &

# Attendre un peu pour que le bot se connecte
sleep 3

# Lancer le serveur web Gunicorn au premier plan
echo "--- Démarrage du serveur web Flask/Gunicorn... ---"
gunicorn --workers 3 --bind 0.0.0.0:10000 app:app