"""Tests des assemblees generales (Finances > Assemblées générales) : choix du
bilan et du PPT modele, remplissage du PPT avec le texte de l'IA (simulee
ici), surlignage de "À compléter", garde-fou sur les montants, versions et
envoi d'un PPT modifie.
Lancer depuis backend/ : PYTHONPATH=src venv/bin/python -m pytest tests"""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.oxml.ns import qn

from database import Database
from financialreports.ai import AnalysisError
from generalassemblies import (
    AssemblyError,
    GeneralAssemblies,
    GeneralAssembliesReceiver,
)
from generalassemblies import slides as slides_module
from generalassemblies.ai import Draft
from generalassemblies.slides import amounts_in, check_amounts, outline, texts

SEASONS = [
    {"id": 1, "name": "2024-2025", "startDate": "2024-07-01", "endDate": "2025-06-30", "licences": 47},
    {"id": 2, "name": "2025-2026", "startDate": "2025-07-01", "endDate": "2026-06-30", "licences": 50},
]

RESULT = {
    "start": "2025-07-01",
    "end": "2026-06-30",
    "cutoff": "2026-06-30",
    "opening": 4922.56,
    "closing": 9716.86,
    "income": [{"category": "Cotisations", "amount": 11945.0}, {"category": "Clôture compte", "amount": 3290.74}],
    "expense": [{"category": "Salaires", "amount": 5905.0}],
    "totalIncome": 15718.28,
    "totalExpense": 10923.98,
    "result": 4794.30,
    "net": {"Cotisations": 11945.0, "Salaires": -5905.0},
    "verification": {"ok": True},
    "analysis": ["Ligne 1"],
    "previous": {
        "season": "2024-2025",
        "opening": 3000.0,
        "closing": 4922.56,
        "totalIncome": 9517.0,
        "totalExpense": 8288.0,
        "result": 1229.0,
        "net": {},
    },
}


def make_pptx(path, title="Résumé exécutif 2024/2025", lines=("Résultat global : +1507 €", "Cotisation : 300 €")):
    presentation = Presentation()
    first = presentation.slides.add_slide(presentation.slide_layouts[0])
    first.shapes.title.text = "Assemblée Générale\vBilan saison 2024-2025"
    first.placeholders[1].text = "Date : 04/07/2025"
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.text = lines[0]
    for line in lines[1:]:
        paragraph = body.add_paragraph()
        paragraph.text = line
        paragraph.level = 1
    presentation.save(str(path))
    return path


class FakeWriter:
    """IA simulee : reecrit la diapo 2 (titre et texte) et la date."""

    def __init__(self, error=None, amount="4 794 €"):
        self.error = error
        self.amount = amount
        self.calls = []

    def write(self, model, data, prompt):
        self.calls.append((model, data, prompt))
        if self.error:
            raise AnalysisError(self.error, cost=0.02)
        zones = {z["role"]: z["zone"] for z in data["modele"][1]["zones"]}
        date_zone = data["modele"][0]["zones"][1]["zone"]
        return Draft(
            zones=[
                {"diapo": 2, "zone": zones["titre"], "paragraphes": [{"niveau": 0, "texte": "Résumé exécutif 2025/2026"}]},
                {
                    "diapo": 2,
                    "zone": zones["texte"],
                    "paragraphes": [
                        {"niveau": 0, "texte": f"Résultat global : +{self.amount}"},
                        {"niveau": 1, "texte": "Cotisation : À compléter"},
                    ],
                },
                {"diapo": 1, "zone": date_zone, "paragraphes": [{"niveau": 0, "texte": "Date : À compléter"}]},
                {"diapo": 9, "zone": 99, "paragraphes": [{"niveau": 0, "texte": "zone inconnue"}]},
            ],
            summary=["Diapos du trésorier remplies."],
            model=model,
            served_by="claude-sonnet-5-5",
            cost=0.12,
        )


class Reports:
    """Bilans simules (FinancialReports.list / get)."""

    def __init__(self):
        self.items = {
            2: [
                {"id": 10, "name": "Bilan brouillon", "state": "brouillon", "hasResult": True},
                {"id": 11, "name": "Bilan officiel", "state": "officiel", "hasResult": True},
                {"id": 12, "name": "Bilan vide", "state": "valide", "hasResult": False},
            ]
        }

    def list(self, season_id):
        return self.items.get(season_id, [])

    def get(self, report_id):
        item = next(r for rs in self.items.values() for r in rs if r["id"] == report_id)
        return {**item, "result": RESULT}


