import { useEffect, useRef, useState } from 'react'

// Menu "trois petits points" en haut a droite de l'appli, present sur tous
// les onglets (voir Navigation.jsx). Ses entrees dependent de l'outil
// affiche : chaque outil peut declarer menu: [{ label, onSelect }].
export function AppMenu({ items = [] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  // Ferme le menu au clic ailleurs ou avec Echap.
  useEffect(() => {
    if (!open) return
    function close(event) {
      if (event.type === 'keydown' ? event.key === 'Escape' : !ref.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div className="app-menu" ref={ref}>
      <button
        className="app-menu-button"
        aria-label="Menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        ⋮
      </button>
      {open && (
        <div className="app-menu-list" role="menu">
          {items.length === 0 ? (
            <span className="app-menu-empty">Aucune action pour cet onglet</span>
          ) : (
            items.map((item) => (
              <button
                key={item.label}
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  item.onSelect()
                }}
              >
                {item.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
