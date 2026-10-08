import { useRef, useState } from 'react'

// Ordre des cartes d'une saison (Bilan financier, Assemblees generales,
// Previsionnel) : fige en base, change seulement en tirant la poignee d'une
// carte (souris ou doigt). Pendant le geste, la carte suit le pointeur dans
// la liste ; au lacher, onReorder recoit l'ordre complet des identifiants.
//
// all : toutes les cartes de la saison, dans l'ordre du serveur ; shown :
// celles affichees (filtre d'etat). Deplacer une carte affichee ne touche
// pas a la place des cartes masquees par le filtre.
export function useCardOrder({ all, shown, onReorder }) {
  const [live, setLive] = useState(null) // identifiants affiches, ordre en cours de geste
  const drag = useRef(null)
  const list = useRef(null)

  const order = live ?? shown.map((item) => item.id)
  const byId = new Map(shown.map((item) => [item.id, item]))
  const ordered = order.filter((id) => byId.has(id)).map((id) => byId.get(id))

  function start(id) {
    return (event) => {
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = { id, order: shown.map((item) => item.id) }
      setLive(drag.current.order)
    }
  }

  function move(event) {
    const state = drag.current
    if (!state) return
    // Carte sous le pointeur : celle dont le cadre contient sa hauteur.
    const cards = [...list.current.querySelectorAll('[data-card-id]')]
    const target = cards.find((card) => {
      const box = card.getBoundingClientRect()
      return event.clientY >= box.top && event.clientY <= box.bottom
    })
    if (!target) return
    const targetId = Number(target.dataset.cardId)
    if (targetId === state.id) return
    const next = state.order.filter((id) => id !== state.id)
    next.splice(state.order.indexOf(targetId), 0, state.id)
    state.order = next
    setLive(next)
  }

  function stop() {
    const state = drag.current
    if (!state) return
    drag.current = null
    setLive(null)
    const before = shown.map((item) => item.id)
    if (state.order.join() === before.join()) return
    // Les cartes affichees reprennent, dans leur nouvel ordre, les places
    // qu'elles occupaient parmi toutes les cartes.
    const visible = new Set(before)
    const queue = [...state.order]
    onReorder(all.map((item) => (visible.has(item.id) ? queue.shift() : item.id)))
  }

  return {
    list,
    ordered,
    draggingId: live ? drag.current?.id : null,
    handle: (id) => ({ onPointerDown: start(id), onPointerMove: move, onPointerUp: stop, onPointerCancel: stop }),
  }
}

// Poignee d'une carte (six points). Un clic dessus n'ouvre pas la carte.
export function CardGrip({ name, ...handlers }) {
  return (
    <span
      className="reports-grip"
      role="button"
      aria-label={`Déplacer ${name}`}
      title="Tirer pour changer l'ordre"
      onClick={(event) => event.stopPropagation()}
      {...handlers}
    >
      <svg viewBox="0 0 12 20" aria-hidden="true">
        {[4, 10, 16].flatMap((y) => [3, 9].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.5" fill="currentColor" />))}
      </svg>
    </span>
  )
}
