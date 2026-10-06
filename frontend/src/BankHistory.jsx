import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BalanceChart } from './BalanceChart.jsx'
import { CurveChart } from './Seasons.jsx'
import { normaliserTexte } from './HelloAsso.jsx'
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
  if (account.kind === 'checking') return 'CC'
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

// Choix du menu "Categories" (voir BankHistory) : tout, les 5 categories
// les plus frequentes, les 5 plus grosses, ou une categorie precise (son
// nom). Les operations sont classees par le backend (bankstatements/
// categories.py).
const ALL_CATEGORIES = 'all'
const TOP_FREQUENT = 'top-frequent'
const TOP_AMOUNT = 'top-amount'
const TOP_COUNT = 5
// Categories qui ne sont pas une vraie nature de recette ou de depense :
// hors des "5 plus...".
const NOT_RANKED = ['Autres', 'Virement interne']

// Par categorie : nombre d'operations, recettes, depenses et total. Un
// virement interne ne compte pas (ni recette ni depense).
function categoryStats(rows) {
  const stats = new Map()
  for (const row of rows) {
    const stat = stats.get(row.category) ?? { name: row.category, count: 0, income: 0, expense: 0, total: 0 }
    stat.count += 1
    if (!row.transfer) {
      if (row.amount > 0) stat.income += row.amount
      else stat.expense += row.amount
      stat.total += row.amount
    }
    stats.set(row.category, stat)
  }
  return stats
}

// Serie du graphique quand un filtre est actif : cumul des operations
// retenues (ex: ce que les salaires ont coute depuis le debut), un point
// par jour entre la 1re et la derniere.
function cumulativeSeries(rows) {
  let sum = 0
  const cumulated = [...rows].reverse().map((row) => {
    sum += row.transfer ? 0 : row.amount
    return { ...row, cumul: Math.round(sum * 100) / 100 }
  })
  const series = ledgerSeries(cumulated.reverse(), (row) => row.cumul)
  // Depart a 0 la veille de la 1re operation : la variation affichee sur
  // toute la periode est ainsi le total des operations retenues.
  if (series.length > 0) series.unshift({ t: series[0].t - DAY_MS, v: 0, ops: [] })
  return series
}

// Periode "Saisons" du graphique : la courbe affichee (comptes et categories
// choisis) decoupee par saison, les saisons superposees sur le meme axe du
// 1er juillet au 30 juin. Sous le graphique, un clic sur une saison de la
// legende la masque ou la reaffiche, comme dans l'onglet Saisons.
// Cumul des operations retenues, remis a zero au debut de chaque saison (une
// valeur par jour d'operation). Un ensemble de depenses (total negatif) est
// compte en positif, pour que la courbe monte avec ce qui est depense.
function seasonalCumul(rows, seasons) {
  const amount = (row) => (row.transfer ? 0 : row.amount)
  const spending = rows.reduce((sum, row) => sum + amount(row), 0) < 0
  const oldestFirst = [...rows].sort((a, b) => a.date.localeCompare(b.date))
  const byDate = new Map()
  for (const season of seasons) {
    let sum = 0
    byDate.set(season.startDate, 0)
    for (const row of oldestFirst) {
      if (row.date < season.startDate || row.date > season.endDate) continue
      sum += spending ? -amount(row) : amount(row)
      byDate.set(row.date, Math.round(sum * 100) / 100)
    }
  }
  const series = [...byDate].sort(([a], [b]) => a.localeCompare(b)).map(([date, total]) => ({ date, total }))
  return { series, spending }
}

