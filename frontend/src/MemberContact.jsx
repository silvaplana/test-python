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
// onSent : appele apres un envoi reussi (met a jour la pastille du bouton).
export function MemberMailDialog({ member, onClose, onSent }) {
  const [settings, setSettings] = useState(null)
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState(`Bonjour ${member.payerFirstName || member.firstName},\n\n`)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  // Mails deja envoyes a cet adherent, rappeles sous le formulaire.
  const [history, setHistory] = useState(null)

  useEffect(() => {
    callApi('/helloasso/mail-settings')
      .then(setSettings)
      .catch((err) => setError(err.message))
    callApi(`/helloasso/members/${member.id}/mails`)
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [member.id])

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
      onSent?.()
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

      <h4 className="member-contact-history">Mails déjà envoyés{history?.length ? ` (${history.length})` : ''}</h4>
      {history ? <MailHistory mails={history} /> : <p className="member-panel-note">Chargement…</p>}
    </ContactDialog>
  )
}

// L'appareil a-t-il une appli SMS ? Vrai sur telephone et tablette (Android,
// iPhone, iPad), faux sur ordinateur : le bouton SMS n'y est pas propose,
// son lien "sms:" n'y ouvrirait rien.
export const CAN_SEND_SMS = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)

// "06 12 34 56 78" -> "+33612345678" (meme regle que le backend,
// helloasso/mails.py), pour le lien "sms:" ; null si pas de numero utilisable.
function smsNumber(value) {
  const text = (value || '').trim()
  const digits = text.replace(/\D/g, '')
  if (digits.length < 9) return null
  if (text.startsWith('+')) return `+${digits}`
  if (digits.startsWith('00')) return `+${digits.slice(2)}`
  if (digits.length === 10 && digits.startsWith('0')) return `+33${digits.slice(1)}`
  if (digits.length === 9) return `+33${digits}`
  return digits
}

// SMS a un adherent : le message est ecrit ici, puis l'appli SMS du telephone
// s'ouvre avec le numero et le texte deja remplis (lien "sms:") -- c'est elle
// qui envoie, depuis le numero de l'utilisateur. L'appli garde la trace du
// SMS prepare (POST /helloasso/members/{id}/sms), sans pouvoir savoir s'il
// est reellement parti. onPrepared : met a jour la pastille du bouton.
export function MemberSmsDialog({ member, onClose, onPrepared }) {
  const rawPhone = member.customFields?.['Numéro de téléphone']
  const phone = smsNumber(rawPhone)
  const [message, setMessage] = useState(`Bonjour ${member.payerFirstName || member.firstName}, `)
  const [history, setHistory] = useState(null)

  useEffect(() => {
    callApi(`/helloasso/members/${member.id}/sms`)
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [member.id])

  // Appele au clic sur le lien : la trace part en parallele, sans retarder
  // l'ouverture de l'appli SMS.
  function record() {
    callApi(`/helloasso/members/${member.id}/sms`, {
      method: 'POST',
      // keepalive : la requete aboutit meme si le telephone met la page en
      // veille en basculant vers l'appli SMS (iPhone notamment).
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
      .then((saved) => {
        setHistory((previous) => [saved, ...(previous ?? [])])
        onPrepared?.()
      })
      .catch((err) => showToast(`SMS non noté dans le journal : ${err.message}`, 'warning'))
  }

  const ready = phone && message.trim()
  return (
    <ContactDialog title={`SMS à ${member.firstName} ${member.lastName}`} onClose={onClose}>
      <dl className="member-mail-headers">
        <div>
          <dt>Au</dt>
          <dd>{rawPhone || 'pas de numéro de téléphone chez HelloAsso'}</dd>
        </div>
      </dl>
      <div className="trial-form-grid">
        <label className="trial-form-wide">
          Message
          <textarea rows={5} value={message} onChange={(e) => setMessage(e.target.value)} />
          <span className="reports-hint">
            {message.length} caractère{message.length > 1 ? 's' : ''}. Le SMS part de l'appli SMS de ton téléphone, donc de ton
            numéro : à utiliser depuis un téléphone.
          </span>
        </label>
      </div>
      <div className="trial-dialog-actions">
        {/* ?&body= : forme comprise par Android comme par iPhone. */}
        <a
          className={ready ? 'member-sms-open' : 'member-sms-open member-sms-open-disabled'}
          href={ready ? `sms:${phone}?&body=${encodeURIComponent(message.trim())}` : undefined}
          aria-disabled={!ready}
          onClick={ready ? record : (e) => e.preventDefault()}
        >
          Ouvrir dans l'appli SMS
        </a>
      </div>

      <h4 className="member-contact-history">SMS déjà préparés{history?.length ? ` (${history.length})` : ''}</h4>
      {history ? <SmsHistory sms={history} /> : <p className="member-panel-note">Chargement…</p>}
    </ContactDialog>
  )
}

// Liste des SMS prepares (journal), le plus recent d'abord. withName :
// affiche aussi le destinataire (journal de tous les adherents).
export function SmsHistory({ sms, withName = false }) {
  if (sms.length === 0) return <p className="member-panel-note">Aucun SMS préparé.</p>
  return (
    <>
      <ul className="mail-history">
        {sms.map((one) => (
          <li key={one.id}>
            <details>
              <summary>
                <span className="mail-history-date">{dateTimeFr(one.sentAt)}</span>
                <span className="mail-history-subject">
                  {withName && `${one.firstName} ${one.lastName} : `}
                  {one.body.length > 60 ? `${one.body.slice(0, 60)}…` : one.body}
                </span>
              </summary>
              <p className="mail-history-meta">Au {one.phone}</p>
              <p className="mail-history-body">{one.body}</p>
            </details>
          </li>
        ))}
      </ul>
      <p className="member-panel-note">
        Préparé dans l'appli, envoyé depuis ton téléphone : l'appli ne peut pas vérifier qu'il est bien parti.
      </p>
    </>
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

// Entree "Mails et SMS envoyés" du menu ⋮ (voir App.jsx).
export function requestSentMails() {
  window.dispatchEvent(new Event(SENT_MAILS_EVENT))
}

// Journal de tous les mails envoyes et SMS prepares, ouvert depuis le menu ⋮.
export function SentMails() {
  const [open, setOpen] = useState(false)
  const [mails, setMails] = useState(null)
  const [sms, setSms] = useState(null)
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
    callApi('/helloasso/sms')
      .then(setSms)
      .catch(() => setSms([]))
  }, [open])

  if (!open) return null
  return (
    <ContactDialog title="Mails et SMS envoyés" onClose={() => setOpen(false)}>
      <h4 className="member-contact-history">Mails</h4>
      {error && <p className="error">{error}</p>}
      {!mails && !error && <p>Chargement…</p>}
      {mails && <MailHistory mails={mails} withName />}
      <h4 className="member-contact-history">SMS préparés</h4>
      {sms ? <SmsHistory sms={sms} withName /> : <p className="member-panel-note">Chargement…</p>}
    </ContactDialog>
  )
}
