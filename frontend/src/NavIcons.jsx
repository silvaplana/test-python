// Icones des onglets (voir App.jsx, proprietes "icon" des sections et des
// outils, affichees par Navigation.jsx). Traits dessines a la couleur du
// texte (currentColor) : elles suivent l'onglet actif et le theme sombre.
// Dessins repris de Lucide (licence ISC).
function NavIcon({ children }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

// Essai : un ticket, celui de la seance d'essai.
export function TrialIcon() {
  return (
    <NavIcon>
      <path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z" />
      <path d="M13 5v2" />
      <path d="M13 17v2" />
      <path d="M13 11v2" />
    </NavIcon>
  )
}

// Finances : une piece marquee du symbole euro.
export function FinancesIcon() {
  return (
    <NavIcon>
      <circle cx="12" cy="12" r="10" />
      <path d="M15.6 8.4a5 5 0 1 0 0 7.2" />
      <path d="M6.8 10.8h6" />
      <path d="M6.8 13.2h5" />
    </NavIcon>
  )
}

// Messagerie : deux bulles.
export function MessagingIcon() {
  return (
    <NavIcon>
      <path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" />
      <path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" />
    </NavIcon>
  )
}

// Mail : une enveloppe.
export function MailIcon() {
  return (
    <NavIcon>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </NavIcon>
  )
}

// Tchat : une bulle.
export function ChatIcon() {
  return (
    <NavIcon>
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
    </NavIcon>
  )
}
