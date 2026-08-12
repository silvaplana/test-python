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

## 1bis. Architecture du VPS : un domaine, plusieurs applis

`silvaplana.cloud` est destiné à héberger **plusieurs applis** (dont
`test-python`), chacune sous un chemin différent
(`/test-python`, plus tard `/openclaw`, etc.). Un seul domaine, un seul
couple de ports 80/443 sur le VPS — donc un seul service peut les
posséder.

C'est le rôle du **gateway** : un Caddy partagé, **hors de ce repo**,
qui vit directement sur le VPS dans `~/gateway` (pas versionné dans Git,
volontairement — c'est juste 2-3 fichiers de config, plus simple à
maintenir à la main qu'un repo séparé). Il :
- possède seul les ports 80/443 et le certificat HTTPS de `silvaplana.cloud` ;
- sert une petite page d'accueil à la racine (`/`) ;
- route `/test-python/*` vers le conteneur `test-python-frontend` de ce
  projet, `/api/*` compris (proxifié plus loin par ce dernier vers le
  backend).

Ce projet (`test-python`), lui, **ne publie aucun port** et ne gère pas de
certificat : il tourne en interne, uniquement joignable par le gateway,
via un réseau Docker externe nommé `web` que les deux partagent :

```
Internet ──443/HTTPS──▶ gateway (Caddy, ~/gateway)
                           │
                           ├── /              → landing page (fichiers statiques)
                           └── /test-python/* → réseau "web" → test-python-frontend:80 (Caddy interne)
                                                                    │
                                                                    └── /api/* → backend:8000 (FastAPI)
```

Le réseau `web` doit exister une seule fois sur le VPS avant de lancer
quoi que ce soit :

```bash
docker network create web
```

Pour ajouter une nouvelle appli plus tard : lui donner un nom de
conteneur stable (`container_name` dans son `docker-compose.yml`), la
rattacher au réseau `web`, ne publier aucun port, puis ajouter un bloc de
routage dans `~/gateway/Caddyfile` sur le VPS.

## 2. Ce qui a été mis en place dans ce repo

```
test-python/
├── backend/
│   ├── Dockerfile        # construit l'image de l'API FastAPI
│   └── .dockerignore     # fichiers à ne pas copier dans l'image (venv, tests, ...)
├── frontend/
│   ├── Dockerfile        # build multi-étapes : Node compile React, puis Caddy sert les fichiers
│   ├── Caddyfile          # Caddy interne : sert le front + proxy /api/... vers le backend
│   └── .dockerignore
└── docker-compose.yml     # démarre les 2 conteneurs, rattache "frontend" au réseau "web"
```

### Le backend (`backend/Dockerfile`)

Construit une image Python 3.12 "slim", installe le package `motor` (donc
`fastapi` + `uvicorn`), et lance `python -m app.main` au démarrage — ce
module assemble les routes `motor` et `helloasso` sur la même app FastAPI
(voir `backend/README.md`).
Le conteneur écoute sur le port 8000, mais **n'est pas exposé directement
à Internet** — voir plus bas.

### Le frontend (`frontend/Dockerfile`)

Ce Dockerfile a **deux étapes** :

1. **Étape "build"** : une image Node compile l'app React (`npm run build`)
   et produit des fichiers statiques (HTML/CSS/JS) dans `dist/`. Le build
   utilise `base: '/test-python/'` (voir `vite.config.js`) : les fichiers
   générés référencent ce chemin, pas la racine du domaine.
2. **Étape finale** : une image **Caddy** (serveur web léger), dans
   laquelle on copie uniquement les fichiers `dist/` produits à l'étape 1.

Résultat : l'image finale ne contient ni Node ni le code source React —
juste Caddy et les fichiers statiques. Elle est donc petite et sécurisée.

`Caddyfile` (interne, pas de domaine ni de TLS ici — c'est le gateway qui
s'en charge) fait deux choses, en voyant les requêtes **comme si l'app
était à la racine** (le gateway a déjà retiré le préfixe `/test-python`
avant de transmettre) :
- sert le site React sur `/`.
- redirige (`reverse_proxy`) tout ce qui arrive sur `/api/...` vers le
  conteneur `backend` sur le port 8000. Exemple : une requête vers
  `/api/motor` est transmise à `http://backend:8000/motor`.

Le frontend est compilé avec `VITE_API_URL=/test-python/api` (voir `ARG
VITE_API_URL` dans le Dockerfile et le build arg dans
`docker-compose.yml`) : il appelle `/test-python/api/...`, que le gateway
route ici en retirant `/test-python`, laissant `/api/...` pour le Caddy
interne ci-dessus.

### `docker-compose.yml`

Décrit les 2 services (`backend`, `frontend`) et comment ils
communiquent :
- `backend` : `expose: 8000` → accessible uniquement par les autres
  conteneurs du même projet compose (via le réseau interne que Docker
  crée automatiquement), pas depuis l'extérieur.
- `frontend` : **aucun port publié**. Rattaché au réseau par défaut du
  projet (pour parler à `backend`) et au réseau externe `web` (pour être
  joignable par le gateway), sous le nom fixe `test-python-frontend`
  (`container_name`).

## 3. Tester en local (optionnel mais recommandé)

Si tu installes Docker Desktop (ou Docker Engine) sur ta machine, teste
l'architecture complète (gateway + appli), comme en prod :

```bash
docker network create web

cd test-python
docker compose up -d --build
```

Le service `frontend` n'a pas de port public : pour l'atteindre depuis un
navigateur, il faut aussi lancer un gateway local. Un gateway minimal
suffit — voir la structure décrite en section 1bis (`Caddyfile` avec
`{$DOMAIN}` + un `handle_path /test-python/* { reverse_proxy
test-python-frontend:80 }`), lancé avec `DOMAIN=localhost` pour obtenir un
certificat local auto-signé (pas d'appel à Let's Encrypt).

Une fois les deux lancés, ouvre `https://localhost/test-python/`
(avertissement de sécurité à accepter, normal en local) : tu dois voir le
frontend, qui appelle l'API via `/test-python/api/motor`.

```bash
docker compose logs -f       # voir les logs des deux conteneurs de test-python
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

### b) Créer le réseau partagé (une seule fois)

```bash
docker network create web
```

### c) Récupérer le projet sur le VPS

```bash
git clone https://github.com/silvaplana/test-python.git
cd test-python
```

(Pour les mises à jour futures : `git pull` puis rebuild, voir plus bas.)

### d) Lancer les conteneurs

```bash
docker compose up -d --build
```

`-d` = en arrière-plan (detached), `--build` = reconstruit les images à
partir des Dockerfile (nécessaire au premier lancement, et à chaque fois
que le code change). Rien n'est encore accessible publiquement à ce
stade : il manque le gateway (voir section 5).

### e) Ouvrir les ports dans le pare-feu

```bash
sudo ufw allow 22/tcp    # garder l'accès SSH !
sudo ufw allow 80/tcp    # HTTP (défi ACME + redirection vers HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### f) Mettre à jour après un nouveau push GitHub

```bash
cd test-python
git pull
docker compose up -d --build
```

## 5. Le gateway et HTTPS (déjà en place)

Le domaine `silvaplana.cloud` pointe vers le VPS (enregistrement DNS de
type A, déjà configuré côté Hostinger) et un Caddy "gateway" — dans
`~/gateway` sur le VPS, **hors de ce repo** — obtient et renouvelle
automatiquement un certificat HTTPS via Let's Encrypt, sert la page
d'accueil sur `/`, et route `/test-python/*` vers ce projet. Voir la
section 1bis pour l'architecture complète.

Le site est accessible sur `https://silvaplana.cloud/test-python/`.
Caddy redirige automatiquement `http://` vers `https://`.

Pour ajouter une nouvelle appli sur le même domaine : lui donner un
`container_name` fixe, la rattacher au réseau `web`, aucun port publié,
puis ajouter un bloc `handle_path` dans `~/gateway/Caddyfile` sur le VPS
et relancer `docker compose up -d` dans `~/gateway`.
