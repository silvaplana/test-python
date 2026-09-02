import { useState } from 'react'

// Navigation en 2 niveaux, avec 2 presentations differentes du premier
// niveau (choix de la section : HelloAsso, FFST, Bilan financier) selon
// la taille d'ecran (voir App.css) :
// - Desktop : barre laterale a gauche, toujours visible.
// - Mobile : barre d'outils fixee en bas, façon appli mobile. Cliquer une
//   section y fait apparaitre ses outils a la place (drill-down), avec un
//   bouton permanent a droite ("⌂") pour revenir aux sections -- sur
//   desktop, ce comportement ne s'applique pas (mobileDrilled est ignore,
//   la barre laterale reste affichee et les outils de la section active
//   restent au 2e niveau, voir plus bas).
//
// Le 2e niveau (choix de l'outil dans une section qui en propose
// plusieurs, ex: Adherents/Impayes) est lui aussi presente differemment :
// onglets au-dessus du contenu sur desktop, fusionne dans la barre du bas
// (apres le drill-down) sur mobile. Bilan financier n'a qu'un seul outil :
// pas de 2e niveau pour elle.
//
// Comme l'ancien Tabs.jsx qu'elle remplace : un outil ne charge son
// contenu qu'a sa premiere ouverture, mais reste monte en permanence une
// fois visite (juste cache via l'attribut HTML "hidden"), pour ne pas
// perdre l'etat d'une tache en cours (ex: Bilan financier et son analyse
// IA en flux SSE) en changeant de section/outil.
function Navigation({ header, sections }) {
  const [activeSection, setActiveSection] = useState(0)
  // Outil actif par section (index) : se souvient du dernier outil
  // consulte dans chaque section quand on y revient.
  const [activeTools, setActiveTools] = useState(() => sections.map(() => 0))
  const [visited, setVisited] = useState(() => new Set(['0-0']))
  // Mobile uniquement (voir commentaire ci-dessus) : la barre du bas
  // affiche-t-elle les outils de la section active (true) ou la liste des
  // sections (false, etat initial) ?
  const [mobileDrilled, setMobileDrilled] = useState(false)

  const activeTool = activeTools[activeSection]

  function selectTool(sectionIndex, toolIndex) {
    setActiveSection(sectionIndex)
    setActiveTools((prev) => {
      if (prev[sectionIndex] === toolIndex) return prev
      const next = [...prev]
      next[sectionIndex] = toolIndex
      return next
    })
    setVisited((prev) => {
      const key = `${sectionIndex}-${toolIndex}`
      return prev.has(key) ? prev : new Set(prev).add(key)
    })
  }

  function selectSection(sectionIndex) {
    selectTool(sectionIndex, activeTools[sectionIndex])
    setMobileDrilled(true)
  }

  return (
    <div className={`navigation${mobileDrilled ? ' nav-drilled' : ''}`}>
      <nav className="sidebar">
        {sections.map((section, i) => (
          <button
            key={section.key}
            className={i === activeSection ? 'sidebar-active' : undefined}
            onClick={() => selectSection(i)}
          >
            {section.label}
          </button>
        ))}
      </nav>

      <div className="app-content">
        {header}

        {sections[activeSection].tools.length > 1 && (
          <div className="tabs-nav" role="tablist">
            {sections[activeSection].tools.map((tool, i) => (
              <button
                key={tool.label}
                role="tab"
                aria-selected={i === activeTool}
                className={i === activeTool ? 'tab-active' : undefined}
                onClick={() => selectTool(activeSection, i)}
              >
                {tool.label}
              </button>
            ))}
          </div>
        )}

        {sections.map((section, sectionIndex) =>
          section.tools.map(
            (tool, toolIndex) =>
              visited.has(`${sectionIndex}-${toolIndex}`) && (
                <div
                  key={tool.label}
                  className="tabs-panel"
                  role="tabpanel"
                  hidden={sectionIndex !== activeSection || toolIndex !== activeTool}
                >
                  {tool.content}
                </div>
              )
          )
        )}
      </div>

      <nav className="bottom-nav bottom-nav-sections">
        {sections.map((section, i) => (
          <button
            key={section.key}
            className={i === activeSection ? 'bottom-nav-active' : undefined}
            onClick={() => selectSection(i)}
          >
            {section.label}
          </button>
        ))}
      </nav>

      <nav className="bottom-nav bottom-nav-tools">
        {sections[activeSection].tools.map((tool, i) => (
          <button
            key={tool.label}
            className={i === activeTool ? 'bottom-nav-active' : undefined}
            onClick={() => selectTool(activeSection, i)}
          >
            {tool.label}
          </button>
        ))}
        <button className="bottom-nav-back" onClick={() => setMobileDrilled(false)} aria-label="Retour aux sections">
          ⌂
        </button>
      </nav>
    </div>
  )
}

export default Navigation
