# Étape 1: Image de base
FROM python:3.11-slim

# Étape 2: Définir le répertoire de travail
WORKDIR /app

# Étape 3: Installer les dépendances système
# [CORRECTION] Remplacement de 'libfontconfig1' par 'fontconfig' pour inclure fc-cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libpoppler-cpp-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libfreetype6-dev \
    libraqm-dev \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Étape 4: Copier et installer les dépendances Python (pour optimiser le cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Étape 5: Copier tout le reste du code de l'application
COPY . .

# Étape 6: Vérifier que le support pour les émojis (Raqm) est bien activé
COPY assets/Gobold-Bold.otf /usr/local/share/fonts/
COPY assets/Gobold-Regular.otf /usr/local/share/fonts/
RUN python -m PIL.features

RUN fc-cache -f -v
