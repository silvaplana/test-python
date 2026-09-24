import { useEffect, useId, useMemo, useRef, useState } from 'react'

const DAY_MS = 24 * 3600 * 1000
const HEIGHT = 250
const MARGIN = { top: 14, right: 14, bottom: 28, left: 66 }

const GREEN = '#4ade80'
const RED = '#f87171'

// Durees proposees (en jours) : seules celles couvertes par les donnees
// disponibles sont affichees, plus "Max" (tout l'historique connu).
const RANGES = [
  { label: '1S', days: 7, long: '1 semaine' },
  { label: '1M', days: 30, long: '1 mois' },
  { label: '3M', days: 90, long: '3 mois' },
  { label: '6M', days: 182, long: '6 mois' },
  { label: '1A', days: 365, long: '1 an' },
  { label: '5A', days: 1826, long: '5 ans' },
]

const eurosFull = (n) =>
  `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
const eurosRound = (n) => `${Math.round(n).toLocaleString('fr-FR')} €`
const dateShort = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' })
const dateMonthYear = new Intl.DateTimeFormat('fr-FR', { month: 'short', year: 'numeric' })
const dateLong = new Intl.DateTimeFormat('fr-FR', { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })

// Reconstitue l'evolution du solde a partir du solde ACTUEL et des operations
// (la banque ne donne pas d'historique de solde) : en remontant le temps, le
// solde de la veille d'une operation est le solde du jour moins cette
// operation. Une valeur par jour (solde en fin de journee), du jour precedant
// la 1ere operation connue jusqu'a aujourd'hui. Les operations sont celles
// renvoyees par l'API ({date: 'AAAA-MM-JJ', amount}).
export function balanceSeries(operations, currentBalance) {
  if (!operations?.length || currentBalance == null) return []
  const changes = new Map()
  let total = 0
  for (const op of operations) {
    if (!op.date) continue
    const day = Date.parse(`${op.date}T00:00:00Z`)
    changes.set(day, (changes.get(day) ?? 0) + op.amount)
    total += op.amount
  }
  if (changes.size === 0) return []
  const first = Math.min(...changes.keys())
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  const last = Math.max(today, ...changes.keys())
  const series = []
  let value = currentBalance - total
  for (let day = first - DAY_MS; day <= last; day += DAY_MS) {
    value += changes.get(day) ?? 0
    series.push({ t: day, v: Math.round(value * 100) / 100 })
  }
  return series
}

// Graduations "rondes" (1, 2, 5 x 10^n) pour l'axe vertical.
function niceTicks(min, max, count = 4) {
  const span = max - min || 1
  const rough = span / count
  const pow = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= rough) ?? 10 * pow
  const ticks = []
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(v)
  return ticks
}

// Courbe lissee passant par tous les points (interpolation cubique
// monotone, Fritsch-Carlson) : pas de "bosses" inventees entre 2 jours, contrairement
// a une spline classique.
function smoothPath(points) {
  const n = points.length
  if (n < 2) return ''
  const dx = []
  const slope = []
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1].x - points[i].x
    slope[i] = (points[i + 1].y - points[i].y) / dx[i]
  }
  const tangent = [slope[0]]
  for (let i = 1; i < n - 1; i++) tangent[i] = slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2
  tangent[n - 1] = slope[n - 2]
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      tangent[i] = tangent[i + 1] = 0
      continue
    }
    const a = tangent[i] / slope[i]
    const b = tangent[i + 1] / slope[i]
    const s = a * a + b * b
    if (s > 9) {
      const tau = 3 / Math.sqrt(s)
      tangent[i] = tau * a * slope[i]
      tangent[i + 1] = tau * b * slope[i]
    }
  }
  let d = `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`
  for (let i = 0; i < n - 1; i++) {
    const c1x = points[i].x + dx[i] / 3
    const c1y = points[i].y + (tangent[i] * dx[i]) / 3
    const c2x = points[i + 1].x - dx[i] / 3
    const c2y = points[i + 1].y - (tangent[i + 1] * dx[i]) / 3
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${points[i + 1].x.toFixed(1)},${points[i + 1].y.toFixed(1)}`
  }
  return d
}

