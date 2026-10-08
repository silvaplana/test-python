// Onglet Messagerie (sous-onglets Mail et Tchat), reserve au mot de passe
// "comptes" (voir App.jsx). Pour l'instant un ecran d'attente par sous-onglet.
function InDevelopment({ title, children }) {
  return (
    <section>
      <div className="section-header">
        <h2>{title}</h2>
      </div>
      <div className="in-development">
        <p className="in-development-badge">🚧 En cours de dev</p>
        <p>{children}</p>
      </div>
    </section>
  )
}

export function MessagingMail() {
  return <InDevelopment title="Mail">La messagerie mail du club.</InDevelopment>
}

export function MessagingChat() {
  return <InDevelopment title="Tchat">Le tchat du club.</InDevelopment>
}
