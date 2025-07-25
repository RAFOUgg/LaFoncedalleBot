# Étape 1: Utiliser une image de base Python officielle et légère
FROM python:3.11-slim

# Étape 2: Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Étape 3: Mettre à jour les paquets et installer les dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    pkg-config \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Étape 4: Copier le fichier des dépendances Python et les installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Étape 5: Copier tout le reste de votre application dans le conteneur
COPY . .

# [CORRECTION FINALE] Étape 6: Forcer le système à trouver et enregistrer les nouvelles polices
RUN fc-cache -f -v

# Étape 7: Rendre le script de démarrage exécutable
RUN chmod +x ./start.sh

# Étape 8: Exposer le port que gunicorn utilisera
EXPOSE 10000

# Étape 9: Définir la commande pour lancer l'application via le script
CMD ["./start.sh"]