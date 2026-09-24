"""Comptes bancaires de l'association (compte courant + Livret bleu) :
solde et dernieres operations, affiches dans l'onglet Finances/Comptes.

Deux modes :
- LIVE : un client Enable Banking est fourni (voir enablebanking.py et les
  variables ENABLE_BANKING_* de app/main.py). L'utilisateur autorise l'acces
  chez sa banque (start_connection / complete_connection) ; la session
  obtenue (comptes autorises + date d'expiration) est memorisee sur disque.
  Elle expire (180 jours max) : il faut alors se reconnecter.
- DEMO : aucun client -> donnees INVENTEES (utile en developpement local, sans
  cle Enable Banking).

Format retourne (independant de la source) :
    compte      {"id", "name", "type", "iban" (masque), "balance", "currency", "simulated"}
    operation   {"date" (AAAA-MM-JJ), "label", "amount", "currency"}
                amount < 0 : debit, amount > 0 : credit.
"""

from __future__ import annotations

import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .enablebanking import EnableBankingClient


class BankAccountNotFoundError(LookupError):
    """Levee quand l'identifiant de compte demande n'existe pas."""


class BankNotConnectedError(RuntimeError):
    """Levee quand aucune session bancaire valide n'existe (jamais connectee
    ou expiree) : il faut passer par start_connection()."""


class InvalidConnectionStateError(ValueError):
    """Levee quand le retour de la banque ne correspond a aucune demande de
    connexion en cours (state inconnu/expire) : refuse un faux retour."""


# (jours avant aujourd'hui, libelle, montant) -- du plus recent au plus
# ancien. Dates relatives a aujourd'hui pour que les donnees inventees aient
# toujours l'air recentes.
_FAKE_ACCOUNTS: dict[str, dict] = {
    "compte-courant": {
        "name": "Compte courant",
        "type": "checking",
        "iban": "FR76 •••• •••• •••• •••• 123",
        "balance": 4823.17,
        "operations": [
            (1, "VIR HELLOASSO ADHESIONS", 612.00),
            (2, "PRLV EDF ELECTRICITE SALLE", -84.35),
            (4, "CB DECATHLON LA CIOTAT", -129.90),
            (6, "VIR HELLOASSO ADHESIONS", 300.00),
            (9, "CHQ 0004521 REMBT DEPLACEMENT", -45.00),
            (12, "CB SUMUP BUVETTE TOURNOI", 187.50),
            (15, "PRLV ASSURANCE MAIF", -62.10),
        ],
    },
    "livret-bleu": {
        "name": "Livret Bleu",
        "type": "savings",
        "iban": "FR76 •••• •••• •••• •••• 456",
        "balance": 12500.00,
        "operations": [
            (20, "VIR DU COMPTE COURANT", 1000.00),
            (45, "INTERETS 2026", 96.83),
            (110, "VIR DU COMPTE COURANT", 500.00),
            (200, "VIR VERS COMPTE COURANT", -800.00),
            (290, "VIR DU COMPTE COURANT", 1500.00),
            (380, "INTERETS 2025", 71.20),
        ],
    },
}