// Graphique d'evolution d'un solde, facon graphique boursier : courbe en
// aires (verte si le solde progresse sur la periode, rouge sinon), choix de
// la duree, curseur qui suit la souris (ou le doigt) avec date + solde, et
// variation sur la periode. SVG maison (aucune dependance), largeur adaptee au
// conteneur.
export function BalanceChart({ series }) {
  const gradientId = useId()
  const wrapperRef = useRef(null)
  const [width, setWidth] = useState(600)
  const [hoverIndex, setHoverIndex] = useState(null)

  const spanDays = series.length > 1 ? (series[series.length - 1].t - series[0].t) / DAY_MS : 0
  const ranges = useMemo(
    () => [...RANGES.filter((r) => r.days < spanDays), { label: 'Max', days: Infinity, long: 'toute la période' }],
    [spanDays]
  )
  // Duree par defaut : la plus longue "ronde" disponible (3M avec 90 jours de
  // donnees) -- sinon Max.
  const [rangeLabel, setRangeLabel] = useState(null)
  const range = ranges.find((r) => r.label === rangeLabel) ?? ranges[ranges.length - 1]

  useEffect(() => {
    const el = wrapperRef.current
    if (!el) return undefined
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const visible = useMemo(() => {
    if (series.length < 2) return series
    const cutoff = series[series.length - 1].t - range.days * DAY_MS
    const slice = series.filter((p) => p.t >= cutoff)
    return slice.length >= 2 ? slice : series
  }, [series, range])

  if (visible.length < 2) {
    return <p className="balance-chart-empty">Pas assez de données pour tracer l'évolution.</p>
  }

  const innerW = width - MARGIN.left - MARGIN.right
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom
  const values = visible.map((p) => p.v)
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const pad = (rawMax - rawMin || Math.abs(rawMax) * 0.02 || 1) * 0.12
  const yMin = rawMin - pad
  const yMax = rawMax + pad
  const t0 = visible[0].t
  const t1 = visible[visible.length - 1].t
  const x = (t) => MARGIN.left + ((t - t0) / (t1 - t0 || 1)) * innerW
  const y = (v) => MARGIN.top + (1 - (v - yMin) / (yMax - yMin)) * innerH
  const points = visible.map((p) => ({ x: x(p.t), y: y(p.v) }))

  const line = smoothPath(points)
  const baseline = MARGIN.top + innerH
  const area = `${line} L${points[points.length - 1].x.toFixed(1)},${baseline} L${points[0].x.toFixed(1)},${baseline} Z`

  const first = visible[0]
  const last = visible[visible.length - 1]
  const change = last.v - first.v
  const percent = first.v !== 0 ? (change / Math.abs(first.v)) * 100 : null
  const color = change >= 0 ? GREEN : RED
  const hovered = hoverIndex != null ? visible[hoverIndex] : null

  const yTicks = niceTicks(yMin, yMax)
  const longRange = (t1 - t0) / DAY_MS > 300
  const xFormat = longRange ? dateMonthYear : dateShort
  const xTickCount = width < 420 ? 3 : 5
  const xTicks = Array.from({ length: xTickCount }, (_, i) => visible[Math.round((i * (visible.length - 1)) / (xTickCount - 1))])

  // Point le plus proche du pointeur (souris ou doigt).
  function onPointerMove(event) {
    const rect = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - rect.left
    let best = 0
    let bestDistance = Infinity
    points.forEach((p, i) => {
      const distance = Math.abs(p.x - px)
      if (distance < bestDistance) {
        best = i
        bestDistance = distance
      }
    })
    setHoverIndex(best)
  }

  return (
    <div className="balance-chart">
      <div className="balance-chart-top">
        <div className="balance-chart-figures">
          {hovered ? (
            <>
              <span className="balance-chart-value">{eurosFull(hovered.v)}</span>
              <span className="balance-chart-sub">{dateLong.format(hovered.t)}</span>
            </>
          ) : (
            <>
              <span className="balance-chart-value" style={{ color }}>
                {change >= 0 ? '▲ +' : '▼ '}
                {eurosFull(change)}
                {percent != null && ` (${change >= 0 ? '+' : ''}${percent.toFixed(2).replace('.', ',')} %)`}
              </span>
              <span className="balance-chart-sub">sur {range.label === 'Max' ? 'la période disponible' : range.long}</span>
            </>
          )}
        </div>
        <div className="balance-chart-ranges" role="group" aria-label="Durée">
          {ranges.map((r) => (
            <button
              key={r.label}
              className={r.label === range.label ? 'filter-chip filter-chip-active' : 'filter-chip'}
              aria-pressed={r.label === range.label}
              onClick={() => {
                setRangeLabel(r.label)
                setHoverIndex(null)
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="balance-chart-plot" ref={wrapperRef}>
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label="Évolution du solde"
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHoverIndex(null)}
          style={{ touchAction: 'pan-y' }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.32" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>

          {yTicks.map((v) => (
            <g key={v}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(v)} y2={y(v)} className="balance-chart-grid" />
              <text x={MARGIN.left - 10} y={y(v) + 4} textAnchor="end" className="balance-chart-axis">
                {eurosRound(v)}
              </text>
            </g>
          ))}
          {xTicks.map((p, i) => (
            <text
              key={i}
              x={x(p.t)}
              y={HEIGHT - 8}
              textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
              className="balance-chart-axis"
            >
              {xFormat.format(p.t)}
            </text>
          ))}

          <path d={area} fill={`url(#${gradientId})`} />
          <path d={line} fill="none" stroke={color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />

          {hovered && (
            <g pointerEvents="none">
              <line x1={points[hoverIndex].x} x2={points[hoverIndex].x} y1={MARGIN.top} y2={baseline} className="balance-chart-cursor" />
              <circle cx={points[hoverIndex].x} cy={points[hoverIndex].y} r="9" fill={color} opacity="0.18" />
              <circle cx={points[hoverIndex].x} cy={points[hoverIndex].y} r="4.5" fill={color} stroke="var(--bg)" strokeWidth="2" />
            </g>
          )}
        </svg>
      </div>
    </div>
  )
}
