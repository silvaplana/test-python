import { useCallback, useEffect, useMemo, useState } from 'react'
import { BalanceChart } from './BalanceChart.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const DAY_MS = 24 * 3600 * 1000
// Vue choisie (tous les comptes ou un seul), memorisee sur cet appareil.
const VIEW_KEY = 'bankhistory-view'

function euros(amount) {
  return `${amount.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
}

// Nom court d'un compte, pour les colonnes du tableau.
function shortName(account) {
  if (!account) return ''
  return { checking: 'Courant', savings: 'Livret' }[account.kind] ?? account.name
}

function dateFr(isoDate) {
  const [year, month, day] = isoDate.split('-')
  return `${day}/${month}/${year}`
}

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `${path} a échoué (${response.status})`)
  }
  return response.json()
}

// Serie du graphique (voir BalanceChart) : solde en fin de journee, un point
// par jour, du 1er au dernier jour connu. rows : lignes de l'historique (la
// plus recente en premier), value(row) : solde a suivre apres la ligne.
function ledgerSeries(rows, value) {
  const byDay = new Map()
  for (const row of [...rows].reverse()) {
    const v = value(row)
    if (v == null) continue
    const t = Date.parse(`${row.date}T00:00:00Z`)
    const day = byDay.get(t) ?? { v, ops: [] }
    day.v = v
    day.ops.push({ label: row.transfer ? `Virement ${row.transfer.from} → ${row.transfer.to}` : row.label, amount: row.amount })
    byDay.set(t, day)
  }
  if (byDay.size === 0) return []
  const days = [...byDay.keys()]
  const first = Math.min(...days)
  const last = Math.max(...days)
  const series = []
  let v = null
  for (let t = first; t <= last; t += DAY_MS) {
    const day = byDay.get(t)
    if (day) v = day.v
    series.push({ t, v, ops: day?.ops ?? [] })
  }
  return series
}

// Historique des comptes du club lu dans les releves PDF (voir backend
// bankstatements/) : total des comptes (vue par defaut) ou un compte seul,
// graphique, tableau des operations, periodes couvertes par les releves et
// depot de nouveaux releves (PDF ou zip).
export function BankHistory() {
  const [view, setView] = useState(() => {
    try {
      return localStorage.getItem(VIEW_KEY) ?? 'all'
    } catch {
      return 'all'
    }
  })
  const [ledger, setLedger] = useState(null)
  const [error, setError] = useState(null)
  const [importing, setImporting] = useState(false)
  const [report, setReport] = useState(null)

  const load = useCallback(async () => {
    try {
      setLedger(await callApi(`/bankstatements/ledger${view === 'all' ? '' : `?account=${view}`}`))
      setError(null)
    } catch (err) {
      // Compte memorise qui n'existe plus : retour a la vue d'ensemble.
      if (view !== 'all') setView('all')
      else setError(err.message)
    }
  }, [view])

  useEffect(() => {
    load()
  }, [load])

  function chooseView(next) {
    setView(next)
    try {
      localStorage.setItem(VIEW_KEY, next)
    } catch {
      // Stockage indisponible : le choix ne sera juste pas retenu.
    }
  }

  async function importFiles(event) {
    const files = [...event.target.files]
    event.target.value = ''
    if (files.length === 0) return
    const body = new FormData()
    for (const file of files) body.append('files', file)
    setImporting(true)
    setReport(null)
    try {
      setReport(await callApi('/bankstatements/import', { method: 'POST', body }))
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setImporting(false)
    }
  }

  const single = view !== 'all'
  const series = useMemo(() => {
    if (!ledger) return []
    return ledgerSeries(ledger.rows, single ? (row) => row.balances[view] : (row) => row.total)
  }, [ledger, single, view])

  if (error) return <p className="error">{error}</p>
  if (!ledger) return null

  const allAccounts = ledger.allAccounts
  const accounts = single ? ledger.accounts : allAccounts
  const shown = ledger.accounts

  return (
    <div className="account-card">
      <div className="account-card-header">
        <div>
          <h3>{single ? shown[0]?.name : 'Total des comptes'}</h3>
          {!single && shown.length > 0 && (
            <span className="account-iban">{shown.map((a) => `${a.name} ${a.balance == null ? '—' : euros(a.balance)}`).join(' · ')}</span>
          )}
        </div>
        <span className="account-balance">{euros(ledger.total)}</span>
      </div>

      {allAccounts.length > 1 && (
        <div className="filter-chips history-views" role="group" aria-label="Comptes affichés">
          {[{ id: 'all', name: 'Les comptes ensemble' }, ...allAccounts].map((a) => (
            <button
              key={a.id}
              className={String(a.id) === view ? 'filter-chip filter-chip-active' : 'filter-chip'}
              aria-pressed={String(a.id) === view}
              onClick={() => chooseView(String(a.id))}
            >
              {a.name}
            </button>
          ))}
        </div>
      )}

      {ledger.rows.length === 0 ? (
        <p>Aucun relevé importé pour l'instant : dépose les relevés PDF de la banque (ou un zip) ci-dessous.</p>
      ) : (
        <>
          <BalanceChart series={series} />
          <div className="table-wrapper operations-scroll history-table">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Libellé</th>
                  <th className="amount-cell">Montant</th>
                  {!single &&
                    accounts.map((a) => (
                      <th key={a.id} className="amount-cell">
                        {shortName(a)}
                      </th>
                    ))}
                  <th className="amount-cell">{single ? 'Solde' : 'Total'}</th>
                </tr>
              </thead>
              <tbody>
                {ledger.rows.map((row) => {
                  const name = shortName(accounts.find((a) => a.id === row.accountId))
                  return (
                    <tr key={row.id} className={row.transfer ? 'history-transfer' : undefined}>
                      <td>{dateFr(row.date)}</td>
                      <td title={row.details || undefined}>
                        {row.transfer ? `Virement ${row.transfer.from} → ${row.transfer.to}` : row.label}
                        <span className="history-details">
                          {[!single && !row.transfer && name, row.details.split('\n')[0]].filter(Boolean).join(' · ')}
                        </span>
                      </td>
                      <td
                        className={`amount-cell ${row.transfer ? '' : row.amount < 0 ? 'unpaid-amount' : 'success-state'}`}
                      >
                        {row.transfer ? '⇄ ' : row.amount > 0 ? '+' : ''}
                        {euros(row.amount)}
                      </td>
                      {!single &&
                        accounts.map((a) => (
                          <td key={a.id} className="amount-cell history-balance">
                            {row.balances[a.id] == null ? '—' : euros(row.balances[a.id])}
                          </td>
                        ))}
                      <td className="amount-cell history-total">
                        {single
                          ? euros(row.balances[view])
                          : row.total == null
                            ? '—'
                            : euros(row.total)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="history-statements">
        <h4>Relevés importés</h4>
        {shown.map((a) => (
          <p key={a.id}>
            <strong>{a.name}</strong> :{' '}
            {a.coverage
              .map((c) => `du ${dateFr(c.from)} au ${dateFr(c.to)} (${c.statements} relevé${c.statements > 1 ? 's' : ''})`)
              .join(', puis ')}
          </p>
        ))}
        {ledger.issues.map((issue) => (
          <p key={issue} className="error">
            {issue}
          </p>
        ))}
        <label className="history-import">
          {importing ? 'Import en cours…' : 'Déposer des relevés (PDF ou zip)'}
          <input type="file" accept=".pdf,.zip,application/pdf,application/zip" multiple hidden disabled={importing} onChange={importFiles} />
        </label>
        {report && (
          <div className="history-report">
            <p>
              {report.imported.length} relevé{report.imported.length > 1 ? 's' : ''} importé
              {report.imported.length > 1 ? 's' : ''}, {report.skipped.length} déjà présent
              {report.skipped.length > 1 ? 's' : ''}
              {report.errors.length > 0 && `, ${report.errors.length} refusé${report.errors.length > 1 ? 's' : ''}`}.
            </p>
            {report.errors.map((e) => (
              <p key={e.file} className="error">
                {e.file} : {e.detail}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
