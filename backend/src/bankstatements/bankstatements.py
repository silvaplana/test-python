"""Historique des comptes bancaires de l'association (compte courant +
Livret Bleu), construit a partir des releves PDF de la banque.

Les releves sont deposes dans l'onglet Finances/Comptes (PDF un par un ou
zip) : chaque operation est stockee dans la base (tables bank_* de
database/database.py), une seule table pour tous les comptes. Un releve
deja importe (meme compte, meme periode) est ignore : on peut redeposer
tout un zip sans creer de doublon.

Virements entre les comptes du club (ex: Livret Bleu -> compte courant) :
visibles sur les deux releves. Les deux operations sont reliees
(transfer_id) pour n'afficher qu'une ligne dans la vue "tous les comptes",
ou elles ne changent pas le total.

Complementaire de bankaccounts/ (connexion bancaire Enable Banking, 90
derniers jours) : ici l'historique complet, sans dependre de la banque.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timezone

from database import Database

from .parser import ParsedStatement, StatementParseError, parse_statement

# Ecart maximal (jours) entre les deux operations d'un virement interne.
TRANSFER_MAX_DAYS = 3


class BankAccountNotFoundError(LookupError):
    """Levee quand le compte demande n'existe pas."""


def _account_name(product: str) -> tuple[str, str]:
    """(libelle affiche, type) d'un compte d'apres l'intitule du releve."""
    upper = product.upper()
    if "LIVRET BLEU" in upper:
        return "Livret Bleu", "savings"
    if "LIVRET" in upper:
        return product.title(), "savings"
    return "Compte courant", "checking"


