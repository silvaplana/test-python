"""Tests de l'historique des comptes (bankstatements) : lecture d'un releve
PDF, import (doublons, zip), virements internes, trous entre releves.
Les releves sont fabriques ici (meme mise en page que ceux du Credit
Mutuel, donnees inventees) : les vrais releves ne vont jamais dans Git.
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

import io
import zipfile

import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bankstatements import BankStatements, BankStatementsReceiver, StatementParseError, parse_statement
from bankstatements.categories import categorize
from database import Database

COURANT = "C/C Connect Asso N° 00020461601 en euros (GD)"
LIVRET = "€ LIVRET BLEU ASSOCIATION N° 00020461602 en euros (GE)"


def fr(amount_cents):
    """1234567 -> '12.345,67' (format des releves)."""
    euros, cents = divmod(amount_cents, 100)
    return f"{euros:,}".replace(",", ".") + f",{cents:02d}"


def make_statement(account_line, start, operations, end_date=None, error=0):
    """PDF de releve : start = (jj/mm/aaaa, solde en centimes), operations =
    [(date, libelle, montant en centimes, [lignes de detail])]."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # Code technique de la banque dans la marge gauche (a ignorer).
    page.insert_text((6, 300), "X", fontsize=8)
    page.insert_text((82, 340), account_line, fontsize=8)
    for x, word in [(63, "Date"), (98, "Date"), (118, "valeur"), (161, "Opération"), (409, "Débit"), (431, "EUROS"), (480, "Crédit"), (506, "EUROS")]:
        page.insert_text((x, 367), word, fontsize=8)

    def right(x_right, y, text):
        page.insert_text((x_right - pymupdf.get_text_length(text, fontsize=8), y), text, fontsize=8)

    y = 386
    page.insert_text((158, y), f"SOLDE CREDITEUR AU {start[0]}", fontsize=8)
    right(534, y, fr(start[1]))
    balance = start[1]
    for date, label, amount, details in operations:
        y += 11
        page.insert_text((52, y), date, fontsize=8)
        page.insert_text((100, y), date, fontsize=8)
        page.insert_text((148, y), label, fontsize=8)
        right(460 if amount < 0 else 534, y, fr(abs(amount)))
        for line in details:
            y += 11
            page.insert_text((148, y), line, fontsize=8)
        balance += amount
    y += 15
    page.insert_text((304, y), "Total des mouvements", fontsize=8)
    y += 15
    page.insert_text((53, y), "Réf : 001", fontsize=8)
    page.insert_text((158, y), f"SOLDE CREDITEUR AU {end_date or operations[-1][0]}", fontsize=8)
    right(534, y, fr(balance + error))
    return doc.tobytes()


def test_parse_statement():
    pdf = make_statement(
        COURANT,
        ("01/06/2026", 429643),
        [
            ("02/06/2026", "PRLV SEPA GIMS", -15240, ["FACTURE FA26019948"]),
            ("24/06/2026", "VIR STRIPE TECHNOLOGY", 329074, []),
        ],
        end_date="30/06/2026",
    )
    statement = parse_statement(pdf)
    assert statement.account_number == "00020461601"
    assert (statement.start_date, statement.start_balance) == ("2026-06-01", 429643)
    assert (statement.end_date, statement.end_balance) == ("2026-06-30", 743477)
    first, second = statement.operations
    assert (first.date, first.label, first.details, first.amount) == ("2026-06-02", "PRLV SEPA GIMS", "FACTURE FA26019948", -15240)
    assert (second.label, second.amount) == ("VIR STRIPE TECHNOLOGY", 329074)


def test_parse_rejects_statement_that_does_not_add_up():
    pdf = make_statement(COURANT, ("01/06/2026", 1000), [("02/06/2026", "CB", -500, [])], error=1)
    with pytest.raises(StatementParseError, match="ne tombe pas juste"):
        parse_statement(pdf)


def test_parse_rejects_other_pdf():
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "Facture")
    with pytest.raises(StatementParseError):
        parse_statement(doc.tobytes())


