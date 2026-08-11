# Déploiement (Docker + VPS Hostinger)

Ce document explique comment fonctionne le "dockerisation" de ce projet et
comment le déployer sur un VPS Hostinger. Écrit pour quelqu'un qui découvre
Docker.

## 1. C'est quoi Docker, en une minute ?

- Une **image** Docker est un paquet autonome contenant le code de
  l'application ET tout ce dont elle a besoin pour tourner (Python, ses
  librairies, etc.). On la construit une fois à partir d'un `Dockerfile`
  (la recette).
- Un **conteneur** est une instance en cours d'exécution de cette image —
  un peu comme une mini-machine isolée, mais beaucoup plus légère qu'une
  VM classique.
- **docker-compose** permet de décrire plusieurs conteneurs qui doivent
  tourner ensemble (ici : le backend et le frontend) et de les démarrer
  d'une seule commande.

Intérêt concret ici : le VPS n'a besoin d'installer que Docker. Pas besoin
d'installer Python, Node, nginx, ni de gérer les versions à la main —
tout est déjà emballé dans les images.

## 2. Ce qui a été mis en place dans ce repo

```
test-python/
├── backend/
│   ├── Dockerfile        # construit l'image de l'API FastAPI
│   └── .dockerignore     # fichiers à ne pas copier dans l'image (venv, tests, ...)
├── frontend/
│   ├── Dockerfile        # build multi-étapes : Node compile React, puis Caddy sert les fichiers
│   ├── Caddyfile          # configuration Caddy : sert le front + proxy vers l'API + HTTPS auto
│   └── .dockerignore
└── docker-compose.yml     # démarre les 2 conteneurs ensemble
```

### Le backend (`backend/Dockerfile`)

Construit une image Python 3.12 "slim", installe le package `motor` (donc
`fastapi` + `uvicorn`), et lance `python -m motor.main` au démarrage.
Le conteneur écoute sur le port 8000, mais **n'est pas exposé directement
à Internet** — voir plus bas.

### Le frontend (`frontend/Dockerfile`)

Ce Dockerfile a **deux étapes** :

1. **Étape "build"** : une image Node compile l'app React (`npm run build`)
   et produit des fichiers statiques (HTML/CSS/JS) dans `dist/`.
2. **Étape finale** : une image **Caddy** (serveur web léger), dans
   laquelle on copie uniquement les fichiers `dist/` produits à l'étape 1.

Résultat : l'image finale ne contient ni Node ni le code source React —
juste Caddy et les fichiers statiques. Elle est donc petite et sécurisée.

`Caddyfile` fait trois choses :
- sert le site React sur `/`.
- redirige (`reverse_proxy`) tout ce qui arrive sur `/api/...` vers le
  conteneur `backend` sur le port 8000. Exemple : une requête vers
  `/api/motor` est transmise à `http://backend:8000/motor`.
- **obtient et renouvelle automatiquement un certificat HTTPS**
  (Let's Encrypt) pour le nom de domaine défini par la variable
  d'environnement `DOMAIN` (voir `docker-compose.yml`) — aucune commande
  `certbot` à lancer, aucun renouvellement manuel : Caddy s'en charge en
  continu tant que le conteneur tourne.

C'est pour ça que le frontend est compilé avec `VITE_API_URL=/api` en
production (voir `ARG VITE_API_URL` dans le Dockerfile) : il appelle son
propre domaine sur `/api/...` au lieu d'une URL `localhost:8000` codée en
dur. Avantages :
- **un seul point d'entrée public** (le domaine, en HTTPS) ;
- **plus de souci de CORS** en production (le navigateur ne voit qu'un
  seul domaine) ;
- le backend reste injoignable directement depuis Internet.

### `docker-compose.yml`

Décrit les 2 services (`backend`, `frontend`) et comment ils
communiquent :
- `backend` : `expose: 8000` → accessible uniquement par les autres
  conteneurs du même projet compose (via le réseau interne que Docker
  crée automatiquement), pas depuis l'extérieur.
- `frontend` : `ports: "80:80"` et `"443:443"` → **seul point d'entrée
  public**. Le port 80 sert au défi ACME (validation du domaine par
  Let's Encrypt) et à rediriger automatiquement vers HTTPS ; le port 443
  sert le trafic HTTPS. Les volumes `caddy_data`/`caddy_config`
  persistent les certificats entre deux redémarrages du conteneur.

## 3. Tester en local (optionnel mais recommandé)

Si tu installes Docker Desktop (ou Docker Engine) sur ta machine :

```bash
cd test-python
docker compose up -d --build
```

Par défaut, Caddy essaiera d'obtenir un certificat Let's Encrypt pour
`silvaplana.cloud`, ce qui échouera en local (le défi ACME ne peut pas
atteindre ta machine). Pour tester proprement en local, surcharge la
variable `DOMAIN` :

```bash
DOMAIN=localhost docker compose up -d --build
```

Caddy reconnaît `localhost` et génère un certificat local auto-signé
(pas d'appel à Let's Encrypt). Ouvre `https://localhost` dans un
navigateur (avertissement de sécurité à accepter, normal en local) : tu
dois voir le frontend, qui appelle l'API via `/api/motor`.

```bash
docker compose logs -f       # voir les logs des deux conteneurs
docker compose down          # tout arrêter et nettoyer
```

## 4. Déployer sur le VPS Hostinger

### a) Installer Docker sur le VPS

Une fois connecté en SSH au VPS (Ubuntu/Debian) :

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# se reconnecter (ou `newgrp docker`) pour que le groupe soit pris en compte
```

Vérifie : `docker --version` et `docker compose version`.

### b) Récupérer le projet sur le VPS

```bash
git clone https://github.com/silvaplana/test-python.git
cd test-python
```

(Pour les mises à jour futures : `git pull` puis rebuild, voir plus bas.)

### c) Lancer les conteneurs

```bash
docker compose up -d --build
```

`-d` = en arrière-plan (detached), `--build` = reconstruit les images à
partir des Dockerfile (nécessaire au premier lancement, et à chaque fois
que le code change).

### d) Ouvrir le port dans le pare-feu (si applicable)

Selon la configuration du VPS Hostinger :

```bash
sudo ufw allow 22/tcp    # garder l'accès SSH !
sudo ufw allow 80/tcp    # HTTP (défi ACME + redirection vers HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### e) Pointer ton nom de domaine

Dans la gestion DNS de ton domaine (chez Hostinger ou ailleurs), crée un
enregistrement **A** pointant vers l'IP publique du VPS. Une fois propagé
(quelques minutes à quelques heures), `http://ton-domaine.com` doit
afficher le frontend.

### f) Mettre à jour après un nouveau push GitHub

```bash
cd test-python
git pull
docker compose up -d --build
```

## 5. HTTPS (déjà en place)

Le domaine `silvaplana.cloud` pointe vers le VPS (enregistrement DNS de
type A) et le frontend est servi par **Caddy**, qui obtient et renouvelle
automatiquement un certificat HTTPS via Let's Encrypt — aucune commande
`certbot` à lancer, rien à renouveler manuellement.

Le site est accessible sur `https://silvaplana.cloud`. Caddy redirige
automatiquement `http://` vers `https://`.

Pour changer de domaine : modifier la variable `DOMAIN` dans
`docker-compose.yml`, s'assurer que le DNS pointe bien vers le VPS, puis
`docker compose up -d --build`.
