#!/bin/bash

# Lancer le serveur web (le pont Flask) en arrière-plan
gunicorn app:app &

# Lancer le bot Discord au premier plan
python catalogue_final.py