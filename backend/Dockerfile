# Image de base : Python 3.12 "slim" (légère, sans les outils inutiles)
FROM python:3.12-slim

# Dossier de travail à l'intérieur du conteneur
WORKDIR /app

# On copie d'abord uniquement ce qui décrit les dépendances (pyproject.toml)
# et le code source. Docker met en cache chaque étape : si tu ne changes
# que le code, la ré-installation des dépendances n'est rejouée que si
# pyproject.toml a changé.
COPY pyproject.toml ./
COPY src ./src

# Installe le package "motor" et ses dépendances de RUNTIME uniquement
# (fastapi, uvicorn) — pas pytest/httpx qui sont réservés au développement.
RUN pip install --no-cache-dir .

# Bonne pratique : ne pas exécuter l'application en tant que root
# à l'intérieur du conteneur.
RUN useradd --create-home appuser

# Pré-crée le dossier de stockage des archives (bilan financier) et le
# donne à appuser : c'est ce contenu/ces droits que Docker copiera dans le
# volume nommé "bank_archives" (docker-compose.yml) lors de sa toute
# première création — indispensable, un simple bind mount ne le ferait pas
# (il refléterait tel quel un dossier hôte, créé root par défaut).
RUN mkdir -p /app/data/bank_archives && chown -R appuser:appuser /app/data

USER appuser

# Documente le port utilisé par l'API (n'ouvre rien à lui seul,
# c'est docker-compose.yml qui décide de ce qui est exposé/publié).
EXPOSE 8000

# Commande lancée au démarrage du conteneur.
CMD ["python", "-m", "app.main"]
