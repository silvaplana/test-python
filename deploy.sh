#!/usr/bin/env bash
# Deploiement sur le VPS (voir DEPLOY.md, section 6) : les memes commandes
# que la mise a jour a la main (section 4 f), en une seule fois.
#
# Lance de deux facons :
#   - par GitHub Actions (.github/workflows/deploy.yml), a chaque fusion
#     dans master : la cle de deploiement est limitee, dans
#     ~/.ssh/authorized_keys, a lancer ce script et rien d'autre ;
#   - a la main sur le VPS : ./deploy.sh
#
# Le script se met d'abord a jour lui-meme (git pull), puis se relance pour
# que ce soit toujours la derniere version qui fasse le reste.
set -euo pipefail

script="$(readlink -f "$0")"
cd "$(dirname "$script")"

if [ -z "${DEPLOY_APRES_PULL:-}" ]; then
  echo "==> git pull"
  git pull --ff-only
  DEPLOY_APRES_PULL=1 exec "$script" "$@"
fi

echo "==> Version : $(git log -1 --format='%h %s')"

echo "==> Reconstruction et redemarrage des conteneurs"
docker compose up -d --build

# /auth/status : seule route du backend accessible sans etre connecte.
echo "==> Attente du backend"
pret=""
for _ in $(seq 1 30); do
  if docker compose exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/auth/status', timeout=3)" \
    >/dev/null 2>&1; then
    pret=1
    break
  fi
  sleep 2
done
if [ -z "$pret" ]; then
  echo "Le backend ne repond pas apres 60 s. Derniers journaux :"
  docker compose logs --tail=50 backend
  exit 1
fi

echo "==> Menage des anciennes images"
docker image prune -f >/dev/null

echo "==> Deploiement termine"
docker compose ps
