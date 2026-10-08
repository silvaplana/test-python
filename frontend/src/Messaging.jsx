import { Webmail } from './Webmail.jsx'

// Onglet Messagerie (sous-onglets Mail et Tchat), reserve au mot de passe
// "comptes" (voir App.jsx). Mail : boite Gmail de l'association (voir
// Webmail.jsx) ; Tchat : "En chantier..." pour l'instant.
function UnderConstruction({ title }) {
  return (
    <section>
      <div className="section-header">
        <h2>{title}</h2>
      </div>
      <div className="in-development">
        <p className="in-development-badge">🚧 En chantier...</p>
      </div>
    </section>
  )
}

export function MessagingMail({ active }) {
  return <Webmail active={active} />
}

export function MessagingChat() {
  return <UnderConstruction title="Tchat" />
}
