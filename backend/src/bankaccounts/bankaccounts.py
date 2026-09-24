"""Comptes bancaires de l'association (compte courant + Livret bleu) :
solde et dernieres operations, affiches dans l'onglet Finances/Comptes.

ETAPE ACTUELLE : donnees INVENTEES (aucune connexion bancaire). Le but est
de valider d'abord toute la chaine (mot de passe "comptes", routes REST,
affichage) avant de brancher la vraie source de donnees (Enable Banking,
agregateur PSD2). L'interface publique (get_accounts, get_transactions) est
celle qu'un client Enable Banking devra reprendre a l'identique : seul le
corps de ces 2 methodes changera, pas le receiver ni le frontend.

Format retourne (independant de la source) :
    compte      {"id", "name", "type", "iban", "balance", "currency", "simulated"}
    operation   {"date" (AAAA-MM-JJ), "label", "amount", "currency"}
                amount < 0 : debit, amount > 0 : credit.
"""

from __future__ import annotations

from datetime import date, timedelta


class BankAccountNotFoundError(LookupError):
    """Levee quand l'identifiant de compte demande n'existe pas."""


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
    """Acces aux comptes bancaires du club. Voir le docstring du module :
    pour l'instant, donnees inventees."""

    CURRENCY = "EUR"

    def get_accounts(self) -> list[dict]:
        """Retourne les comptes (identifiant, nom, type, IBAN masque, solde)."""
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

    def get_transactions(self, account_id: str, limit: int = 5) -> list[dict]:
        """Retourne les `limit` dernieres operations du compte, la plus
        recente en premier. Leve BankAccountNotFoundError si le compte n'existe
        pas."""
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
