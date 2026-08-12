"""Bilan financier du club.

Premiere etape : reception et stockage de l'archive zip des releves
bancaires (compte courant + Livret bleu) envoyee depuis le frontend. Pas
encore d'analyse du contenu -- juste la reception et le stockage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class FinancialBalance:
    """Gere la reception et le stockage des archives de releves bancaires.

    storage_dir doit pointer vers un repertoire persistant (volume Docker
    monte, voir docker-compose.yml) : sans ca, les archives recues
    seraient perdues au prochain redeploiement (reconstruction de l'image).
    """

    def __init__(self, storage_dir: str = "data/bank_archives") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_bank_account_archive(self, filename: str, content: bytes) -> dict:
        """Enregistre l'archive zip recue sur disque et retourne des infos
        sur le fichier stocke (nom final, taille, date de reception).

        Leve ValueError si le fichier ne semble pas etre une archive zip.
        """
        if not filename.lower().endswith(".zip"):
            raise ValueError("Le fichier envoye doit etre une archive .zip")

        received_at = datetime.now(timezone.utc)
        timestamp = received_at.strftime("%Y%m%dT%H%M%SZ")
        # Path(...).name pour ne garder que le nom de fichier, jamais un
        # chemin (evite tout risque d'ecriture hors de storage_dir).
        safe_name = Path(filename).name
        stored_name = f"{timestamp}_{safe_name}"
        stored_path = self.storage_dir / stored_name
        stored_path.write_bytes(content)

        print(f"FinancialBalance.save_bank_account_archive: {stored_name} ({len(content)} octets)")
        return {
            "filename": stored_name,
            "size": len(content),
            "uploadedAt": received_at.isoformat(),
        }
