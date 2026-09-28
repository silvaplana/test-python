"""Mail de confirmation envoye a l'eleve apres son inscription au cours
d'essai : son QR code + le contenu de la page (modalites, horaires, lieux).

HTML volontairement simple (tableaux, styles en ligne) : c'est ce que les
messageries (Gmail, Outlook, Apple Mail) affichent le plus fidelement. Le QR
code est une image integree au mail (src="cid:...", voir Mailer.send) :
affichee meme quand la messagerie bloque les images externes. Version texte
en plus, pour les messageries qui n'affichent pas le HTML.
"""

from __future__ import annotations

from html import escape

from . import content


QR_CID = "qrcode"


def confirmation_email(student: dict) -> tuple[str, str, str]:
    """Retourne (sujet, HTML, texte) du mail de confirmation. Le HTML
    reference l'image du QR code par src="cid:qrcode" (voir QR_CID)."""
    name = escape(f"{student['firstName']} {student['lastName']}")
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
    html = f"""\
<!doctype html>
<html lang="fr">
<body style="margin:0;padding:0;background:#f4f4f5;font-family:Arial,Helvetica,sans-serif;color:#222">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#fff;border-radius:10px">
<tr><td style="padding:24px">
  <h1 style="font-size:22px;margin:0 0 4px">{escape(content.TITLE)}</h1>
  <p style="margin:0 0 20px;color:#666">{escape(content.CLUB_NAME)}</p>
  <p style="margin:0 0 16px">Bonjour,</p>
  <p style="margin:0 0 16px">L'inscription de <strong>{name}</strong> au cours d'essai est confirmée.
  <strong>Présentez ce QR code à l'entraîneur au début du cours d'essai</strong> (sur votre téléphone ou imprimé) :</p>
  <p style="text-align:center;margin:0 0 8px">
    <img src="cid:{QR_CID}" width="240" height="240" alt="QR code du cours d'essai" style="display:inline-block;border:0">
  </p>
  <p style="text-align:center;margin:0 0 24px;font-size:13px;color:#666">
    Il n'est valable que pour un seul cours d'essai.</p>

  <h2 style="font-size:17px;margin:0 0 8px">Modalités</h2>
  <ul style="margin:0 0 20px;padding-left:20px">{rules}</ul>

  <h2 style="font-size:17px;margin:0 0 8px">Horaires d'entraînement</h2>
  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;width:100%">{schedule}</table>
  {places}

  <p style="margin:20px 0 0">Une question ? {contacts}</p>

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
            f"L'inscription de {student['firstName']} {student['lastName']} au cours d'essai est confirmée.",
            "Présentez le QR code de ce mail à l'entraîneur au début du cours d'essai (valable pour un seul cours).",
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
            content.PRIVACY,
        ]
    )
    return f"Votre cours d'essai – {content.CLUB_NAME}", html, text
