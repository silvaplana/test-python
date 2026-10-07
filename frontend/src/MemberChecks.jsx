import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const POLL_MS = 2000
// Demande venue du menu ⋮ (voir requestMemberChecks) ; statut modifie
// ailleurs (dossier valide a la main dans la fiche).
const RUN_EVENT = 'member-checks-run'
const CHANGED_EVENT = 'member-checks-changed'

// Entree "Vérifier adhérents par IA" du menu ⋮ (voir App.jsx) : lance la
// verification et ouvre le panneau d'avancement (MemberChecksPanel).
export function requestMemberChecks() {
  window.dispatchEvent(new Event(RUN_EVENT))
}

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || `Échec (${response.status})`)
  return body
}

export const euros = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`

// Verification par IA du dossier des adherents (voir backend
// helloasso/verification.py) : statut de chaque adherent, cout cumule et
// avancement, relus toutes les 2 s pendant une verification.
// Retourne {state, panelOpen, closePanel, markOk}.
export function useMemberChecks() {
  const [state, setState] = useState(null)
  const [panelOpen, setPanelOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      setState(await callApi('/helloasso/checks'))
    } catch {
      // Statuts indisponibles : le tableau reste utilisable sans eux.
    }
  }, [])

  useEffect(() => {
    load()
    window.addEventListener(CHANGED_EVENT, load)
    return () => window.removeEventListener(CHANGED_EVENT, load)
  }, [load])

  // Menu ⋮ : ouvre le panneau et lance la verification (si aucune n'est en cours).
  useEffect(() => {
    async function run() {
      setPanelOpen(true)
      try {
        await callApi('/helloasso/checks/run', { method: 'POST' })
      } catch (err) {
        showToast(err.message, 'warning')
      }
      load()
    }
    window.addEventListener(RUN_EVENT, run)
    return () => window.removeEventListener(RUN_EVENT, run)
  }, [load])

  const running = state?.run.running
  useEffect(() => {
    if (!running) return undefined
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [running, load])

  return { state, panelOpen, closePanel: () => setPanelOpen(false) }
}

// Dossier valide a la main (fiche de l'adherent) : ne sera plus reverifie.
export async function markCheckOk(memberId) {
  await callApi(`/helloasso/checks/${memberId}/ok`, { method: 'PUT' })
  window.dispatchEvent(new Event(CHANGED_EVENT))
}

export async function fetchChecks() {
  return callApi('/helloasso/checks')
}

// Statut de verification d'un adherent dans le tableau. A verifier : en
// orange, les raisons au survol (et dans sa fiche).
export function CheckStatus({ check }) {
  if (!check) return <span className="member-check member-check-none">—</span>
  if (check.status === 'ok')
    return (
      <span className="member-check member-check-ok" title={check.manual ? 'Validé à la main' : "Vérifié par l'IA"}>
        OK
      </span>
    )
  return (
    <span className="member-check member-check-problem" title={check.issues.join('\n')}>
      {check.status === 'erreur' ? 'Erreur' : 'À vérifier'}
    </span>
  )
}

const RUN_STATES = {
  attente: 'en attente',
  encours: 'vérification…',
  deja: 'déjà vérifié',
  ok: 'OK',
  probleme: 'à vérifier',
  erreur: 'erreur',
}

// Panneau d'avancement de la verification : une ligne par adherent. A la
// fin, un bouton envoie a l'association le recapitulatif des dossiers a
// regarder (POST /helloasso/checks/report).
export function MemberChecksPanel({ state, onClose }) {
  const dialogRef = useRef(null)
  const [sending, setSending] = useState(false)
  const [reported, setReported] = useState(null)

  async function sendReport() {
    setSending(true)
    try {
      const sent = await callApi('/helloasso/checks/report', { method: 'POST' })
      setReported(sent)
      showToast(`Récapitulatif envoyé à ${sent.to}`)
    } catch (err) {
      showToast(err.message, 'warning')
    }
    setSending(false)
  }

  useEffect(() => {
    dialogRef.current.showModal()
  }, [])
  const run = state?.run
  const items = run?.items ?? []
  const toCheck = items.filter((item) => item.state !== 'deja')
  const done = toCheck.filter((item) => !['attente', 'encours'].includes(item.state))
  const problems = done.filter((item) => item.state !== 'ok')
  // Tous les dossiers a regarder, y compris ceux des verifications precedentes.
  const toFix = Object.values(state?.checks ?? {}).filter((check) => check.status !== 'ok').length

  return (
    <dialog ref={dialogRef} className="trial-dialog member-checks" onClose={onClose}>
      <div className="trial-scan-header">
        <h3>Vérification des adhérents par IA</h3>
        <button type="button" className="trial-scan-close" onClick={() => dialogRef.current.close()} aria-label="Fermer" title="Fermer">
          ✕
        </button>
      </div>

      {!run || items.length === 0 ? (
        <p>Démarrage…</p>
      ) : (
        <>
          <p className="member-checks-summary">
            {run.running ? (
              <>
                <b>
                  {done.length} / {toCheck.length}
                </b>{' '}
                dossiers vérifiés…
              </>
            ) : toCheck.length === 0 ? (
              <b>Tous les dossiers étaient déjà vérifiés : aucun appel à l'IA.</b>
            ) : (
              <>
                <b>
                  Terminé : {done.length - problems.length} OK, {problems.length} à vérifier
                </b>
              </>
            )}{' '}
            {items.length - toCheck.length > 0 && `${items.length - toCheck.length} déjà bons, non revérifiés. `}
            Coût IA cumulé : {euros(state.totalCost)} ({state.modelLabel}).
          </p>
          {run.running && <div className="reports-progress" />}
          <p className="member-panel-note">Tu peux fermer cette fenêtre : la vérification continue.</p>
          {!run.running && toFix > 0 && (
            <div className="member-checks-report">
              <button type="button" onClick={sendReport} disabled={sending}>
                {sending ? 'Envoi…' : `Envoyer par mail à l'association les ${toFix} dossier${toFix > 1 ? 's' : ''} à vérifier`}
              </button>
              {reported && <span className="member-panel-note">Envoyé à {reported.to}.</span>}
            </div>
          )}
          <ul className="member-checks-list">
            {items.map((item) => (
              <li key={item.memberId} className={`member-checks-${item.state}`}>
                <span className="member-checks-name">{item.name}</span>
                <span className="member-checks-state">{RUN_STATES[item.state] ?? item.state}</span>
                {item.issues.length > 0 && (
                  <ul className="member-checks-issues">
                    {item.issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </dialog>
  )
}
