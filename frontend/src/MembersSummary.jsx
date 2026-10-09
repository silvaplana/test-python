import { useEffect, useRef, useState } from 'react'
import { useAuth } from './Auth.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
// Demande d'ouverture venue du menu ⋮ (voir requestMembersSummary).
const OPEN_EVENT = 'members-summary-open'

// Entree "Statistiques des adhérents de la saison" du menu ⋮ (voir App.jsx) : ouvre le
// panneau MembersSummary.
export function requestMembersSummary() {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

const euros = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
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
// backend), en deux encadres dont le detail se deplie : deja encaisse sur le
// compte courant, et reste a encaisser (versement en cours, encaisse sur
// HelloAsso en attente du versement automatique, encaissements futurs jour
// par jour). C'est le releve des comptes qui dit si un versement est arrive
// (HelloAsso reste "en attente de confirmation" bien apres).
function CashSummary({ cash }) {
  return (
    <>
      <h4 className="members-summary-title">Encaissements</h4>

      <CashBox title="Déjà encaissé sur le compte courant" total={cash.onAccount.total}>
        <CashPart empty="Aucun versement pour l'instant.">
          {cash.onAccount.rows.map((row) => (
            <CashRow
              key={row.date + (row.requested ?? '')}
              // Avec les comptes : jour d'arrivee a la banque, et date du versement chez HelloAsso.
              label={row.requested ? `Reçu le ${dayLabel(row.date)} (versement HelloAsso du ${shortDay(row.requested)})` : `Versé le ${dayLabel(row.date)}`}
              count={plural(row.payments, 'paiement')}
              amount={row.amount}
            />
          ))}
        </CashPart>
      </CashBox>

      <CashBox title="Reste à encaisser sur le compte courant" total={cash.toReceive} accent>
        <CashPart
          title="Versement en cours HelloAsso → compte courant"
          total={cash.inTransit.total}
          empty={
            cash.bankAsOf
              ? `Aucun (opérations du compte connues jusqu'au ${shortDay(cash.bankAsOf)}).`
              : 'Aucun.'
          }
        >
          {cash.inTransit.rows.map((row) => (
            <CashRow key={row.date} label={`Versement du ${dayLabel(row.date)}`} count={plural(row.payments, 'paiement')} amount={row.amount} />
          ))}
        </CashPart>
        <CashPart
          title="Encaissé sur HelloAsso, viré prochainement sur le compte courant (versement automatique vers le 10 du mois)"
          total={cash.held.total}
          empty="Rien en attente chez HelloAsso."
        >
          {cash.held.payments > 0 && <CashRow label="En attente du prochain versement" count={plural(cash.held.payments, 'paiement')} amount={cash.held.total} />}
        </CashPart>
        <CashPart title="Encaissements futurs sur HelloAsso" total={cash.upcoming.total} empty="Aucune échéance à venir.">
          {cash.upcoming.rows.map((row) => (
            <CashRow key={row.date} label={dayLabel(row.date)} count={plural(row.payments, 'échéance')} amount={row.amount} />
          ))}
        </CashPart>
      </CashBox>

      {cash.offline.payments > 0 && (
        <p className="members-summary-note">
          En plus : {euros(cash.offline.total)} payés hors HelloAsso ({plural(cash.offline.payments, 'paiement')} par chèque, espèces…).
        </p>
      )}
    </>
  )
}

// Solde actuel des comptes (compte courant + Livret Bleu), au-dessus des
// encaissements : ce que le club a aujourd'hui, avant ce qui doit arriver.
function Balances({ accounts }) {
  return (
    <>
      <h4 className="members-summary-title">Solde actuel</h4>
      <div className="members-summary-box members-summary-balance">
        <div className="members-summary-balance-total">
          <span className="members-summary-box-title">
            {accounts.list.map((account) => account.name).join(' + ')}
          </span>
          <b>{euros(accounts.total)}</b>
        </div>
        <table className="members-summary-table members-summary-cash">
          <tbody>
            {accounts.list.map((account) => (
              <tr key={account.id}>
                {/* Chaque compte a sa propre date de dernier solde connu. */}
                <td colSpan="2">
                  {account.name}
                  {account.asOf && <span className="members-summary-count"> au {shortDay(account.asOf)}</span>}
                </td>
                <td className="members-summary-amount">{account.balance != null ? euros(account.balance) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

const monthFormat = new Intl.DateTimeFormat('fr-FR', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const shortMonthFormat = new Intl.DateTimeFormat('fr-FR', { month: 'short', timeZone: 'UTC' })

// "2026-11" -> "novembre 2026" ; court : "nov."
function monthName(month, short = false) {
  const t = Date.parse(`${month}-01T00:00:00Z`)
  if (Number.isNaN(t)) return month
  return (short ? shortMonthFormat : monthFormat).format(t)
}

// Encadre a total, avec un "i" qui deplie l'explication du calcul.
function InfoBox({ title, total, accent = false, children }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`members-summary-box members-summary-info${accent ? ' members-summary-box-accent' : ''}`}>
      <div className="members-summary-info-head">
        <span className="members-summary-box-title">{title}</span>
        <button
          type="button"
          className="members-summary-info-button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          title={open ? 'Masquer le détail du calcul' : 'Voir le détail du calcul'}
          aria-label={open ? 'Masquer le détail du calcul' : 'Voir le détail du calcul'}
        >
          i
        </button>
        <b>{total}</b>
      </div>
      {open && <div className="members-summary-box-detail">{children}</div>}
    </div>
  )
}

// Salaires et cotisations a payer jusqu'a la fin de la saison : projection
// calculee par le backend depuis les operations des comptes (voir
// seasons/projection.py). Le "i" explique chaque ligne.
function Payroll({ payroll }) {
  return (
    <InfoBox
      title={`Salaires et cotisations encore à payer jusqu'au ${shortDay(payroll.seasonEnd)} (projection)`}
      total={`− ${euros(payroll.total)}`}
    >
      <table className="members-summary-table members-summary-cash">
        <tbody>
          {payroll.lines.map((line) => (
            <tr key={line.category}>
              <td colSpan="2">
                <strong>{line.category}</strong> : {euros(line.monthly)} × {line.months} mois
                {line.months > 0 && ` (${monthName(line.firstMonth)} à ${monthName(line.lastMonth)})`}
                <span className="members-summary-explain">
                  {line.basis === 'regular'
                    ? `Montant des ${line.basisMonths.length} derniers versements, identiques (${line.basisMonths.map((m) => monthName(m.month, true)).join(', ')}).`
                    : `Versements irréguliers : moyenne des ${line.basisMonths.length} derniers mois complets (${line.basisMonths
                        .map((m) => `${monthName(m.month, true)} ${euros(m.amount)}`)
                        .join(', ')}).`}{' '}
                  {line.paidThisMonth ? 'Le mois en cours est déjà payé.' : 'Le mois en cours n’est pas encore payé : il est compté.'}
                </span>
              </td>
              <td className="members-summary-amount">{euros(line.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="members-summary-explain">
        Calculé depuis les opérations du compte, sans IA. C'est une estimation : elle suppose que ces montants ne changent pas
        d'ici la fin de la saison.
      </p>
    </InfoBox>
  )
}

// Licences FFST que le club devra encore payer cette saison (summary.licences,
// voir licences_to_pay du backend) : une par adherent, plus celle du coach,
// moins celles deja payees (Licences > Licencies).
function Licences({ licences, seasonEnd }) {
  return (
    <InfoBox
      title={`Licences encore à payer${seasonEnd ? ` jusqu'au ${shortDay(seasonEnd)}` : ''} (projection)`}
      total={`− ${euros(licences.amount)}`}
    >
      <table className="members-summary-table members-summary-cash">
        <tbody>
          <tr>
            <td colSpan="2">Adhérents de la saison</td>
            <td className="members-summary-amount">{licences.members}</td>
          </tr>
          <tr>
            <td colSpan="2">+ Coach</td>
            <td className="members-summary-amount">{licences.coach}</td>
          </tr>
          <tr>
            <td colSpan="2">− Licences déjà payées (Licences &gt; Licenciés)</td>
            <td className="members-summary-amount">{licences.paid}</td>
          </tr>
          <tr>
            <td colSpan="2">
              <strong>
                = {plural(licences.remaining, 'licence')} à payer × {euros(licences.price)}
              </strong>
            </td>
            <td className="members-summary-amount">
              <strong>{euros(licences.amount)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <p className="members-summary-explain">
        Estimation : elle suppose une licence par adhérent, au tarif de {euros(licences.price)}, et aucun nouvel adhérent d'ici
        la fin de la saison.
      </p>
    </InfoBox>
  )
}

// Synthese : solde actuel + reste a encaisser - salaires et cotisations
// - licences FFST restant a payer.
function ProjectedBalance({ accounts, cash, payroll, licences }) {
  const projected = accounts.total + cash.toReceive - payroll.total - (licences?.amount ?? 0)
  return (
    <>
      <h4 className="members-summary-title">Projection de fin de saison</h4>
      <InfoBox title={`Solde projeté au ${shortDay(payroll.seasonEnd)}`} total={euros(projected)} accent>
        <table className="members-summary-table members-summary-cash">
          <tbody>
            <tr>
              <td colSpan="2">Solde actuel</td>
              <td className="members-summary-amount">{euros(accounts.total)}</td>
            </tr>
            <tr>
              <td colSpan="2">+ Reste à encaisser sur le compte courant</td>
              <td className="members-summary-amount">{euros(cash.toReceive)}</td>
            </tr>
            <tr>
              <td colSpan="2">− Salaires et cotisations encore à payer (projection)</td>
              <td className="members-summary-amount">{euros(payroll.total)}</td>
            </tr>
            {licences && (
              <tr>
                <td colSpan="2">− Licences encore à payer (projection)</td>
                <td className="members-summary-amount">{euros(licences.amount)}</td>
              </tr>
            )}
          </tbody>
        </table>
        <p className="members-summary-explain">
          Chiffre optimiste : il ne compte pas les autres dépenses (matériel, frais bancaires, médecine du travail…), ni les
          adhésions qui pourraient encore arriver.
          {!licences && ' Les licences FFST ne sont pas comptées : FFST est injoignable pour l’instant.'}
        </p>
      </InfoBox>
    </>
  )
}

// Encadre "titre : total", dont le detail se deplie d'un clic.
function CashBox({ title, total, accent = false, children }) {
  return (
    <details className={`members-summary-box${accent ? ' members-summary-box-accent' : ''}`}>
      <summary>
        <span className="members-summary-box-title">{title}</span>
        <b>{euros(total)}</b>
      </summary>
      <div className="members-summary-box-detail">{children}</div>
    </details>
  )
}

// Partie du detail d'un encadre : titre et sous-total facultatifs, puis ses lignes.
function CashPart({ title, total, empty, children }) {
  const rows = (Array.isArray(children) ? children.flat() : [children]).filter(Boolean)
  return (
    <table className="members-summary-table members-summary-cash">
      {title && (
        <thead>
          <tr>
            <th colSpan="2">{title}</th>
            <th className="members-summary-amount">{euros(total)}</th>
          </tr>
        </thead>
      )}
      <tbody>
        {rows.length > 0 ? (
          rows
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

// Panneau "Statistiques des adhérents de la saison" de l'onglet HelloAsso > Adherents, ouvert
// depuis le menu ⋮ : majeurs et mineurs, prix moyen de la licence, et ce
// qui reste a encaisser mois par mois (voir backend helloasso/summary.py).
// Les chiffres sont relus chez HelloAsso a chaque ouverture.
export function MembersSummary() {
  const dialogRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)
  // Soldes des comptes (compte courant, Livret Bleu) : donnee des comptes,
  // lue et affichee seulement avec le mot de passe "comptes".
  const { canViewAccounts } = useAuth()
  const [accounts, setAccounts] = useState(null)
  // Salaires et cotisations a payer jusqu'a la fin de la saison (meme niveau d'acces).
  const [payroll, setPayroll] = useState(null)

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
    setAccounts(null)
    setPayroll(null)
    if (canViewAccounts) {
      fetch(`${API_URL}/seasons/payroll-projection`, { credentials: 'include' })
        .then((response) => (response.ok ? response.json() : null))
        .then((body) => {
          if (!cancelled && body?.projection) setPayroll(body.projection)
        })
        .catch(() => {})
      fetch(`${API_URL}/bankstatements/ledger`, { credentials: 'include' })
        .then((response) => (response.ok ? response.json() : null))
        .then((ledger) => {
          if (!cancelled && ledger) setAccounts({ list: ledger.accounts, total: ledger.total })
        })
        .catch(() => {})
    }
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
  }, [open, canViewAccounts])

  if (!open) return null

  return (
    <dialog ref={dialogRef} className="trial-dialog" onClose={() => setOpen(false)}>
      <div className="trial-scan-header">
        <h3>
          Statistiques des adhérents de la saison{summary?.season ? ` ${summary.season}` : ''}
          {summary ? ` (${summary.members})` : ''}
        </h3>
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

          {accounts?.list.length > 0 && <Balances accounts={accounts} />}
          {payroll && <Payroll payroll={payroll} />}
          {summary.licences && <Licences licences={summary.licences} seasonEnd={summary.seasonEnd} />}
          <CashSummary cash={summary.cash} />
          {accounts?.list.length > 0 && payroll && (
            <ProjectedBalance accounts={accounts} cash={summary.cash} payroll={payroll} licences={summary.licences} />
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
