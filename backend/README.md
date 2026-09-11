# backend

API REST (FastAPI) packagée avec `pyproject.toml` et un layout `src/`. Un
seul point d'entrée (`app.main`) assemble plusieurs modules sur la même
app FastAPI :

- **helloasso** : client API HelloAsso (`GET /helloasso/campaign`,
  `/helloasso/members`, `/helloasso/unpaid`, `/helloasso/photo`) — voir
  `src/helloasso/helloasso.py` pour le detail des methodes et
  `.env.example` pour la config requise. `/helloasso/photo` relaie (avec
  authentification, requise par HelloAsso) et redimensionne en vignette
  les photos d'adherent, avec un cache disque (`HELLOASSO_PHOTO_CACHE_DIR`,
  defaut `data/photos_cache`) : une photo n'est telechargee/redimensionnee
  qu'une seule fois.
- **ffst** : scraping du portail de licences FFST (`GET /ffst/licences`,
  `GET /ffst/demandes_validated`, `GET /ffst/demandes_draft`, pas d'API —
  parsing d'un bloc XML integre a la page HTML) + `POST
  /ffst/demandes_renouvellement` pour soumettre une demande de licence
  (pilote un vrai navigateur Playwright — essaie d'abord un renouvellement
  pour un ancien licencie du club, puis une nouvelle demande si
  l'adherent n'a jamais ete licencie, voir
  `Ffst.create_demande_renouvellement`) — voir `src/ffst/ffst.py`.
- **financialbalance** : upload de l'archive des relevés bancaires
  (`POST /financialbalance/archives`) puis analyse IA (Claude, via l'API
  Anthropic) en flux Server-Sent Events (`GET /financialbalance/analysis`)
  — résumé synthétique + ventilation par catégorie. Voir
  `src/financialbalance/financialbalance.py` et `ANTHROPIC_API_KEY` dans
  `.env.example`.
- **members_history** : historique des adhérents (payeurs) toutes saisons
  confondues (`GET /members_history`) — ne parle à aucune API, lit un
  fichier xlsx statique embarqué dans le backend
  (`src/members_history/data/liste_adherents_nombre_campagnes.xlsx`,
  généré manuellement hors de ce repo) ; pour le mettre à jour, remplacer
  ce fichier et redéployer. Voir `src/members_history/members_history.py`.
- **notifications** : notifications push "nouvel adhérent" (Web Push +
  VAPID, voir `src/notifications/notifications.py`). Un thread de fond
  (`_poll_new_members` dans `app/main.py`) interroge `HelloAsso.get_members()`
  toutes les `NOTIFICATIONS_POLL_INTERVAL_SECONDS` (polling, pas de
  webhook HelloAsso) et notifie tous les abonnés de tout nouvel `id`
  d'adhérent jamais vu. Endpoints `GET /notifications/vapid_public_key`,
  `POST /notifications/subscribe`, `POST /notifications/unsubscribe`
  (utilisés par l'onglet Profil du frontend). Clés VAPID à générer une
  fois via `generate-vapid-keys` (voir `.env.example`).

## Structure

```
backend/
├── pyproject.toml
├── .env.example            # variables HELLOASSO_* et FFST_* attendues
├── src/
│   ├── app/
│   │   └── main.py         # point d'entrée : cree l'app FastAPI + CORS, assemble tous les modules, lance uvicorn
│   ├── helloasso/
│   │   ├── __init__.py
│   │   ├── helloasso.py    # HelloAsso : client OAuth2 + appels API (organisation, formulaires, commandes)
│   │   └── receiver.py     # HelloAssoReceiver : endpoints REST FastAPI /helloasso/...
│   ├── ffst/
│   │   ├── __init__.py
│   │   ├── ffst.py         # Ffst : connexion WEBDEV + parsing XML des licences
│   │   └── receiver.py     # FfstReceiver : endpoints REST FastAPI /ffst/licences, /ffst/demandes_validated, /ffst/demandes_draft, /ffst/demandes_renouvellement
│   ├── financialbalance/
│   │   ├── __init__.py
│   │   ├── financialbalance.py  # FinancialBalance : stockage archives + analyse IA (Claude)
│   │   └── receiver.py          # FinancialBalanceReceiver : endpoints /financialbalance/archives, /analysis (SSE)
│   ├── members_history/
│   │   ├── __init__.py
│   │   ├── data/liste_adherents_nombre_campagnes.xlsx  # fichier source, embarque dans l'image
│   │   ├── members_history.py   # MembersHistory : parsing du xlsx
│   │   └── receiver.py          # MembersHistoryReceiver : endpoint /members_history
│   └── notifications/
│       ├── __init__.py
│       ├── notifications.py        # PushNotifications : abonnements + detection nouveaux adherents + envoi
│       ├── receiver.py             # NotificationsReceiver : endpoints /notifications/...
│       └── generate_vapid_keys.py  # script one-shot : genere VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY
└── tests/                  # pas de test pour l'instant (voir "Tests" plus bas)
```

## Installation (venv + pip)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Utilisation

```bash
app
# ou
python -m app.main
```

Le serveur écoute par défaut sur `http://0.0.0.0:8000`.

- `GET /helloasso/campaign` -> titre de la campagne d'adhésion configurée (`HELLOASSO_FORM_SLUG`)
- `GET /helloasso/members` -> liste des adhérents de cette campagne
- `GET /helloasso/unpaid` -> adhérents avec au moins un paiement refusé
- `GET /helloasso/photo?url=...` -> relaie (authentifié) + redimensionne en vignette carrée une photo d'adhérent (`url` = valeur déjà présente dans `customFields["photo d'identité"]`, doit pointer vers `docs.helloasso.com`)
- `GET /ffst/licences` -> liste des licences FFST du club (saison en cours)
- `GET /ffst/demandes_validated` -> demandes de nouvelle licence / renouvellement en cours (liste vide = cas normal)
- `GET /ffst/demandes_draft` -> demandes en brouillon, pas encore validées/soumises (le "panier" du portail ; liste vide = cas normal)
- `GET /ffst/fonctions` -> liste des valeurs possibles pour le champ "fonction" d'une demande de licence (41 rôles, ex. "005-PRATIQUANT", "004-ENTRAINEUR", ...)
- `POST /ffst/demandes_renouvellement` avec body `{"lastName", "firstName", "fonction", "gender", "birthDate", "addressLine1", "postalCode", "city", "phone", "email"}` -> soumet une demande de licence pour un adhérent du club (doit être identifiable de façon non ambiguë) : `fonction` par défaut à `"005-PRATIQUANT"` (voir `/ffst/fonctions` pour les autres valeurs) ; essaie d'abord un renouvellement (seuls lastName/firstName/fonction utilisés) puis, si l'adhérent n'a jamais été licencié, une nouvelle demande à partir des autres champs (obligatoires dans ce cas, sauf phone/email) ; la place dans `/ffst/demandes_draft` sans déclencher de facturation (celle-ci n'intervient qu'à la validation, manuelle, sur le portail). Toute `fonction` autre que `"005-PRATIQUANT"` exige côté FFST une "Commune de naissance" (absente de HelloAsso) : approximée avec `city`, erreur 400 explicite si introuvable ou ambiguë (à compléter alors manuellement sur le portail) ; la confirmation FFST est aussi vérifiée après soumission (erreur 400 si la demande a en fait été rejetée, ex. coordonnées manquantes pour Président/Trésorier/Secrétaire)
- `DELETE /ffst/demandes_draft` avec body `{"lastName", "firstName"}` -> supprime une demande en brouillon (doit correspondre à une seule ligne du panier)
- `POST /financialbalance/archives` (multipart, champ `file`) -> stocke une archive `.zip` de relevés bancaires
- `GET /financialbalance/analysis` -> flux SSE : progression puis bilan IA (résumé + tableau par catégorie) de la dernière archive envoyée
- `GET /members_history` -> historique des adhérents (payeurs) toutes saisons confondues (nom, prénom, nombre de saisons, détail des saisons), à partir du fichier xlsx embarqué
- `GET /notifications/vapid_public_key` -> clé publique VAPID (base64url), nécessaire côté navigateur pour `PushManager.subscribe()`
- `POST /notifications/subscribe` avec le corps `PushSubscription.toJSON()` du navigateur -> enregistre un abonnement aux notifications push
- `POST /notifications/unsubscribe` avec `{"endpoint"}` -> retire un abonnement

Exemple :

```bash
curl http://localhost:8000/helloasso/members
curl http://localhost:8000/ffst/licences
```

## Tests

```bash
pytest
```

Pas de test pour l'instant (le seul existant, `test_motor.py`, ciblait le
module `motor`, retiré car du code mort — aucun endpoint `/motor` n'était
appelé par le frontend).
