"""Prompts enregistres d'un calcul (bilan financier, assemblee generale,
previsionnel) : la disquette de l'ecran ajoute le prompt en cours a la liste
du calcul, reproposee dans le menu "Prompt donné à l'IA". Propres a chaque
calcul ; une table par module, de meme forme (id, <colonne du calcul>,
prompt, created_at).

`table` et `column` : toujours des noms ecrits dans le code, jamais des
valeurs recues.
"""

from datetime import datetime, timezone


def saved(db, table: str, column: str, owner_id: int) -> list[dict]:
    """Prompts enregistres du calcul, du plus recent au plus ancien."""
    with db.connect() as connection:
        rows = connection.execute(
            f"SELECT id, prompt FROM {table} WHERE {column} = ? ORDER BY id DESC", (owner_id,)
        ).fetchall()
    return [{"id": row["id"], "prompt": row["prompt"]} for row in rows]


def save(db, table: str, column: str, owner_id: int, prompt: str) -> list[dict]:
    """Ajoute ce prompt (deja nettoye, non vide) a ceux du calcul, sans doublon."""
    with db.connect() as connection:
        exists = connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ? AND prompt = ?", (owner_id, prompt)
        ).fetchone()
        if not exists:
            connection.execute(
                f"INSERT INTO {table} ({column}, prompt, created_at) VALUES (?, ?, ?)",
                (owner_id, prompt, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
    return saved(db, table, column, owner_id)


def delete(db, table: str, column: str, owner_id: int, prompt_id: int) -> list[dict]:
    """Retire un prompt du calcul (sans effet s'il appartient a un autre)."""
    with db.connect() as connection:
        connection.execute(f"DELETE FROM {table} WHERE id = ? AND {column} = ?", (prompt_id, owner_id))
    return saved(db, table, column, owner_id)
