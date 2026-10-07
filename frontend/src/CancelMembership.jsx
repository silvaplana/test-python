import { useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Etats HelloAsso d'une adhesion resiliee (voir backend helloasso/summary.py).
const CANCELED_STATES = new Set(['Canceled', 'Refunded', 'Refunding', 'Abandoned'])

export const isCanceled = (member) => CANCELED_STATES.has(member.state)

const euros = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || `Échec (${response.status})`)
  return body
}

// Fenetre de resiliation de l'adhesion d'un membre (onglet HelloAsso >
// Adherents). HelloAsso ne resilie pas une personne mais sa COMMANDE : tous
// les adherents de la commande le sont ensemble, les echeances a venir sont
// annulees et rien n'est rembourse. La fenetre montre donc d'abord ce que la
// resiliation changera (GET .../cancellation), puis demande confirmation.
// Action irreversible, reservee au mot de passe "comptes".
export function CancelMembershipDialog({ member, onClose, onDone }) {
  const dialogRef = useRef(null)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    dialogRef.current.showModal()
    callApi(`/helloasso/orders/${member.orderId}/cancellation`)
      .then(setPreview)
      .catch((err) => setError(err.message))
  }, [member.orderId])

  async function confirm() {
    setPending(true)
    setError(null)
    try {
      const after = await callApi(`/helloasso/orders/${member.orderId}/cancel`, { method: 'POST' })
      showToast(
        after.canceled
          ? `Adhésion résiliée : ${after.members.map((m) => `${m.firstName} ${m.lastName}`).join(', ')}`
          : 'Résiliation envoyée à HelloAsso',
        after.canceled ? undefined : 'warning'
      )
      onDone(after)
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  const several = preview && preview.members.length > 1

  return (
    <dialog ref={dialogRef} className="trial-dialog" onClose={onClose}>
      <div className="trial-scan-header">
        <h3>Résilier l'adhésion</h3>
        <button
          type="button"
          className="trial-scan-close"
          onClick={() => dialogRef.current.close()}
          disabled={pending}
          aria-label="Fermer sans résilier"
          title="Fermer sans résilier"
        >
          ✕
        </button>
      </div>

      {!preview && !error && <p>Chargement…</p>}

      {preview && (
        <div className="cancel-membership">
          <p>
            HelloAsso résilie une <b>commande entière</b>, pas une personne. Celle-ci{' '}
            {several ? `contient ${preview.members.length} adhérents, qui seront tous résiliés` : 'contient un seul adhérent'} :
          </p>
          <ul>
            {preview.members.map((m, i) => (
              <li key={i}>
                <b>
                  {m.firstName} {m.lastName}
                </b>{' '}
                — {euros(m.amount)}
                {m.promoCode ? `, code ${m.promoCode}` : ''}
              </li>
            ))}
          </ul>
          {several && (
            <p className="warning">
              Impossible de n'en résilier qu'une partie : pour garder l'un d'eux, il devra se réinscrire.
            </p>
          )}
          {preview.paid > 0 && (
            <p className="warning">
              <b>{euros(preview.paid)} déjà encaissés ne seront pas remboursés</b> par la résiliation : le remboursement se
              fait dans ton espace HelloAsso.
            </p>
          )}
          {preview.scheduledCount > 0 && (
            <p>
              {preview.scheduledCount} échéance{preview.scheduledCount > 1 ? 's' : ''} à venir ({euros(preview.scheduled)}) seront
              annulées.
            </p>
          )}
          {preview.paid === 0 && preview.scheduledCount === 0 && <p>Rien n'a été payé : aucun remboursement à faire.</p>}
          <p>
            L'adhésion reste visible dans HelloAsso, marquée résiliée. <b>Cette action est définitive.</b>
          </p>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <div className="trial-dialog-actions">
        <button type="button" className="seasons-delete" onClick={confirm} disabled={!preview || preview.canceled || pending}>
          {pending
            ? 'Résiliation…'
            : preview?.canceled
              ? 'Déjà résiliée'
              : several
                ? `Résilier les ${preview.members.length} adhésions`
                : "Résilier l'adhésion"}
        </button>
      </div>
    </dialog>
  )
}
