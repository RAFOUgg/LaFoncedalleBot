# Étape 1: Utiliser une image de base Python officielle et légère
FROM python:3.11-slim

# Étape 2: Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Étape 3: Mettre à jour les paquets et installer les dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    pkg-config \
    fontconfig \
    libharfbuzz-dev \
    libfribidi-dev \
    libraqm-dev \
    && rm -rf /var/lib/apt/lists/*

# Étape 4: Copier le fichier des dépendances Python
COPY requirements.txt .

# Étape 5: Forcer la recompilation de Pillow et installer les dépendances
# --- C'EST LA MODIFICATION CRUCIALE ---
# --no-binary :all: force pip à compiler depuis les sources au lieu d'utiliser des paquets pré-compilés
# Cela permet à Pillow de détecter et d'utiliser libraqm que nous venons d'installer.
RUN pip install --no-cache-dir --force-reinstall --no-binary :all: -r requirements.txt

# Étape 6: Vérifier que le support RAQM est bien activé dans Pillow (pour le débogage)
# Cherchez "RAQM" et "HarfBuzz" avec la valeur "True" dans les logs de déploiement.
RUN python -m PIL.features

# Étape 7: Copier tout le reste de votre application dans le conteneur
COPY . .

# Étape 8: Forcer le système à trouver et enregistrer les nouvelles polices
RUN fc-cache -f -v

# Étape 9: Rendre le script de démarrage exécutable
RUN chmod +x ./start.sh

# Étape 10: Exposer le port que gunicorn utilisera
EXPOSE 10000

# Étape 11: Définir la commande pour lancer l'application via le script
CMD ["./start.sh"]