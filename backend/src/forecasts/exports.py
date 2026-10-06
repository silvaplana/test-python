"""Telechargement du resultat d'un previsionnel : image (PNG) ou PDF.

Les deux contiennent la meme chose, et rien d'autre : le titre, les
parametres choisis (position des curseurs), les soldes (debut de saison,
prevu en fin de saison), le resultat prevu et le graphique -- reel puis
prevu, avec les saisons choisies a l'ecran pour comparer. L'image est
dessinee en SVG puis convertie par PyMuPDF ; le PDF a son texte en vrai
texte et le graphique en image.
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
REAL, FORECAST, ACTUAL = "#7c3aed", "#ea7a1a", "#b9a3e8"
# Couleur des saisons comparees, dans l'ordre des saisons : les memes qu'a
# l'ecran (SEASON_COLORS de Seasons.jsx).
SEASON_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]
# Hauteur du haut de l'image (titre, parametres, soldes) au-dessus du graphique.
HEADER = 150
PARAMS_LINE = 118  # caracteres par ligne de parametres dans l'image
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


def chosen_parameters(forecast: dict) -> list[tuple[str, str]]:
    """Parametres choisis : (libelle, valeur) a la position des curseurs."""
    params = forecast.get("params") or {}
    return [(p["label"], _value(p, params.get(p["name"], p["default"]))) for p in forecast["result"]["parameters"]]


def figures(forecast: dict) -> list[tuple[str, str]]:
    """Soldes et resultat : (libelle, valeur) du debut de saison, du solde
    prevu en fin de saison et du resultat prevu (leur difference)."""
    data = forecast["result"]["data"]
    end = forecast["result"]["points"][-1]["solde"]
    opening = data.get("soldeDebutSaison")
    outcome = None if opening is None else end - opening
    return [
        (f"Solde au {_fr(data['debutSaison'])}", _eur(opening)),
        (f"Solde prévu au {_fr(data['finSaison'])}", _eur(end)),
        (
            f"Résultat prévu au {_fr(data['finSaison'])}",
            "—" if outcome is None else ("+" if outcome >= 0 else "−") + _eur(abs(outcome)),
        ),
    ]


def _wrap(parts: list[str], width: int) -> list[str]:
    """Regroupe des morceaux de texte en lignes d'au plus `width` caracteres."""
    lines: list[str] = []
    for part in parts:
        if lines and len(lines[-1]) + len(part) + 3 <= width:
            lines[-1] += " ; " + part
        else:
            lines.append(part)
    return lines