class BankStatements:
    """Import des releves et lecture de l'historique (voir le docstring du
    module)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ----- import -----

    def import_files(self, files: list[tuple[str, bytes]]) -> dict:
        """Importe des releves PDF (ou des zip de PDF). Retourne le compte
        rendu : {"imported": [...], "skipped": [...], "errors": [...]}, une
        entree {"file", "detail"} par releve."""
        report: dict[str, list[dict]] = {"imported": [], "skipped": [], "errors": []}
        for name, data in self._expand(files):
            try:
                statement = parse_statement(data)
            except StatementParseError as exc:
                report["errors"].append({"file": name, "detail": str(exc)})
                continue
            period = f"{statement.start_date} → {statement.end_date}"
            if self._store(name, statement):
                report["imported"].append({"file": name, "detail": f"{period}, {len(statement.operations)} opérations"})
            else:
                report["skipped"].append({"file": name, "detail": f"{period} déjà importé"})
        if report["imported"]:
            self._link_transfers()
        return report

    @staticmethod
    def _expand(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
        """Remplace chaque zip par les PDF qu'il contient."""
        expanded = []
        for name, data in files:
            if zipfile.is_zipfile(io.BytesIO(data)):
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for member in sorted(archive.namelist()):
                        if member.lower().endswith(".pdf") and not member.startswith("__MACOSX/"):
                            expanded.append((member.rsplit("/", 1)[-1], archive.read(member)))
            else:
                expanded.append((name, data))
        return expanded

    def _store(self, file_name: str, statement: ParsedStatement) -> bool:
        """Enregistre le releve et ses operations. False s'il etait deja la."""
        name, kind = _account_name(statement.account_product)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO bank_accounts (number, name, kind) VALUES (?, ?, ?)",
                (statement.account_number, name, kind),
            )
            account_id = connection.execute(
                "SELECT id FROM bank_accounts WHERE number = ?", (statement.account_number,)
            ).fetchone()["id"]
            cursor = connection.execute(
                """INSERT OR IGNORE INTO bank_statements
                   (account_id, start_date, start_balance, end_date, end_balance, file_name, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_id,
                    statement.start_date,
                    statement.start_balance,
                    statement.end_date,
                    statement.end_balance,
                    file_name,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                return False
            connection.executemany(
                """INSERT INTO bank_operations
                   (account_id, statement_id, position, date, value_date, label, details, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (account_id, cursor.lastrowid, i, op.date, op.value_date, op.label, op.details, op.amount)
                    for i, op in enumerate(statement.operations)
                ],
            )
        return True

    def _link_transfers(self) -> None:
        """Relie les virements entre comptes du club pas encore relies : un
        virement ("VIR...") dans un compte et l'operation de montant oppose
        dans un autre compte, a TRANSFER_MAX_DAYS jours pres."""
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT id, account_id, date, amount FROM bank_operations
                   WHERE transfer_id IS NULL AND label LIKE 'VIR%' ORDER BY date, id"""
            ).fetchall()
            linked: set[int] = set()
            for debit in (r for r in rows if r["amount"] < 0):
                for credit in rows:
                    if (
                        credit["id"] not in linked
                        and credit["account_id"] != debit["account_id"]
                        and credit["amount"] == -debit["amount"]
                        and abs((date.fromisoformat(credit["date"]) - date.fromisoformat(debit["date"])).days)
                        <= TRANSFER_MAX_DAYS
                    ):
                        linked.update((debit["id"], credit["id"]))
                        connection.execute("UPDATE bank_operations SET transfer_id = ? WHERE id = ?", (credit["id"], debit["id"]))
                        connection.execute("UPDATE bank_operations SET transfer_id = ? WHERE id = ?", (debit["id"], credit["id"]))
                        break

    # ----- lecture -----

    def get_ledger(self, account_id: int | None = None) -> dict:
        """Historique, la plus recente operation en premier.

        account_id absent : tous les comptes ensemble. Chaque ligne porte le
        solde de chaque compte apres l'operation et leur total (None tant
        qu'un compte n'a pas encore de releve). Un virement interne n'occupe
        qu'une ligne (transfer: {"from", "to"}, montant positif).
        Avec account_id : les operations de ce compte seul et son solde.

        Retour : {"accounts": [{"id", "name", "kind", "balance", "asOf",
        "coverage": [{"from", "to", "statements"}]}], "allAccounts",
        "total", "rows": [...], "issues": [...]} (montants en euros).
        """
        with self.db.connect() as connection:
            accounts = [dict(r) for r in connection.execute("SELECT id, name, kind FROM bank_accounts ORDER BY kind, id")]
            statements = connection.execute(
                "SELECT account_id, start_date, start_balance, end_date, end_balance, file_name FROM bank_statements ORDER BY account_id, start_date"
            ).fetchall()
            operations = connection.execute(
                """SELECT o.id, o.account_id, o.date, o.value_date, o.label, o.details, o.amount, o.transfer_id
                   FROM bank_operations o JOIN bank_statements s ON s.id = o.statement_id
                   ORDER BY o.date, s.start_date, o.account_id, o.position"""
            ).fetchall()
        if account_id is not None and account_id not in {a["id"] for a in accounts}:
            raise BankAccountNotFoundError(account_id)

        first: dict[int, dict] = {}
        last: dict[int, dict] = {}
        # Periodes couvertes sans trou, par compte : releves qui s'enchainent
        # (solde de debut = solde de fin du precedent).
        coverage: dict[int, list[dict]] = {}
        issues = []
        for s in statements:
            previous = last.get(s["account_id"])
            periods = coverage.setdefault(s["account_id"], [])
            if previous is not None and s["start_balance"] == previous["end_balance"]:
                periods[-1]["to"] = s["end_date"]
                periods[-1]["statements"] += 1
            else:
                periods.append({"from": s["start_date"], "to": s["end_date"], "statements": 1})
            if previous is None:
                first[s["account_id"]] = s
            elif s["start_balance"] != previous["end_balance"]:
                name = next(a["name"] for a in accounts if a["id"] == s["account_id"])
                issues.append(
                    f"{name} : il manque un relevé entre le {_fr(previous['end_date'])} "
                    f"({previous['end_balance'] / 100:.2f} €) et le {_fr(s['start_date'])} "
                    f"({s['start_balance'] / 100:.2f} €)"
                )
            last[s["account_id"]] = s

        names = {a["id"]: a["name"] for a in accounts}
        visible = [a["id"] for a in accounts if account_id in (None, a["id"])]
        balances: dict[int, int | None] = {a: None for a in visible}
        by_id = {op["id"]: op for op in operations}
        rows = []
        for op in operations:
            if op["account_id"] not in balances:
                continue
            twin = by_id.get(op["transfer_id"]) if account_id is None else None
            if twin is not None and op["amount"] > 0:
                continue  # ligne deja produite par le debit du virement
            # Un compte entre dans le total a la date de debut de son 1er releve.
            for aid, balance in balances.items():
                if balance is None and aid in first and first[aid]["start_date"] <= op["date"]:
                    balances[aid] = first[aid]["start_balance"]
            for affected in (op, twin) if twin is not None else (op,):
                balances[affected["account_id"]] += affected["amount"]
            known = all(b is not None for b in balances.values())
            row = {
                "id": op["id"],
                "date": op["date"],
                "valueDate": op["value_date"],
                "accountId": op["account_id"],
                "label": op["label"],
                "details": op["details"],
                "amount": (abs(op["amount"]) if twin is not None else op["amount"]) / 100,
                "transfer": {"from": names[op["account_id"]], "to": names[twin["account_id"]]} if twin is not None else None,
                "balances": {str(a): (b / 100 if b is not None else None) for a, b in balances.items()},
                "total": sum(balances.values()) / 100 if known else None,
            }
            rows.append(row)
        # Comptes sans aucune operation importee : solde du releve.
        for aid in visible:
            if balances[aid] is None and aid in first:
                balances[aid] = first[aid]["start_balance"]
        rows.reverse()

        return {
            "accounts": [
                {
                    **a,
                    "balance": balances[a["id"]] / 100 if balances.get(a["id"]) is not None else None,
                    "asOf": last[a["id"]]["end_date"] if a["id"] in last else None,
                    "coverage": coverage.get(a["id"], []),
                }
                for a in accounts
                if a["id"] in visible
            ],
            # Tous les comptes (pour choisir la vue), meme avec account_id.
            "allAccounts": [{"id": a["id"], "name": a["name"], "kind": a["kind"]} for a in accounts],
            "total": sum(b for b in balances.values() if b is not None) / 100,
            "rows": rows,
            "issues": issues,
        }


def _fr(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"
