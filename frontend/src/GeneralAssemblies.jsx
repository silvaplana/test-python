import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'

// Finances > Assemblées générales : base du PowerPoint de l'AG d'une saison
// (voir backend/src/generalassemblies). Meme ecran que Bilan financier
// (liste des calculs par saison, etats, panneau prompt / modele / cout) ;
// chaque calcul garde 3 PPT (voir KINDS) : le modele choisi (fichier de
// l'ordinateur ou PPT d'un autre calcul), celui produit par l'IA et celui
// modifie par le tresorier. "Produire le PPT par IA" fait ecrire les diapos du
// tresorier par l'IA a partir du bilan de la saison, en arriere-plan :
// l'ecran relit le calcul jusqu'a la fin.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const POLL_MS = 2000
const STATE_LABELS = { brouillon: 'Brouillon', valide: 'Validé', officiel: 'Officiel' }
// Les 3 PPT d'un calcul (voir backend generalassemblies.py), dans l'ordre
// d'affichage.
const KINDS = [
  { id: 'modele', label: 'PPT modèle' },
  { id: 'genere', label: 'PPT produit par IA' },
  { id: 'modifie', label: 'PPT modifié' },
]

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

function sendFile(path, file) {
  const body = new FormData()
  body.append('file', file)
  return callApi(path, { method: 'POST', body })
}

