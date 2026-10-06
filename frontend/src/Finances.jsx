// Sous-onglets de Finances a venir (voir App.jsx) : Saisons, Bilan
// financier, Assemblees generales, Previsionnel. Pour l'instant un simple
// ecran d'attente par sous-onglet, qui rappelle a quoi il servira.
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

export function Seasons() {
  return (
    <InDevelopment title="Saisons">
      L'organisation du temps par saison (ex : 2026-2027), l'unité de temps importante pour un club.
    </InDevelopment>
  )
}

export function FinancialReports() {
  return (
    <InDevelopment title="Bilan financier">L'espace où calculer et conserver les bilans financiers.</InDevelopment>
  )
}

export function GeneralAssemblies() {
  return (
    <InDevelopment title="Assemblées générales">
      L'espace où préparer et conserver les présentations PowerPoint des assemblées générales.
    </InDevelopment>
  )
}

export function Forecast() {
  return <InDevelopment title="Prévisionnel">L'espace où faire les prévisions financières.</InDevelopment>
}
