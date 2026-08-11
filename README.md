# test-python

Monorepo contenant l'API et l'interface web du projet.

## Structure

```
test-python/
├── backend/     # API REST FastAPI (voir backend/README.md)
└── frontend/    # Application React (à venir)
```

## Backend

Voir [backend/README.md](backend/README.md) pour l'installation, l'utilisation et les tests.

## Frontend

Voir [frontend/README.md](frontend/README.md).

## Déploiement

Le projet est "dockerisé" (backend + frontend/nginx) pour être déployé
facilement sur un VPS. Voir [DEPLOY.md](DEPLOY.md) pour l'explication
détaillée et les étapes de déploiement sur un VPS Hostinger.
