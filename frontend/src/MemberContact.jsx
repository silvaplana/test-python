import { useEffect, useRef, useState } from 'react'
import { showToast } from './Toast.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || `Échec (${response.status})`)
  return body
}

// Cadre commun aux deux fenetres : titre et croix de fermeture.
function ContactDialog({ title, onClose, busy = false, children }) {
  const dialogRef = useRef(null)
  useEffect(() => {
    dialogRef.current.showModal()
  }, [])
  return (
    <dialog ref={dialogRef} className="trial-dialog" onClose={onClose}>
      <div className="trial-scan-header">
        <h3>{title}</h3>
        <button
          type="button"
          className="trial-scan-close"
          onClick={() => dialogRef.current.close()}
          disabled={busy}
          aria-label="Fermer"
          title="Fermer"
        >
          ✕
        </button>
      </div>
      {children}
    </dialog>
  )
}

// Mail a un adherent (onglet HelloAsso > Adherents) : objet et message
// libres, envoyes par le backend (POST /helloasso/members/{id}/mail) a son
// adresse HelloAsso, l'association en copie et en adresse de reponse.
export function MemberMailDialog({ member, onClose }) {
  const [settings, setSettings] = useState(null)
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState(`Bonjour ${member.payerFirstName || member.firstName},\n\n`)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    callApi('/helloasso/mail-settings')
      .then(setSettings)
      .catch((err) => setError(err.message))
  }, [])

  async function send(e) {
    e.preventDefault()
    setPending(true)
    setError(null)
    try {
      const sent = await callApi(`/helloasso/members/${member.id}/mail`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject, message }),
      })
      showToast(`Mail envoyé à ${sent.to}`)
      onClose()
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  return (
    <ContactDialog title={`Mail à ${member.firstName} ${member.lastName}`} onClose={onClose} busy={pending}>
      <form onSubmit={send}>
        <dl className="member-mail-headers">
          <div>
            <dt>À</dt>
            <dd>{member.email || 'pas d’adresse e-mail'}</dd>
          </div>
          {settings && (
            <>
              <div>
                <dt>De</dt>
                <dd>{settings.sender}</dd>
              </div>
              {settings.contact && (
                <div>
                  <dt>Copie et réponses</dt>
                  <dd>{settings.contact}</dd>
                </div>
              )}
            </>
          )}
        </dl>
        {settings && !settings.enabled && <p className="warning">L'envoi de mails n'est pas configuré sur le serveur.</p>}
        <div className="trial-form-grid">
          <label className="trial-form-wide">
            Objet
            <input value={subject} onChange={(e) => setSubject(e.target.value)} required autoComplete="off" />
          </label>
          <label className="trial-form-wide">
            Message
            <textarea rows={9} value={message} onChange={(e) => setMessage(e.target.value)} required />
          </label>
        </div>

        {error && <p className="error">{error}</p>}

        <div className="trial-dialog-actions">
          <button type="submit" className="trial-save" disabled={pending || !member.email || (settings && !settings.enabled)}>
            {pending ? 'Envoi…' : 'Envoyer'}
          </button>
        </div>
      </form>
    </ContactDialog>
  )
}

// SMS a un adherent : pas encore disponible.
export function MemberSmsDialog({ member, onClose }) {
  const phone = member.customFields?.['Numéro de téléphone']
  return (
    <ContactDialog title={`SMS à ${member.firstName} ${member.lastName}`} onClose={onClose}>
      <div className="in-development">
        <p className="in-development-badge">🚧 En construction</p>
        <p>L'envoi de SMS depuis l'appli n'est pas encore disponible.</p>
      </div>
      <p className="member-panel-note">Numéro chez HelloAsso : {phone || 'non renseigné'}</p>
    </ContactDialog>
  )
}
