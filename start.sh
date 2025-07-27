
echo "--- Démarrage du Bot Discord en arrière-plan... ---"
python3 bot_runner.py &

echo "--- Démarrage du serveur web Flask/Gunicorn au premier plan... ---"
gunicorn --workers 1 --bind 0.0.0.0:10000 --timeout 60 app:app