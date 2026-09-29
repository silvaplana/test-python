"""Mail de confirmation envoye a l'eleve apres son inscription au cours
d'essai : le QR code de chaque personne inscrite + le contenu de la page
(modalites, horaires, lieux).

HTML volontairement simple (tableaux, styles en ligne) : c'est ce que les
messageries (Gmail, Outlook, Apple Mail) affichent le plus fidelement. Le QR
code de chaque personne est une image integree au mail (src="cid:...", voir Mailer.send) :
affichee meme quand la messagerie bloque les images externes. Version texte
en plus, pour les messageries qui n'affichent pas le HTML.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import content

PARIS = ZoneInfo("Europe/Paris")


def signature_cid(index: int) -> str:
    """Identifiant de l'image de la signature numero index (1re personne,
    puis representants legaux) dans le mail : src="cid:signature-0"..."""
    return f"signature-{index}"


def qr_cid(index: int) -> str:
    """Identifiant de l'image du QR code de la personne numero index (a
    partir de 0) dans le mail : src="cid:qrcode-0"..."""
    return f"qrcode-{index}"


def _names(students: list[dict]) -> str:
    names = [f"{s['firstName']} {s['lastName']}" for s in students]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1]


def _summary(students: list[dict]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Recapitulatif de ce qui a ete saisi a l'inscription : [(titre,
    [(libelle, valeur)])], une section par personne puis le contact (les
    signatures sont ajoutees a part, en image)."""
    # C'est la 1re personne inscrite qui remplit le formulaire : c'est elle
    # qui accepte la decharge pour chacun.
    author = f"{students[0]['firstName']} {students[0]['lastName']}"
    sections = []
    for student in students:
        rows = [
            ("Prénom", student["firstName"]),
            ("Nom", student["lastName"]),
            ("Âge", f"{student['age']} ans (mineur)" if student["age"] is not None else "majeur"),
            ("Certificat médical", "joint" if student["hasMedicalCertificate"] else "non fourni"),
            ("Décharge de responsabilité", f"acceptée par {author}" if student["waiverAccepted"] else "non acceptée"),
        ]
        if student["parentName"]:
            rows.append(("Parent ou représentant légal", student["parentName"]))
            rows.append(
                ("Autorisation parentale", "donnée (signature)" if student["parentalConsent"] else "non donnée")
            )
        sections.append((f"{student['firstName']} {student['lastName']}", rows))
    sections.append(("Contact", [("E-mail", students[0]["email"] or "")]))
    return sections


def _signed_at(signed_at: str | None) -> str | None:
    """Date et heure de la signature, heure de Paris ("29/09/2026 à 14h05")."""
    if not signed_at:
        return None
    return datetime.fromisoformat(signed_at).astimezone(PARIS).strftime("%d/%m/%Y à %Hh%M")


def _signature_title(signature: dict, students: list[dict]) -> str:
    """"Signature de Paul Martin" (+ ", représentant légal de Léa Martin")."""
    title = f"Signature de {signature['name']}"
    children = [s for s in students if (s["parentName"] or "").casefold() == signature["name"].casefold()]
    if children:
        title += f", représentant légal de {_names(children)}"
    return title


