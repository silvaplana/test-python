import { useCallback, useEffect, useRef, useState } from 'react'
import { niceTicks } from './BalanceChart.jsx'
import { showToast } from './Toast.jsx'

// Finances > Prévisionnel : previsionnels d'une saison (voir
// backend/src/forecasts). Chaque previsionnel a un nom, un etat, une date de
// depart, un prompt et un modele d'IA ; "Executer le calcul" fait ecrire par
// l'IA une formule Python (verifiee et executee par l'appli) qui prevoit le
// solde (courant + Livret Bleu) chaque semaine jusqu'a la fin de la saison.
// Les curseurs reglent les parametres de la formule : la courbe est
// recalculee sans rappeler l'IA, et leur position est enregistree.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const POLL_MS = 2000
// Delai apres le dernier mouvement d'un curseur avant de recalculer.
const SLIDER_DELAY_MS = 250
const STATE_LABELS = { brouillon: 'Brouillon', valide: 'Validé', officiel: 'Officiel' }
const REAL = '#c084fc'
const FORECAST = '#fdba74'
const ACTUAL = '#d1d5db'
// Saisons comparees : memes couleurs que "Superposées" dans Saisons.
const SEASON_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9']
const CHART_HEIGHT = 280
const DAY_MS = 86_400_000
const COMPARE_KEY = 'forecasts-compare'

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

const euros = (n) => (n == null ? '—' : `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`)
const eurosRound = (n) => (n == null ? '—' : `${(Math.round(n) || 0).toLocaleString('fr-FR')} €`)
const ts = (isoDate) => Date.parse(`${isoDate.slice(0, 10)}T00:00:00Z`)
const monthShort = new Intl.DateTimeFormat('fr-FR', { month: 'short', timeZone: 'UTC' })

function dateFr(iso) {
  const [year, month, day] = iso.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

function paramLabel(param, value) {
  const text = Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 2 })
  return param.unit ? `${text} ${param.unit}` : text
}

function readCompare() {
  try {
    const ids = JSON.parse(localStorage.getItem(COMPARE_KEY) ?? 'null')
    return Array.isArray(ids) ? new Set(ids) : null
  } catch {
    return null
  }
}

function writeCompare(ids) {
  try {
    localStorage.setItem(COMPARE_KEY, JSON.stringify([...ids]))
  } catch {
    // Stockage indisponible : le choix ne sera juste pas retenu.
  }
}

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

