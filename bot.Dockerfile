# bot.Dockerfile

# --- Étape 1 : Le "builder" qui clone le dépôt ---
FROM python:3.11-slim AS builder

# Installer git
RUN apt-get update && apt-get install -y git

# Définir le répertoire de travail
WORKDIR /cloned_repo

# Recevoir les arguments de build
ARG GITHUB_TOKEN
ARG GITHUB_REPO_OWNER
ARG GITHUB_REPO_NAME

# Cloner le dépôt en utilisant le token pour l'authentification
RUN git clone https://${GITHUB_TOKEN}@github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}.git .


# --- Étape 2 : L'image finale du bot ---
FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système (comme avant)
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
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers du code cloné depuis l'étape "builder"
COPY --from=builder /cloned_repo .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier les polices et reconstruire le cache
COPY assets/Gobold-Bold.otf /usr/local/share/fonts/
COPY assets/Gobold-Regular.otf /usr/local/share/fonts/
RUN fc-cache -f -v

# Lancer le bot
CMD ["python", "bot_runner.py"]