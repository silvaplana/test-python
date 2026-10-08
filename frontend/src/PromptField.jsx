import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'

// Champ "Prompt donné à l'IA" d'un calcul (Bilan financier, Assemblees
// generales, Previsionnel), avec ses prompts enregistres, propres a chaque
// calcul (routes <basePath>/prompts du backend, voir database/prompts.py) :
// - cliquer sur le titre ouvre le menu des prompts enregistres ; cliquer sur
//   un prompt le met dans le champ, sa corbeille le retire de la liste ;
// - la disquette du champ enregistre le prompt en cours.
// Le champ et chaque prompt du menu ont a droite une meme colonne : bouton,
// ascenseur, poignee (voir useRail).
//
// basePath : "/financial-reports/12"... ; null tant que le calcul n'est pas
// cree (pas d'enregistrement possible). owner : "ce bilan", "cette AG"...
// children : texte d'aide sous le champ.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || `Échec (${response.status})`)
  return body
}

// Menu deroulant ouvert d'un clic sur un titre ; ferme d'un clic ailleurs ou
// par Echap. ref : a poser sur l'element qui contient le titre et le menu.
export function useDropdown() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    function close(event) {
      if (event.type === 'keydown' ? event.key === 'Escape' : !ref.current?.contains(event.target)) {
        // Echap ne doit pas fermer aussi la fenetre (dialog) qui contient le menu.
        if (event.type === 'keydown') event.preventDefault()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close, true)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close, true)
    }
  }, [open])
  return { open, setOpen, ref }
}

