import { useEffect, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
// Demande d'ouverture venue du menu ⋮ (voir requestMembersSummary).
const OPEN_EVENT = 'members-summary-open'

// Entree "Chiffres des adhérents" du menu ⋮ (voir App.jsx) : ouvre le
// panneau MembersSummary.
export function requestMembersSummary() {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

const euros = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
const monthYear = new Intl.DateTimeFormat('fr-FR', { month: 'long', year: 'numeric', timeZone: 'UTC' })

// "2026-11" -> "novembre 2026" ; echeance sans date : "Date inconnue".
function monthLabel(month) {
  const t = Date.parse(`${month}-01T00:00:00Z`)
  return Number.isNaN(t) ? 'Date inconnue' : monthYear.format(t)
}

const plural = (n, word) => `${n} ${word}${n > 1 ? 's' : ''}`

// Panneau "Chiffres des adhérents" de l'onglet HelloAsso > Adherents, ouvert
// depuis le menu ⋮ : majeurs et mineurs, prix moyen de la licence, et ce
// qui reste a encaisser mois par mois (voir backend helloasso/summary.py).
// Les chiffres sont relus chez HelloAsso a chaque ouverture.
export function MembersSummary() {
  const dialogRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(OPEN_EVENT, show)
    return () => window.removeEventListener(OPEN_EVENT, show)
  }, [])

  useEffect(() => {
    if (!open) return undefined
    dialogRef.current.showModal()
    let cancelled = false
    setSummary(null)
    setError(null)
    fetch(`${API_URL}/helloasso/summary`, { credentials: 'include' })
      .then(async (response) => {
        const body = await response.json().catch(() => null)
        if (!response.ok) throw new Error(body?.detail || `Chiffres indisponibles (${response.status})`)
        if (!cancelled) setSummary(body)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  if (!open) return null

  return (
    <dialog ref={dialogRef} className="trial-dialog" onClose={() => setOpen(false)}>
      <div className="trial-scan-header">
        <h3>Chiffres des adhérents</h3>
        <button
          type="button"
          className="trial-scan-close"
          onClick={() => dialogRef.current.close()}
          aria-label="Fermer"
          title="Fermer"
        >
          ✕
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!summary && !error && <p>Chargement…</p>}

      {summary && (
        <>
          <div className="members-summary-figures">
            <div className="seasons-figure">
              <span className="seasons-figure-label">Majeurs</span>
              <span className="seasons-figure-value">{summary.adults}</span>
            </div>
            <div className="seasons-figure">
              <span className="seasons-figure-label">Mineurs</span>
              <span className="seasons-figure-value">{summary.minors}</span>
            </div>
            <div className="seasons-figure">
              <span className="seasons-figure-label">Prix moyen de la licence</span>
              <span className="seasons-figure-value">
                {summary.averagePrice != null ? euros(summary.averagePrice) : '—'}
              </span>
            </div>
          </div>
          <p className="members-summary-note">
            {plural(summary.members, 'adhérent')}, {euros(summary.totalPrice)} au total
            {summary.freeMembers > 0 && `, dont ${plural(summary.freeMembers, 'licence')} à 0 €`}
            {summary.unknownAge > 0 && `. Âge inconnu pour ${plural(summary.unknownAge, 'adhérent')}`}.
          </p>

          <h4 className="members-summary-title">Reste à encaisser</h4>
          {summary.remaining.length === 0 ? (
            <p className="members-summary-note">Aucune échéance à venir.</p>
          ) : (
            <table className="members-summary-table">
              <tbody>
                {summary.remaining.map((row) => (
                  <tr key={row.month}>
                    <td>{monthLabel(row.month)}</td>
                    <td className="members-summary-count">{plural(row.payments, 'échéance')}</td>
                    <td className="members-summary-amount">{euros(row.amount)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan="2">Total</td>
                  <td className="members-summary-amount">{euros(summary.remainingTotal)}</td>
                </tr>
              </tfoot>
            </table>
          )}
          {summary.unpaidTotal > 0 && (
            <p className="members-summary-note">
              En plus : <span className="unpaid-amount">{euros(summary.unpaidTotal)}</span> d'échéances refusées (voir
              Impayés).
            </p>
          )}
        </>
      )}
    </dialog>
  )
}
