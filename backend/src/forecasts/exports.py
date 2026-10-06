"""Telechargement du resultat d'un previsionnel : image (PNG) ou PDF.

L'image : titre, chiffres cles et courbe du solde (reel puis prevu, et la
saison precedente pour comparer), dessinee en SVG puis convertie par
PyMuPDF. Le PDF reprend l'image, les curseurs, l'explication et la formule.
"""

from __future__ import annotations

import html
import io
import math
from datetime import date

import pymupdf

from . import data as forecast_data

WIDTH, HEIGHT = 1000, 560
CHART = {"left": 80, "right": 970, "top": 170, "bottom": 500}
REAL, FORECAST, PREVIOUS, ACTUAL = "#7c3aed", "#ea7a1a", "#3987e5", "#b9a3e8"
BASELINE = "#9ca3af"  # ligne d'equilibre (solde du debut de la saison)
MONTHS = ["juil.", "août", "sept.", "oct.", "nov.", "déc.", "janv.", "févr.", "mars", "avr.", "mai", "juin"]


def _eur(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    text = f"{abs(value):,.{decimals}f}".replace(",", " ").replace(".", ",")
    return ("−" if value < 0 else "") + text + " €"


def _fr(iso: str) -> str:
    year, month, day = iso[:10].split("-")
    return f"{day}/{month}/{year}"


def _day(iso: str) -> int:
    return date.fromisoformat(iso).toordinal()


def _value(param: dict, value: float) -> str:
    number = f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
    return f"{number} {param['unit']}".strip()


def summary(forecast: dict) -> dict:
    """Chiffres cles : solde prevu en fin de saison, point le plus bas."""
    points = forecast["result"]["points"]
    low = min(points, key=lambda p: p["solde"])
    return {"end": points[-1], "low": low, "start": points[0]}


def chart_svg(forecast: dict, ledger: dict, previous: dict | None) -> str:
    """Image du resultat (SVG). previous : saison precedente (fiche de
    Seasons) a superposer, ou None."""
    result = forecast["result"]
    data = result["data"]
    rows = forecast_data.history(ledger)
    season_start, season_end = data["debutSaison"], data["finSaison"]
    x0, x1 = _day(season_start), _day(season_end)
    start = data["dateDepart"]

    # Reel jusqu'a la date de depart (le solde reste plat apres la derniere
    # operation).
    real = forecast_data.realized(rows, season_start, start)
    if real and real[-1]["date"] < start:
        real.append({"date": start, "solde": data["soldeDepart"]})
    after = forecast_data.realized(rows, start, season_end)[1:]  # reel apres le depart (test sur le passe)
    prev = []
    if previous is not None:
        offset = x0 - _day(previous["startDate"])
        points = forecast_data.realized(rows, previous["startDate"], previous["endDate"])
        if points and points[-1]["date"] < previous["endDate"]:
            points.append({"date": previous["endDate"], "solde": points[-1]["solde"]})
        prev = [{"x": _day(p["date"]) + offset, "v": p["solde"]} for p in points]
    lines = {
        "real": [{"x": _day(p["date"]), "v": p["solde"]} for p in real],
        "after": [{"x": _day(start), "v": data["soldeDepart"]}] + [{"x": _day(p["date"]), "v": p["solde"]} for p in after] if after else [],
        "forecast": [{"x": _day(p["date"]), "v": p["solde"]} for p in result["points"]],
        "prev": prev,
    }
    values = [p["v"] for line in lines.values() for p in line if p["v"] is not None]
    # Ligne d'equilibre : le solde du debut de la saison.
    baseline = data.get("soldeDebutSaison")
    if baseline is not None:
        values.append(baseline)
    low, high = min(values), max(values)
    step = _nice_step((high - low) / 4 or 1000)
    y_min, y_max = math.floor(low / step) * step, math.ceil(high / step) * step
    if y_min == y_max:
        y_max += step
    c = CHART

    def x(day: int) -> float:
        return c["left"] + (day - x0) / (x1 - x0 or 1) * (c["right"] - c["left"])

    def y(v: float) -> float:
        return c["bottom"] - (v - y_min) / (y_max - y_min) * (c["bottom"] - c["top"])

    def steps(line: list[dict]) -> str:
        """Escalier (le solde ne change qu'aux operations)."""
        out = []
        for i, p in enumerate(line):
            if i:
                out.append(f"{x(p['x']):.1f},{y(line[i - 1]['v']):.1f}")
            out.append(f"{x(p['x']):.1f},{y(p['v']):.1f}")
        return " ".join(out)

    def dashes(line: list[dict], dash: float = 9, gap: float = 6) -> str:
        """Trait en pointilles (PyMuPDF ignore stroke-dasharray)."""
        pts = [(x(p["x"]), y(p["v"])) for p in line]
        out, on, left = [], True, dash
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            length = math.hypot(bx - ax, by - ay)
            pos = 0.0
            while pos < length:
                cut = min(length, pos + left)
                if on:
                    f0, f1 = pos / length, cut / length
                    out.append(
                        f'<line x1="{ax + (bx - ax) * f0:.1f}" y1="{ay + (by - ay) * f0:.1f}" '
                        f'x2="{ax + (bx - ax) * f1:.1f}" y2="{ay + (by - ay) * f1:.1f}" '
                        f'stroke="{FORECAST}" stroke-width="3" stroke-linecap="round"/>'
                    )
                left -= cut - pos
                pos = cut
                if left <= 1e-6:
                    on = not on
                    left = dash if on else gap
        return "".join(out)

    figures = summary(forecast)
    e = html.escape
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" font-family="sans-serif">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        f'<text x="40" y="44" font-size="24" font-weight="bold" fill="#1f2937">{e(forecast["name"])} — saison {e(result["seasonName"])}</text>',
        f'<text x="40" y="72" font-size="14" fill="#6b7280">Solde courant + Livret Bleu. Départ le {_fr(start)} ({_eur(data["soldeDepart"])}), '
        f'formule écrite par {e(result["modelLabel"])}.</text>',
        f'<text x="40" y="112" font-size="14" fill="#6b7280">Solde prévu au {_fr(season_end)}</text>',
        f'<text x="40" y="142" font-size="26" font-weight="bold" fill="{FORECAST}">{_eur(figures["end"]["solde"])}</text>',
    ]
    if data.get("soldeDebutSaison") is not None:
        outcome = figures["end"]["solde"] - data["soldeDebutSaison"]
        parts.append(f'<text x="330" y="112" font-size="14" fill="#6b7280">Résultat prévu au {_fr(season_end)}</text>')
        parts.append(f'<text x="330" y="142" font-size="20" fill="#1f2937">{"+" if outcome >= 0 else "−"}{_eur(abs(outcome))}</text>')
    if after:
        parts.append(f'<text x="680" y="112" font-size="14" fill="#6b7280">Réel au {_fr(after[-1]["date"])}</text>')
        parts.append(f'<text x="680" y="142" font-size="20" fill="#1f2937">{_eur(after[-1]["solde"])}</text>')
    v = y_min
    while v <= y_max + 1e-6:
        parts.append(f'<line x1="{c["left"]}" y1="{y(v):.1f}" x2="{c["right"]}" y2="{y(v):.1f}" stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(f'<text x="{c["left"] - 8}" y="{y(v) + 4:.1f}" font-size="12" fill="#6b7280" text-anchor="end">{_eur(v, 0)}</text>')
        v += step
    first = date.fromisoformat(season_start)
    for i, name in enumerate(MONTHS):
        month = date(first.year + (first.month + i - 1) // 12, (first.month + i - 1) % 12 + 1, 15)
        if month.toordinal() <= x1:
            parts.append(f'<text x="{x(month.toordinal()):.1f}" y="{c["bottom"] + 22}" font-size="12" fill="#6b7280" text-anchor="middle">{name}</text>')
    if baseline is not None:
        parts.append(
            f'<line x1="{c["left"]}" y1="{y(baseline):.1f}" x2="{c["right"]}" y2="{y(baseline):.1f}" stroke="{BASELINE}" stroke-width="1.5"/>'
        )
    if prev:
        parts.append(f'<polyline points="{steps(prev)}" fill="none" stroke="{PREVIOUS}" stroke-width="1.5"/>')
    if lines["after"]:
        parts.append(f'<polyline points="{steps(lines["after"])}" fill="none" stroke="{ACTUAL}" stroke-width="2"/>')
    if lines["real"]:
        parts.append(f'<polyline points="{steps(lines["real"])}" fill="none" stroke="{REAL}" stroke-width="3"/>')
    parts.append(dashes(lines["forecast"]))
    if baseline is not None:
        # Par-dessus les courbes, sur un fond blanc pour rester lisible.
        text = f"ligne d'équilibre : {_eur(baseline, 0)}"
        parts.append(
            f'<rect x="{c["right"] - 7 * len(text) - 6}" y="{y(baseline) - 20:.1f}" width="{7 * len(text) + 6}" height="16" fill="#ffffff" opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{c["right"]}" y="{y(baseline) - 7:.1f}" font-size="12" fill="#4b5563" text-anchor="end">{text}</text>'
        )
    legend = [(REAL, "réalisé"), (FORECAST, "prévision")]
    if lines["after"]:
        legend.append((ACTUAL, "réel après le départ"))
    if previous is not None:
        legend.append((PREVIOUS, previous["name"]))
    if baseline is not None:
        legend.append((BASELINE, "ligne d'équilibre"))
    lx = c["left"]
    for color, label in legend:
        parts.append(f'<line x1="{lx}" y1="{HEIGHT - 22}" x2="{lx + 22}" y2="{HEIGHT - 22}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{lx + 30}" y="{HEIGHT - 17}" font-size="13" fill="#374151">{e(label)}</text>')
        lx += 60 + 8 * len(label)
    parts.append("</svg>")
    return "".join(parts)


def _nice_step(raw: float) -> float:
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * power:
            return factor * power
    return 10 * power


def to_png(svg: str) -> bytes:
    document = pymupdf.open(stream=svg.encode(), filetype="svg")
    return document[0].get_pixmap(dpi=144).tobytes("png")


_CSS = """
* { font-family: sans-serif; font-size: 9.5pt; color: #222; }
h1 { font-size: 15pt; margin: 0 0 4pt; }
h2 { font-size: 11.5pt; margin: 10pt 0 4pt; }
table { border-collapse: collapse; }
th { background: #ece6f6; text-align: left; padding: 2pt 6pt; }
td { padding: 2pt 6pt; border-bottom: 1px solid #ddd; }
td.num { text-align: right; }
pre { font-family: monospace; font-size: 7.5pt; background: #f5f5f5; padding: 6pt; }
.muted { color: #666; }
"""


def to_pdf(forecast: dict, png: bytes) -> bytes:
    result = forecast["result"]
    params = forecast["params"]
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(p['label'])}</td><td class='num'>{e(_value(p, params.get(p['name'], p['default'])))}</td>"
        f"<td class='num'>{e(_value(p, p['default']))}</td><td class='num'>{e(_value(p, p['min']))} à {e(_value(p, p['max']))}</td></tr>"
        for p in result["parameters"]
    )
    body = (
        f"<h1>Prévisionnel « {e(forecast['name'])} » — saison {e(result['seasonName'])}</h1>"
        f"<p class='muted'>Calculé le {_fr(result['generatedAt'])} : formule écrite par {e(result['modelLabel'])}, "
        f"exécutée par l'application.</p>"
        "<img src='courbe.png' width='520'/>"
        f"<h2>Paramètres</h2><table><tr><th>Paramètre</th><th>Valeur</th><th>Défaut</th><th>Bornes</th></tr>{rows}</table>"
        f"<h2>Explication de l'IA</h2><p>{e(result['explanation'])}</p>"
        f"<h2>Prompt</h2><p>{e(forecast['prompt'] or '(aucun)')}</p>"
        f"<h2>Formule Python</h2><pre>{e(result['code'])}</pre>"
    )
    archive = pymupdf.Archive()
    archive.add(png, "courbe.png")
    buffer = io.BytesIO()
    page = pymupdf.paper_rect("a4")
    where = page + (36, 36, -36, -36)
    story = pymupdf.Story(html=body, user_css=_CSS, archive=archive)
    writer = pymupdf.DocumentWriter(buffer)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    # Polices reduites aux caracteres utilises et contenu compresse : sans
    # cela le PDF embarque les polices entieres (plusieurs Mo).
    document = pymupdf.open(stream=buffer.getvalue(), filetype="pdf")
    try:
        document.subset_fonts()
    except Exception:  # noqa: BLE001 - outil de reduction absent : PDF plus lourd, mais correct
        pass
    return document.tobytes(garbage=4, deflate=True)
