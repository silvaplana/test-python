"""Genere une paire de cles VAPID pour les notifications push (voir
.env.example) et l'affiche au format attendu par VAPID_PRIVATE_KEY /
VAPID_PUBLIC_KEY.

A executer UNE SEULE FOIS pour la duree de vie du club : regenerer les
cles invalide tous les abonnements deja enregistres (chaque utilisateur
devrait refaire "Activer les notifications" dans l'onglet Profil).

Usage :
    cd backend && source venv/bin/activate && python -m notifications.generate_vapid_keys
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def main() -> None:
    vapid = Vapid02()
    vapid.generate_keys()

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    private_b64url = base64.urlsafe_b64encode(private_raw).decode().rstrip("=")

    public_raw = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64url = base64.urlsafe_b64encode(public_raw).decode().rstrip("=")

    print(f"VAPID_PRIVATE_KEY={private_b64url}")
    print(f"VAPID_PUBLIC_KEY={public_b64url}")


if __name__ == "__main__":
    main()
