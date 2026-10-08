import { useEffect, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
// Demande d'ouverture venue du menu ⋮ (voir requestMembersSummary).
const OPEN_EVENT = 'members-summary-open'

// Entree "Statistiques des adhérents de la saison" du menu ⋮ (voir App.jsx) : ouvre le
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

const dayFormat = new Intl.DateTimeFormat('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

// "2026-11-30" -> "lun. 30 nov. 2026" ; sans date : "date inconnue".
function dayLabel(day) {
  const t = Date.parse(`${day}T00:00:00Z`)
  return Number.isNaN(t) ? 'date inconnue' : dayFormat.format(t)
}

// "2026-10-07" -> "07/10/2026".
function shortDay(day) {
  const [year, month, date] = (day || '').split('-')
  return date ? `${date}/${month}/${year}` : 'date inconnue'
}

// Ou en est l'argent des adhesions (summary.cash, voir cash_summary du
// backend), dans l'ordre de son trajet : echeances a venir (jour par jour),
// encaisse par HelloAsso sans versement lance, en transit (versement lance,
// pas encore vu a la banque), puis arrive sur le compte courant. C'est le
// releve des comptes qui dit si un versement est arrive (HelloAsso reste "en
// attente de confirmation" bien apres). En tete, le total qui doit encore
// arriver sur le compte.
function CashSummary({ cash }) {
  // Echeances a venir regroupees par mois, chaque jour detaille.
  const months = []
  for (const row of cash.upcoming.rows) {
    const key = row.date.slice(0, 7)
    if (months.at(-1)?.key !== key) months.push({ key, amount: 0, rows: [] })
    months.at(-1).amount += row.amount
    months.at(-1).rows.push(row)
  }
  return (
    <>
      <h4 className="members-summary-title">Encaissements</h4>
      <div className="members-summary-receive">
        <span>Encore à encaisser sur le compte courant</span>
        <b>{euros(cash.toReceive)}</b>
      </div>

      <CashBlock title="Déjà arrivé sur le compte courant" total={cash.onAccount.total} empty="Aucun versement pour l'instant.">
        {cash.onAccount.rows.map((row) => (
          <CashRow
            key={row.date + (row.requested ?? '')}
            // Avec les comptes : jour d'arrivee a la banque, et date du versement chez HelloAsso.
            label={row.requested ? `Reçu le ${dayLabel(row.date)} (versement HelloAsso du ${shortDay(row.requested)})` : `Versé le ${dayLabel(row.date)}`}
            count={plural(row.payments, 'paiement')}
            amount={row.amount}
          />
        ))}
      </CashBlock>

      <CashBlock
        title="En transit vers le compte courant"
        total={cash.inTransit.total}
        empty="Aucun versement en transit."
        hint={
          cash.bankAsOf
            ? `Versement lancé par HelloAsso, pas encore vu sur le compte courant (opérations connues jusqu'au ${shortDay(cash.bankAsOf)}).`
            : "Versement demandé à HelloAsso, pas encore confirmé (comptes non consultés : l'argent est peut-être déjà arrivé)."
        }
      >
        {cash.inTransit.rows.map((row) => (
          <CashRow key={row.date} label={`Versement HelloAsso du ${dayLabel(row.date)}`} count={plural(row.payments, 'paiement')} amount={row.amount} />
        ))}
      </CashBlock>

      <CashBlock title="Chez HelloAsso, versement pas encore lancé" total={cash.held.total} empty="Rien en attente chez HelloAsso.">
        {cash.held.payments > 0 && (
          <CashRow label="Date de versement inconnue" count={plural(cash.held.payments, 'paiement')} amount={cash.held.total} />
        )}
      </CashBlock>

      <CashBlock title="Échéances à venir" total={cash.upcoming.total} empty="Aucune échéance à venir.">
        {months.map((month) => (
          <MonthRows key={month.key} month={month} />
        ))}
      </CashBlock>

      {cash.offline.payments > 0 && (
        <p className="members-summary-note">
          En plus : {euros(cash.offline.total)} payés hors HelloAsso ({plural(cash.offline.payments, 'paiement')} par chèque, espèces…).
        </p>
      )}
    </>
  )
}

function CashBlock({ title, total, empty, hint, children }) {
  const rows = (Array.isArray(children) ? children.flat() : [children]).filter(Boolean)
  return (
    <table className="members-summary-table members-summary-cash">
      <thead>
        <tr>
          <th colSpan="2">{title}</th>
          <th className="members-summary-amount">{euros(total)}</th>
        </tr>
      </thead>
      <tbody>
        {rows.length > 0 ? (
          <>
            {hint && (
              <tr>
                <td colSpan="3" className="members-summary-empty">
                  {hint}
                </td>
              </tr>
            )}
            {rows}
          </>
        ) : (
          <tr>
            <td colSpan="3" className="members-summary-empty">
              {empty}
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}

function CashRow({ label, count, amount }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="members-summary-count">{count}</td>
      <td className="members-summary-amount">{euros(amount)}</td>
    </tr>
  )
}

// Un mois d'echeances : sa ligne de sous-total, puis chaque jour de prelevement.
function MonthRows({ month }) {
  return (
    <>
      <tr className="members-summary-month">
        <td colSpan="2">{monthLabel(month.key)}</td>
        <td className="members-summary-amount">{euros(month.amount)}</td>
      </tr>
      {month.rows.map((row) => (
        <CashRow key={row.date} label={dayLabel(row.date)} count={plural(row.payments, 'échéance')} amount={row.amount} />
      ))}
    </>
  )
}

// Panneau "Statistiques des adhérents de la saison" de l'onglet HelloAsso > Adherents, ouvert
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
        <h3>Statistiques des adhérents de la saison{summary ? ` (${summary.members})` : ''}</h3>
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

          <CashSummary cash={summary.cash} />
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
