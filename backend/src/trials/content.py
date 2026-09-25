"""Textes de la page publique d'inscription au cours d'essai (modalites,
horaires, decharge...), repris aussi dans le mail envoye a l'eleve : une
seule source pour les deux.

A MODIFIER ICI quand les horaires ou les textes changent. Changer un texte
que l'eleve accepte (decharge, accord parental, attestation) : changer aussi
TERMS_VERSION -- chaque inscription garde la version acceptee.
"""

TERMS_VERSION = "2026-09-26"

CLUB_NAME = "Alliance Sambo Combat La Ciotat"

TITLE = "Cours d'essai MMA / Sambo"

INTRO = (
    "Envie de découvrir le MMA ou le sambo ? Venez faire un cours d'essai gratuit à La Bédoule "
    "ou à La Ciotat. Inscrivez-vous ci-dessous : vous recevrez un QR code à présenter au début du cours."
)

RULES = [
    "Le cours d'essai est gratuit et sans engagement.",
    "Un seul cours d'essai par personne.",
    "Présentez votre QR code à l'entraîneur au début du cours (sur votre téléphone ou imprimé).",
    "Tenue : short ou jogging, t-shirt, bouteille d'eau. Pas de bijoux. Protège-dents conseillé.",
    "Arrivez 10 minutes avant le début du cours.",
    "Les mineurs doivent être inscrits par un parent ou représentant légal.",
]

# EXEMPLES A REMPLACER par les vrais lieux et creneaux.
SESSIONS = [
    {
        "place": "La Bédoule (à compléter)",
        "address": "Adresse du gymnase à compléter",
        "slots": [
            {"day": "Mardi", "time": "18h30 – 20h00", "audience": "Adultes (à compléter)"},
            {"day": "Jeudi", "time": "18h30 – 20h00", "audience": "Adultes (à compléter)"},
        ],
    },
    {
        "place": "La Ciotat (à compléter)",
        "address": "Adresse du dojo à compléter",
        "slots": [
            {"day": "Mercredi", "time": "17h00 – 18h00", "audience": "Enfants (à compléter)"},
            {"day": "Samedi", "time": "10h00 – 12h00", "audience": "Ados et adultes (à compléter)"},
        ],
    },
]

MEDICAL_ATTESTATION = (
    "J'atteste que {eleve} ne présente, à ma connaissance, aucune contre-indication à la pratique "
    "des sports de combat (MMA, sambo)."
)

MEDICAL_CERTIFICATE_HINT = (
    "Facultatif pour le cours d'essai : vous pouvez joindre un certificat médical (photo ou PDF)."
)

PARENTAL_CONSENT = (
    "Je soussigné(e), représentant légal de {eleve}, l'autorise à participer à un cours d'essai "
    "de MMA / sambo organisé par {club}, et autorise les encadrants à prendre toute mesure "
    "d'urgence nécessaire (appel des secours) en cas d'accident."
)

WAIVER = (
    "Je reconnais que le MMA et le sambo sont des sports de combat comportant des risques de "
    "blessure. {eleve} participe au cours d'essai en respectant les consignes des encadrants. "
    "Je renonce à tout recours contre {club} et ses encadrants en cas d'accident survenu pendant "
    "le cours d'essai, sauf faute de leur part. Je déclare être couvert(e) par une assurance "
    "responsabilité civile."
)

PRIVACY = (
    "Vos informations servent uniquement à organiser votre cours d'essai. Elles sont conservées "
    "au plus un an, puis supprimées automatiquement. Pour les consulter ou les faire supprimer "
    "plus tôt, répondez simplement au mail de confirmation."
)


def public_info() -> dict:
    """Contenu de la page publique (GET /public/trials/info)."""
    return {
        "termsVersion": TERMS_VERSION,
        "club": CLUB_NAME,
        "title": TITLE,
        "intro": INTRO,
        "rules": RULES,
        "sessions": SESSIONS,
        "medicalAttestation": MEDICAL_ATTESTATION,
        "medicalCertificateHint": MEDICAL_CERTIFICATE_HINT,
        "parentalConsent": PARENTAL_CONSENT,
        "waiver": WAIVER,
        "privacy": PRIVACY,
    }
