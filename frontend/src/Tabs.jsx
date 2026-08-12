import { useState } from 'react'

// Tabs generique : n'affiche/ne monte que le contenu de l'onglet actif.
// Consequence pratique utile ici : les donnees d'un onglet ne sont
// chargees qu'a la premiere ouverture de cet onglet, pas toutes au
// chargement de la page.
function Tabs({ tabs }) {
  const [active, setActive] = useState(0)

  return (
    <div className="tabs">
      <div className="tabs-nav" role="tablist">
        {tabs.map((tab, i) => (
          <button
            key={tab.label}
            role="tab"
            aria-selected={i === active}
            className={i === active ? 'tab-active' : undefined}
            onClick={() => setActive(i)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tabs-panel" role="tabpanel">
        {tabs[active].content}
      </div>
    </div>
  )
}

export default Tabs
