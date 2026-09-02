import { useState } from 'react'

// Navigation en 2 niveaux :
// - 1er niveau (choix de la section : HelloAsso, FFST, Bilan financier) :
//   toujours fixe et visible, en barre laterale a gauche sur desktop, en
//   barre d'outils fixee en bas sur mobile (voir App.css) -- jamais
//   remplace par le 2e niveau, contrairement a un menu mobile classique
//   type Reglages (juge trop deroutant : les outils de depart changeraient
//   de sens/position).
// - 2e niveau (choix de l'outil dans la section active, ex:
//   Adherents/Impayes) : un rang d'onglets au-dessus du contenu, identique
//   sur desktop et mobile. Bilan financier n'a qu'un seul outil : pas de
//   2e niveau pour elle.
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
  }

  return (
    <div className="navigation">
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

      <nav className="bottom-nav">
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
    </div>
  )
}

export default Navigation
