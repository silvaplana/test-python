"""Textes de la page publique d'inscription au cours d'essai (modalites,
horaires, decharge...), repris aussi dans le mail envoye a l'eleve : une
seule source pour les deux.

A MODIFIER ICI quand les horaires ou les textes changent. Changer un texte
que l'eleve accepte (decharge, accord parental, attestation) : changer aussi
TERMS_VERSION -- chaque inscription garde la version acceptee.
"""

TERMS_VERSION = "2026-09-26"

CLUB_NAME = "Alliance Sambo Combat La Ciotat"

TITLE = "S'inscrire à un cours d'essai gratuit"

SUBTITLE = "Sport de combat MMA Sambo – La Ciotat, La Bédoule"

INTRO = (
    "Venez découvrir le sambo et le MMA ! Inscrivez-vous ci-dessous : vous recevrez par e-mail "
    "un QR code à présenter à l'entraîneur au début de votre cours d'essai."
)

RULES = [
    "Le cours d'essai est gratuit et sans engagement.",
    "Un seul cours d'essai par personne.",
    "Présentez votre QR code à l'entraîneur au début du cours (sur votre téléphone ou imprimé).",
    "Tenue : short ou jogging, t-shirt, bouteille d'eau. Pas de bijoux. Protège-dents conseillé.",
    "Arrivez 10 minutes avant le début du cours.",
    "Les mineurs doivent être inscrits par un parent ou représentant légal.",
]

# Horaires d'entrainement (repris du site du club,
# https://mma-sambo-bedoule-ciotat.e-monsite.com/). "place" : cle de PLACES.
SCHEDULE = [
    {"day": "Lundi", "time": "19h – 21h", "course": "Sambo MMA", "place": "La Bédoule"},
    {"day": "Jeudi", "time": "19h15 – 21h15", "course": "Sambo MMA", "place": "La Ciotat"},
    {"day": "Samedi", "time": "9h – 10h", "course": "Cross training", "place": "La Ciotat"},
    {"day": "Samedi", "time": "10h15 – 12h15", "course": "Sambo MMA", "place": "La Ciotat"},
]

# Salles (points GPS des cartes Google Maps du site du club).
PLACES = [
    {
        "name": "La Bédoule",
        "address": "Salle Marius Aimonetto, allée Hippolyte Gondrexon, 13830 Roquefort-la-Bédoule",
        "map": "https://www.google.com/maps/search/?api=1&query=43.248059%2C5.585899",
    },
    {
        "name": "La Ciotat",
        "address": "Complexe Étienne Masse, avenue de la Pétanque, 13600 La Ciotat",
        "map": "https://www.google.com/maps/search/?api=1&query=43.175804%2C5.600121",
    },
]

CONTACTS = [
    {"name": "Roland", "phone": "06 86 13 84 54"},
    {"name": "Karima", "phone": "07 66 09 63 68"},
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
        "subtitle": SUBTITLE,
        "intro": INTRO,
        "rules": RULES,
        "schedule": SCHEDULE,
        "places": PLACES,
        "contacts": CONTACTS,
        "medicalAttestation": MEDICAL_ATTESTATION,
        "medicalCertificateHint": MEDICAL_CERTIFICATE_HINT,
        "parentalConsent": PARENTAL_CONSENT,
        "waiver": WAIVER,
        "privacy": PRIVACY,
    }