@pytest.fixture
def statements(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    return BankStatements(db)


def history():
    """Compte courant (2 releves) + livret, avec un virement livret -> courant."""
    return [
        ("c1.pdf", make_statement(COURANT, ("30/06/2024", 100000), [("03/07/2024", "CB DECATHLON", -20000, []), ("07/07/2024", "VIR DE ALLIANCE SAMBO", 50000, [])], "31/07/2024")),
        ("c2.pdf", make_statement(COURANT, ("31/07/2024", 130000), [("12/08/2024", "VIR SALAIRE", -37739, [])], "31/08/2024")),
        ("l1.pdf", make_statement(LIVRET, ("31/12/2023", 400000), [("07/07/2024", "VIR C/C EUROCOMPTE", -50000, [])], "31/07/2024")),
    ]


def test_import_and_ledger(statements):
    report = statements.import_files(history())
    assert len(report["imported"]) == 3 and not report["errors"]

    ledger = statements.get_ledger()
    courant, livret = ledger["accounts"]
    assert (courant["name"], courant["balance"], courant["asOf"]) == ("Compte courant", 922.61, "2024-08-31")
    assert (livret["name"], livret["balance"]) == ("Livret Bleu", 3500.0)
    assert ledger["total"] == 4422.61
    assert ledger["issues"] == []
    # Virement interne : une seule ligne, total inchange.
    assert [r["label"] for r in ledger["rows"]] == ["VIR SALAIRE", "VIR C/C EUROCOMPTE", "CB DECATHLON"]
    transfer = ledger["rows"][1]
    assert transfer["transfer"] == {"from": "Livret Bleu", "to": "Compte courant"}
    assert transfer["amount"] == 500.0
    assert transfer["total"] == ledger["rows"][2]["total"] == 4800.0

    # Un compte seul : le virement est une operation ordinaire.
    alone = statements.get_ledger(courant["id"])
    assert [r["amount"] for r in alone["rows"]] == [-377.39, 500.0, -200.0]
    assert alone["total"] == 922.61


def test_import_twice_and_zip(statements):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in history():
            archive.writestr(f"comptes/{name}", data)
    assert len(statements.import_files([("comptes.zip", buffer.getvalue())])["imported"]) == 3
    report = statements.import_files(history())
    assert len(report["skipped"]) == 3 and not report["imported"]
    assert len(statements.get_ledger()["rows"]) == 3  # virement interne : 1 ligne


def test_missing_statement_is_reported(statements):
    first, _, livret = history()
    later = ("c3.pdf", make_statement(COURANT, ("30/09/2024", 50000), [("05/10/2024", "CB", -1000, [])], "31/10/2024"))
    statements.import_files([first, livret, later])
    ledger = statements.get_ledger()
    assert len(ledger["issues"]) == 1 and "il manque un relevé" in ledger["issues"][0]
    assert len(ledger["accounts"][0]["coverage"]) == 2


def test_routes(statements):
    app = FastAPI()
    BankStatementsReceiver(client=statements, app=app)
    client = TestClient(app)
    files = [("files", (name, data, "application/pdf")) for name, data in history()]
    assert len(client.post("/bankstatements/import", files=files).json()["imported"]) == 3
    assert client.get("/bankstatements/ledger").json()["total"] == 4422.61
    assert client.get("/bankstatements/ledger?account=99").status_code == 404


def test_import_7z_and_tar(statements, tmp_path):
    import tarfile

    import py7zr

    first, second, livret = history()
    seven = tmp_path / "a.7z"
    with py7zr.SevenZipFile(seven, "w") as archive:
        archive.writestr(first[1], first[0])
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w:gz") as archive:
        for name, data in (second, livret):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    report = statements.import_files([("a.7z", seven.read_bytes()), ("b.tar.gz", tar.getvalue())])
    assert sorted(i["file"] for i in report["imported"]) == ["c1.pdf", "c2.pdf", "l1.pdf"]


IBAN_COURANT = "FR76 1027 8089 7200 0204 6160 122"


def test_sync_live(statements):
    statements.import_files(history())  # compte courant releve jusqu'au 31/08/2024
    live = [
        {
            "iban": IBAN_COURANT,
            "operations": [
                {"date": "2024-09-03", "label": "CB INTERSPORT", "amount": -42.5},
                {"date": "2024-08-30", "label": "deja dans le releve", "amount": -1.0},
            ],
        },
        {"iban": "FR76 9999", "operations": [{"date": "2024-09-03", "label": "autre banque", "amount": 5.0}]},
    ]
    added = statements.sync_live(live)["added"]
    assert [(a["label"], a["amount"], a["account"]) for a in added] == [("CB INTERSPORT", -42.5, "Compte courant")]
    ledger = statements.get_ledger()
    assert ledger["rows"][0]["label"] == "CB INTERSPORT" and ledger["rows"][0]["provisional"]
    assert ledger["total"] == 4380.11
    assert ledger["accounts"][0]["asOf"] == "2024-09-03"

    # 2e ouverture de l'onglet : rien de nouveau, rien en double.
    live[0]["operations"].insert(0, {"date": "2024-09-04", "label": "VIR HELLOASSO", "amount": 100.0})
    assert [a["label"] for a in statements.sync_live(live)["added"]] == ["VIR HELLOASSO"]
    assert len(statements.get_ledger()["rows"]) == 5

    # Le releve de septembre remplace les operations provisoires.
    statements.import_files(
        [("c3.pdf", make_statement(COURANT, ("31/08/2024", 92261), [("03/09/2024", "CB INTERSPORT", -4250, [])], "30/09/2024"))]
    )
    rows = statements.get_ledger()["rows"]
    assert [r["label"] for r in rows][:2] == ["CB INTERSPORT", "VIR SALAIRE"]
    assert not rows[0]["provisional"]


IBAN_LIVRET = "FR76 1027 8089 7200 0204 6160 222"

# Virement interne du 05/09/2024, vu par la connexion bancaire dans chaque compte.
LIVE_TRANSFER = [
    {"iban": IBAN_COURANT, "operations": [{"date": "2024-09-05", "label": "VIR LIVRET BLEU", "amount": -300.0}]},
    {"iban": IBAN_LIVRET, "operations": [{"date": "2024-09-05", "label": "VIR C/C EUROCOMPTE", "amount": 300.0}]},
]


def september(account, start_balance, amount, label):
    return make_statement(account, ("31/08/2024" if account == COURANT else "31/07/2024", start_balance), [("05/09/2024", label, amount, [])], "30/09/2024")


def test_sync_twice_with_provisional_internal_transfer(statements):
    """Les 2 operations provisoires d'un virement interne sont reliees entre
    elles : les remplacer a la synchro suivante ne doit pas echouer (cle
    etrangere transfer_id), et le virement doit rester relie."""
    statements.import_files(history())
    assert len(statements.sync_live(LIVE_TRANSFER)["added"]) == 2
    assert statements.sync_live(LIVE_TRANSFER) == {"added": []}
    ledger = statements.get_ledger()
    assert ledger["rows"][0]["transfer"] == {"from": "Compte courant", "to": "Livret Bleu"}
    assert ledger["total"] == 4422.61  # virement interne : total inchange


@pytest.mark.parametrize("first_imported", [COURANT, LIVRET])
def test_statement_replaces_provisional_internal_transfer(statements, first_imported):
    """Le releve d'un des 2 comptes remplace son operation provisoire alors
    que sa jumelle (provisoire) est dans l'autre compte, puis le releve de
    l'autre compte fait de meme : le virement reste une seule ligne."""
    statements.import_files(history())
    statements.sync_live(LIVE_TRANSFER)
    courant = ("c3.pdf", september(COURANT, 92261, -30000, "VIR LIVRET BLEU"))
    livret = ("l2.pdf", september(LIVRET, 350000, 30000, "VIR C/C EUROCOMPTE"))
    for statement in (courant, livret) if first_imported == COURANT else (livret, courant):
        report = statements.import_files([statement])
        assert len(report["imported"]) == 1 and not report["errors"]
        ledger = statements.get_ledger()
        assert ledger["rows"][0]["transfer"] == {"from": "Compte courant", "to": "Livret Bleu"}
        assert ledger["total"] == 4422.61
    assert not any(r["provisional"] for r in statements.get_ledger()["rows"])


def test_sync_route_never_fails(statements):
    app = FastAPI()

    def broken():
        raise RuntimeError("Banque non connectée")

    BankStatementsReceiver(client=statements, app=app, live_operations=broken)
    assert TestClient(app).post("/bankstatements/sync").json() == {"added": [], "error": "Banque non connectée"}



@pytest.mark.parametrize(
    "label, details, category",
    [
        ("VIR STRIPE TECHNOLOGY", "", "Cotisations en ligne"),
        ("VIR HELLOASSOPAY R4WOXYY6WK2XP0Q HELLOASSO 35", "", "Cotisations en ligne"),
        ("VIR SEPA SALAIRE CHRISTOPHE CH3V26216L038172", "", "Salaires"),
        ("VIR Salaires", "", "Salaires"),
        ("PRLV SEPA URSSAF PACA UR 937000002004519013", "", "URSSAF"),
        ("PLAN SANTE SA1406498", "2508001 SA1406498", "Mutuelle"),
        ("VIR AFFIL. FFST", "", "FFST (licences)"),
        ("REMBOURSEMENT LICENCES", "", "FFST (licences)"),
        ("FACT SGT25089720011273", "DONT TVA 0,38EUR", "Frais bancaires"),
        ("PAIEMENT CB 2603 VOIRON", "FACTURE DIGITALEA", "Autres"),
        ("SOUTIEN ASSO SPORTIVE/CULTURELL", "", "Soutien asso (banque)"),
        ("Intérêts Livret Bleu", "", "Intérêts"),
        ("CB DECATHLON", "", "Autres"),
    ],
)
def test_categorize(label, details, category):
    assert categorize(label, details) == category


def test_ledger_rows_have_a_category(statements):
    statements.import_files(history())
    ledger = statements.get_ledger()
    assert {r["label"]: r["category"] for r in ledger["rows"]} == {
        "VIR SALAIRE": "Salaires",
        "VIR C/C EUROCOMPTE": "Virement interne",
        "CB DECATHLON": "Autres",
    }
    assert ledger["categories"][-2:] == ["Autres", "Virement interne"]
    # Un compte seul : le virement interne reste classe a part.
    alone = statements.get_ledger(ledger["accounts"][0]["id"])
    assert [r["category"] for r in alone["rows"]] == ["Salaires", "Virement interne", "Autres"]