const aiCost = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`

function dateFr(iso) {
  const [year, month, day] = iso.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

function timeFr(iso) {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

// Bouton qui ouvre le choix d'un fichier .pptx.
function PptxButton({ label, onFile, disabled, className }) {
  const input = useRef(null)
  return (
    <>
      <button className={className} onClick={() => input.current.click()} disabled={disabled}>
        {label}
      </button>
      <input
        ref={input}
        type="file"
        accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
        hidden
        onChange={(e) => {
          const file = e.target.files[0]
          e.target.value = ''
          if (file) onFile(file)
        }}
      />
    </>
  )
}

export function GeneralAssemblies({ active }) {
  const [seasons, setSeasons] = useState(null)
  const [seasonId, setSeasonId] = useState(null)
  const [listing, setListing] = useState(null)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState(null)
  // Panneau de calcul ouvert : null, "new" ou l'id du calcul.
  const [editing, setEditing] = useState(null)

  useEffect(() => {
    if (!active) return
    callApi('/seasons')
      .then((data) => {
        setSeasons(data.seasons)
        setSeasonId((id) => id ?? (data.seasons.find((s) => s.current) ?? data.seasons[data.seasons.length - 1])?.id ?? null)
      })
      .catch((err) => setError(err.message))
  }, [active])

  const load = useCallback(async () => {
    if (seasonId == null) return
    try {
      setListing(await callApi(`/general-assemblies?seasonId=${seasonId}`))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [seasonId])

  useEffect(() => {
    if (active) load()
  }, [active, load])

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
  const assemblies = listing?.assemblies ?? []
  const shown = assemblies.filter((a) => filter === 'all' || a.state === filter)

  async function remove(assembly) {
    if (!window.confirm(`Supprimer « ${assembly.name} » ?\n\nSes PPT, son prompt et son coût IA sont effacés. Le bilan financier n'est pas touché.`)) return
    try {
      await callApi(`/general-assemblies/${assembly.id}`, { method: 'DELETE' })
      showToast(`« ${assembly.name} » supprimé`)
      load()
    } catch (err) {
      showToast(`Suppression impossible : ${err.message}`, 'warning')
    }
  }

  async function uploadTemplate(file) {
    try {
      await sendFile('/general-assemblies/template', file)
      showToast('Modèle général enregistré')
      load()
    } catch (err) {
      showToast(err.message, 'warning')
    }
  }

  if (editing !== null && listing)
    return (
      <AssemblyPanel
        key={editing}
        assemblyId={editing === 'new' ? null : editing}
        season={season}
        options={listing}
        onClose={() => {
          setEditing(null)
          load()
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
            </option>
          ))}
        </select>
        <button className="seasons-primary" onClick={() => setEditing('new')} disabled={!listing} aria-label="Nouveau calcul">
          +<span className="seasons-wide-only"> Nouveau calcul</span>
        </button>
      </div>

      {listing && <Sources options={listing} onTemplate={uploadTemplate} />}

      <div className="filter-chips" role="group" aria-label="État">
        {['all', ...Object.keys(STATE_LABELS)].map((state) => (
          <button
            key={state}
            className={state === filter ? 'filter-chip filter-chip-active' : 'filter-chip'}
            aria-pressed={state === filter}
            onClick={() => setFilter(state)}
          >
            {state === 'all' ? 'Tous' : STATE_LABELS[state]} ({assemblies.filter((a) => state === 'all' || a.state === state).length})
          </button>
        ))}
      </div>

      {!listing ? (
        <p>Chargement…</p>
      ) : shown.length === 0 ? (
        <div className="seasons-empty">
          <p>{assemblies.length === 0 ? `Aucun PPT d'AG pour ${season?.name} : lancez un nouveau calcul.` : 'Aucun calcul dans cet état.'}</p>
        </div>
      ) : (
        <ul className="reports-list">
          {shown.map((a) => (
            <li key={a.id}>
              <div className="reports-item-main">
                <span className="reports-item-name">{a.name}</span>
                <span className="reports-item-meta">
                  <span className={`reports-badge reports-badge-${a.state}`}>{STATE_LABELS[a.state]}</span>
                  {a.status === 'running'
                    ? 'calcul en cours…'
                    : a.status === 'error'
                      ? 'dernier calcul en erreur'
                      : a.hasPpt
                        ? `PPT prêt · ${a.modelLabel}`
                        : 'pas encore calculé'}
                  {' · '}
                  {aiCost(a.aiCost)}
                  {' · '}
                  {dateFr(a.updatedAt)}
                </span>
              </div>
              <button className="reports-icon" onClick={() => setEditing(a.id)} aria-label={`Modifier ${a.name}`} title="Modifier">
                <PencilIcon />
              </button>
              <button className="reports-icon reports-icon-danger" onClick={() => remove(a)} aria-label={`Supprimer ${a.name}`} title="Supprimer">
                <TrashIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// Bilan et PPT modele que prendrait un calcul pour la saison choisie.
function Sources({ options, onTemplate }) {
  return (
    <div className={options.report ? 'ag-sources' : 'ag-sources ag-sources-alert'}>
      <span>
        Bilan utilisé :{' '}
        {options.report ? (
          <b>
            {options.report.name} ({STATE_LABELS[options.report.state].toLowerCase()})
          </b>
        ) : (
          <b>aucun bilan calculé pour cette saison, à faire d'abord dans Bilan financier</b>
        )}
      </span>
      <span>
        PPT modèle d'un calcul qui n'en a pas : <b>{options.template ? options.template.name : 'aucun'}</b>{' '}
        <PptxButton
          className="ag-link"
          label={options.templateUploaded ? 'Changer le modèle général' : 'Envoyer un modèle général'}
          onFile={onTemplate}
        />
      </span>
    </div>
  )
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

// Panneau d'un calcul : creation (assemblyId null) ou modification.
function AssemblyPanel({ assemblyId, season, options, onClose, onCreated }) {
  const [assembly, setAssembly] = useState(null)
  const [form, setForm] = useState({ name: `AG ${season.name}`, state: 'brouillon', prompt: '', model: options.defaultModel })
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  // PPT affiche dans le resultat : une sorte de KINDS (null : le plus abouti).
  const [kind, setKind] = useState(null)
  // PPT des autres calculs utilisables comme modele.
  const [sources, setSources] = useState([])

  const load = useCallback(async () => {
    const data = await callApi(`/general-assemblies/${assemblyId}`)
    setAssembly(data)
    return data
  }, [assemblyId])

  useEffect(() => {
    if (assemblyId == null) return
    load()
      .then((data) => setForm({ name: data.name, state: data.state, prompt: data.prompt, model: data.model }))
      .catch((err) => setError(err.message))
  }, [assemblyId, load])

  useEffect(() => {
    callApi(`/general-assemblies/model-sources${assemblyId == null ? '' : `?exclude=${assemblyId}`}`)
      .then(setSources)
      .catch(() => {
        // Liste indisponible : le modele peut toujours etre envoye en fichier.
      })
  }, [assemblyId])

  const running = assembly?.status === 'running'
  useEffect(() => {
    if (!running) return undefined
    const timer = setInterval(() => {
      load()
        .then((data) => {
          if (data.status === 'error') showToast(data.error, 'warning')
          else if (data.status === 'idle') {
            setKind('genere')
            showToast('PPT prêt')
          }
        })
        .catch(() => {
          // Coupure passagere : on reessaie au prochain tour.
        })
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [running, load])

  function update(key) {
    return (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  async function save() {
    if (assemblyId == null) {
      const created = await sendJson('/general-assemblies', 'POST', { ...form, seasonId: season.id })
      return created.id
    }
    setAssembly(await sendJson(`/general-assemblies/${assemblyId}`, 'PUT', form))
    return assemblyId
  }

  async function submit(run) {
    setPending(true)
    setError(null)
    try {
      const id = await save()
      if (run) {
        const started = await sendJson(`/general-assemblies/${id}/run`, 'POST', { prompt: form.prompt, model: form.model })
        if (assemblyId == null) {
          onCreated(id)
          return
        }
        setAssembly(started)
      } else if (assemblyId == null) {
        onCreated(id)
        return
      } else {
        showToast('Enregistré')
      }
    } catch (err) {
      setError(err.message)
    }
    setPending(false)
  }

  const files = assembly?.files ?? {}
  const shownKind = files[kind] ? kind : ['modifie', 'genere', 'modele'].find((k) => files[k])
  const shownFile = files[shownKind]

  async function download() {
    try {
      const response = await fetch(`${API_URL}/general-assemblies/${assemblyId}/download?kind=${shownKind}`, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`Téléchargement impossible (${response.status})`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = shownFile.filename.replace(/[\\/:*?"<>|]/g, '-')
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      showToast(err.message, 'warning')
    }
  }

  async function uploadModified(file) {
    try {
      setAssembly(await sendFile(`/general-assemblies/${assemblyId}/upload`, file))
      setKind('modifie')
      showToast('PPT modifié enregistré')
    } catch (err) {
      showToast(err.message, 'warning')
    }
  }

  // Choix du PPT modele : send(id) l'enregistre pour le calcul id. Un
  // nouveau calcul est d'abord cree (il lui faut un identifiant).
  async function chooseModel(send) {
    setPending(true)
    setError(null)
    try {
      const id = await save()
      const updated = await send(id)
      showToast('PPT modèle enregistré')
      if (assemblyId == null) {
        onCreated(id)
        return
      }
      setAssembly(updated)
      setKind('modele')
    } catch (err) {
      setError(err.message)
    }
    setPending(false)
  }

  const uploadModel = (file) => chooseModel((id) => sendFile(`/general-assemblies/${id}/model`, file))

  function copyModel(value) {
    const source = sources.find((x) => `${x.assemblyId}:${x.kind}` === value)
    if (source)
      chooseModel((id) => sendJson(`/general-assemblies/${id}/model`, 'PUT', { sourceId: source.assemblyId, kind: source.kind }))
  }

  const result = assembly?.result
  const modelLabel = (id) => options.models.find((m) => m.id === id)?.label ?? id

  return (
    <section className="reports">
      <div className="reports-panel-header">
        <button onClick={onClose} aria-label="Retour aux calculs">
          ← <span className="seasons-wide-only">Calculs de {season.name}</span>
        </button>
        <h2>{assemblyId == null ? 'Nouveau calcul' : 'Modifier le calcul'}</h2>
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
        <label className="trial-form-wide">
          Prompt donné à l'IA
          <textarea
            rows={4}
            value={form.prompt}
            onChange={update('prompt')}
            placeholder="Ex : la cotisation reste à 300 €, l'AG a lieu le 04/07, mets en avant la hausse des licenciés."
          />
          <span className="reports-hint">
            S'ajoute aux consignes fixes : partir du PPT modèle, garder sa mise en page, écrire les diapos du trésorier avec les
            chiffres du bilan, mettre les années à jour et marquer « À compléter » ce qui n'est pas connu.
          </span>
        </label>
        <div className="trial-form-wide ag-model">
          <span>PPT modèle</span>
          <b>
            {files.modele
              ? files.modele.filename
              : options.template
                ? `Pas encore choisi. Par défaut : ${options.template.name}`
                : "Aucun pour l'instant"}
          </b>
          {/* D'ou vient le modele (inconnu pour un PPT d'avant cette information). */}
          {files.modele?.source && <span className="ag-model-source">{files.modele.source}</span>}
          <div className="ag-model-actions">
            <PptxButton label="Choisir un fichier" onFile={uploadModel} disabled={pending || running || !form.name.trim()} />
            <select
              aria-label="Prendre le PPT d'un autre calcul"
              value=""
              onChange={(e) => copyModel(e.target.value)}
              disabled={pending || running || !form.name.trim() || sources.length === 0}
            >
              <option value="">{sources.length === 0 ? 'Aucun PPT dans les autres calculs' : "Prendre le PPT d'un autre calcul…"}</option>
              {sources.map((x) => (
                <option key={`${x.assemblyId}:${x.kind}`} value={`${x.assemblyId}:${x.kind}`}>
                  {x.label}
                </option>
              ))}
            </select>
          </div>
          <span className="reports-hint">
            L'exemple dont l'IA reprend la mise en page : un fichier de ton ordinateur, ou un PPT déjà enregistré dans un autre
            calcul. Il est copié dans ce calcul.
          </span>
        </div>
        <label>
          Modèle d'IA
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
          <b>{aiCost(assembly?.aiCost ?? 0)}</b>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {assembly?.status === 'error' && <p className="error">{assembly.error}</p>}

      <div className="reports-actions">
        <button onClick={() => submit(false)} disabled={pending || running}>
          Enregistrer
        </button>
        <button className="reports-run" onClick={() => submit(true)} disabled={pending || running || !form.name.trim()}>
          {running ? 'Production en cours…' : 'Produire le PPT par IA'}
        </button>
      </div>

      <div className="reports-result">
        <div className="reports-result-header">
          <h3>Résultat</h3>
          {result && (
            <span className="reports-result-meta">
              {result.modelLabel} · {aiCost(result.cost)} · {dateFr(result.generatedAt)}
            </span>
          )}
          <div className="reports-downloads">
            <PptxButton label="Importer le PPT modifié" onFile={uploadModified} disabled={assemblyId == null || running} />
          </div>
        </div>

        {running ? (
          <div className="reports-running">
            <div className="reports-progress" />
            <p>{modelLabel(assembly.model)} prépare le PPT… (jusqu'à quelques minutes)</p>
          </div>
        ) : !shownFile ? (
          <p className="reports-placeholder">Pas encore de PPT : choisis un PPT modèle, puis lance « Produire le PPT par IA ».</p>
        ) : (
          <>
            <div className="seasons-segmented" role="group" aria-label="PPT affiché">
              {KINDS.map((k) => (
                <button
                  key={k.id}
                  aria-pressed={k.id === shownKind}
                  disabled={!files[k.id]}
                  title={files[k.id] ? files[k.id].filename : 'Pas encore de PPT de cette sorte'}
                  onClick={() => setKind(k.id)}
                >
                  {k.label}
                </button>
              ))}
            </div>
            {/* Telecharge le PPT choisi juste au-dessus. */}
            <div className="ag-shown-file">
              <span className="reports-period">
                {shownFile.filename}, enregistré le {dateFr(shownFile.createdAt)} à {timeFr(shownFile.createdAt)}.
                {shownFile.source && ` ${shownFile.source}.`}
              </span>
              <button onClick={download}>Télécharger</button>
            </div>
            {result && shownKind === 'genere' && <RunDetails result={result} />}
            <SlidesPreview
              key={`${shownKind}-${shownFile.createdAt}`}
              assemblyId={assemblyId}
              kind={shownKind}
              changed={result && shownKind === 'genere' ? result.changedSlides : []}
            />
          </>
        )}
      </div>
    </section>
  )
}

function RunDetails({ result }) {
  return (
    <div className="ag-details">
      <p className="reports-period">
        À partir de « {result.report.name} » ({STATE_LABELS[result.report.state].toLowerCase()}) et de : {result.template.name}.
      </p>
      {result.warnings.length > 0 && (
        <div className="reports-check reports-check-alert">
          <b>Montants à vérifier</b>
          <ul className="ag-warnings">
            {result.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      {result.summary.length > 0 && (
        <ul className="ag-summary">
          {result.summary.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Image d'une diapo (route protegee : chargee avec le cookie de session).
function useImage(url) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    if (!url) return undefined
    let objectUrl = null
    let cancelled = false
    fetch(url, { credentials: 'include' })
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (blob && !cancelled) {
          objectUrl = URL.createObjectURL(blob)
          setSrc(objectUrl)
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [url])
  return src
}

function SlideText({ slide }) {
  return (
    <div className="ag-slide-text">
      <span className="ag-slide-title">{slide.title || `Diapo ${slide.number}`}</span>
      <ul>
        {slide.lines.map((line, i) => (
          <li key={i} style={{ marginLeft: `${line.level * 0.8}em` }}>
            {line.text.split('À compléter').map((part, j) => (
              <span key={j}>
                {j > 0 && <mark>À compléter</mark>}
                {part}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </div>
  )
}

function SlideView({ assemblyId, kind, slide }) {
  const src = useImage(slide.image ? `${API_URL}/general-assemblies/${assemblyId}/files/${kind}/slides/${slide.image}.png` : null)
  if (slide.image && src) return <img src={src} alt={`Diapo ${slide.number} : ${slide.title}`} />
  return <SlideText slide={slide} />
}

function SlidesPreview({ assemblyId, kind, changed }) {
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)

  useEffect(() => {
    callApi(`/general-assemblies/${assemblyId}/files/${kind}/slides`)
      .then(setPreview)
      .catch((err) => setError(err.message))
  }, [assemblyId, kind])

  useEffect(() => {
    if (open === null) return undefined
    function onKey(e) {
      if (e.key === 'Escape') setOpen(null)
      if (e.key === 'ArrowRight') setOpen((i) => Math.min(i + 1, preview.slides.length - 1))
      if (e.key === 'ArrowLeft') setOpen((i) => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, preview])

  if (error) return <p className="error">{error}</p>
  if (!preview) return <p className="reports-placeholder">Préparation de l'aperçu des diapos…</p>
  const changedSet = new Set(changed)
  const current = open === null ? null : preview.slides[open]

  return (
    <>
      {!preview.thumbnails && <p className="reports-hint">Images des diapos indisponibles (LibreOffice absent du serveur) : aperçu du texte.</p>}
      <div className="ag-slides">
        {preview.slides.map((slide, i) => (
          <button key={slide.number} className={slide.hidden ? 'ag-thumb ag-thumb-hidden' : 'ag-thumb'} onClick={() => setOpen(i)} aria-label={`Diapo ${slide.number} : ${slide.title}`}>
            <div className="ag-thumb-stage">
              <SlideView assemblyId={assemblyId} kind={kind} slide={slide} />
            </div>
            <span className="ag-thumb-caption">
              <span className="ag-thumb-number">{slide.number}</span>
              <span className="ag-thumb-title">{slide.title || '—'}</span>
              {changedSet.has(slide.number) && <span className="ag-ai-dot" title="Écrite par l'IA" />}
              {slide.hidden && <span className="ag-thumb-tag">masquée</span>}
            </span>
          </button>
        ))}
      </div>
      {changedSet.size > 0 && (
        <p className="reports-hint">
          <span className="ag-ai-dot" /> diapo écrite par l'IA ; <mark>À compléter</mark> : à remplir par toi.
        </p>
      )}

      {current && (
        <div className="ag-viewer" role="dialog" aria-modal="true" aria-label={`Diapo ${current.number}`} onClick={(e) => e.target === e.currentTarget && setOpen(null)}>
          <div className="ag-viewer-box">
            <div className="ag-viewer-stage">
              <SlideView assemblyId={assemblyId} kind={kind} slide={current} />
            </div>
            <div className="ag-viewer-footer">
              <span>
                {current.number} / {preview.slides.length}
                {changedSet.has(current.number) ? ' · écrite par l’IA' : ''}
              </span>
              <span className="reports-downloads">
                <button onClick={() => setOpen(Math.max(open - 1, 0))} disabled={open === 0}>
                  Précédente
                </button>
                <button onClick={() => setOpen(Math.min(open + 1, preview.slides.length - 1))} disabled={open === preview.slides.length - 1}>
                  Suivante
                </button>
                <button onClick={() => setOpen(null)}>Fermer</button>
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
