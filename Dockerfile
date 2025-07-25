# Étape 1: Utiliser une image de base Python officielle et légère
FROM python:3.11-slim

# Étape 2: Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Étape 3: Mettre à jour les paquets et installer les dépendances système
# C'est ici que nous corrigeons l'erreur !
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    pkg-config \
    fontconfig \
    # Nettoyer le cache d'apt pour garder l'image légère
    && rm -rf /var/lib/apt/lists/*

# Étape 4: Copier le fichier des dépendances Python et les installer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Étape 5: Copier tout le reste de votre application dans le conteneur
COPY . .

# Étape 6: Exposer le port que gunicorn utilisera
EXPOSE 10000

RUN chmod +x ./start.sh

# Étape 8: Définir la commande pour lancer l'application via le script
CMD ["./start.sh"]