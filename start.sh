#!/bin/bash
echo "--- Démarrage du serveur web Flask/Gunicorn... ---"
# ON PASSE DE 3 WORKERS À 1 POUR ÉCONOMISER LA RAM
gunicorn --workers 1 --worker-class gevent --bind 0.0.0.0:10000 --timeout 60 app:app &

echo "--- Démarrage du Bot Discord au premier plan... ---"
python3 bot_runner.py