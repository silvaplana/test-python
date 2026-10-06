import { useCallback, useEffect, useRef, useState } from 'react'
import { niceTicks } from './BalanceChart.jsx'
import { showToast } from './Toast.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
// Choix du graphique memorises sur cet appareil.
const MODE_KEY = 'seasons-mode'
const METRIC_KEY = 'seasons-metric'

const MODES = [
  { id: 'spread', label: 'Étalées' },
  { id: 'overlay', label: 'Superposées' },
  { id: 'selected', label: 'Sélectionnée' },
]
const METRICS = [
  { id: 'licences', label: 'Licenciés' },
  { id: 'account', label: 'Compte' },
  { id: 'detail', label: 'Compte détaillé' },
  { id: 'ai', label: 'Coût IA' },
]

const ACCENT = '#c084fc'
const SAVINGS = '#93c5fd'
const AI = '#5eead4'
// Mode "Superposées" : la saison choisie en violet, les autres dans ces
// couleurs.
const OVERLAY_COLORS = ['#fdba74', '#5eead4', '#93c5fd', '#f9a8d4', '#fde047']

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

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `${path} a échoué (${response.status})`)
  }
  return response.json()
}

function sendJson(path, method, body) {
  return callApi(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

const euros = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
// `|| 0` : pas de "-0 €" pour une graduation a peine negative.
const eurosRound = (n) => `${(Math.round(n) || 0).toLocaleString('fr-FR')} €`
const signed = (n) => `${n >= 0 ? '+' : '−'}${euros(Math.abs(n))}`

function dateFr(isoDate) {
  const [year, month, day] = isoDate.split('-')
  return `${day}/${month}/${year}`
}

const ts = (isoDate) => Date.parse(`${isoDate}T00:00:00Z`)
const monthShort = new Intl.DateTimeFormat('fr-FR', { month: 'short', timeZone: 'UTC' })
const monthYear = new Intl.DateTimeFormat('fr-FR', { month: 'short', year: 'numeric', timeZone: 'UTC' })

// "2025-2026" -> "25-26" (axe des barres sur telephone).
function shortName(name, narrow) {
  const match = narrow && name.match(/^\d{2}(\d{2})-\d{2}(\d{2})$/)
  return match ? `${match[1]}-${match[2]}` : name
}

// Saison qui commence le 1er juillet de l'annee `year`.
function julySeason(year) {
  return { name: `${year}-${year + 1}`, startDate: `${year}-07-01`, endDate: `${year + 1}-06-30` }
}

// Valeurs proposees pour une nouvelle saison : la saison en cours (1er
// juillet - 30 juin) si elle n'existe pas encore, sinon celle qui suit la
// derniere.
function newSeasonDefaults(seasons, today) {
  const [year, month] = today.split('-').map(Number)
  const currentYear = month >= 7 ? year : year - 1
  if (!seasons.some((s) => s.startDate <= today && today <= s.endDate)) return julySeason(currentYear)
  const last = seasons[seasons.length - 1]
  return julySeason(Number(last.startDate.slice(0, 4)) + 1)
}

// Largeur du conteneur, suivie quand l'ecran change (telephone tourne...).
function useWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(600)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

// Onglet Finances > Saisons (voir backend seasons/) : une saison va par
// defaut du 1er juillet au 30 juin. Choix de la saison, creation /
// modification / suppression de sa fiche, ses chiffres cles et un graphique
// de toutes les saisons. A chaque ouverture de l'onglet (active), le nombre
// de licencies de la saison en cours est repris de FFST.
export function Seasons({ active }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [mode, setMode] = useState(() => readSetting(MODE_KEY, 'spread'))
  const [metric, setMetric] = useState(() => readSetting(METRIC_KEY, 'detail'))
  // Fiche ouverte : null, "create" ou "edit".
  const [dialog, setDialog] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await callApi('/seasons'))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    if (active) load()
  }, [active, load])

  // Licencies de la saison en cours, repris de FFST (quelques secondes).
  useEffect(() => {
    if (!active) return
    let cancelled = false
    callApi('/seasons/sync-licences', { method: 'POST' })
      .then(({ season }) => {
        if (!cancelled && season) load()
      })
      .catch(() => {
        // FFST injoignable : le dernier nombre connu reste affiche.
      })
    return () => {
      cancelled = true
    }
  }, [active, load])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p>Chargement…</p>

  const seasons = data.seasons
  // Saison affichee : celle choisie, sinon celle en cours, sinon la derniere.
  const selected = seasons.find((s) => s.id === selectedId) ?? seasons.find((s) => s.current) ?? seasons[seasons.length - 1]
  const previous = selected ? seasons[seasons.indexOf(selected) - 1] : undefined

  function chooseMode(id) {
    setMode(id)
    writeSetting(MODE_KEY, id)
  }

  function chooseMetric(id) {
    setMetric(id)
    writeSetting(METRIC_KEY, id)
  }

  async function remove() {
    if (
      !window.confirm(
        `Supprimer la saison ${selected.name} ?\n\nSa fiche est effacée (dates, licenciés, soldes, coût IA). Les opérations bancaires de cette période restent dans Comptes.`
      )
    )
      return
    try {
      await callApi(`/seasons/${selected.id}`, { method: 'DELETE' })
      setSelectedId(null)
      showToast(`Saison ${selected.name} supprimée`)
      load()
    } catch (err) {
      showToast(`Suppression impossible : ${err.message}`, 'warning')
    }
  }

  function saved(season) {
    setDialog(null)
    setSelectedId(season.id)
    load()
  }

  // Superposer des barres n'a pas de sens : seul "Compte detaille" (courbe)
  // propose "Superposées".
  const curve = metric === 'detail'
  const effectiveMode = !curve && mode === 'overlay' ? 'spread' : mode

  return (
    <section className="seasons">
      <div className="seasons-toolbar">
        <label className="seasons-picker">
          <span>Saison</span>
          <select
            value={selected?.id ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value))}
            disabled={seasons.length === 0}
          >
            {seasons.length === 0 && <option value="">Aucune saison</option>}
            {[...seasons].reverse().map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.current ? ' (en cours)' : ''}
              </option>
            ))}
          </select>
        </label>
        {selected && (
          <span className="seasons-range">
            {dateFr(selected.startDate)} – {dateFr(selected.endDate)}
          </span>
        )}
        <div className="seasons-actions">
          <button className="seasons-primary" onClick={() => setDialog('create')}>
            + Nouvelle<span className="seasons-wide-only"> saison</span>
          </button>
          <button onClick={() => setDialog('edit')} disabled={!selected}>
            Modifier
          </button>
          <button className="seasons-danger" onClick={remove} disabled={!selected}>
            Supprimer
          </button>
        </div>
      </div>

      {seasons.length === 0 ? (
        <div className="seasons-empty">
          <p>Aucune saison pour l'instant.</p>
          <p>Une saison va par défaut du 1er juillet au 30 juin : créez la saison en cours, puis les précédentes.</p>
        </div>
      ) : (
        <>
          <SeasonFigures season={selected} previous={previous} />

          <div className="seasons-chart-card">
            <div className="seasons-chart-filters">
              <div className="filter-chips" role="group" aria-label="Affichage des saisons">
                {MODES.map((m) => {
                  const disabled = m.id === 'overlay' && !curve
                  return (
                    <button
                      key={m.id}
                      className={m.id === effectiveMode ? 'filter-chip filter-chip-active' : 'filter-chip'}
                      aria-pressed={m.id === effectiveMode}
                      disabled={disabled}
                      title={disabled ? 'Seulement pour « Compte détaillé »' : undefined}
                      onClick={() => chooseMode(m.id)}
                    >
                      {m.label}
                    </button>
                  )
                })}
              </div>
              <div className="filter-chips" role="group" aria-label="Donnée affichée">
                {METRICS.map((m) => (
                  <button
                    key={m.id}
                    className={m.id === metric ? 'filter-chip filter-chip-active' : 'filter-chip'}
                    aria-pressed={m.id === metric}
                    onClick={() => chooseMetric(m.id)}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
            {curve ? (
              <CurveChart data={data} selected={selected} mode={effectiveMode} />
            ) : (
              <BarsChart seasons={seasons} selected={selected} mode={effectiveMode} metric={metric} />
            )}
          </div>
        </>
      )}

      {dialog && (
        <SeasonDialog
          season={dialog === 'edit' ? selected : null}
          defaults={newSeasonDefaults(seasons, data.today)}
          onClose={() => setDialog(null)}
          onSaved={saved}
        />
      )}
    </section>
  )
}

// Chiffres cles de la saison choisie.
function SeasonFigures({ season, previous }) {
  const balance = season.balance
  const delta =
    balance.total != null && previous?.balance.total != null ? balance.total - previous.balance.total : null
  // Solde calcule d'une saison passee dont la fin n'est pas couverte par
  // les releves : date du dernier mouvement connu.
  const balanceNote = !balance.auto
    ? 'saisi'
    : !season.current && balance.asOf && balance.asOf < season.endDate
      ? `au ${dateFr(balance.asOf)}`
      : null
  return (
    <div className="seasons-figures">
      <div className="seasons-figure">
        <span className="seasons-figure-label">Licenciés</span>
        <span className="seasons-figure-value">{season.licences ?? '—'}</span>
        <span className="seasons-figure-sub">{season.current ? 'repris de FFST' : ' '}</span>
      </div>
      <div className="seasons-figure">
        <span className="seasons-figure-label">{season.current ? 'Solde à ce jour' : 'Solde fin de saison'}</span>
        <span className="seasons-figure-value">{balance.total != null ? euros(balance.total) : '—'}</span>
        <span className="seasons-figure-sub">
          {balance.total != null
            ? `courant ${eurosRound(balance.checking)} + Bleu ${eurosRound(balance.savings)}${balanceNote ? ` · ${balanceNote}` : ''}`
            : 'pas de relevé à cette date'}
        </span>
      </div>
      <div className="seasons-figure">
        <span className="seasons-figure-label">Variation</span>
        <span className={`seasons-figure-value${delta != null && delta < 0 ? ' seasons-negative' : ''}`}>
          {delta != null ? signed(delta) : '—'}
        </span>
        <span className="seasons-figure-sub">
          {previous ? `depuis fin ${previous.name}` : 'pas de saison précédente'}
        </span>
      </div>
      <div className="seasons-figure">
        <span className="seasons-figure-label">Coût IA</span>
        <span className="seasons-figure-value">{season.aiCost != null ? euros(season.aiCost) : '—'}</span>
        <span className="seasons-figure-sub">cumul sur la saison</span>
      </div>
    </div>
  )
}

const CHART_HEIGHT = 260

// Graphique "Compte detaille" : solde total (courant + Livret Bleu) apres
// chaque operation, en escalier (il ne change qu'aux operations).
// - Etalees : toutes les saisons a la suite, chacune dans sa bande ;
// - Superposees : une courbe par saison sur le meme axe (debut -> fin de
//   saison), pour comparer les saisons entre elles ;
// - Selectionnee : la saison choisie seule.
function CurveChart({ data, selected, mode }) {
  const [ref, width] = useWidth()
  const narrow = width < 480
  const margin = { top: 26, right: 12, bottom: 28, left: narrow ? 46 : 66 }
  const innerW = width - margin.left - margin.right
  const innerH = CHART_HEIGHT - margin.top - margin.bottom
  const series = data.series.map((p) => ({ t: ts(p.date), v: p.total }))
  const today = ts(data.today)
  const lastKnown = series.length ? series[series.length - 1].t : today
  const seasons = data.seasons

  // Solde en fin de journee t (derniere operation ce jour-la ou avant).
  function valueAt(t) {
    let value = null
    for (const p of series) {
      if (p.t > t) break
      value = p.v
    }
    return value
  }

  // Points d'une saison, de son debut a sa fin (ou au dernier jour connu).
  function seasonPoints(season) {
    const start = ts(season.startDate)
    const end = Math.min(ts(season.endDate), Math.max(today, lastKnown))
    const points = []
    const initial = valueAt(start)
    if (initial != null) points.push({ t: start, v: initial })
    for (const p of series) if (p.t > start && p.t <= end) points.push(p)
    if (points.length) points.push({ t: end, v: points[points.length - 1].v })
    return points
  }

  // lines : [{key, color, width, points, x0, x1}] ; x0/x1 : debut et fin de
  // l'axe horizontal pour cette courbe.
  let lines
  let bands = []
  if (mode === 'spread') {
    const x0 = Math.min(...[seasons[0] && ts(seasons[0].startDate), series[0]?.t].filter((v) => v != null))
    const x1 = Math.max(lastKnown, today, ...seasons.map((s) => ts(s.endDate)))
    const points = series.filter((p) => p.t >= x0 && p.t <= x1)
    if (points.length) points.push({ t: Math.min(Math.max(today, lastKnown), x1), v: points[points.length - 1].v })
    lines = [{ key: 'all', color: ACCENT, width: 2, points, x0, x1 }]
    bands = seasons.map((s) => ({ season: s, from: ts(s.startDate), to: ts(s.endDate), x0, x1 }))
  } else {
    const shown = mode === 'selected' ? [selected] : seasons
    lines = shown.map((s) => ({
      key: s.id,
      label: s.name,
      color: s.id === selected.id ? ACCENT : OVERLAY_COLORS[shown.indexOf(s) % OVERLAY_COLORS.length],
      width: s.id === selected.id ? 2.6 : 1.6,
      points: seasonPoints(s),
      x0: ts(s.startDate),
      x1: ts(s.endDate),
    }))
  }

  const values = lines.flatMap((l) => l.points.map((p) => p.v))
  if (values.length === 0) {
    return (
      <div ref={ref}>
        <p className="balance-chart-empty">Pas encore d'opérations bancaires sur cette période (voir Comptes).</p>
      </div>
    )
  }
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const pad = (rawMax - rawMin || Math.abs(rawMax) * 0.05 || 1) * 0.12
  const yMin = rawMin - pad
  const yMax = rawMax + pad
  const y = (v) => margin.top + (1 - (v - yMin) / (yMax - yMin)) * innerH
  const xOf = (line, t) => margin.left + ((t - line.x0) / (line.x1 - line.x0 || 1)) * innerW

  function stepPath(line) {
    return line.points
      .map((p, i) => {
        const x = xOf(line, p.t).toFixed(1)
        return i === 0 ? `M${x},${y(p.v).toFixed(1)}` : `H${x} V${y(p.v).toFixed(1)}`
      })
      .join(' ')
  }

  // Axe horizontal : dates de la saison (Selectionnee) ou mois de la saison
  // choisie (Superposees, toutes les saisons ramenees sur le meme axe).
  const reference = lines[lines.length - 1]
  const xTicks =
    mode === 'spread'
      ? []
      : (narrow ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1]).map((f) => {
          const base = mode === 'overlay' ? { x0: ts(selected.startDate), x1: ts(selected.endDate) } : reference
          const t = base.x0 + f * (base.x1 - base.x0)
          return { x: margin.left + f * innerW, label: mode === 'overlay' ? monthShort.format(t) : monthYear.format(t) }
        })

  return (
    <div ref={ref} className="seasons-chart">
      <svg width={width} height={CHART_HEIGHT} role="img" aria-label="Évolution du solde total par saison">
        {bands.map((b) => {
          const left = xOf(b, b.from)
          const right = xOf(b, b.to)
          const isSelected = b.season.id === selected.id
          return (
            <g key={b.season.id}>
              {isSelected && (
                <rect x={left} y={margin.top} width={right - left} height={innerH} fill={ACCENT} opacity="0.08" />
              )}
              <line x1={right} x2={right} y1={margin.top} y2={margin.top + innerH} className="balance-chart-grid" />
              <text
                x={(left + right) / 2}
                y={margin.top - 9}
                textAnchor="middle"
                className={isSelected ? 'seasons-axis-strong' : 'balance-chart-axis'}
              >
                {shortName(b.season.name, narrow || right - left < 70)}
              </text>
            </g>
          )
        })}
        {niceTicks(yMin, yMax, 5).map((v) => (
          <g key={v}>
            <line x1={margin.left} x2={width - margin.right} y1={y(v)} y2={y(v)} className="balance-chart-grid" />
            <text x={margin.left - 8} y={y(v) + 4} textAnchor="end" className="balance-chart-axis">
              {narrow ? `${Math.round(v / 100) / 10 || 0} k` : eurosRound(v)}
            </text>
          </g>
        ))}
        {xTicks.map((tick, i) => (
          <text
            key={i}
            x={tick.x}
            y={CHART_HEIGHT - 8}
            textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
            className="balance-chart-axis"
          >
            {tick.label}
          </text>
        ))}
        {lines.map((line) => (
          <path
            key={line.key}
            d={stepPath(line)}
            fill="none"
            stroke={line.color}
            strokeWidth={line.width}
            strokeLinejoin="round"
          />
        ))}
      </svg>
      {mode === 'overlay' && (
        <div className="seasons-legend">
          {lines.map((line) => (
            <span key={line.key} className={line.key === selected.id ? 'seasons-legend-selected' : undefined}>
              <i style={{ background: line.color }} />
              {line.label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// Graphiques en barres, une par saison (ou la saison choisie seule) :
// licencies, coût IA, ou soldes de fin de saison (courant + Livret Bleu
// empiles).
function BarsChart({ seasons, selected, mode, metric }) {
  const [ref, width] = useWidth()
  const narrow = width < 480
  const margin = { top: 24, bottom: 30 }
  const innerH = CHART_HEIGHT - margin.top - margin.bottom
  const shown = mode === 'selected' ? [selected] : seasons

  // Segments de chaque barre, de bas en haut ; null : pas de valeur.
  function segments(s) {
    if (metric === 'licences') return s.licences != null ? [{ v: s.licences, color: ACCENT }] : null
    if (metric === 'ai') return s.aiCost != null ? [{ v: s.aiCost, color: AI }] : null
    if (s.balance.total == null) return null
    return [
      { v: s.balance.checking, color: ACCENT },
      { v: s.balance.savings, color: SAVINGS },
    ]
  }
  const format = (v) => (metric === 'licences' ? String(v) : narrow && v >= 1000 ? `${Math.round(v / 100) / 10} k€` : eurosRound(v))
  // Meme echelle quel que soit l'affichage (comparer d'un coup d'oeil). Un
  // solde negatif (decouvert) descend sous la ligne du zero.
  const sum = (s, sign) => (segments(s) ?? []).reduce((total, seg) => total + Math.max(0, sign * seg.v), 0)
  const maxUp = Math.max(1, ...seasons.map((s) => sum(s, 1)))
  const maxDown = Math.max(0, ...seasons.map((s) => sum(s, -1)))
  const scale = innerH / (maxUp + maxDown)
  const zeroY = margin.top + maxUp * scale
  const slot = width / shown.length
  const barW = Math.min(narrow ? 44 : 64, slot * 0.55)

  return (
    <div ref={ref} className="seasons-chart">
      <svg width={width} height={CHART_HEIGHT} role="img" aria-label={METRICS.find((m) => m.id === metric).label}>
        <line x1={0} x2={width} y1={zeroY} y2={zeroY} className="balance-chart-grid" />
        {shown.map((s, i) => {
          const center = slot * i + slot / 2
          const segs = segments(s)
          const total = segs?.reduce((sum, seg) => sum + seg.v, 0)
          let top = zeroY
          let bottom = zeroY
          const dim = s.id !== selected.id && mode !== 'selected'
          return (
            <g key={s.id} opacity={dim ? 0.55 : 1}>
              {segs?.map((seg, j) => {
                const h = Math.abs(seg.v) * scale
                const y = seg.v >= 0 ? (top -= h) : (bottom += h) - h
                return <rect key={j} x={center - barW / 2} y={y} width={barW} height={h} fill={seg.color} rx="2" />
              })}
              <text x={center} y={top - 7} textAnchor="middle" className="seasons-axis-strong">
                {segs ? format(total) : '—'}
              </text>
              <text
                x={center}
                y={CHART_HEIGHT - 8}
                textAnchor="middle"
                className={dim ? 'balance-chart-axis' : 'seasons-axis-strong'}
              >
                {shortName(s.name, narrow)}
              </text>
            </g>
          )
        })}
      </svg>
      {metric === 'account' && (
        <div className="seasons-legend">
          <span>
            <i style={{ background: ACCENT }} />
            Compte courant
          </span>
          <span>
            <i style={{ background: SAVINGS }} />
            Livret Bleu
          </span>
        </div>
      )}
    </div>
  )
}

// "1 234,5" -> 1234.5 ; vide -> null.
function parseNumber(text) {
  const clean = text.replace(/\s/g, '').replace(',', '.')
  if (clean === '') return null
  const n = Number(clean)
  return Number.isFinite(n) ? n : NaN
}

const toInput = (n) => (n == null ? '' : String(n).replace('.', ','))

// Fiche d'une saison : creation (season null) ou modification. Les soldes de
// fin de saison laisses vides sont calcules depuis les releves (valeur
// rappelee en grise dans le champ).
function SeasonDialog({ season, defaults, onClose, onSaved }) {
  const dialogRef = useRef(null)
  const manual = season && !season.balance.auto
  const [form, setForm] = useState(() =>
    season
      ? {
          name: season.name,
          startDate: season.startDate,
          endDate: season.endDate,
          licences: toInput(season.licences),
          checkingBalance: manual ? toInput(season.balance.checking) : '',
          savingsBalance: manual ? toInput(season.balance.savings) : '',
          aiCost: toInput(season.aiCost),
        }
      : { ...defaults, licences: '', checkingBalance: '', savingsBalance: '', aiCost: '' }
  )
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    dialogRef.current.showModal()
  }, [])

  function update(key) {
    return (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  // Nom "AAAA-AAAA" : dates du 1er juillet au 30 juin, tant qu'elles
  // suivent encore le nom precedent (pas modifiees a la main).
  function updateName(e) {
    const name = e.target.value
    setForm((prev) => {
      const before = prev.name.match(/^(\d{4})-\d{4}$/)
      const after = name.match(/^(\d{4})-\d{4}$/)
      const followed =
        !before ||
        (prev.startDate === julySeason(Number(before[1])).startDate && prev.endDate === julySeason(Number(before[1])).endDate)
      if (!after || !followed) return { ...prev, name }
      const dates = julySeason(Number(after[1]))
      return { ...prev, name, startDate: dates.startDate, endDate: dates.endDate }
    })
  }

  async function save(e) {
    e.preventDefault()
    const body = {
      name: form.name.trim(),
      startDate: form.startDate,
      endDate: form.endDate,
      licences: parseNumber(form.licences),
      checkingBalance: parseNumber(form.checkingBalance),
      savingsBalance: parseNumber(form.savingsBalance),
      aiCost: parseNumber(form.aiCost),
    }
    if (Object.values(body).some((v) => Number.isNaN(v))) {
      setError('Nombre invalide')
      return
    }
    if (body.licences != null && !Number.isInteger(body.licences)) {
      setError('Le nombre de licenciés doit être un entier')
      return
    }
    // Un seul des deux soldes saisi : l'autre garde la valeur calculee.
    const computed = season?.balance.computed
    if ((body.checkingBalance == null) !== (body.savingsBalance == null)) {
      body.checkingBalance ??= computed?.checking ?? 0
      body.savingsBalance ??= computed?.savings ?? 0
    }
    setPending(true)
    setError(null)
    try {
      onSaved(season ? await sendJson(`/seasons/${season.id}`, 'PUT', body) : await sendJson('/seasons', 'POST', body))
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  const computed = season?.balance.computed
  const placeholder = (key) =>
    computed ? `auto : ${euros(computed[key])}` : season ? 'pas de relevé à cette date' : 'calculé depuis les relevés'

  return (
    <dialog ref={dialogRef} className="trial-dialog" onClose={onClose}>
      <form onSubmit={save}>
        <h3>{season ? `Modifier la saison ${season.name}` : 'Nouvelle saison'}</h3>
        <div className="trial-form-grid">
          <label className="trial-form-wide">
            Nom *
            <input value={form.name} onChange={updateName} required autoComplete="off" />
          </label>
          <label>
            Début *
            <input type="date" value={form.startDate} onChange={update('startDate')} required />
          </label>
          <label>
            Fin *
            <input type="date" value={form.endDate} onChange={update('endDate')} required />
          </label>
          <label className="trial-form-wide">
            Licenciés
            <input inputMode="numeric" value={form.licences} onChange={update('licences')} autoComplete="off" />
            <span className="profile-hint">Repris de FFST pour la saison en cours ; à saisir pour les saisons passées.</span>
          </label>
          <label>
            Solde fin, compte courant (€)
            <input
              inputMode="decimal"
              value={form.checkingBalance}
              placeholder={placeholder('checking')}
              onChange={update('checkingBalance')}
              autoComplete="off"
            />
          </label>
          <label>
            Solde fin, Livret Bleu (€)
            <input
              inputMode="decimal"
              value={form.savingsBalance}
              placeholder={placeholder('savings')}
              onChange={update('savingsBalance')}
              autoComplete="off"
            />
          </label>
          <span className="profile-hint trial-form-wide">
            Laissez vide pour le solde calculé depuis les relevés à la date de fin (à ce jour pour la saison en cours).
          </span>
          <label className="trial-form-wide">
            Coût IA (€)
            <input inputMode="decimal" value={form.aiCost} onChange={update('aiCost')} autoComplete="off" />
          </label>
        </div>

        {error && <p className="error">{error}</p>}

        <div className="trial-dialog-actions">
          <button type="button" onClick={() => dialogRef.current.close()} disabled={pending}>
            Annuler
          </button>
          <button type="submit" className="trial-save" disabled={pending}>
            Enregistrer
          </button>
        </div>
      </form>
    </dialog>
  )
}