@pytest.fixture
def setup(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    with db.connect() as connection:
        for s in SEASONS:
            connection.execute(
                "INSERT INTO seasons (id, name, start_date, end_date, created_at, updated_at) VALUES (?, ?, ?, ?, 'x', 'x')",
                (s["id"], s["name"], s["startDate"], s["endDate"]),
            )
    costs = []
    writer = FakeWriter()
    reports = Reports()
    client = GeneralAssemblies(
        db=db,
        storage_dir=str(tmp_path / "ag"),
        seasons=lambda: SEASONS,
        reports=reports.list,
        report=reports.get,
        # Saison en cours : le cout n'est plus rattache a la saison du calcul.
        add_ai_cost=costs.append,
        writer=writer,
        background=False,
    )
    client.set_template(make_pptx(tmp_path / "modele.pptx").read_bytes())
    return client, writer, reports, costs, tmp_path


def test_amounts_in():
    assert amounts_in("15 718 € et 4 794,36 € puis +1507€, 3.290,74 euros, saison 2025-2026, 50 licenciés") == [
        15718.0,
        4794.36,
        1507.0,
        3290.74,
    ]


def test_check_amounts_flags_unknown_amounts():
    zones = [{"diapo": 7, "paragraphes": [{"texte": "Résultat : +4 794 € ; cotisation 300 €"}]}]
    assert check_amounts(zones, {4794.30}) == ["Diapo 7 : 300 € ne vient pas du bilan, à vérifier."]


def test_run_fills_the_template_with_the_official_report(setup):
    client, writer, _, costs, _ = setup
    assembly = client.create({"seasonId": 2, "name": "AG 2026", "model": "haiku", "prompt": "Ton simple"})
    done = client.run(assembly["id"], {})

    assert done["status"] == "idle"
    assert done["hasPpt"] is True
    # Le modele par defaut (modele general) est devenu le modele du calcul.
    assert [kind for kind, file in done["files"].items() if file] == ["modele", "genere"]
    assert done["files"]["modele"]["source"] == "Pris par défaut, faute de modèle choisi : Modèle général"
    result = done["result"]
    assert result["report"]["name"] == "Bilan officiel"
    assert result["template"]["kind"] == "uploaded"
    assert result["changedSlides"] == [1, 2]
    assert result["warnings"] == []
    assert result["summary"] == ["Diapos du trésorier remplies."]
    assert done["aiCost"] == pytest.approx(0.12)
    assert costs == [0.12]

    model, data, prompt = writer.calls[0]
    assert (model, prompt) == ("haiku", "Ton simple")
    assert data["saison"] == "2025-2026" and data["saisonSuivante"] == "2026-2027"
    assert data["bilan"]["totalRecettes"] == 15718.28
    assert data["licencies"] == [{"saison": "2024-2025", "licencies": 47}, {"saison": "2025-2026", "licencies": 50}]
    assert data["modele"][0]["zones"][0]["paragraphes"][0]["texte"] == "Assemblée Générale\nBilan saison 2024-2025"

    path, filename = client.file_path(assembly["id"])
    assert filename == "AG-2025-2026-AG 2026.pptx"
    slide = texts(path)[1]
    assert slide["title"] == "Résumé exécutif 2025/2026"
    assert slide["lines"] == [
        {"level": 0, "text": "Résultat global : +4 794 €"},
        {"level": 1, "text": "Cotisation : À compléter"},
    ]
    # "À compléter" dans un morceau a part, surligne en jaune.
    body = Presentation(str(path)).slides[1].placeholders[1].text_frame.paragraphs[1]
    highlighted = [r.text for r in body.runs if r._r.find(qn("a:rPr") + "/" + qn("a:highlight")) is not None]
    assert highlighted == ["À compléter"]


def test_run_warns_about_amounts_not_in_the_report(setup):
    client, writer, *_ = setup
    writer.amount = "1 507 €"
    assembly = client.create({"seasonId": 2, "name": "AG"})
    assert client.run(assembly["id"], {})["result"]["warnings"] == ["Diapo 2 : 1 507 € ne vient pas du bilan, à vérifier."]
    # Un montant donne dans le prompt est accepte.
    assert client.run(assembly["id"], {"prompt": "Le résultat de l'an dernier était 1507 €"})["result"]["warnings"] == []
    # Le nouveau PPT a remplace le precedent : un seul fichier par sorte.
    folder = client.storage / str(assembly["id"])
    assert len(list(folder.glob("v*.pptx"))) == 2


def test_run_needs_a_report_and_a_template(setup):
    client, _, reports, _, _ = setup
    assembly = client.create({"seasonId": 1, "name": "AG 2025"})
    with pytest.raises(AssemblyError, match="Bilan financier"):
        client.run(assembly["id"], {})
    reports.items[1] = [{"id": 20, "name": "B", "state": "valide", "hasResult": True}]
    client.template_path.unlink()
    with pytest.raises(AssemblyError, match="PPT modèle"):
        client.run(assembly["id"], {})


def test_previous_official_assembly_is_the_template(setup):
    client, _, reports, _, tmp_path = setup
    reports.items[1] = [{"id": 20, "name": "B", "state": "valide", "hasResult": True}]
    previous = client.create({"seasonId": 1, "name": "AG 2025", "state": "officiel"})
    client.upload(previous["id"], make_pptx(tmp_path / "ag2025.pptx", title="Résumé 2025").read_bytes(), "ag2025.pptx")

    options = client.options(2)
    assert options["report"] == {"id": 11, "name": "Bilan officiel", "state": "officiel"}
    assert options["template"] == {"kind": "previous", "name": "AG officielle 2024-2025 (AG 2025)"}
    assembly = client.create({"seasonId": 2, "name": "AG 2026"})
    assert client.run(assembly["id"], {})["result"]["template"]["kind"] == "previous"


def test_own_model_is_used_instead_of_the_default(setup):
    client, writer, _, _, tmp_path = setup
    assembly = client.create({"seasonId": 2, "name": "AG 2026"})
    client.set_model(assembly["id"], make_pptx(tmp_path / "ex.pptx", title="Exemple du club").read_bytes(), "ex.pptx")

    done = client.run(assembly["id"], {})

    assert done["result"]["template"] == {"kind": "own", "name": "ex.pptx"}
    assert writer.calls[0][1]["modele"][1]["zones"][0]["paragraphes"][0]["texte"] == "Exemple du club"
    # Le modele reste celui choisi, et un PPT modifie ne le remplace pas.
    client.upload(assembly["id"], make_pptx(tmp_path / "m.pptx", title="Retouché").read_bytes(), "m.pptx")
    files = client.get(assembly["id"])["files"]
    assert [files[kind]["filename"] for kind in ("modele", "genere", "modifie")] == ["ex.pptx", "AG-2025-2026-AG 2026.pptx", "m.pptx"]
    assert texts(client.file_path(assembly["id"])[0])[1]["title"] == "Retouché"


def test_one_official_per_season_and_delete(setup):
    client, *_ = setup
    first = client.create({"seasonId": 2, "name": "A", "state": "officiel"})
    client.run(first["id"], {})
    second = client.create({"seasonId": 2, "name": "B", "state": "officiel"})
    assert client.get(first["id"])["state"] == "valide"
    assert client.get(second["id"])["state"] == "officiel"
    folder = client.storage / str(first["id"])
    assert folder.exists()
    client.delete(first["id"])
    assert not folder.exists()
    assert [a["name"] for a in client.list(2)] == ["B"]


def test_ai_error_keeps_cost_and_no_version(setup):
    client, writer, _, costs, _ = setup
    writer.error = "L'IA a refusé de préparer cette AG."
    assembly = client.create({"seasonId": 2, "name": "AG"})
    done = client.run(assembly["id"], {})
    assert (done["status"], done["error"]) == ("error", "L'IA a refusé de préparer cette AG.")
    assert done["hasPpt"] is False
    assert costs == [0.02]


def test_api_upload_download_and_slides(setup, monkeypatch):
    client, *_, tmp_path = setup
    monkeypatch.setattr(slides_module, "soffice", lambda: None)
    app = FastAPI()
    GeneralAssembliesReceiver(client=client, app=app)
    http = TestClient(app)

    created = http.post("/general-assemblies", json={"seasonId": 2, "name": "AG 2026"}).json()
    assert http.post(f"/general-assemblies/{created['id']}/run", json={"model": "fable"}).json()["model"] == "fable"

    sent = make_pptx(tmp_path / "modifie.pptx", title="Ma version").read_bytes()
    response = http.post(f"/general-assemblies/{created['id']}/upload", files={"file": ("ma-version.pptx", sent)})
    assert [kind for kind, file in response.json()["files"].items() if file] == ["modele", "genere", "modifie"]
    assert response.json()["files"]["modifie"]["filename"] == "ma-version.pptx"

    download = http.get(f"/general-assemblies/{created['id']}/download")
    assert download.status_code == 200
    assert texts(io.BytesIO(download.content))[1]["title"] == "Ma version"
    first = http.get(f"/general-assemblies/{created['id']}/download?kind=genere")
    assert texts(io.BytesIO(first.content))[1]["title"] == "Résumé exécutif 2025/2026"

    preview = http.get(f"/general-assemblies/{created['id']}/files/modifie/slides").json()
    assert preview["thumbnails"] is False
    assert [s["title"] for s in preview["slides"]] == ["Assemblée Générale Bilan saison 2024-2025", "Ma version"]

    bad = http.post(f"/general-assemblies/{created['id']}/upload", files={"file": ("x.pptx", b"pas un ppt")})
    assert bad.status_code == 400
    listing = http.get("/general-assemblies?seasonId=2").json()
    assert listing["templateUploaded"] is True
    assert listing["counts"] == {"2": 1}
    assert [a["hasPpt"] for a in listing["assemblies"]] == [True]
    assert http.get(f"/general-assemblies/{created['id']}/files/inconnu/slides").status_code == 404

    # Modele d'un autre calcul : fichier de l'ordinateur, ou PPT d'un calcul.
    other = http.post("/general-assemblies", json={"seasonId": 2, "name": "Essai"}).json()
    local = make_pptx(tmp_path / "local.pptx", title="Mon exemple").read_bytes()
    sent = http.post(f"/general-assemblies/{other['id']}/model", files={"file": ("exemple.pptx", local)}).json()
    assert sent["files"]["modele"]["filename"] == "exemple.pptx" and sent["hasPpt"] is False
    sources = http.get(f"/general-assemblies/model-sources?exclude={other['id']}").json()
    assert [(x["assemblyId"], x["kind"]) for x in sources] == [
        (created["id"], "modifie"),
        (created["id"], "genere"),
        (created["id"], "modele"),
        (None, "general"),
    ]
    assert sources[0]["label"] == "2025-2026, AG 2026 : PPT modifié"
    copied = http.put(f"/general-assemblies/{other['id']}/model", json={"sourceId": created["id"], "kind": "modifie"})
    assert copied.json()["files"]["modele"]["filename"] == "ma-version.pptx"
    assert copied.json()["files"]["modele"]["source"] == "Copie du PPT modifié du calcul « AG 2026 » (2025-2026)"
    assert sent["files"]["modele"]["source"] == "Importé de ton ordinateur"
    model = http.get(f"/general-assemblies/{other['id']}/download?kind=modele")
    assert texts(io.BytesIO(model.content))[1]["title"] == "Ma version"
    assert http.put(f"/general-assemblies/{other['id']}/model", json={"sourceId": other["id"], "kind": "modele"}).status_code == 400
    assert http.put(f"/general-assemblies/{other['id']}/model", json={"kind": "general"}).status_code == 200


def test_outline_skips_empty_zones(tmp_path):
    path = make_pptx(tmp_path / "m.pptx")
    zones = outline(path)[1]["zones"]
    assert [z["role"] for z in zones] == ["titre", "texte"]
    assert zones[1]["paragraphes"][1] == {"niveau": 1, "texte": "Cotisation : 300 €"}


def test_settings_open_is_kept(setup):
    """La zone "Réglages de l'IA" pliee ou depliee est retenue par calcul."""
    client, *_ = setup
    app = FastAPI()
    GeneralAssembliesReceiver(client=client, app=app)
    http = TestClient(app)
    created = http.post("/general-assemblies", json={"seasonId": 2, "name": "AG"}).json()
    assert created["settingsOpen"] is True
    assert http.put(f"/general-assemblies/{created['id']}/settings", json={"open": False}).json() == {"settingsOpen": False}
    assert http.get(f"/general-assemblies/{created['id']}").json()["settingsOpen"] is False
    assert http.put("/general-assemblies/999/settings", json={"open": True}).status_code == 404
