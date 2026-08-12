import { useState } from 'react'

// Tabs generique : ne charge le contenu d'un onglet qu'a sa premiere
// ouverture (pas tous au chargement de la page), mais une fois visite,
// reste monte en permanence (juste cache via l'attribut HTML "hidden"
// quand ce n'est pas l'onglet actif) au lieu d'etre demonte.
//
// Important pour tout onglet avec une tache en cours (ex: Bilan financier
// et son analyse IA en flux SSE) : demonter le composant en changeant
// d'onglet coupait la connexion et perdait toute la progression. En
// gardant le composant monte, son etat (et sa connexion EventSource
// ouverte) continue de vivre en arriere-plan meme onglet non visible.
function Tabs({ tabs }) {
  const [active, setActive] = useState(0)
  const [visited, setVisited] = useState(() => new Set([0]))

  const selectTab = (i) => {
    setActive(i)
    setVisited((prev) => (prev.has(i) ? prev : new Set(prev).add(i)))
  }

  return (
    <div className="tabs">
      <div className="tabs-nav" role="tablist">
        {tabs.map((tab, i) => (
          <button
            key={tab.label}
            role="tab"
            aria-selected={i === active}
            className={i === active ? 'tab-active' : undefined}
            onClick={() => selectTab(i)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map(
        (tab, i) =>
          visited.has(i) && (
            <div key={tab.label} className="tabs-panel" role="tabpanel" hidden={i !== active}>
              {tab.content}
            </div>
          )
      )}
    </div>
  )
}

export default Tabs
