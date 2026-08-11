# ---- Étape 1 : "build" — compile l'app React avec Node ----
# Cette étape produit des fichiers HTML/CSS/JS statiques (dist/).
# Node ne sera PAS présent dans l'image finale : il ne sert qu'à construire.
FROM node:22-alpine AS build

WORKDIR /app

# On copie d'abord package.json / package-lock.json seuls : tant que les
# dépendances ne changent pas, Docker réutilise le cache et évite de
# relancer "npm ci" (qui est l'étape la plus longue) à chaque build.
COPY package.json package-lock.json ./
RUN npm ci

# Le reste du code source
COPY . .

# URL de l'API utilisée par le frontend une fois compilé. Par défaut "/api" :
# le frontend appelle son propre domaine sur /api/..., et c'est nginx
# (voir nginx.conf) qui redirige ces requêtes vers le conteneur backend.
# Ça évite tout problème de CORS en production et n'expose qu'un seul port.
ARG VITE_API_URL=/api
RUN echo "VITE_API_URL=${VITE_API_URL}" > .env.production

RUN npm run build

# ---- Étape 2 : image finale — juste nginx + les fichiers statiques ----
FROM nginx:alpine

# Les fichiers compilés de l'étape "build" (dossier dist/)
COPY --from=build /app/dist /usr/share/nginx/html

# Configuration nginx : sert le front + proxy vers l'API (voir nginx.conf)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
