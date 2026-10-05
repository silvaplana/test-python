"""Lecture d'un releve bancaire PDF du Credit Mutuel (compte courant ou
Livret Bleu) : solde de debut, operations, solde de fin.

Les PDF sont du texte (pas des images) : on lit chaque mot avec sa position
(PyMuPDF) plutot que le texte brut, car la mise en page varie d'un releve a
l'autre (date et libelle sur la meme ligne ou non selon l'epoque). Colonnes
du tableau : Date | Date valeur | Operation | Debit EUROS | Credit EUROS. Un
montant est un debit ou un credit selon la colonne dont son bord droit est le
plus proche (montants alignes a droite).

Le releve est verifie : solde de debut + operations = solde de fin, au
centime pres. Sinon StatementParseError (mieux vaut refuser un releve que
stocker des operations fausses).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf


class StatementParseError(ValueError):
    """Levee quand le PDF n'est pas un releve reconnu ou ne tombe pas juste."""


@dataclass
class ParsedOperation:
    date: str  # AAAA-MM-JJ
    value_date: str
    label: str  # 1re ligne du libelle
    details: str  # lignes suivantes (beneficiaire, reference...), separees par \n
    amount: int  # centimes, < 0 : debit


@dataclass
class ParsedStatement:
    account_number: str  # ex: "00020461601"
    account_product: str  # ex: "C/C Connect Asso", "LIVRET BLEU ASSOCIATION"
    start_date: str
    start_balance: int  # centimes
    end_date: str
    end_balance: int
    operations: list[ParsedOperation] = field(default_factory=list)


_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_AMOUNT = re.compile(r"^\d{1,3}(\.\d{3})*,\d{2}$")
_ACCOUNT = re.compile(r"^(?:€\s*)?(?P<product>.+?)\s+N°\s*(?P<number>\d{11})\b")
# Marge gauche : codes techniques de la banque imprimes verticalement
# (caracteres isoles), a ignorer.
_MARGIN_RIGHT = 40
# Ecart vertical (points) en dessous duquel deux mots sont sur la meme ligne.
_LINE_TOLERANCE = 3


def _iso(date_fr: str) -> str:
    day, month, year = date_fr.split("/")
    return f"{year}-{month}-{day}"


def _cents(amount_fr: str) -> int:
    euros, cents = amount_fr.replace(".", "").split(",")
    return int(euros) * 100 + int(cents)


def _lines(page) -> list[list[tuple]]:
    """Mots de la page regroupes par ligne (de haut en bas, puis de gauche a
    droite). Mot = (x0, y0, x1, y1, texte, ...)."""
    words = sorted((w for w in page.get_text("words") if w[2] > _MARGIN_RIGHT), key=lambda w: (w[3], w[0]))
    lines: list[list[tuple]] = []
    for word in words:
        if lines and abs(lines[-1][0][3] - word[3]) <= _LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w[0]) for line in lines]


def parse_statement(pdf_bytes: bytes) -> ParsedStatement:
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise StatementParseError("PDF illisible") from exc

    account_number = account_product = None
    start = end = None
    operations: list[ParsedOperation] = []
    # Bord droit des colonnes Debit / Credit (lu dans l'en-tete du tableau).
    debit_right = credit_right = None
    label_left = None
    current: ParsedOperation | None = None

    for page in document:
        in_table = False
        for line in _lines(page):
            texts = [w[4] for w in line]
            text = " ".join(texts)

            if account_number is None and (match := _ACCOUNT.match(text)):
                account_number, account_product = match["number"], match["product"].strip()
                continue

            if texts[:2] == ["Date", "Date"] and "Débit" in texts and "Crédit" in texts:
                debit_right = line[texts.index("Débit") + 1][2]
                credit_right = line[texts.index("Crédit") + 1][2]
                label_left = line[texts.index("Opération")][0] - 15
                in_table = True
                continue
            if not in_table:
                continue

            if "SOLDE" in texts and "AU" in texts:
                i = texts.index("SOLDE")
                if i + 3 >= len(texts) or not _DATE.match(texts[i + 3]) or not _AMOUNT.match(texts[-1]):
                    continue
                sign = -1 if texts[i + 1] == "DEBITEUR" else 1
                balance = (_iso(texts[i + 3]), sign * _cents(texts[-1]))
                current = None
                if start is None:
                    start = balance
                else:
                    end = balance
                    in_table = False
                continue

            if texts[0] == "Total" or text.startswith(("HT.", "QXBAN", "IBAN", "Réf")):
                current = None
                continue

            if len(texts) >= 2 and _DATE.match(texts[0]) and _DATE.match(texts[1]):
                amounts = [w for w in line[2:] if _AMOUNT.match(w[4]) and w[0] > label_left + 200]
                if len(amounts) != 1:
                    raise StatementParseError(f"Montant introuvable : {text}")
                amount_word = amounts[0]
                cents = _cents(amount_word[4])
                is_debit = abs(amount_word[2] - debit_right) < abs(amount_word[2] - credit_right)
                label = " ".join(w[4] for w in line[2:] if w is not amount_word)
                current = ParsedOperation(
                    date=_iso(texts[0]),
                    value_date=_iso(texts[1]),
                    label=label,
                    details="",
                    amount=-cents if is_debit else cents,
                )
                operations.append(current)
                continue

            # Suite du libelle de l'operation en cours (meme colonne).
            if current is not None and line[0][0] >= label_left:
                if not current.label:
                    current.label = text
                else:
                    current.details = f"{current.details}\n{text}" if current.details else text
            else:
                current = None

    if account_number is None or start is None or end is None:
        raise StatementParseError("Ce PDF n'est pas un relevé de compte reconnu")
    total = start[1] + sum(op.amount for op in operations)
    if total != end[1]:
        raise StatementParseError(
            f"Le relevé ne tombe pas juste : {start[1] / 100:.2f} + opérations = {total / 100:.2f}, "
            f"attendu {end[1] / 100:.2f}"
        )
    return ParsedStatement(
        account_number=account_number,
        account_product=account_product,
        start_date=start[0],
        start_balance=start[1],
        end_date=end[0],
        end_balance=end[1],
        operations=operations,
    )
