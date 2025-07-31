# Étape 1: Image de base
FROM python:3.11-slim

# Étape 2: Définir le répertoire de travail
WORKDIR /app

# Étape 3: Installer les dépendances système, y compris git
# L'option --no-install-recommends est ajoutée pour garder l'image légère
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
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
    # Nettoie le cache apt pour réduire la taille de l'image
    && rm -rf /var/lib/apt/lists/*

# Étape 4: Copier et installer les dépendances Python (pour optimiser le cache Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Étape 5: Copier tout le reste du code de l'application
COPY . .

# Étape 6: Copier les polices et reconstruire le cache de polices
COPY assets/Gobold-Bold.otf /usr/local/share/fonts/
COPY assets/Gobold-Regular.otf /usr/local/share/fonts/
RUN fc-cache -f -v

# Étape 7: (Optionnel) Vérifier que le support pour les émojis (Raqm) est bien activé
RUN python -m PIL.features

# Étape 8: Spécifier la commande à exécuter
# On utilise la liste pour être plus propre que la chaîne de caractères
CMD ["python", "bot_runner.py"]