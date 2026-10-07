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

function dateTimeFr(iso) {
  return new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// Liste de mails du journal (voir backend helloasso/mails.py), le plus recent
// d'abord ; un clic sur un mail montre son texte. withName : affiche aussi
// le destinataire (journal de tous les adherents).
export function MailHistory({ mails, withName = false }) {
  if (mails.length === 0) return <p className="member-panel-note">Aucun mail envoyé.</p>
  return (
    <ul className="mail-history">
      {mails.map((mail) => (
        <li key={mail.id}>
          <details>
            <summary>
              <span className="mail-history-date">{dateTimeFr(mail.sentAt)}</span>
              <span className="mail-history-subject">
                {withName && `${mail.firstName} ${mail.lastName} : `}
                {mail.subject}
              </span>
              {!mail.sent && <span className="mail-history-failed">non envoyé</span>}
            </summary>
            <p className="mail-history-meta">
              À {mail.to}
              {mail.cc ? `, copie à ${mail.cc}` : ''}
              {mail.sender ? `, de ${mail.sender}` : ''}
            </p>
            {mail.error && <p className="error">{mail.error}</p>}
            <p className="mail-history-body">{mail.body}</p>
          </details>
        </li>
      ))}
    </ul>
  )
}

// Demande d'ouverture venue du menu ⋮ (voir requestSentMails).
const SENT_MAILS_EVENT = 'member-mails-open'

// Entree "Mails envoyés" du menu ⋮ (voir App.jsx).
export function requestSentMails() {
  window.dispatchEvent(new Event(SENT_MAILS_EVENT))
}

// Journal de tous les mails envoyes aux adherents, ouvert depuis le menu ⋮.
export function SentMails() {
  const [open, setOpen] = useState(false)
  const [mails, setMails] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(SENT_MAILS_EVENT, show)
    return () => window.removeEventListener(SENT_MAILS_EVENT, show)
  }, [])

  useEffect(() => {
    if (!open) return
    setMails(null)
    setError(null)
    callApi('/helloasso/mails')
      .then(setMails)
      .catch((err) => setError(err.message))
  }, [open])

  if (!open) return null
  return (
    <ContactDialog title="Mails envoyés" onClose={() => setOpen(false)}>
      {error && <p className="error">{error}</p>}
      {!mails && !error && <p>Chargement…</p>}
      {mails && <MailHistory mails={mails} withName />}
    </ContactDialog>
  )
}