def confirmation_email(students: list[dict], signatures: list[dict]) -> tuple[str, str, str]:
    """Retourne (sujet, HTML, texte) du mail de confirmation pour les
    personnes d'une meme demande (1 a 3), avec le QR code de chacune (voir
    qr_cid) et les signatures de la demande (voir signature_cid)."""
    several = len(students) > 1
    qr_codes = "".join(
        f"""<p style="text-align:center;margin:0 0 4px">
    <img src="cid:{qr_cid(i)}" width="220" height="220" alt="QR code de {escape(s['firstName'])}" style="display:inline-block;border:0">
  </p>
  <p style="text-align:center;margin:0 0 20px;font-weight:bold">{escape(s['firstName'])} {escape(s['lastName'])}</p>"""
        for i, s in enumerate(students)
    )
    rules = "".join(f"<li style='margin-bottom:4px'>{escape(rule)}</li>" for rule in content.RULES)
    schedule = "".join(
        f"<tr><td style='padding:6px 8px;border:1px solid #ccc'><strong>{escape(slot['day'])}</strong> "
        f"{escape(slot['time'])}</td><td style='padding:6px 8px;border:1px solid #ccc'>{escape(slot['course'])}</td>"
        f"<td style='padding:6px 8px;border:1px solid #ccc'>{escape(slot['place'])}</td></tr>"
        for slot in content.SCHEDULE
    )
    places = "".join(
        f"<p style='margin:10px 0 0'><strong>{escape(place['name'])}</strong> : {escape(place['address'])} "
        f"(<a href='{escape(place['map'])}' style='color:#bc964f'>voir sur la carte</a>)</p>"
        for place in content.PLACES
    )
    contacts = " – ".join(f"{escape(c['name'])} : {escape(c['phone'])}" for c in content.CONTACTS)
    first = students[0]
    author = escape(f"{first['firstName']} {first['lastName']}")
    signature_html = "".join(
        f"""<h3 style="font-size:15px;margin:18px 0 6px">{escape(_signature_title(sig, students))}</h3>
  <img src="cid:{signature_cid(i)}" width="280" alt="Signature" style="display:block;max-width:100%;height:auto;border:1px solid #ccc">
  {f'<p style="margin:6px 0 0;font-size:13px;color:#666">Signée le {_signed_at(sig["signedAt"])}</p>' if sig["signedAt"] else ''}"""
        for i, sig in enumerate(signatures)
    )
    certificates_note = (
        "Le certificat médical de chaque personne est joint à ce mail."
        if several
        else "Le certificat médical est joint à ce mail."
    )
    summary = _summary(students)
    summary_html = "".join(
        f"<h3 style='font-size:15px;margin:14px 0 4px'>{escape(title)}</h3>"
        + "".join(f"<div>{escape(label)} : <strong>{escape(value)}</strong></div>" for label, value in rows)
        for title, rows in summary
    )
    html = f"""\
<!doctype html>
<html lang="fr">
<body style="margin:0;padding:0;background:#f4f4f5;font-family:Arial,Helvetica,sans-serif;color:#222">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#fff;border-radius:10px">
<tr><td style="padding:24px">
  <h1 style="font-size:22px;margin:0 0 4px">Votre cours d'essai gratuit</h1>
  <p style="margin:0 0 20px;color:#666">{escape(content.CLUB_NAME)}</p>
  <p style="margin:0 0 16px">Bonjour,</p>
  <p style="margin:0 0 16px">L'inscription de <strong>{escape(_names(students))}</strong> au cours d'essai est confirmée.
  <strong>Présentez {"le QR code de chaque personne" if several else "ce QR code"} à l'entraîneur au début du cours d'essai</strong>
  (sur votre téléphone ou imprimé) :</p>
  {qr_codes}
  <p style="text-align:center;margin:0 0 24px;font-size:13px;color:#666">
    {"Chaque QR code n'est valable" if several else "Il n'est valable"} que pour un seul cours d'essai.</p>

  <h2 style="font-size:17px;margin:0 0 8px">Modalités</h2>
  <ul style="margin:0 0 20px;padding-left:20px">{rules}</ul>

  <h2 style="font-size:17px;margin:0 0 8px">Horaires d'entraînement</h2>
  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;width:100%">{schedule}</table>
  {places}

  <p style="margin:20px 0 0">Une question ? {contacts}</p>

  <h2 style="font-size:17px;margin:28px 0 4px;padding-top:16px;border-top:1px solid #ddd">Informations renseignées par {author}</h2>
  <div style="font-size:14px">{summary_html}</div>
  <p style="margin:12px 0 0;font-size:13px;color:#666">{certificates_note}</p>
  {signature_html}

  <p style="margin:24px 0 0;font-size:12px;color:#888">{escape(content.PRIVACY)}</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    text = "\n".join(
        [
            "Bonjour,",
            "",
            f"L'inscription de {_names(students)} au cours d'essai est confirmée.",
            "Présentez le QR code de chaque personne (images de ce mail) à l'entraîneur au début du cours d'essai "
            "(valable pour un seul cours).",
            "",
            "MODALITÉS",
            *(f"- {rule}" for rule in content.RULES),
            "",
            "HORAIRES D'ENTRAÎNEMENT",
            *(f"- {slot['day']} {slot['time']} : {slot['course']} ({slot['place']})" for slot in content.SCHEDULE),
            "",
            *(f"{place['name']} : {place['address']}" for place in content.PLACES),
            "",
            "Une question ? " + " – ".join(f"{c['name']} : {c['phone']}" for c in content.CONTACTS),
            "",
            f"INFORMATIONS RENSEIGNÉES PAR {first['firstName']} {first['lastName']}".upper(),
            *(
                line
                for title, rows in _summary(students)
                for line in ("", title, *(f"- {label} : {value}" for label, value in rows))
            ),
            "",
            certificates_note,
            "",
            *(
                f"{_signature_title(sig, students)} : image dans ce mail, signée le {_signed_at(sig['signedAt'])}."
                for sig in signatures
            ),
            "",
            content.PRIVACY,
        ]
    )
    return f"Votre cours d'essai – {content.CLUB_NAME}", html, text