def chart_svg(forecast: dict, ledger: dict, compared: list[dict], header: bool = True) -> str:
    """Image du resultat (SVG). compared : saisons a superposer pour comparer
    (fiches de Seasons, avec leur "color"). header=False : le graphique seul,
    sans le titre, les parametres ni les soldes (pour le PDF)."""
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
    # Saisons comparees, ramenees sur l'axe de la saison du previsionnel.
    others = []
    for season in compared:
        offset = x0 - _day(season["startDate"])
        points = forecast_data.realized(rows, season["startDate"], season["endDate"])
        if points and points[-1]["date"] < season["endDate"]:
            points.append({"date": season["endDate"], "solde": points[-1]["solde"]})
        if points:
            others.append((season, [{"x": _day(p["date"]) + offset, "v": p["solde"]} for p in points]))
    lines = {
        "real": [{"x": _day(p["date"]), "v": p["solde"]} for p in real],
        "after": [{"x": _day(start), "v": data["soldeDepart"]}] + [{"x": _day(p["date"]), "v": p["solde"]} for p in after] if after else [],
        "forecast": [{"x": _day(p["date"]), "v": p["solde"]} for p in result["points"]],
    }
    values = [p["v"] for line in [*lines.values(), *(points for _, points in others)] for p in line if p["v"] is not None]
    # Ligne d'equilibre : le solde du debut de la saison.
    baseline = data.get("soldeDebutSaison")
    if baseline is not None:
        values.append(baseline)
    low, high = min(values), max(values)
    step = _nice_step((high - low) / 4 or 1000)
    y_min, y_max = math.floor(low / step) * step, math.ceil(high / step) * step
    if y_min == y_max:
        y_max += step
    # Haut de l'image : titre, parametres choisis (une ou plusieurs lignes),
    # soldes et resultat. Le graphique descend d'autant.
    e = html.escape
    params_lines = _wrap([f"{label} : {value}" for label, value in chosen_parameters(forecast)], PARAMS_LINE) if header else []
    top = (HEADER + 20 * max(0, len(params_lines) - 1)) if header else 20
    shift = top - CHART["top"]
    c = {**CHART, "top": CHART["top"] + shift, "bottom": CHART["bottom"] + shift}
    height = HEIGHT + shift

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

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" font-family="sans-serif">',
        f'<rect width="{WIDTH}" height="{height}" fill="#ffffff"/>',
    ]
    if header:
        parts.append(
            f'<text x="40" y="44" font-size="24" font-weight="bold" fill="#1f2937">{e(forecast["name"])} — saison {e(result["seasonName"])}</text>'
        )
        for i, line in enumerate(params_lines):
            parts.append(f'<text x="40" y="{70 + 20 * i}" font-size="14" fill="#374151">{e(line)}</text>')
        base = 70 + 20 * max(1, len(params_lines))
        for i, (label, value) in enumerate(figures(forecast)):
            color = FORECAST if i == 1 else "#1f2937"
            parts.append(f'<text x="{40 + 310 * i}" y="{base + 14}" font-size="14" fill="#6b7280">{e(label)}</text>')
            parts.append(f'<text x="{40 + 310 * i}" y="{base + 42}" font-size="22" font-weight="bold" fill="{color}">{e(value)}</text>')
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
    for season, points in others:
        parts.append(f'<polyline points="{steps(points)}" fill="none" stroke="{season["color"]}" stroke-width="1.5"/>')
    if lines["after"]:
        parts.append(f'<polyline points="{steps(lines["after"])}" fill="none" stroke="{ACTUAL}" stroke-width="2"/>')
    if lines["real"]:
        parts.append(f'<polyline points="{steps(lines["real"])}" fill="none" stroke="{REAL}" stroke-width="3"/>')
    parts.append(dashes(lines["forecast"]))
    if baseline is not None:
        # Par-dessus les courbes, avec un lisere blanc pour rester lisible
        # (trace d'abord en contour epais, puis en plein).
        text = f"ligne d'équilibre : {_eur(baseline, 0)}"
        where = f'x="{c["right"]}" y="{y(baseline) - 7:.1f}" font-size="12" text-anchor="end"'
        parts.append(f'<text {where} fill="#ffffff" stroke="#ffffff" stroke-width="4">{text}</text>')
        parts.append(f'<text {where} fill="#4b5563">{text}</text>')
    legend = [(REAL, "réalisé"), (FORECAST, "prévision")]
    if lines["after"]:
        legend.append((ACTUAL, "réel après le départ"))
    legend += [(season["color"], season["name"]) for season, _ in others]
    if baseline is not None:
        legend.append((BASELINE, "ligne d'équilibre"))
    lx = c["left"]
    for color, label in legend:
        parts.append(f'<line x1="{lx}" y1="{height - 22}" x2="{lx + 22}" y2="{height - 22}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{lx + 30}" y="{height - 17}" font-size="13" fill="#374151">{e(label)}</text>')
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
td.num { text-align: right; white-space: nowrap; }
pre { font-family: monospace; font-size: 7.5pt; background: #f5f5f5; padding: 6pt; }
.muted { color: #666; }
"""


def to_pdf(forecast: dict, png: bytes) -> bytes:
    """PDF : titre, parametres choisis, soldes et resultat, puis le
    graphique (png : image du graphique seul)."""
    result = forecast["result"]
    e = html.escape
    params = "".join(f"<tr><td>{e(label)}</td><td class='num'>{e(value)}</td></tr>" for label, value in chosen_parameters(forecast))
    amounts = "".join(f"<tr><td>{e(label)}</td><td class='num'>{e(value)}</td></tr>" for label, value in figures(forecast))
    body = (
        f"<h1>{e(forecast['name'])} — saison {e(result['seasonName'])}</h1>"
        + (f"<h2>Paramètres choisis</h2><table>{params}</table>" if params else "")
        + f"<h2>Soldes et résultat</h2><table>{amounts}</table>"
        + "<h2>Graphique</h2><img src='courbe.png' width='520'/>"
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
