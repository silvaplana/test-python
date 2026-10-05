import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BalanceChart } from './BalanceChart.jsx'
import { showToast } from './Toast.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const DAY_MS = 24 * 3600 * 1000
// Choix memorises sur cet appareil : comptes affiches, graphique ou tableau.
const VIEW_KEY = 'bankhistory-view'
const DISPLAY_KEY = 'bankhistory-display'
// Tableau : lignes affichees d'abord, puis par paquets en descendant.
const ROWS_PAGE = 50
// Demande d'import de releves venue du menu ⋮ (voir requestStatementImport).
const IMPORT_EVENT = 'bankhistory-import'

// Entree "Importer relevés" du menu ⋮ (voir App.jsx) : ouvre le choix de
// fichiers de BankHistory.
export function requestStatementImport() {
  window.dispatchEvent(new Event(IMPORT_EVENT))
}

function readSetting(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function writeSetting(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Stockage indisponible : le choix ne sera juste pas retenu.
  }
}

function euros(amount) {
  return `${amount.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
}

function dateFr(isoDate) {
  const [year, month, day] = isoDate.split('-')
  return `${day}/${month}/${year}`
}

const plural = (n, word) => `${n} ${word}${n > 1 ? 's' : ''}`

// Nom court d'un compte (filtres et colonnes du tableau).
function shortName(account) {
  if (!account) return ''
  if (account.kind === 'checking') return 'Courant'
  if (/bleu/i.test(account.name)) return 'Bleu'
  return account.name
}

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `${path} a échoué (${response.status})`)
  }
  return response.json()
}

function rowLabel(row) {
  return row.transfer ? `Virement ${row.transfer.from} → ${row.transfer.to}` : row.label
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
    day.ops.push({ label: rowLabel(row), amount: row.amount })
    byDay.set(t, day)
  }
  if (byDay.size === 0) return []
  const days = [...byDay.keys()]
  const last = Math.max(...days)
  const series = []
  let v = null
  for (let t = Math.min(...days); t <= last; t += DAY_MS) {
    const day = byDay.get(t)
    if (day) v = day.v
    series.push({ t, v, ops: day?.ops ?? [] })
  }
  return series
}

// Etat des comptes du club, lu dans la base (voir backend bankstatements/) :
// total des comptes (vue par defaut) ou un compte seul, en graphique ou en
// tableau. A chaque ouverture de l'onglet (active), les dernieres operations
// de la banque sont ajoutees a la base (syncReady : connexion bancaire
// prete, voir BankAccounts.jsx). Import de releves PDF / archives depuis le
// menu ⋮.
export function BankHistory({ active, syncReady }) {
  const [view, setView] = useState(() => readSetting(VIEW_KEY, 'all'))
  const [display, setDisplay] = useState(() => readSetting(DISPLAY_KEY, 'chart'))
  const [ledger, setLedger] = useState(null)
  const [error, setError] = useState(null)
  const [importing, setImporting] = useState(false)
  const [importErrors, setImportErrors] = useState([])
  const [shownRows, setShownRows] = useState(ROWS_PAGE)
  const fileInput = useRef(null)
  const sentinel = useRef(null)

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

  // Dernieres operations de la banque, a chaque ouverture de l'onglet.
  useEffect(() => {
    if (!active || !syncReady) return
    let cancelled = false
    callApi('/bankstatements/sync', { method: 'POST' })
      .then(({ added }) => {
        if (cancelled || added.length === 0) return
        showToast(
          added.length === 1
            ? `Opération ajoutée depuis la banque : ${added[0].label} (${euros(added[0].amount)})`
            : `${plural(added.length, 'opération')} ajoutées depuis la banque`
        )
        load()
      })
      .catch(() => {
        // Banque injoignable : l'historique deja en base reste affiche.
      })
    return () => {
      cancelled = true
    }
  }, [active, syncReady, load])

  // Menu ⋮ > "Importer relevés".
  useEffect(() => {
    const open = () => fileInput.current?.click()
    window.addEventListener(IMPORT_EVENT, open)
    return () => window.removeEventListener(IMPORT_EVENT, open)
  }, [])

  async function importFiles(event) {
    const files = [...event.target.files]
    event.target.value = ''
    if (files.length === 0) return
    const body = new FormData()
    for (const file of files) body.append('files', file)
    setImporting(true)
    setImportErrors([])
    try {
      const report = await callApi('/bankstatements/import', { method: 'POST', body })
      const operations = report.imported.reduce((n, i) => n + Number.parseInt(i.detail.split(', ')[1]), 0)
      const parts = [`${plural(report.imported.length, 'relevé')} importé${report.imported.length > 1 ? 's' : ''}`]
      if (report.imported.length) parts[0] += ` (${plural(operations, 'opération')})`
      if (report.skipped.length) parts.push(`${report.skipped.length} déjà présent${report.skipped.length > 1 ? 's' : ''}`)
      if (report.errors.length) parts.push(`${report.errors.length} refusé${report.errors.length > 1 ? 's' : ''}`)
      showToast(parts.join(', '), report.errors.length ? 'warning' : 'info')
      setImportErrors(report.errors)
      await load()
    } catch (err) {
      showToast(`Import impossible : ${err.message}`, 'warning')
    } finally {
      setImporting(false)
    }
  }

  function chooseView(next) {
    setView(next)
    setShownRows(ROWS_PAGE)
    writeSetting(VIEW_KEY, next)
  }

  function chooseDisplay(next) {
    setDisplay(next)
    setShownRows(ROWS_PAGE)
    writeSetting(DISPLAY_KEY, next)
  }

  const single = view !== 'all'
  const series = useMemo(() => {
    if (!ledger) return []
    return ledgerSeries(ledger.rows, single ? (row) => row.balances[view] : (row) => row.total)
  }, [ledger, single, view])

  // Tableau : n'affiche que les premieres lignes, puis la suite quand on
  // arrive en bas de la zone qui defile.
  const rowCount = ledger?.rows.length ?? 0
  useEffect(() => {
    if (display !== 'table' || !sentinel.current) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) setShownRows((n) => Math.min(n + ROWS_PAGE, rowCount))
    })
    observer.observe(sentinel.current)
    return () => observer.disconnect()
  }, [display, rowCount, shownRows])

  const input = (
    <input
      ref={fileInput}
      type="file"
      accept=".pdf,.zip,.7z,.tar,.gz,.tgz,.bz2,.xz,application/pdf,application/zip"
      multiple
      hidden
      onChange={importFiles}
    />
  )

  if (error) return <p className="error">{error}</p>
  if (!ledger) return input

  const allAccounts = ledger.allAccounts
  const accounts = single ? ledger.accounts : allAccounts
  const shown = ledger.accounts
  const filters = [{ id: 'all', label: allAccounts.map(shortName).join(' + ') }, ...allAccounts.map((a) => ({ id: String(a.id), label: shortName(a) }))]

  return (
    <div className="account-card">
      {input}
      <div className="account-card-header">
        <div>
          <h3>{single ? shown[0]?.name : 'Total des comptes'}</h3>
          <span className="account-iban">
            {single
              ? shown[0]?.asOf && `au ${dateFr(shown[0].asOf)}`
              : shown.map((a) => `${a.name} ${a.balance == null ? '—' : euros(a.balance)}`).join(' · ')}
          </span>
        </div>
        <span className="account-balance">{euros(ledger.total)}</span>
      </div>

      {importing && <p className="loading-label">Import des relevés…</p>}
      {importErrors.map((e) => (
        <p key={e.file} className="error">
          {e.file} : {e.detail}
        </p>
      ))}

      {ledger.rows.length === 0 ? (
        <p>Aucun relevé importé pour l'instant : menu ⋮ en haut à droite › Importer relevés (PDF ou archive).</p>
      ) : (
        <>
          <div className="history-toolbar">
            {allAccounts.length > 1 && (
              <div className="filter-chips" role="group" aria-label="Comptes affichés">
                {filters.map((f) => (
                  <button
                    key={f.id}
                    className={f.id === view ? 'filter-chip filter-chip-active' : 'filter-chip'}
                    aria-pressed={f.id === view}
                    onClick={() => chooseView(f.id)}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            )}
            <div className="filter-chips" role="group" aria-label="Affichage">
              {[
                { id: 'chart', label: 'Graphique' },
                { id: 'table', label: 'Tableau' },
              ].map((d) => (
                <button
                  key={d.id}
                  className={d.id === display ? 'filter-chip filter-chip-active' : 'filter-chip'}
                  aria-pressed={d.id === display}
                  onClick={() => chooseDisplay(d.id)}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          {display === 'chart' ? (
            <BalanceChart series={series} />
          ) : (
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
                  {ledger.rows.slice(0, shownRows).map((row) => {
                    const name = shortName(accounts.find((a) => a.id === row.accountId))
                    const subline = [
                      !single && !row.transfer && name,
                      row.provisional && 'banque, en attente du relevé',
                      row.details.split('\n')[0],
                    ]
                    return (
                      <tr key={row.id} className={row.transfer ? 'history-transfer' : undefined}>
                        <td>{dateFr(row.date)}</td>
                        <td title={row.details || undefined}>
                          {rowLabel(row)}
                          <span className="history-details">{subline.filter(Boolean).join(' · ')}</span>
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
                          {single ? euros(row.balances[view]) : row.total == null ? '—' : euros(row.total)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {shownRows < ledger.rows.length && <div ref={sentinel} className="history-more" />}
            </div>
          )}
        </>
      )}

      {(shown.some((a) => a.coverage.length) || ledger.issues.length > 0) && (
        <div className="history-statements">
          {shown.map((a) => (
            <p key={a.id}>
              Relevés {a.name} :{' '}
              {a.coverage
                .map((c) => `du ${dateFr(c.from)} au ${dateFr(c.to)} (${plural(c.statements, 'relevé')})`)
                .join(', puis ')}
            </p>
          ))}
          {ledger.issues.map((issue) => (
            <p key={issue} className="error">
              {issue}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
