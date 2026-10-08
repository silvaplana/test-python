"""Ordre d'affichage fige des cartes d'une saison (bilans financiers,
assemblees generales, previsionnels) : colonne `position`, la plus petite en
premier. L'ordre ne change que si l'utilisateur deplace une carte (poignee de
l'ecran) ; une nouvelle carte se place en tete.

`table` : toujours un nom ecrit dans le code, jamais une valeur recue.
"""


def top_position(connection, table: str, season_id: int) -> int:
    """Position d'une nouvelle carte : avant toutes celles de la saison."""
    row = connection.execute(f"SELECT MIN(position) FROM {table} WHERE season_id = ?", (season_id,)).fetchone()
    return (row[0] if row[0] is not None else 1) - 1


def reorder(connection, table: str, season_id: int, ids: list[int]) -> None:
    """Range les cartes de la saison dans l'ordre de `ids`. Les identifiants
    d'une autre saison sont ignores ; une carte absente de `ids` (creee
    entre-temps) passe apres, dans son ordre actuel."""
    current = [
        row[0]
        for row in connection.execute(
            f"SELECT id FROM {table} WHERE season_id = ? ORDER BY position, id DESC", (season_id,)
        ).fetchall()
    ]
    known = set(current)
    ordered = []
    for item in ids:
        if item in known and item not in ordered:
            ordered.append(item)
    ordered += [item for item in current if item not in ordered]
    for position, item in enumerate(ordered):
        connection.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (position, item))
