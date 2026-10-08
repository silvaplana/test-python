import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'
import { readSeasonChoice, writeSeasonChoice } from './seasonChoice.js'
import { AiSettings } from './AiSettings.jsx'

// Finances > Bilan financier : calculs de bilan d'une saison (voir
// backend/src/financialreports). Chaque calcul a un nom, un etat (brouillon,
// valide, officiel), un prompt et un modele d'IA ; "Produire le bilan financier par IA" fait
// calculer le compte d'exploitation par l'appli (au centime, avec la
// verification des soldes) et l'analyse par l'IA, en arriere-plan : l'ecran
// relit le bilan jusqu'a la fin du calcul.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const POLL_MS = 2000
const STATE_LABELS = { brouillon: 'Brouillon', valide: 'Validé', officiel: 'Officiel' }
const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']

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
const eurosRound = (n) => (n == null ? '—' : `${(Math.round(n) || 0).toLocaleString('fr-FR')} €`)
const amount = (n) => (n == null || Math.abs(n) < 0.005 ? '' : n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const aiCost = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`

function dateFr(iso) {
  const [year, month, day] = iso.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

// "2025-07" -> "juil.-25" (comme le modele du tresorier).
const monthLabel = (month) => `${MONTHS[Number(month.slice(5, 7)) - 1]}-${month.slice(2, 4)}`

// Lignes recettes ou depenses avec la saison precedente : montant net de la
// meme categorie, du meme cote (une depense est comptee en positif).
function comparison(result, side) {
  const previous = result.previous?.net ?? {}
  const sign = side === 'income' ? 1 : -1
  return result[side].map((row) => {
    const before = previous[row.category] == null ? null : sign * previous[row.category]
    const pct = before ? Math.round(((row.amount - before) / Math.abs(before)) * 100) : null
    // Couleur de l'ecart : bleu quand c'est une bonne nouvelle (plus de
    // recettes, moins de depenses), orange sinon ; neutre sous 5 %.
    const good = side === 'income' ? row.amount >= (before ?? 0) : row.amount <= (before ?? 0)
    const tone = pct === null || Math.abs(pct) < 5 ? '' : good ? 'reports-good' : 'reports-bad'
    return { ...row, previous: before, pct, tone }
  })
}

export function FinancialReports({ active }) {
  const [seasons, setSeasons] = useState(null)
  const [seasonId, setSeasonId] = useState(null)
  const [listing, setListing] = useState(null)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState(null)
  // Panneau de calcul ouvert : null, "new" ou l'id du bilan.
  const [editing, setEditing] = useState(null)
  // Lu au retour sur l'onglet (voir le chargement des saisons).
  const editingRef = useRef(null)
  editingRef.current = editing

  useEffect(() => {
    if (!active) return
    callApi('/seasons')
      .then((data) => {
        setSeasons(data.seasons)
        // Saison retenue (commune aux ecrans de Finances), sinon celle en
        // cours. Pas pendant qu'un calcul est ouvert : il garde sa saison.
        setSeasonId((id) =>
          editingRef.current !== null && id != null
            ? id
            : (readSeasonChoice(data.seasons) ?? id ?? (data.seasons.find((s) => s.current) ?? data.seasons[data.seasons.length - 1])?.id ?? null)
        )
      })
      .catch((err) => setError(err.message))
  }, [active])

  const loadReports = useCallback(async () => {
    if (seasonId == null) return
    try {
      setListing(await callApi(`/financial-reports?seasonId=${seasonId}`))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [seasonId])

  useEffect(() => {
    if (active) loadReports()
  }, [active, loadReports])

  if (error) return <p className="error">{error}</p>
  if (!seasons) return <p>Chargement…</p>
  if (seasons.length === 0)
    return (
      <section className="reports">
        <div className="seasons-empty">
          <p>Aucune saison pour l'instant : créez d'abord la saison dans l'onglet Saisons.</p>
        </div>
      </section>
    )

  const season = seasons.find((s) => s.id === seasonId)
  const reports = listing?.reports ?? []
  const shown = reports.filter((r) => filter === 'all' || r.state === filter)

  async function remove(report) {
    if (!window.confirm(`Supprimer le bilan « ${report.name} » ?\n\nSon prompt, son résultat et son coût IA sont effacés. Les opérations bancaires ne sont pas touchées.`)) return
    try {
      await callApi(`/financial-reports/${report.id}`, { method: 'DELETE' })
      showToast(`Bilan « ${report.name} » supprimé`)
      loadReports()
    } catch (err) {
      showToast(`Suppression impossible : ${err.message}`, 'warning')
    }
  }

  if (editing !== null && listing)
    return (
      <ReportPanel
        key={editing}
        reportId={editing === 'new' ? null : editing}
        season={season}
        options={listing}
        onClose={() => {
          setEditing(null)
          loadReports()
        }}
        onCreated={(id) => setEditing(id)}
      />
    )

  return (
    <section className="reports">
      <div className="seasons-toolbar">
        <select
          aria-label="Saison"
          value={seasonId ?? ''}
          onChange={(e) => {
            setSeasonId(Number(e.target.value))
            writeSeasonChoice(Number(e.target.value))
          }}
        >
          {[...seasons].reverse().map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.current ? ' (en cours)' : ''}
              {/* Nombre de calculs de la saison (connu une fois la liste chargee). */}
              {listing?.counts && ` : ${listing.counts[s.id] ?? 0}`}
            </option>
          ))}
        </select>
        <button className="seasons-primary" onClick={() => setEditing('new')} disabled={!listing} aria-label="Nouveau calcul">
          +<span className="seasons-wide-only"> Nouveau calcul</span>
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
            {state === 'all' ? 'Tous' : STATE_LABELS[state]} ({reports.filter((r) => state === 'all' || r.state === state).length})
          </button>
        ))}
      </div>

      {!listing ? (
        <p>Chargement…</p>
      ) : shown.length === 0 ? (
        <div className="seasons-empty">
          <p>{reports.length === 0 ? `Aucun bilan pour ${season?.name} : lancez un nouveau calcul.` : 'Aucun bilan dans cet état.'}</p>
        </div>
      ) : (
        <ul className="reports-list">
          {shown.map((r) => (
            // Toute la carte ouvre le calcul, comme le crayon.
            <li key={r.id} className="reports-item-open" onClick={() => setEditing(r.id)}>
              <div className="reports-item-main">
                <span className="reports-item-name">{r.name}</span>
                <span className="reports-item-meta">
                  <StateBadge state={r.state} />
                  {r.status === 'running' ? 'calcul en cours…' : r.status === 'error' ? 'dernier calcul en erreur' : r.hasResult ? r.modelLabel : 'pas encore calculé'}
                  {' · '}
                  {aiCost(r.aiCost)}
                  {' · '}
                  {dateFr(r.updatedAt)}
                </span>
              </div>
              <button
                className="reports-icon reports-icon-danger"
                onClick={(e) => {
                  // Ne pas ouvrir la carte en meme temps.
                  e.stopPropagation()
                  remove(r)
                }}
                aria-label={`Supprimer ${r.name}`}
                title="Supprimer"
              >
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

function TrashIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
    </svg>
  )
}

// Panneau d'un calcul : creation (reportId null) ou modification.
function ReportPanel({ reportId, season, options, onClose, onCreated }) {
  const [report, setReport] = useState(null)
  // Zone "Réglages de l'IA" depliee : retenu en base, par calcul.
  const [settingsOpen, setSettingsOpen] = useState(true)
  const [form, setForm] = useState({ name: `Bilan ${season.name}`, state: 'brouillon', prompt: '', model: options.defaultModel })
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const [view, setView] = useState('category')

  const load = useCallback(async () => {
    const data = await callApi(`/financial-reports/${reportId}`)
    setReport(data)
    setSettingsOpen(data.settingsOpen ?? true)
    return data
  }, [reportId])

  useEffect(() => {
    if (reportId == null) return
    load()
      .then((data) => setForm({ name: data.name, state: data.state, prompt: data.prompt, model: data.model }))
      .catch((err) => setError(err.message))
  }, [reportId, load])

  // Calcul en cours : relu jusqu'a la fin.
  const running = report?.status === 'running'
  useEffect(() => {
    if (!running) return undefined
    const timer = setInterval(() => {
      load()
        .then((data) => {
          if (data.status === 'error') showToast(data.error, 'warning')
          else if (data.status === 'idle') showToast('Bilan calculé')
        })
        .catch(() => {
          // Coupure passagere : on reessaie au prochain tour.
        })
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [running, load])

  // Plie ou deplie les reglages de l'IA, et le retient pour ce calcul.
  function toggleSettings() {
    const open = !settingsOpen
    setSettingsOpen(open)
    if (reportId != null)
      sendJson(`/financial-reports/${reportId}/settings`, 'PUT', { open }).catch(() => {
        // Non retenu (reseau...) : sans consequence pour l'affichage en cours.
      })
  }

  // Prompts enregistres de ce bilan (disquette) ; celui qui correspond au
  // texte en cours, s'il y en a un.
  // Menu ouvert d'un clic sur "Prompt donné à l'IA" ; ferme d'un clic ailleurs.
  const [promptMenuOpen, setPromptMenuOpen] = useState(false)
  const promptMenuRef = useRef(null)
  useEffect(() => {
    if (!promptMenuOpen) return
    function close(event) {
      if (event.type === 'keydown' ? event.key === 'Escape' : !promptMenuRef.current?.contains(event.target)) {
        setPromptMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [promptMenuOpen])
  const savedPrompts = report?.savedPrompts ?? []
  const selectedPrompt = savedPrompts.find((p) => p.prompt === form.prompt.trim())

  async function savePrompt() {
    try {
      const body = await sendJson(`/financial-reports/${reportId}/prompts`, 'POST', { prompt: form.prompt })
      setReport((current) => ({ ...current, savedPrompts: body.savedPrompts }))
      showToast('Prompt enregistré pour ce bilan', 'success')
    } catch (err) {
      setError(err.message)
    }
  }

  function choosePrompt(saved) {
    const known = !form.prompt.trim() || savedPrompts.some((p) => p.prompt === form.prompt.trim())
    if (!known && !window.confirm('Remplacer le prompt actuel par ce prompt enregistré ?')) return
    setForm((current) => ({ ...current, prompt: saved.prompt }))
    setPromptMenuOpen(false)
  }

  async function deletePrompt(saved) {
    if (!window.confirm('Retirer ce prompt des prompts enregistrés de ce bilan ?')) return
    try {
      const body = await callApi(`/financial-reports/${reportId}/prompts/${saved.id}`, { method: 'DELETE' })
      setReport((current) => ({ ...current, savedPrompts: body.savedPrompts }))
    } catch (err) {
      setError(err.message)
    }
  }

  function update(key) {
    return (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  // Cree le bilan s'il est nouveau, sinon enregistre ses champs ; retourne son id.
  async function save() {
    if (reportId == null) {
      const created = await sendJson('/financial-reports', 'POST', { ...form, seasonId: season.id })
      return created.id
    }
    setReport(await sendJson(`/financial-reports/${reportId}`, 'PUT', form))
    return reportId
  }

  async function submit(run) {
    setPending(true)
    setError(null)
    try {
      const id = await save()
      if (run) {
        const started = await sendJson(`/financial-reports/${id}/run`, 'POST', { prompt: form.prompt, model: form.model })
        if (reportId == null) {
          onCreated(id)
          return
        }
        setReport(started)
      } else if (reportId == null) {
        onCreated(id)
        return
      } else {
        showToast('Bilan enregistré')
      }
    } catch (err) {
      setError(err.message)
    }
    setPending(false)
  }

  async function download(format) {
    try {
      const response = await fetch(`${API_URL}/financial-reports/${reportId}/download?format=${format}`, { credentials: 'include' })
      if (!response.ok) throw new Error(`Téléchargement impossible (${response.status})`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = `bilan-${season.name}-${form.name}.${format}`.replace(/[\\/:*?"<>|]/g, '-')
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      showToast(err.message, 'warning')
    }
  }

  const result = report?.result
  const modelLabel = (id) => options.models.find((m) => m.id === id)?.label ?? id

  return (
    <section className="reports">
      <div className="reports-panel-header">
        <button onClick={onClose} aria-label="Retour aux calculs">
          ← <span className="seasons-wide-only">Calculs de {season.name}</span>
        </button>
        <h2>{reportId == null ? 'Nouveau calcul' : 'Modifier le calcul'}</h2>
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
          État
          <select value={form.state} onChange={update('state')}>
            {options.states.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <AiSettings
          open={settingsOpen}
          onToggle={toggleSettings}
          summary={`${options.models.find((m) => m.id === form.model)?.label ?? form.model} · ${aiCost(report?.aiCost ?? 0)}`}
        >
        <div className="trial-form-wide reports-prompt-field">
          <div className="reports-prompt-title" ref={promptMenuRef}>
            {/* Clic sur le titre : menu des prompts enregistres de ce bilan. */}
            <button
              type="button"
              className="reports-prompt-menu-button"
              aria-haspopup="menu"
              aria-expanded={promptMenuOpen}
              onClick={() => setPromptMenuOpen((open) => !open)}
              title="Prompts enregistrés de ce bilan"
            >
              Prompt donné à l'IA <span aria-hidden="true">▾</span>
            </button>
            <button
              type="button"
              className="reports-prompt-button"
              onClick={savePrompt}
              disabled={!reportId || !form.prompt.trim() || Boolean(selectedPrompt)}
              title={
                !reportId
                  ? 'Crée d\u2019abord le calcul pour enregistrer son prompt'
                  : selectedPrompt
                    ? 'Ce prompt est déjà enregistré'
                    : 'Enregistrer ce prompt dans les prompts de ce bilan'
              }
              aria-label="Enregistrer ce prompt dans les prompts de ce bilan"
            >
              <SaveIcon />
            </button>
            {promptMenuOpen && (
              <div className="reports-prompt-menu" role="menu">
                {savedPrompts.length === 0 && (
                  <p className="reports-prompt-menu-empty">
                    Aucun prompt enregistré pour ce bilan. La disquette enregistre le prompt en cours.
                  </p>
                )}
                {savedPrompts.map((p) => (
                  <div key={p.id} className={`reports-prompt-menu-item${p.id === selectedPrompt?.id ? ' reports-prompt-menu-current' : ''}`}>
                    <SavedPrompt prompt={p.prompt} onChoose={() => choosePrompt(p)} />
                    <button
                      type="button"
                      className="reports-prompt-button reports-prompt-delete"
                      onClick={() => deletePrompt(p)}
                      title="Retirer ce prompt des prompts enregistrés"
                      aria-label="Retirer ce prompt des prompts enregistrés"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <textarea
            rows={4}
            value={form.prompt}
            onChange={update('prompt')}
            placeholder="Ex : mets en avant la hausse des cotisations, ton simple pour l'AG."
          />
          <span className="reports-hint">
            S'ajoute aux consignes fixes : l'appli calcule le tableau au centime, l'IA classe les opérations « Autres » et écrit
            l'analyse en 5 lignes (faits marquants, comparaison avec les saisons précédentes).
          </span>
        </div>
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
          <b>{aiCost(report?.aiCost ?? 0)}</b>
        </div>
        </AiSettings>
      </div>

      {error && <p className="error">{error}</p>}
      {report?.status === 'error' && <p className="error">{report.error}</p>}

      <div className="reports-actions">
        <button onClick={() => submit(false)} disabled={pending || running}>
          Enregistrer
        </button>
        <button className="reports-run" onClick={() => submit(true)} disabled={pending || running || !form.name.trim()}>
          {running ? 'Production en cours…' : 'Produire le bilan financier par IA'}
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
            <button onClick={() => download('xlsx')} disabled={!result || running}>
              Télécharger Excel
            </button>
            <button onClick={() => download('pdf')} disabled={!result || running}>
              Télécharger PDF
            </button>
          </div>
        </div>

        {running ? (
          <div className="reports-running">
            <div className="reports-progress" />
            <p>
              {modelLabel(report.model)} rédige le bilan… (jusqu'à quelques minutes)
            </p>
          </div>
        ) : !result ? (
          <p className="reports-placeholder">Pas encore de résultat : lancez « Produire le bilan financier par IA ».</p>
        ) : (
          <ReportResult result={result} view={view} onView={setView} />
        )}
      </div>
    </section>
  )
}

function ReportResult({ result, view, onView }) {
  const v = result.verification
  const unfinished = result.cutoff < result.end
  const known = result.opening != null && result.closing != null
  return (
    <>
      <p className="reports-period">
        Du {dateFr(result.start)} au {dateFr(result.cutoff)}
        {unfinished ? ' (saison en cours, arrêtée au dernier jour connu des comptes)' : ''}. Virements entre courant et Livret
        Bleu exclus.
      </p>

      <div className={known && v.ok ? 'reports-check' : 'reports-check reports-check-alert'}>
        {known ? (
          <>
            <b>{v.ok ? 'Vérifié' : `Écart de ${euros(v.gap)}`}</b> : {euros(result.opening)} au {dateFr(result.start)} + recettes{' '}
            {euros(result.totalIncome)} − dépenses {euros(result.totalExpense)} = {euros(v.expected)}
            {v.ok ? ', égal au' : ', au lieu du'} solde réel au {dateFr(result.cutoff)} (courant + Livret Bleu) : {euros(v.actual)}.
          </>
        ) : (
          <>Vérification impossible : soldes inconnus sur cette période (relevés manquants).</>
        )}
        {result.issues?.length > 0 && <span className="reports-issues">{result.issues.join(' ')}</span>}
      </div>

      <div className="seasons-figures">
        <Figure label="Recettes" value={eurosRound(result.totalIncome)} sub={result.previous && `${result.previous.season} : ${eurosRound(result.previous.totalIncome)}`} />
        <Figure label="Dépenses" value={eurosRound(result.totalExpense)} sub={result.previous && `${result.previous.season} : ${eurosRound(result.previous.totalExpense)}`} />
        <Figure
          label={result.result >= 0 ? 'Excédent' : 'Déficit'}
          value={`${result.result >= 0 ? '+' : '−'}${eurosRound(Math.abs(result.result))}`}
          tone={result.result >= 0 ? 'reports-good' : 'reports-bad'}
          sub={result.previous && `${result.previous.season} : ${result.previous.result >= 0 ? '+' : '−'}${eurosRound(Math.abs(result.previous.result))}`}
        />
        <Figure label="Solde fin (courant + Bleu)" value={eurosRound(result.closing)} sub={`début ${eurosRound(result.opening)}`} />
      </div>

      <h4 className="reports-subtitle">Analyse</h4>
      <ol className="reports-analysis">
        {result.analysis.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ol>

      <div className="filter-chips" role="group" aria-label="Présentation du tableau">
        {[
          ['category', 'Par catégorie'],
          ['month', 'Par mois'],
        ].map(([id, label]) => (
          <button key={id} className={id === view ? 'filter-chip filter-chip-active' : 'filter-chip'} aria-pressed={id === view} onClick={() => onView(id)}>
            {label}
          </button>
        ))}
      </div>

      {view === 'category' ? <CategoryTables result={result} /> : <MonthTable result={result} />}
    </>
  )
}

function Figure({ label, value, sub, tone = '' }) {
  return (
    <div className="seasons-figure">
      <span className="seasons-figure-label">{label}</span>
      <span className={`seasons-figure-value ${tone}`}>{value}</span>
      {sub && <span className="seasons-figure-sub">{sub}</span>}
    </div>
  )
}

function CategoryTables({ result }) {
  const classified = new Set(Object.values(result.classifications ?? {}))
  const previousName = result.previous?.season
  return (
    <div className="reports-categories">
      {[
        ['income', 'Recettes', result.totalIncome],
        ['expense', 'Dépenses', result.totalExpense],
      ].map(([side, title, total]) => (
        <table key={side} className="reports-table">
          <thead>
            <tr>
              <th>{title}</th>
              <th>{result.seasonName}</th>
              {previousName && <th className="reports-wide-col">{previousName}</th>}
              {previousName && <th>Écart</th>}
            </tr>
          </thead>
          <tbody>
            {comparison(result, side).map((row) => (
              <tr key={row.category}>
                <td>
                  {row.category}
                  {classified.has(row.category) && <span className="reports-ai-badge">classé par l'IA</span>}
                  {previousName && <span className="reports-narrow-prev">{previousName} : {eurosRound(row.previous)}</span>}
                </td>
                <td>{eurosRound(row.amount)}</td>
                {previousName && <td className="reports-wide-col">{eurosRound(row.previous)}</td>}
                {previousName && <td className={row.tone}>{row.pct === null ? 'nouveau' : `${row.pct > 0 ? '+' : ''}${row.pct} %`}</td>}
              </tr>
            ))}
            <tr className="reports-total">
              <td>Total</td>
              <td>{eurosRound(total)}</td>
              {previousName && <td className="reports-wide-col">{eurosRound(side === 'income' ? result.previous.totalIncome : result.previous.totalExpense)}</td>}
              {previousName && <td />}
            </tr>
          </tbody>
        </table>
      ))}
    </div>
  )
}

function MonthTable({ result }) {
  const categories = result.categories
  const totals = categories.map((c) => result.months.reduce((sum, m) => sum + (m.amounts[c] ?? 0), 0))
  return (
    <>
      <p className="reports-month-title">Compte d'exploitation {result.seasonName}, établi suivant les relevés de banque</p>
      <div className="reports-scroll">
        <table className="reports-table reports-month-table">
          <thead>
            <tr>
              <th>Mois</th>
              <th>Solde au 1er</th>
              {categories.map((c) => (
                <th key={c}>{c}</th>
              ))}
              <th>Solde fin de mois</th>
            </tr>
          </thead>
          <tbody>
            {result.months.map((m) => (
              <tr key={m.month}>
                <td>{monthLabel(m.month)}</td>
                <td>{amount(m.opening)}</td>
                {categories.map((c) => (
                  <td key={c}>{amount(m.amounts[c])}</td>
                ))}
                <td>{amount(m.closing)}</td>
              </tr>
            ))}
            <tr className="reports-total">
              <td>Vérif</td>
              <td>{amount(result.opening)}</td>
              {totals.map((t, i) => (
                <td key={categories[i]}>{amount(t)}</td>
              ))}
              <td>{amount(result.verification.expected)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  )
}

// Prompt enregistre dans le menu : cliquer dessus l'utilise. Trop long pour
// tenir (plus de PROMPT_PREVIEW_PX de haut) : coupe, avec une poignee dans le
// coin en bas a droite a tirer (souris ou doigt) pour en voir plus -- pas de
// barre de defilement.
const PROMPT_PREVIEW_PX = 84

function SavedPrompt({ prompt, onChoose }) {
  const box = useRef(null)
  const drag = useRef(null)
  const [full, setFull] = useState(null)
  const [height, setHeight] = useState(PROMPT_PREVIEW_PX)

  // Hauteur du texte entier, mesuree une fois affiche.
  useEffect(() => {
    setFull(box.current.scrollHeight)
  }, [prompt])

  const long = full != null && full > PROMPT_PREVIEW_PX + 4

  function startDrag(event) {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { y: event.clientY, height: box.current.clientHeight }
  }

  function moveDrag(event) {
    if (!drag.current) return
    const next = drag.current.height + event.clientY - drag.current.y
    setHeight(Math.min(full, Math.max(48, next)))
  }

  return (
    <div className="reports-prompt-menu-text">
      <div ref={box} className="reports-prompt-menu-clip" style={long ? { height: Math.min(height, full) } : undefined}>
        <button type="button" role="menuitem" className="reports-prompt-menu-choice" onClick={onChoose} title="Utiliser ce prompt">
          {prompt}
        </button>
      </div>
      {long && (
        <span
          className="reports-prompt-menu-handle"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Tirer pour voir plus ou moins du prompt"
          title="Tirer pour voir plus ou moins du prompt"
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M11 4 4 11M11 8l-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
          </svg>
        </span>
      )}
    </div>
  )
}

// Disquette (enregistrer) et corbeille : traits Lucide (licence ISC).
function SaveIcon() {
  return (
    <svg className="reports-prompt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
      <path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" />
      <path d="M7 3v4a1 1 0 0 0 1 1h7" />
    </svg>
  )
}