export function Forecasts({ active }) {
  // Saisons et courbe du solde (GET /seasons), pour le graphique.
  const [seasonsData, setSeasonsData] = useState(null)
  const [seasonId, setSeasonId] = useState(null)
  const [listing, setListing] = useState(null)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState(null)
  // Panneau ouvert : null, "new" ou l'id du previsionnel.
  const [editing, setEditing] = useState(null)

  useEffect(() => {
    if (!active) return
    callApi('/seasons')
      .then((data) => {
        setSeasonsData(data)
        setSeasonId((id) => id ?? (data.seasons.find((s) => s.current) ?? data.seasons[data.seasons.length - 1])?.id ?? null)
      })
      .catch((err) => setError(err.message))
  }, [active])

  const loadForecasts = useCallback(async () => {
    if (seasonId == null) return
    try {
      setListing(await callApi(`/forecasts?seasonId=${seasonId}`))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [seasonId])

  useEffect(() => {
    if (active) loadForecasts()
  }, [active, loadForecasts])

  if (error) return <p className="error">{error}</p>
  if (!seasonsData) return <p>Chargement…</p>
  const seasons = seasonsData.seasons
  if (seasons.length === 0)
    return (
      <section className="reports">
        <div className="seasons-empty">
          <p>Aucune saison pour l'instant : créez d'abord la saison dans l'onglet Saisons.</p>
        </div>
      </section>
    )

  const season = seasons.find((s) => s.id === seasonId)
  const forecasts = listing?.forecasts ?? []
  const shown = forecasts.filter((f) => filter === 'all' || f.state === filter)

  async function remove(forecast) {
    if (
      !window.confirm(
        `Supprimer le prévisionnel « ${forecast.name} » ?\n\nSon prompt, sa formule, la position des curseurs et son coût IA sont effacés. Les opérations bancaires ne sont pas touchées.`,
      )
    )
      return
    try {
      await callApi(`/forecasts/${forecast.id}`, { method: 'DELETE' })
      showToast(`Prévisionnel « ${forecast.name} » supprimé`)
      loadForecasts()
    } catch (err) {
      showToast(`Suppression impossible : ${err.message}`, 'warning')
    }
  }

  if (editing !== null && listing)
    return (
      <ForecastPanel
        key={editing}
        forecastId={editing === 'new' ? null : editing}
        season={season}
        seasonsData={seasonsData}
        options={listing}
        onClose={() => {
          setEditing(null)
          loadForecasts()
        }}
        onCreated={(id) => setEditing(id)}
      />
    )

  return (
    <section className="reports">
      <div className="seasons-toolbar">
        <select aria-label="Saison" value={seasonId ?? ''} onChange={(e) => setSeasonId(Number(e.target.value))}>
          {[...seasons].reverse().map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.current ? ' (en cours)' : ''}
              {/* Nombre de prévisionnels de la saison (connu une fois la liste chargee). */}
              {listing?.counts && ` : ${listing.counts[s.id] ?? 0} prévisionnel${(listing.counts[s.id] ?? 0) > 1 ? 's' : ''}`}
            </option>
          ))}
        </select>
        <button className="seasons-primary" onClick={() => setEditing('new')} disabled={!listing} aria-label="Nouveau prévisionnel">
          +<span className="seasons-wide-only"> Nouveau prévisionnel</span>
        </button>
      </div>

      <div className="filter-chips" role="group" aria-label="État">
        {['all', ...Object.keys(STATE_LABELS)].map((state) => (
          <button
            key={state}
            className={state === filter ? 'filter-chip filter-chip-active' : 'filter-chip'}
            aria-pressed={state === filter}
            onClick={() => setFilter(state)}
          >
            {state === 'all' ? 'Tous' : STATE_LABELS[state]} ({forecasts.filter((f) => state === 'all' || f.state === state).length})
          </button>
        ))}
      </div>

      {!listing ? (
        <p>Chargement…</p>
      ) : shown.length === 0 ? (
        <div className="seasons-empty">
          <p>{forecasts.length === 0 ? `Aucun prévisionnel pour ${season?.name} : créez-en un.` : 'Aucun prévisionnel dans cet état.'}</p>
        </div>
      ) : (
        <ul className="reports-list">
          {shown.map((f) => (
            <li key={f.id}>
              <div className="reports-item-main">
                <span className="reports-item-name">{f.name}</span>
                <span className="reports-item-meta">
                  <StateBadge state={f.state} />
                  {f.status === 'running' ? (
                    'calcul en cours…'
                  ) : f.status === 'error' ? (
                    'dernier calcul en erreur'
                  ) : f.endBalance != null ? (
                    <>
                      au {dateFr(season.endDate)} : <b className="forecasts-end">{eurosRound(f.endBalance)}</b>
                    </>
                  ) : (
                    'pas encore calculé'
                  )}
                  {' · '}
                  {f.hasResult ? `${f.modelLabel} · ` : ''}
                  {euros(f.aiCost)}
                  {' · '}
                  {dateFr(f.updatedAt)}
                </span>
              </div>
              <button className="reports-icon" onClick={() => setEditing(f.id)} aria-label={`Modifier ${f.name}`} title="Modifier">
                <PencilIcon />
              </button>
              <button className="reports-icon reports-icon-danger" onClick={() => remove(f)} aria-label={`Supprimer ${f.name}`} title="Supprimer">
                <TrashIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function StateBadge({ state }) {
  return <span className={`reports-badge reports-badge-${state}`}>{STATE_LABELS[state]}</span>
}

function PencilIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
    </svg>
  )
}

// Panneau d'un previsionnel : creation (forecastId null) ou modification.
function ForecastPanel({ forecastId, season, seasonsData, options, onClose, onCreated }) {
  const [forecast, setForecast] = useState(null)
  const [form, setForm] = useState({
    name: `Prévision ${season.name}`,
    state: 'brouillon',
    startDate: '',
    prompt: '',
    model: options.defaultModel,
  })
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('explain')
  // Position des curseurs a l'ecran (enregistree apres SLIDER_DELAY_MS).
  const [params, setParams] = useState({})
  const [replaying, setReplaying] = useState(false)
  const timer = useRef(null)

  const load = useCallback(async () => {
    const data = await callApi(`/forecasts/${forecastId}`)
    setForecast(data)
    return data
  }, [forecastId])

  useEffect(() => {
    if (forecastId == null) return
    load()
      .then((data) => {
        setForm({ name: data.name, state: data.state, startDate: data.startDate ?? '', prompt: data.prompt, model: data.model })
        setParams(data.params)
      })
      .catch((err) => setError(err.message))
  }, [forecastId, load])

  // Calcul en cours : relu jusqu'a la fin.
  const running = forecast?.status === 'running'
  useEffect(() => {
    if (!running) return undefined
    const poll = setInterval(() => {
      load()
        .then((data) => {
          if (data.status === 'error') showToast(data.error, 'warning')
          else if (data.status === 'idle') {
            setParams(data.params)
            showToast('Prévisionnel calculé')
          }
        })
        .catch(() => {
          // Coupure passagere : on reessaie au prochain tour.
        })
    }, POLL_MS)
    return () => clearInterval(poll)
  }, [running, load])

  useEffect(() => () => clearTimeout(timer.current), [])

  function update(key) {
    return (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  async function save() {
    if (forecastId == null) {
      const created = await sendJson('/forecasts', 'POST', { ...form, seasonId: season.id })
      return created.id
    }
    setForecast(await sendJson(`/forecasts/${forecastId}`, 'PUT', form))
    return forecastId
  }

  async function submit(run) {
    setPending(true)
    setError(null)
    try {
      const id = await save()
      if (run) {
        const started = await sendJson(`/forecasts/${id}/run`, 'POST', form)
        if (forecastId == null) {
          onCreated(id)
          return
        }
        setForecast(started)
      } else if (forecastId == null) {
        onCreated(id)
        return
      } else {
        showToast('Prévisionnel enregistré')
      }
    } catch (err) {
      setError(err.message)
    }
    setPending(false)
  }

  // Un curseur bouge : la valeur s'affiche tout de suite, la formule est
  // rejouee (et la position enregistree) une fois le curseur immobile.
  function slide(name, value) {
    const next = { ...params, [name]: value }
    setParams(next)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => replay(next), SLIDER_DELAY_MS)
  }

  async function replay(next) {
    setReplaying(true)
    try {
      setForecast(await sendJson(`/forecasts/${forecastId}/params`, 'PUT', { params: next }))
    } catch (err) {
      showToast(err.message, 'warning')
    }
    setReplaying(false)
  }

  function resetParams() {
    const defaults = Object.fromEntries(forecast.result.parameters.map((p) => [p.name, p.default]))
    setParams(defaults)
    clearTimeout(timer.current)
    replay(defaults)
  }

  async function download(format) {
    try {
      const response = await fetch(`${API_URL}/forecasts/${forecastId}/download?format=${format}`, { credentials: 'include' })
      if (!response.ok) throw new Error(`Téléchargement impossible (${response.status})`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = `previsionnel-${season.name}-${form.name}.${format}`.replace(/[\\/:*?"<>|]/g, '-')
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      showToast(err.message, 'warning')
    }
  }

  const result = forecast?.result
  const modelLabel = (id) => options.models.find((m) => m.id === id)?.label ?? id
  const ended = seasonsData.today > season.endDate

  return (
    <section className="reports">
      <div className="reports-panel-header">
        <button onClick={onClose} aria-label="Retour aux prévisionnels">
          ← <span className="seasons-wide-only">Prévisionnels de {season.name}</span>
        </button>
        <h2>{forecastId == null ? 'Nouveau prévisionnel' : 'Modifier le prévisionnel'}</h2>
      </div>

      <div className="trial-form-grid reports-form">
        <label className="reports-form-name">
          Nom
          <input value={form.name} onChange={update('name')} autoComplete="off" />
        </label>
        <label>
          Saison
          <input value={season.name} readOnly />
        </label>
        <label>
          Date de départ
          <input type="date" value={form.startDate} min={season.startDate} max={season.endDate} onChange={update('startDate')} />
          <span className="reports-hint">
            {form.startDate
              ? 'Le réel après cette date s’affiche pour comparer.'
              : ended
                ? 'Saison terminée : choisissez une date pour tester.'
                : 'Vide : dernier jour connu des comptes.'}
          </span>
        </label>
        <label>
          État
          <select value={form.state} onChange={update('state')}>
            {options.states.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="trial-form-wide">
          Prompt donné à l'IA
          <textarea
            rows={5}
            value={form.prompt}
            onChange={update('prompt')}
            placeholder="Ex : prévois le solde jusqu'à fin juin. Paramètres : nouveaux adhérents d'ici mars (0 à 20, défaut 5), salaire mensuel (400 à 800 €, défaut 580)…"
          />
          <span className="reports-hint">
            S'ajoute aux consignes fixes : l'IA écrit une formule Python prevoir(donnees, p) qui donne le solde (courant + Livret
            Bleu) chaque semaine jusqu'à la fin de la saison, et déclare les paramètres nommés dans le prompt (libellé, min, max,
            défaut). L'appli lui prépare les données : solde réel à la date de départ, moyennes mensuelles par catégorie des 12
            derniers mois, adhérents et échéances HelloAsso à venir.
          </span>
        </label>
        <label>
          Modèle
          <select value={form.model} onChange={update('model')}>
            {options.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <div className="reports-cost">
          <span>Coût IA cumulé</span>
          <b>{euros(forecast?.aiCost ?? 0)}</b>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {forecast?.status === 'error' && <p className="error">{forecast.error}</p>}

      <div className="reports-actions">
        <button onClick={() => submit(false)} disabled={pending || running}>
          Enregistrer
        </button>
        <button className="reports-run" onClick={() => submit(true)} disabled={pending || running || !form.name.trim()}>
          {running ? 'Calcul en cours…' : 'Exécuter le calcul'}
        </button>
      </div>

      <div className="reports-result">
        <div className="reports-result-header">
          <h3>Résultat</h3>
          {result && (
            <span className="reports-result-meta">
              {result.modelLabel} · {euros(result.cost)} · {dateFr(result.generatedAt)}
            </span>
          )}
          <div className="reports-downloads">
            <button onClick={() => download('png')} disabled={!result || running}>
              Image
            </button>
            <button onClick={() => download('pdf')} disabled={!result || running}>
              PDF
            </button>
          </div>
        </div>

        {running ? (
          <div className="reports-running">
            <div className="reports-progress" />
            <p>{modelLabel(forecast.model)} écrit la formule, puis l'appli la vérifie et la teste… (jusqu'à quelques minutes)</p>
          </div>
        ) : !result ? (
          <p className="reports-placeholder">Pas encore de formule : lancez « Exécuter le calcul ».</p>
        ) : (
          <>
            <div className="filter-chips" role="group" aria-label="Résultat">
              {[
                ['explain', 'Explication'],
                ['code', 'Formule Python'],
              ].map(([id, label]) => (
                <button key={id} className={id === tab ? 'filter-chip filter-chip-active' : 'filter-chip'} aria-pressed={id === tab} onClick={() => setTab(id)}>
                  {label}
                </button>
              ))}
            </div>
            <div className="reports-check">
              <b>Formule vérifiée</b> : une seule fonction prevoir, aucun import hors math et datetime, ni fichier ni réseau ;
              exécutée à part par l'appli. Départ le {dateFr(result.data.dateDepart)} avec {euros(result.data.soldeDepart)} (courant +
              Livret Bleu){result.data.adherents ? '' : ', sans les données HelloAsso'}.
            </div>
            {tab === 'explain' ? <p className="forecasts-explanation">{result.explanation}</p> : <pre className="forecasts-code">{result.code}</pre>}
          </>
        )}
      </div>

      {result && !running && (
        <>
          <div className="reports-result">
            <div className="reports-result-header">
              <h3>Paramètres</h3>
              <span className="reports-result-meta">{replaying ? 'recalcul…' : 'position enregistrée automatiquement'}</span>
              <div className="reports-downloads">
                <button onClick={resetParams}>Revenir aux défauts</button>
              </div>
            </div>
            {result.parameters.length === 0 ? (
              <p className="reports-placeholder">Cette formule n'a pas de paramètre réglable.</p>
            ) : (
              <div className="forecasts-params">
                {result.parameters.map((p) => {
                  const value = params[p.name] ?? p.default
                  return (
                    <label key={p.name} className="forecasts-param">
                      <span className="forecasts-param-head">
                        <span>{p.label}</span>
                        <b>{paramLabel(p, value)}</b>
                      </span>
                      <input type="range" min={p.min} max={p.max} step={p.step} value={value} onChange={(e) => slide(p.name, Number(e.target.value))} />
                      <span className="forecasts-param-bounds">
                        <span>{paramLabel(p, p.min)}</span>
                        <span>défaut {paramLabel(p, p.default)}</span>
                        <span>{paramLabel(p, p.max)}</span>
                      </span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>
          <ForecastResult result={result} season={season} seasonsData={seasonsData} />
        </>
      )}
    </section>
  )
}

// Solde total de la courbe des saisons en fin de journee t.
function valueAt(series, t) {
  let value = null
  for (const p of series) {
    if (p.t > t) break
    value = p.v
  }
  return value
}

// Points (t, v) du solde reel de from a to, en escalier ; le dernier point
// prolonge le solde jusqu'a `to`.
function realPoints(series, from, to) {
  const points = []
  const initial = valueAt(series, from - DAY_MS)
  if (initial != null) points.push({ t: from, v: initial })
  for (const p of series) if (p.t >= from && p.t <= to) points.push(p)
  if (points.length) points.push({ t: to, v: points[points.length - 1].v })
  return points
}

// Chiffres cles et graphique : saisons superposees (comme "Compte détaillé"
// dans Saisons), reel puis prevision, autres saisons au choix.
function ForecastResult({ result, season, seasonsData }) {
  const seasons = seasonsData.seasons
  const others = seasons.filter((s) => s.id !== season.id && s.startDate < season.startDate)
  const previous = others[others.length - 1]
  // Saisons comparees (choix retenu sur cet appareil) ; par defaut la
  // precedente.
  const [compare, setCompare] = useState(() => readCompare() ?? new Set(previous ? [previous.id] : []))
  function toggle(id) {
    const next = new Set(compare)
    if (!next.delete(id)) next.add(id)
    setCompare(next)
    writeCompare(next)
  }

  const points = result.points
  const end = points[points.length - 1]
  const low = points.reduce((a, b) => (b.solde < a.solde ? b : a), points[0])
  const series = seasonsData.series.map((p) => ({ t: ts(p.date), v: p.total }))
  const start = ts(result.data.dateDepart)
  const lastKnown = series.length ? series[series.length - 1].t : start
  const afterStart = lastKnown > start ? realPoints(series, start, Math.min(lastKnown, ts(season.endDate))) : []
  const actualEnd = afterStart.length ? afterStart[afterStart.length - 1] : null
  const reference = previous?.balance.total

  return (
    <div className="reports-result">
      <div className="seasons-figures">
        <div className="seasons-figure">
          <span className="seasons-figure-label">Solde prévu au {dateFr(season.endDate)}</span>
          <span className="seasons-figure-value forecasts-end">{euros(end.solde)}</span>
          {reference != null && (
            <span className="seasons-figure-sub">
              {end.solde >= reference ? '+' : '−'}
              {eurosRound(Math.abs(end.solde - reference))} par rapport à la fin de {previous.name}
            </span>
          )}
        </div>
        <div className="seasons-figure">
          <span className="seasons-figure-label">Point le plus bas prévu</span>
          <span className="seasons-figure-value">{eurosRound(low.solde)}</span>
          <span className="seasons-figure-sub">vers le {dateFr(low.date)}</span>
        </div>
        <div className="seasons-figure">
          <span className="seasons-figure-label">Réel au départ</span>
          <span className="seasons-figure-value">{eurosRound(result.data.soldeDepart)}</span>
          <span className="seasons-figure-sub">le {dateFr(result.data.dateDepart)}</span>
        </div>
        <div className="seasons-figure">
          <span className="seasons-figure-label">{actualEnd ? 'Réel à comparer' : 'Fin de ' + (previous?.name ?? 'saison précédente')}</span>
          <span className="seasons-figure-value">{actualEnd ? eurosRound(actualEnd.v) : eurosRound(reference)}</span>
          <span className="seasons-figure-sub">{actualEnd ? `le ${dateFr(new Date(actualEnd.t).toISOString())}` : 'courant + Livret Bleu'}</span>
        </div>
      </div>
      <ForecastChart
        series={series}
        season={season}
        start={start}
        points={points}
        afterStart={afterStart}
        others={others}
        seasons={seasons}
        compare={compare}
        onToggle={toggle}
      />
      <p className="reports-hint">
        Saisons superposées du 1er juillet au 30 juin. Prévision : un point par semaine ; bouger un curseur la recalcule sans rappeler
        l'IA.
      </p>
    </div>
  )
}

function ForecastChart({ series, season, start, points, afterStart, others, seasons, compare, onToggle }) {
  const [ref, width] = useWidth()
  const narrow = width < 480
  const margin = { top: 22, right: 12, bottom: 28, left: narrow ? 46 : 66 }
  const innerW = width - margin.left - margin.right
  const innerH = CHART_HEIGHT - margin.top - margin.bottom
  const x0 = ts(season.startDate)
  const x1 = ts(season.endDate)
  const [pointerX, setPointerX] = useState(null)

  // Courbes, ramenees sur l'axe de la saison choisie (decalage en jours).
  const lines = [
    ...others
      .filter((s) => compare.has(s.id))
      .map((s) => {
        const offset = x0 - ts(s.startDate)
        return {
          key: `s${s.id}`,
          label: s.name,
          color: SEASON_COLORS[seasons.indexOf(s) % SEASON_COLORS.length],
          width: 1.6,
          step: true,
          points: realPoints(series, ts(s.startDate), ts(s.endDate)).map((p) => ({ t: p.t + offset, v: p.v })),
        }
      }),
    { key: 'after', label: 'réel après le départ', color: ACTUAL, width: 1.8, step: true, points: afterStart },
    { key: 'real', label: `${season.name} réalisé`, color: REAL, width: 2.6, step: true, points: realPoints(series, x0, start) },
    { key: 'forecast', label: 'prévision', color: FORECAST, width: 2.6, dashed: true, points: points.map((p) => ({ t: ts(p.date), v: p.solde })) },
  ].filter((l) => l.points.length > 0)

  const values = lines.flatMap((l) => l.points.map((p) => p.v))
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const pad = (rawMax - rawMin || Math.abs(rawMax) * 0.05 || 1) * 0.12
  const yMin = rawMin - pad
  const yMax = rawMax + pad
  const y = (v) => margin.top + (1 - (v - yMin) / (yMax - yMin)) * innerH
  const x = (t) => margin.left + ((t - x0) / (x1 - x0 || 1)) * innerW

  function path(line) {
    return line.points
      .map((p, i) => {
        const px = x(p.t).toFixed(1)
        if (i === 0) return `M${px},${y(p.v).toFixed(1)}`
        return line.step ? `H${px} V${y(p.v).toFixed(1)}` : `L${px},${y(p.v).toFixed(1)}`
      })
      .join(' ')
  }

  // Lecture sous le doigt : solde de chaque courbe a cette date.
  const fraction = pointerX == null ? null : Math.min(1, Math.max(0, (pointerX - margin.left) / innerW))
  const cursorT = fraction == null ? null : Math.round((x0 + fraction * (x1 - x0)) / DAY_MS) * DAY_MS
  const readout =
    cursorT == null
      ? []
      : lines.flatMap((line) => {
          const pts = line.points
          if (cursorT < pts[0].t || cursorT > pts[pts.length - 1].t) return []
          let v = pts[0].v
          for (let i = 0; i < pts.length; i++) {
            if (pts[i].t > cursorT) {
              if (!line.step && i > 0) {
                const a = pts[i - 1]
                const b = pts[i]
                v = a.v + ((b.v - a.v) * (cursorT - a.t)) / (b.t - a.t || 1)
              }
              break
            }
            v = pts[i].v
          }
          return [{ line, v }]
        })
  const cursorX = cursorT == null ? null : x(cursorT)
  const track = (e) => setPointerX(e.clientX - e.currentTarget.getBoundingClientRect().left)
  const xTicks = (narrow ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1]).map((f) => ({ x: margin.left + f * innerW, t: x0 + f * (x1 - x0) }))

  return (
    <div className="forecasts-chart-block">
      <div className="seasons-legend forecasts-legend">
        <span>
          <i style={{ background: REAL }} />
          réalisé
        </span>
        <span>
          <i className="forecasts-dash" />
          prévision
        </span>
        {afterStart.length > 0 && (
          <span>
            <i style={{ background: ACTUAL }} />
            réel après le départ
          </span>
        )}
        {others.map((s) => {
          const on = compare.has(s.id)
          return (
            <button
              key={s.id}
              type="button"
              className={on ? undefined : 'seasons-legend-off'}
              aria-pressed={on}
              title={on ? 'Masquer cette saison' : 'Comparer avec cette saison'}
              onClick={() => onToggle(s.id)}
            >
              <i style={{ background: SEASON_COLORS[seasons.indexOf(s) % SEASON_COLORS.length] }} />
              {s.name}
            </button>
          )
        })}
      </div>
      <div ref={ref} className="seasons-chart">
        <svg
          width={width}
          height={CHART_HEIGHT}
          role="img"
          aria-label="Solde réel et prévu de la saison"
          onPointerDown={track}
          onPointerMove={track}
          onPointerLeave={(e) => e.pointerType === 'mouse' && setPointerX(null)}
        >
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
              {monthShort.format(tick.t)}
            </text>
          ))}
          <line x1={x(start)} x2={x(start)} y1={margin.top} y2={margin.top + innerH} className="forecasts-start" />
          <text x={x(start)} y={margin.top - 8} textAnchor="middle" className="balance-chart-axis">
            départ
          </text>
          {lines.map((line) => (
            <path
              key={line.key}
              d={path(line)}
              fill="none"
              stroke={line.color}
              strokeWidth={line.width}
              strokeDasharray={line.dashed ? '7 5' : undefined}
              strokeLinejoin="round"
            />
          ))}
          {readout.length > 0 && <line x1={cursorX} x2={cursorX} y1={margin.top} y2={margin.top + innerH} className="balance-chart-cursor" />}
          {readout.map(({ line, v }) => (
            <circle key={line.key} cx={cursorX} cy={y(v)} r="4.5" fill={line.color} className="seasons-chart-dot" />
          ))}
        </svg>
        {readout.length > 0 && (
          <div
            className="balance-chart-tooltip seasons-tooltip"
            style={cursorX > width / 2 ? { top: margin.top, right: width - cursorX + 12 } : { top: margin.top, left: cursorX + 12 }}
          >
            <div className="seasons-tooltip-date">{dateFr(new Date(cursorT).toISOString())}</div>
            {readout.map(({ line, v }) => (
              <div key={line.key} className="seasons-tooltip-row">
                <b>{euros(v)}</b>
                <span>
                  <i style={{ background: line.color }} />
                  {line.label}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
