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

Operations recentes : la connexion bancaire (bankaccounts/, 90 derniers
jours) complete l'historique apres le dernier releve importe (voir
sync_live). Ces operations sont provisoires (source "banque") : le releve
qui couvre leur periode les remplace a son import.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
import zipfile
from pathlib import Path
from datetime import date, datetime, timezone

import py7zr

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
        """Remplace chaque archive (zip, 7z, tar/tar.gz...) par les PDF
        qu'elle contient, dans l'ordre alphabetique."""
        expanded = []
        for name, data in files:
            members: list[tuple[str, bytes]] = []
            if zipfile.is_zipfile(io.BytesIO(data)):
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = [(m, archive.read(m)) for m in archive.namelist() if not m.endswith("/")]
            elif py7zr.is_7zfile(io.BytesIO(data)):
                with tempfile.TemporaryDirectory() as tmp, py7zr.SevenZipFile(io.BytesIO(data)) as archive:
                    archive.extractall(tmp)
                    members = [(str(f.relative_to(tmp)), f.read_bytes()) for f in Path(tmp).rglob("*") if f.is_file()]
            else:
                try:
                    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                        members = [(m.name, archive.extractfile(m).read()) for m in archive.getmembers() if m.isfile()]
                except tarfile.TarError:
                    expanded.append((name, data))
                    continue
            expanded.extend(
                (member.rsplit("/", 1)[-1], content)
                for member, content in sorted(members)
                if member.lower().endswith(".pdf") and "__MACOSX/" not in member
            )
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
            # Operations provisoires de la connexion bancaire couvertes par
            # ce releve : remplacees par celles du releve.
            connection.execute(
                "DELETE FROM bank_operations WHERE account_id = ? AND source = 'banque' AND date <= ?",
                (account_id, statement.end_date),
            )
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

    def sync_live(self, live_accounts: list[dict]) -> dict:
        """Ajoute les operations recentes lues par la connexion bancaire.

        live_accounts : [{"iban", "operations": [{"date", "label", "amount"
        (euros)}]}]. Un compte est reconnu a son numero contenu dans l'IBAN
        (comptes sans releve importe : ignores). Seules les operations
        posterieures au dernier releve du compte sont gardees (avant : le
        releve fait foi). Les operations provisoires deja en base pour la
        periode lue sont remplacees : appeler deux fois n'ajoute rien.

        Retour : {"added": [{"date", "label", "amount", "account"}]}, les
        operations qui n'etaient pas encore en base.
        """
        added = []
        with self.db.connect() as connection:
            accounts = connection.execute("SELECT id, number, name FROM bank_accounts").fetchall()
            for live in live_accounts:
                iban = (live.get("iban") or "").replace(" ", "")
                account = next((a for a in accounts if a["number"] in iban), None)
                if account is None:
                    continue
                last_end = connection.execute(
                    "SELECT MAX(end_date) FROM bank_statements WHERE account_id = ?", (account["id"],)
                ).fetchone()[0]
                fetched = sorted(
                    (op for op in live["operations"] if op.get("date") and (last_end is None or op["date"] > last_end)),
                    key=lambda op: op["date"],
                )
                if not fetched:
                    continue
                since = fetched[0]["date"]
                previous = [
                    (r["date"], r["label"], r["amount"])
                    for r in connection.execute(
                        "SELECT date, label, amount FROM bank_operations WHERE account_id = ? AND source = 'banque' AND date >= ?",
                        (account["id"], since),
                    )
                ]
                connection.execute(
                    "DELETE FROM bank_operations WHERE account_id = ? AND source = 'banque' AND date >= ?",
                    (account["id"], since),
                )
                for position, op in enumerate(fetched):
                    amount = round(op["amount"] * 100)
                    connection.execute(
                        """INSERT INTO bank_operations
                           (account_id, statement_id, source, position, date, value_date, label, details, amount)
                           VALUES (?, NULL, 'banque', ?, ?, ?, ?, '', ?)""",
                        (account["id"], position, op["date"], op["date"], op["label"], amount),
                    )
                    key = (op["date"], op["label"], amount)
                    if key in previous:
                        previous.remove(key)
                    else:
                        added.append({"date": op["date"], "label": op["label"], "amount": amount / 100, "account": account["name"]})
        if added:
            self._link_transfers()
        return {"added": added}

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
                """SELECT o.id, o.account_id, o.date, o.value_date, o.label, o.details, o.amount, o.transfer_id, o.source
                   FROM bank_operations o LEFT JOIN bank_statements s ON s.id = o.statement_id
                   ORDER BY o.date, COALESCE(s.start_date, '9999'), o.account_id, o.position"""
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
            transfer = {"from": names[op["account_id"]], "to": names[twin["account_id"]]} if twin is not None else None
            row = {
                "id": op["id"],
                "date": op["date"],
                "valueDate": op["value_date"],
                "accountId": op["account_id"],
                "label": op["label"],
                "details": op["details"],
                "amount": (abs(op["amount"]) if twin is not None else op["amount"]) / 100,
                "transfer": transfer,
                # Lue par la connexion bancaire, pas encore dans un releve.
                "provisional": op["source"] == "banque",
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
                    # Date jusqu'a laquelle le solde est connu : fin du dernier
                    # releve, ou derniere operation lue a la banque.
                    "asOf": max(
                        ([last[a["id"]]["end_date"]] if a["id"] in last else [])
                        + [op["date"] for op in operations if op["account_id"] == a["id"] and op["source"] == "banque"],
                        default=None,
                    ),
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
