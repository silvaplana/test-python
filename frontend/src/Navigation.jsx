import { useState } from 'react'
import { AppMenu } from './AppMenu.jsx'

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
//
// Le dernier ecran affiche (section + outil) est retenu sur l'appareil : a
// la reouverture de l'appli, on repart de celui-ci. forcedSection l'emporte
// (ouverture par un lien precis : retour de la banque, QR code d'un eleve),
// avec forcedTool, le libelle de l'outil a ouvrir dans cette section.
const LAST_SCREEN_KEY = 'navigation-last-screen'

// Dernier ecran retenu, en positions dans sections ; null si aucun, ou s'il
// n'existe plus (onglet retire, acces aux finances perdu...).
function readLastScreen(sections) {
  try {
    const saved = JSON.parse(localStorage.getItem(LAST_SCREEN_KEY))
    const section = sections.findIndex((s) => s.key === saved.section)
    if (section < 0) return null
    const tool = sections[section].tools.findIndex((t) => t.label === saved.tool)
    return { section, tool: Math.max(tool, 0) }
  } catch {
    return null
  }
}

function Navigation({ header, sections, forcedSection = null, forcedTool = null }) {
  // Ecran de depart, fige a la 1re ouverture.
  const [start] = useState(
    () =>
      (forcedSection == null
        ? readLastScreen(sections)
        : {
            section: forcedSection,
            tool: Math.max(0, sections[forcedSection].tools.findIndex((t) => t.label === forcedTool)),
          }) ?? { section: 0, tool: 0 }
  )
  const initialSection = start.section
  const initialTool = start.tool
  const [activeSection, setActiveSection] = useState(initialSection)
  // Outil actif par section (index) : se souvient du dernier outil
  // consulte dans chaque section quand on y revient.
  const [activeTools, setActiveTools] = useState(() =>
    sections.map((_, i) => (i === initialSection ? initialTool : 0))
  )
  const [visited, setVisited] = useState(() => new Set([`${initialSection}-${initialTool}`]))

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
    try {
      const screen = { section: sections[sectionIndex].key, tool: sections[sectionIndex].tools[toolIndex]?.label }
      localStorage.setItem(LAST_SCREEN_KEY, JSON.stringify(screen))
    } catch {
      // Stockage indisponible : l'ecran ne sera juste pas retenu.
    }
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
            {section.icon}
            <span className="nav-label">
              {section.label}
              {section.badge}
            </span>
          </button>
        ))}
      </nav>

      <div className="app-content">
        {/* Menu ⋮ (voir AppMenu.jsx) : entrees propres a l'outil affiche. */}
        <AppMenu items={sections[activeSection].tools[activeTool]?.menu} />
        {header}

        {/* alwaysShowTabs : barre de sous-onglets meme avec un seul outil (ex:
            Finances, qui n'a qu'"Bilan financier" sans le mot de passe
            "comptes") -- l'ecran garde la meme structure quel que soit le
            niveau d'acces. */}
        {(sections[activeSection].tools.length > 1 || sections[activeSection].alwaysShowTabs) && (
          <div className="tabs-nav" role="tablist">
            {sections[activeSection].tools.map((tool, i) => (
              <button
                key={tool.label}
                role="tab"
                aria-selected={i === activeTool}
                className={i === activeTool ? 'tab-active' : undefined}
                onClick={() => selectTool(activeSection, i)}
              >
                {/* .tab-label-short remplace .tab-label-full sur mobile (voir
                    App.css) -- reprend tool.label si aucun raccourci fourni,
                    pour que les outils sans shortLabel restent lisibles. */}
                {tool.icon}
                <span className="tab-label-full">{tool.label}</span>
                <span className="tab-label-short">{tool.shortLabel ?? tool.label}</span>
                {tool.badge}
              </button>
            ))}
          </div>
        )}

        {sections.map((section, sectionIndex) =>
          section.tools.map((tool, toolIndex) => {
            if (!visited.has(`${sectionIndex}-${toolIndex}`)) return null
            const isActive = sectionIndex === activeSection && toolIndex === activeTool
            return (
              <div key={tool.label} className="tabs-panel" role="tabpanel" hidden={!isActive}>
                {/* content est une fonction (pas un element tout fait) : lui
                    permet de savoir s'il est reellement affiche en ce moment
                    (pas juste monte -- un outil deja visite reste monte mais
                    cache via "hidden" ci-dessus, voir le commentaire de
                    Navigation en haut du fichier), ex. pour MembersTable qui
                    doit distinguer "consulte maintenant" de "charge en fond". */}
                {tool.content(isActive)}
              </div>
            )
          })
        )}
      </div>

      <nav className="bottom-nav">
        {sections.map((section, i) => (
          <button
            key={section.key}
            className={i === activeSection ? 'bottom-nav-active' : undefined}
            onClick={() => selectSection(i)}
          >
            {section.icon}
            <span className="nav-label">
              {section.label}
              {section.badge}
            </span>
          </button>
        ))}
      </nav>
    </div>
  )
}

export default Navigation
