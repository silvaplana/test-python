import { useEffect, useState } from 'react'

// Messages temporaires en bas de l'ecran (ex: "3 operations ajoutees"),
// appelables de n'importe ou : showToast(texte) ; <Toasts /> est monte une
// seule fois (voir App.jsx).
const TOAST_EVENT = 'app-toast'
const TOAST_DURATION_MS = 5000

export function showToast(message, kind = 'info') {
  window.dispatchEvent(new CustomEvent(TOAST_EVENT, { detail: { message, kind } }))
}

let nextId = 0

export function Toasts() {
  const [toasts, setToasts] = useState([])

  useEffect(() => {
    function add(event) {
      const id = ++nextId
      setToasts((list) => [...list, { id, ...event.detail }])
      setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), TOAST_DURATION_MS)
    }
    window.addEventListener(TOAST_EVENT, add)
    return () => window.removeEventListener(TOAST_EVENT, add)
  }, [])

  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          {t.message}
        </div>
      ))}
    </div>
  )
}