class BankAccounts:
    """Acces aux comptes bancaires du club (voir le docstring du module)."""

    CURRENCY = "EUR"
    STATE_TTL_SECONDS = 30 * 60
    # Cache des reponses de la banque (soldes/operations) : les banques
    # limitent le nombre d'acces automatiques par jour (PSD2, typiquement 4) --
    # sans cache, chaque affichage de l'onglet consommerait ce quota. Le bouton
    # "Rafraichir" force une relecture (refresh=True).
    CACHE_TTL_SECONDS = 10 * 60
    # Types de solde Enable Banking (ISO 20022) par ordre de preference : solde
    # comptable de cloture, puis solde provisoire, puis disponible.
    BALANCE_TYPES = ("CLBD", "ITBD", "XPCD", "CLAV", "ITAV")

    def __init__(
        self,
        storage_dir: str | None = None,
        client: EnableBankingClient | None = None,
        display: list[tuple[str, str]] | None = None,
    ) -> None:
        """display : comptes a afficher, dans l'ordre, sous forme de couples
        (fin de l'IBAN, libelle) -- ex: [("6527", "Compte courant")]. Seuls
        ces comptes sont lus (economise le quota d'acces de la banque).
        Absent : tous les comptes ayant un IBAN (les cartes n'en ont pas)."""
        self.client = client
        self.display = display or []
        self._cache: dict[str, tuple[float, object]] = {}
        self.session_path = Path(storage_dir or "data/bankaccounts") / "session.json"
        if client is not None:
            self.session_path.parent.mkdir(parents=True, exist_ok=True)

    # ----- session persistante (mode live) -----

    def _read_store(self) -> dict:
        try:
            return json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_store(self, store: dict) -> None:
        self.session_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    def _active_session(self) -> dict | None:
        session = self._read_store().get("session")
        if not session:
            return None
        valid_until = datetime.fromisoformat(session["valid_until"].replace("Z", "+00:00"))
        return session if valid_until > datetime.now(timezone.utc) else None

    # ----- statut et connexion -----

    def get_status(self) -> dict:
        """Mode (demo/live), et en live : connexion bancaire active ou non
        (+ date d'expiration et banque)."""
        if self.client is None:
            return {"mode": "demo", "connected": True, "validUntil": None, "bank": None}
        session = self._active_session()
        return {
            "mode": "live",
            "connected": session is not None,
            "validUntil": session["valid_until"] if session else None,
            "bank": self.client.aspsp_name,
        }

    def start_connection(self) -> str:
        """Retourne l'URL de la banque ou envoyer l'utilisateur pour autoriser
        l'acces (un `state` aleatoire est memorise pour verifier le retour)."""
        if self.client is None:
            raise BankNotConnectedError("Enable Banking n'est pas configuré")
        store = self._read_store()
        now = time.time()
        pending = {s: t for s, t in store.get("pending", {}).items() if now - t < self.STATE_TTL_SECONDS}
        state = secrets.token_urlsafe(24)
        pending[state] = now
        url = self.client.start_authorization(state)
        store["pending"] = pending
        self._write_store(store)
        return url

    def complete_connection(self, code: str, state: str) -> None:
        """Termine la connexion apres le retour de la banque : verifie le
        `state`, echange le code contre une session et la memorise (elle
        remplace la precedente)."""
        if self.client is None:
            raise BankNotConnectedError("Enable Banking n'est pas configuré")
        store = self._read_store()
        pending = store.get("pending", {})
        created = pending.pop(state, None)
        if created is None or time.time() - created > self.STATE_TTL_SECONDS:
            raise InvalidConnectionStateError("Retour de la banque inattendu ou expiré")
        data = self.client.create_session(code)
        store["pending"] = pending
        store["session"] = {
            "session_id": data["session_id"],
            "valid_until": data["access"]["valid_until"],
            "accounts": [
                {
                    "uid": a["uid"],
                    "iban": (a.get("account_id") or {}).get("iban") or "",
                    "name": a.get("name") or a.get("product") or "",
                    "product": a.get("product") or "",
                    "details": a.get("details") or "",
                    "currency": a.get("currency") or self.CURRENCY,
                }
                for a in data.get("accounts", [])
                if a.get("uid")
            ],
        }
        self._write_store(store)

    # ----- donnees -----

    def _cached(self, key: str, refresh: bool, fetch):
        """Retourne la valeur en cache si recente (sauf refresh=True), sinon
        la recalcule via fetch() et la memorise."""
        entry = self._cache.get(key)
        if entry and not refresh and time.time() - entry[0] < self.CACHE_TTL_SECONDS:
            return entry[1]
        value = fetch()
        self._cache[key] = (time.time(), value)
        return value

    @staticmethod
    def _mask_iban(iban: str) -> str:
        return f"•••• {iban[-4:]}" if len(iban) >= 4 else "••••"

    def _pick_balance(self, balances: list[dict]) -> float | None:
        by_type = {b.get("balance_type"): b for b in balances}
        for balance_type in self.BALANCE_TYPES:
            if balance_type in by_type:
                return float(by_type[balance_type]["balance_amount"]["amount"])
        return float(balances[0]["balance_amount"]["amount"]) if balances else None

    def _visible_accounts(self, session: dict) -> list[tuple[dict, str | None]]:
        """Comptes de la session a afficher, dans l'ordre, avec leur libelle
        (voir display). Sans IBAN = carte : jamais affichee."""
        accounts = [a for a in session["accounts"] if a["iban"]]
        if not self.display:
            return [(a, None) for a in accounts]
        visible = []
        for suffix, label in self.display:
            match = next((a for a in accounts if a["iban"].endswith(suffix)), None)
            if match:
                visible.append((match, label))
        return visible

    def get_accounts(self, refresh: bool = False) -> list[dict]:
        """Retourne les comptes (identifiant, nom, type, IBAN masque, solde)."""
        if self.client is None:
            return self._fake_accounts()
        session = self._active_session()
        if session is None:
            raise BankNotConnectedError("Banque non connectée")

        def fetch_account(item: tuple[dict, str | None]) -> dict:
            account, label = item
            balance = self._pick_balance(self.client.get_balances(account["uid"]))
            # "XXX" = "aucune devise" (code ISO 4217) renvoye par certaines banques.
            currency = account["currency"] if account["currency"] not in ("", "XXX") else self.CURRENCY
            return {
                "id": account["uid"],
                "name": label or account["details"] or account["product"] or account["name"] or "Compte",
                "type": "unknown",
                "iban": self._mask_iban(account["iban"]),
                "balance": balance,
                "currency": currency,
                "simulated": False,
            }

        def fetch_all() -> list[dict]:
            # En parallele : un appel reseau par compte (~1 s chacun).
            with ThreadPoolExecutor(max_workers=5) as pool:
                return list(pool.map(fetch_account, self._visible_accounts(session)))

        return self._cached(f"accounts:{session['session_id']}", refresh, fetch_all)

    def get_transactions(self, account_id: str, limit: int = 5, refresh: bool = False) -> list[dict]:
        """Retourne les `limit` dernieres operations du compte, la plus
        recente en premier. Leve BankAccountNotFoundError si le compte n'existe
        pas."""
        if self.client is None:
            return self._fake_transactions(account_id, limit)
        session = self._active_session()
        if session is None:
            raise BankNotConnectedError("Banque non connectée")
        if account_id not in {a["uid"] for a, _ in self._visible_accounts(session)}:
            raise BankAccountNotFoundError(account_id)

        def fetch() -> list[dict]:
            # 90 jours en arriere, sur quelques pages au plus : suffisant pour
            # trouver les dernieres operations meme sur un compte peu actif.
            date_from = (date.today() - timedelta(days=90)).isoformat()
            raw: list[dict] = []
            continuation_key = None
            for _ in range(5):
                page = self.client.get_transactions(account_id, date_from, continuation_key)
                raw.extend(page.get("transactions", []))
                continuation_key = page.get("continuation_key")
                if not continuation_key:
                    break
            operations = [self._to_operation(t) for t in raw]
            operations.sort(key=lambda op: op["date"], reverse=True)
            return operations

        # Toutes les operations recuperees sont mises en cache (pas seulement
        # `limit`) : limit ne change que le decoupage final.
        return self._cached(f"transactions:{account_id}", refresh, fetch)[:limit]

    def _to_operation(self, transaction: dict) -> dict:
        amount = float(transaction["transaction_amount"]["amount"])
        debit = transaction.get("credit_debit_indicator") == "DBIT"
        counterparty = transaction.get("creditor" if debit else "debtor") or {}
        label = " ".join(transaction.get("remittance_information") or []).strip() or counterparty.get("name") or "—"
        return {
            "date": transaction.get("booking_date") or transaction.get("value_date") or transaction.get("transaction_date") or "",
            "label": label,
            "amount": -abs(amount) if debit else abs(amount),
            "currency": transaction["transaction_amount"].get("currency", self.CURRENCY),
        }

    # ----- mode demo -----

    def _fake_accounts(self) -> list[dict]:
        return [
            {
                "id": account_id,
                "name": account["name"],
                "type": account["type"],
                "iban": account["iban"],
                "balance": account["balance"],
                "currency": self.CURRENCY,
                "simulated": True,
            }
            for account_id, account in _FAKE_ACCOUNTS.items()
        ]

    def _fake_transactions(self, account_id: str, limit: int) -> list[dict]:
        account = _FAKE_ACCOUNTS.get(account_id)
        if account is None:
            raise BankAccountNotFoundError(account_id)
        today = date.today()
        return [
            {
                "date": (today - timedelta(days=days_ago)).isoformat(),
                "label": label,
                "amount": amount,
                "currency": self.CURRENCY,
            }
            for days_ago, label, amount in account["operations"][:limit]
        ]
