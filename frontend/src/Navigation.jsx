import { useState } from 'react'

// Navigation en 2 niveaux : une barre d'outils fixee en bas de l'ecran
// (façon appli mobile) pour choisir la section (HelloAsso, FFST, Bilan
// financier), puis un second niveau d'onglets au-dessus du contenu pour
// choisir l'outil dans les sections qui en proposent plusieurs (Bilan
// financier n'en propose qu'un seul : pas de second niveau pour elle).
//
// Comme l'ancien Tabs.jsx qu'elle remplace : un outil ne charge son
// contenu qu'a sa premiere ouverture, mais reste monte en permanence une
// fois visite (juste cache via l'attribut HTML "hidden"), pour ne pas
// perdre l'etat d'une tache en cours (ex: Bilan financier et son analyse
// IA en flux SSE) en changeant de section/outil.
function Navigation({ sections }) {
  const [activeSection, setActiveSection] = useState(0)
  // Outil actif par section (index) : se souvient du dernier outil
  // consulte dans chaque section quand on y revient depuis la barre du bas.
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

  return (
    <div className="navigation">
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

      <nav className="bottom-nav">
        {sections.map((section, i) => (
          <button
            key={section.key}
            className={i === activeSection ? 'bottom-nav-active' : undefined}
            onClick={() => selectTool(i, activeTools[i])}
          >
            {section.label}
          </button>
        ))}
      </nav>
    </div>
  )
}

export default Navigation