function SeasonsOverlay({ series, rows, filtering, seasonsData }) {
  if (!seasonsData) return <p className="balance-chart-empty">Chargement des saisons…</p>
  const seasons = seasonsData.seasons
  if (seasons.length === 0)
    return <p className="balance-chart-empty">Aucune saison : crée-les d'abord dans l'onglet Saisons.</p>
  // Sans filtre : le solde. Avec un filtre : le cumul des operations
  // retenues depuis le debut de chaque saison (pas depuis le 1er releve).
  const cumul = filtering ? seasonalCumul(rows, seasons) : null
  const data = {
    seasons,
    today: seasonsData.today,
    series: cumul
      ? cumul.series
      : series.filter((p) => p.v != null).map((p) => ({ date: new Date(p.t).toISOString().slice(0, 10), total: p.v })),
  }
  const current = seasons.find((s) => s.current) ?? seasons[seasons.length - 1]
  return (
    <>
      {cumul && (
        <p className="history-chart-note">
          {cumul.spending ? 'Dépenses cumulées' : 'Recettes cumulées'} depuis le début de chaque saison
        </p>
      )}
      <CurveChart data={data} selected={current} mode="overlay" hiddenKey="bankhistory-seasons-hidden" />
    </>
  )
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
  // Filtres sur la nature des operations : menu "Categories" + recherche.
  const [category, setCategory] = useState(ALL_CATEGORIES)
  const [search, setSearch] = useState('')
  // Saisons du club (periode "Saisons" du graphique, voir SeasonsOverlay).
  const [seasonsData, setSeasonsData] = useState(null)
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

  // Saisons du club, pour la periode "Saisons" du graphique.
  useEffect(() => {
    if (!active) return
    callApi('/seasons')
      .then(setSeasonsData)
      .catch(() => {
        // Saisons indisponibles : les autres periodes restent utilisables.
      })
  }, [active])

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

  function chooseCategory(next) {
    setCategory(next)
    setShownRows(ROWS_PAGE)
  }

  function chooseSearch(next) {
    setSearch(next)
    setShownRows(ROWS_PAGE)
  }

  const single = view !== 'all'

  // Categories presentes, et celles retenues par le menu (null : toutes).
  const stats = useMemo(() => categoryStats(ledger?.rows ?? []), [ledger])
  const selectedCategories = useMemo(() => {
    if (category === ALL_CATEGORIES) return null
    if (category !== TOP_FREQUENT && category !== TOP_AMOUNT) return [category]
    const ranked = [...stats.values()].filter((stat) => !NOT_RANKED.includes(stat.name))
    const byAmount = (a, b) => Math.abs(b.total) - Math.abs(a.total)
    // A nombre d'operations egal : la plus grosse d'abord.
    ranked.sort(category === TOP_FREQUENT ? (a, b) => b.count - a.count || byAmount(a, b) : byAmount)
    return ranked.slice(0, TOP_COUNT).map((stat) => stat.name)
  }, [category, stats])

  // Operations retenues par le menu et la recherche (libelle, details ou
  // categorie, sans tenir compte des majuscules ni des accents).
  const wanted = normaliserTexte(search.trim())
  const filtering = selectedCategories !== null || wanted !== ''
  const rows = useMemo(() => {
    if (!ledger) return []
    if (!filtering) return ledger.rows
    return ledger.rows.filter(
      (row) =>
        (selectedCategories === null || selectedCategories.includes(row.category)) &&
        (wanted === '' || normaliserTexte(`${rowLabel(row)} ${row.details} ${row.category}`).includes(wanted))
    )
  }, [ledger, filtering, selectedCategories, wanted])
  // Recettes, depenses et detail par categorie de la selection.
  const selection = useMemo(() => {
    const perCategory = [...categoryStats(rows).values()].sort((a, b) => Math.abs(b.total) - Math.abs(a.total))
    return {
      perCategory,
      income: perCategory.reduce((sum, stat) => sum + stat.income, 0),
      expense: perCategory.reduce((sum, stat) => sum + stat.expense, 0),
    }
  }, [rows])

  // Graphique : solde des comptes, ou cumul des operations retenues quand un
  // filtre est actif (le solde n'aurait plus de sens).
  const series = useMemo(() => {
    if (!ledger) return []
    if (filtering) return cumulativeSeries(rows)
    return ledgerSeries(ledger.rows, single ? (row) => row.balances[view] : (row) => row.total)
  }, [ledger, filtering, rows, single, view])

  // Tableau : n'affiche que les premieres lignes, puis la suite quand on
  // arrive en bas de la zone qui defile.
  const rowCount = rows.length
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

          <div className="history-filters">
            <select
              value={category}
              onChange={(e) => chooseCategory(e.target.value)}
              aria-label="Catégories affichées"
              className={category === ALL_CATEGORIES ? undefined : 'history-filter-active'}
            >
              <option value={ALL_CATEGORIES}>Toutes les catégories</option>
              <option value={TOP_FREQUENT}>Les {TOP_COUNT} plus fréquentes</option>
              <option value={TOP_AMOUNT}>Les {TOP_COUNT} plus grosses</option>
              <optgroup label="Une catégorie">
                {ledger.categories
                  .filter((name) => stats.has(name))
                  .map((name) => (
                    <option key={name} value={name}>
                      {name} ({stats.get(name).count})
                    </option>
                  ))}
              </optgroup>
            </select>
            <label className="member-search">
              <span aria-hidden="true">🔍</span>
              <input
                type="search"
                name="operation-search"
                placeholder="Rechercher une opération..."
                value={search}
                onChange={(e) => chooseSearch(e.target.value)}
              />
            </label>
          </div>

          {filtering && (
            <div className="history-selection">
              <p>
                <strong>{plural(rows.length, 'opération')}</strong> · Recettes{' '}
                <span className="success-state">+{euros(selection.income)}</span> · Dépenses{' '}
                <span className="unpaid-amount">{euros(selection.expense)}</span> · Net{' '}
                <strong>{euros(selection.income + selection.expense)}</strong>
              </p>
              {selection.perCategory.length > 1 && (
                <ul>
                  {selection.perCategory.map((stat) => (
                    <li key={stat.name}>
                      <button className="history-category" onClick={() => chooseCategory(stat.name)}>
                        {stat.name}
                      </button>{' '}
                      <span className={stat.total < 0 ? 'unpaid-amount' : 'success-state'}>
                        {stat.total > 0 ? '+' : ''}
                        {euros(stat.total)}
                      </span>{' '}
                      <small>({plural(stat.count, 'opération')})</small>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {rows.length === 0 ? (
            <p className="empty-state">Aucune opération ne correspond</p>
          ) : display === 'chart' ? (
            <>
              {filtering && <p className="history-chart-note">Cumul des opérations retenues, depuis le début de la période</p>}
              <BalanceChart
                series={series}
                showPercent={!filtering}
                fromZero={filtering}
                extraRange={{
                  label: 'Saisons',
                  content: <SeasonsOverlay series={series} rows={rows} filtering={filtering} seasonsData={seasonsData} />,
                }}
              />
            </>
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
                  {rows.slice(0, shownRows).map((row) => {
                    const name = shortName(accounts.find((a) => a.id === row.accountId))
                    const subline = [
                      !row.transfer && row.category,
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
              {shownRows < rows.length && <div ref={sentinel} className="history-more" />}
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
