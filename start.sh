#!/bin/bash

# Lancer le serveur web Gunicorn en arrière-plan
echo "--- Démarrage du serveur web Flask/Gunicorn... ---"

# CORRECTION : Utilisation de workers 'gevent' plus performants pour les appels API
gunicorn --workers 3 --worker-class gevent --bind 0.0.0.0:10000 --timeout 60 app:app &

echo "--- Démarrage du Bot Discord au premier plan... ---"
python3 bot_runner.py