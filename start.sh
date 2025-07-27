#!/bin/bash
#!/bin/bash

echo "--- Démarrage du Bot Discord en arrière-plan... ---"
python3 bot_runner.py

echo "--- Démarrage du serveur web Flask/Gunicorn au premier plan... ---"
# Gunicorn est maintenant le processus principal. Le conteneur restera en vie tant qu'il tourne.
gunicorn --workers 1 --bind 0.0.0.0:10000 --timeout 60 app:app