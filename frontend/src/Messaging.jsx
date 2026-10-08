// Onglet Messagerie (sous-onglets Mail et Tchat), reserve au mot de passe
// "comptes" (voir App.jsx). Pour l'instant un ecran "En chantier..." par
// sous-onglet.
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

export function MessagingMail() {
  return <UnderConstruction title="Mail" />
}

export function MessagingChat() {
  return <UnderConstruction title="Tchat" />
}
