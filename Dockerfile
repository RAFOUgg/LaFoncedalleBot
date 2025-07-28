# Étape 1: Image de base
FROM python:3.11-slim

# Étape 2: Définir le répertoire de travail
WORKDIR /app

# Étape 3: Installer les dépendances système
# [CORRECTION] Ajout des dépendances de développement pour Pillow (jpeg, freetype, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libfreetype6-dev \
    libraqm-dev \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Étape 4: Copier et installer les dépendances Python (pour optimiser le cache)
COPY requirements.txt .
# Cette commande devrait maintenant fonctionner grâce aux dépendances système
RUN pip install --no-cache-dir --force-reinstall --no-binary Pillow -r requirements.txt

# Étape 5: Copier tout le reste du code de l'application
COPY . .

# Étape 6: Vérifier que le support pour les émojis (Raqm) est bien activé
RUN python -m PIL.features

# Étape 7: Forcer le système à trouver les polices copiées
RUN fc-cache -f -v

# La commande de démarrage est gérée par docker-compose.yml