export function PromptField({ value, onChange, basePath, savedPrompts, onSavedPrompts, owner, placeholder, children }) {
  const { open: menuOpen, setOpen: setMenuOpen, ref: menuRef } = useDropdown()

  const saved = savedPrompts ?? []
  // Prompt enregistre qui correspond au texte en cours, s'il y en a un.
  const selected = saved.find((p) => p.prompt === value.trim())

  async function save() {
    try {
      const body = await callApi(`${basePath}/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: value }),
      })
      onSavedPrompts(body.savedPrompts)
      showToast(`Prompt enregistré pour ${owner}`, 'success')
    } catch (err) {
      showToast(`Prompt non enregistré : ${err.message}`, 'warning')
    }
  }

  function choose(prompt) {
    const known = !value.trim() || saved.some((p) => p.prompt === value.trim())
    if (!known && !window.confirm('Remplacer le prompt actuel par ce prompt enregistré ?')) return
    onChange(prompt.prompt)
    setMenuOpen(false)
  }

  async function remove(prompt) {
    if (!window.confirm(`Retirer ce prompt des prompts enregistrés de ${owner} ?`)) return
    try {
      const body = await callApi(`${basePath}/prompts/${prompt.id}`, { method: 'DELETE' })
      onSavedPrompts(body.savedPrompts)
    } catch (err) {
      showToast(`Prompt non retiré : ${err.message}`, 'warning')
    }
  }

  return (
    <div className="trial-form-wide reports-prompt-field">
      <div className="reports-prompt-title" ref={menuRef}>
        <button
          type="button"
          className="reports-prompt-menu-button"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
          title={`Prompts enregistrés de ${owner}`}
        >
          Prompt donné à l'IA <span aria-hidden="true">▾</span>
        </button>
        {menuOpen && (
          <div className="reports-prompt-menu" role="menu">
            {saved.length === 0 && (
              <p className="reports-prompt-menu-empty">
                Aucun prompt enregistré pour {owner}. La disquette enregistre le prompt en cours.
              </p>
            )}
            {saved.map((p) => (
              <SavedPrompt key={p.id} prompt={p.prompt} current={p.id === selected?.id} onChoose={() => choose(p)} onDelete={() => remove(p)} />
            ))}
          </div>
        )}
      </div>
      <PromptInput
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onSave={save}
        saveDisabled={!basePath || !value.trim() || Boolean(selected)}
        saveTitle={
          !basePath
            ? 'Crée d\u2019abord le calcul pour enregistrer son prompt'
            : selected
              ? 'Ce prompt est déjà enregistré'
              : `Enregistrer ce prompt dans les prompts de ${owner}`
        }
        placeholder={placeholder}
      />
      {children && <span className="reports-hint">{children}</span>}
    </div>
  )
}

// Colonne a droite d'un texte qui defile (prompt en cours ou prompt
// enregistre) : un bouton en haut, puis un ascenseur et une poignee, tous sur
// la meme verticale. L'ascenseur est fait maison (la barre native du texte
// est masquee) pour s'aligner avec le reste et se tirer au doigt ; la poignee
// agrandit le cadre entre min et max() pixels.
function useRail(box, { initial, min, max }) {
  const track = useRef(null)
  const drag = useRef(null)
  const [height, setHeight] = useState(initial)
  // Curseur de l'ascenseur : position et taille, en fraction de la piste.
  const [thumb, setThumb] = useState({ top: 0, size: 1 })

  const measure = useCallback(() => {
    const el = box.current
    if (!el) return
    const next = { top: el.scrollTop / el.scrollHeight, size: Math.min(1, el.clientHeight / el.scrollHeight) }
    setThumb((current) => (current.top === next.top && current.size === next.size ? current : next))
  }, [box])

  function start(kind) {
    return (event) => {
      event.preventDefault()
      event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = { kind, y: event.clientY, height: box.current.clientHeight, scroll: box.current.scrollTop }
    }
  }

  function move(event) {
    const from = drag.current
    if (!from) return
    const delta = event.clientY - from.y
    if (from.kind === 'resize') {
      setHeight(Math.min(max(), Math.max(min, from.height + delta)))
    } else {
      // Curseur : un pixel de piste vaut scrollHeight / hauteur de piste.
      box.current.scrollTop = from.scroll + (delta * box.current.scrollHeight) / track.current.clientHeight
    }
  }

  function stop() {
    drag.current = null
  }

  const handlers = (kind) => ({ onPointerDown: start(kind), onPointerMove: move, onPointerUp: stop, onPointerCancel: stop })
  return { track, height, thumb, measure, handlers }
}

function RailControls({ rail, label }) {
  return (
    <>
      <div ref={rail.track} className="reports-prompt-menu-track" aria-hidden="true">
        {rail.thumb.size < 1 && (
          <span
            className="reports-prompt-menu-thumb"
            style={{ top: `${rail.thumb.top * 100}%`, height: `${rail.thumb.size * 100}%` }}
            {...rail.handlers('scroll')}
          />
        )}
      </div>
      <span className="reports-prompt-menu-handle" role="separator" aria-orientation="horizontal" aria-label={label} title={label} {...rail.handlers('resize')}>
        <svg viewBox="0 0 12 12" aria-hidden="true">
          <path d="M11 4 4 11M11 8l-3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
        </svg>
      </span>
    </>
  )
}

// Champ du prompt : a droite, la disquette (enregistre le prompt pour ce
// calcul), l'ascenseur et la poignee.
const PROMPT_INPUT_PX = 132

export function PromptInput({ value, onChange, onSave, saveDisabled, saveTitle, placeholder, saveLabel = 'Enregistrer ce prompt', required = false }) {
  const box = useRef(null)
  const rail = useRail(box, { initial: PROMPT_INPUT_PX, min: PROMPT_INPUT_PX, max: () => Math.round(window.innerHeight * 0.7) })
  const { measure } = rail

  useEffect(measure, [measure, value, rail.height])

  return (
    <div className="reports-prompt-input">
      <textarea
        ref={box}
        className="reports-prompt-menu-clip"
        style={{ height: rail.height }}
        value={value}
        onChange={onChange}
        onScroll={measure}
        placeholder={placeholder}
        required={required}
      />
      <div className="reports-prompt-menu-rail">
        <button
          type="button"
          className="reports-prompt-button"
          onClick={onSave}
          disabled={saveDisabled}
          title={saveTitle}
          aria-label={saveLabel}
        >
          <SaveIcon />
        </button>
        <RailControls rail={rail} label="Tirer pour agrandir ou réduire le champ" />
      </div>
    </div>
  )
}

// Prompt enregistre dans le menu : cliquer sur le texte l'utilise. A droite :
// la corbeille, puis, si le prompt ne tient pas dans PROMPT_PREVIEW_PX de
// haut, l'ascenseur et la poignee.
const PROMPT_PREVIEW_PX = 96

export function SavedPrompt({ prompt, title, current, onChoose, onDelete, chooseLabel = 'Utiliser ce prompt', deleteLabel = 'Retirer ce prompt des prompts enregistrés' }) {
  const box = useRef(null)
  const [full, setFull] = useState(null)
  const rail = useRail(box, { initial: PROMPT_PREVIEW_PX, min: PROMPT_PREVIEW_PX, max: () => full })
  const { measure } = rail

  // Hauteur du texte entier, mesuree une fois affiche.
  useEffect(() => {
    setFull(box.current.scrollHeight)
  }, [prompt])

  useEffect(measure, [measure, full, rail.height])

  const long = full != null && full > PROMPT_PREVIEW_PX + 4

  return (
    <div className={`reports-prompt-menu-item${current ? ' reports-prompt-menu-current' : ''}`}>
      <div ref={box} className="reports-prompt-menu-clip" style={long ? { height: Math.min(rail.height, full) } : undefined} onScroll={measure}>
        <button type="button" role="menuitem" className="reports-prompt-menu-choice" onClick={onChoose} title={chooseLabel}>
          {/* Titre facultatif (objet d'un mail preenregistre). */}
          {title && <strong className="reports-prompt-menu-heading">{title}</strong>}
          {prompt}
        </button>
      </div>
      <div className="reports-prompt-menu-rail">
        <button
          type="button"
          className="reports-prompt-button reports-prompt-delete"
          onClick={onDelete}
          title={deleteLabel}
          aria-label={deleteLabel}
        >
          <TrashIcon />
        </button>
        {long && <RailControls rail={rail} label="Tirer pour agrandir ou réduire le prompt" />}
      </div>
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

function TrashIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
    </svg>
  )
}
