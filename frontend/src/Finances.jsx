// Sous-onglet de Finances a venir (voir App.jsx) : Previsionnel (Saisons :
// voir Seasons.jsx, Bilan financier : FinancialReports.jsx, Assemblees
// generales : GeneralAssemblies.jsx). Pour l'instant un simple ecran
// d'attente, qui rappelle a quoi il servira.
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

export function Forecast() {
  return <InDevelopment title="Prévisionnel">L'espace où faire les prévisions financières.</InDevelopment>
}
