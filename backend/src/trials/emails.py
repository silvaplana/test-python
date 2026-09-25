"""Mail de confirmation envoye a l'eleve apres son inscription au cours
d'essai : son QR code + le contenu de la page (modalites, horaires, lieux).

HTML volontairement simple (tableaux, styles en ligne) : c'est ce que les
messageries (Gmail, Outlook, Apple Mail) affichent le plus fidelement. Le QR
code est une image hebergee (qr_url) -- Gmail bloque les images integrees en
data: -- et aussi une piece jointe, lisible meme images bloquees.
"""

from __future__ import annotations

from html import escape

from . import content


def confirmation_email(student: dict, qr_url: str) -> tuple[str, str]:
    """Retourne (sujet, HTML) du mail de confirmation."""
    name = escape(f"{student['firstName']} {student['lastName']}")
    rules = "".join(f"<li style='margin-bottom:4px'>{escape(rule)}</li>" for rule in content.RULES)
    sessions = "".join(
        f"<p style='margin:12px 0 4px'><strong>{escape(session['place'])}</strong><br>"
        f"<span style='color:#666'>{escape(session['address'])}</span></p>"
        + "".join(
            f"<div>• {escape(slot['day'])} {escape(slot['time'])} — {escape(slot['audience'])}</div>"
            for slot in session["slots"]
        )
        for session in content.SESSIONS
    )
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
    <img src="{escape(qr_url)}" width="240" height="240" alt="QR code du cours d'essai" style="display:inline-block;border:0">
  </p>
  <p style="text-align:center;margin:0 0 24px;font-size:13px;color:#666">
    Le QR code est aussi joint à ce mail. Il n'est valable que pour un seul cours d'essai.</p>

  <h2 style="font-size:17px;margin:0 0 8px">Modalités</h2>
  <ul style="margin:0 0 20px;padding-left:20px">{rules}</ul>

  <h2 style="font-size:17px;margin:0 0 8px">Horaires et lieux</h2>
  {sessions}

  <p style="margin:24px 0 0;font-size:12px;color:#888">{escape(content.PRIVACY)}</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    return f"Votre cours d'essai – {content.CLUB_NAME}", html
