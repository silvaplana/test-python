import { useEffect, useRef, useState } from 'react'
import { fetchChecks, markCheckOk } from './MemberChecks.jsx'
import { MailHistory } from './MemberContact.jsx'
import { showToast } from './Toast.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const euros = (n) => `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`

function dateFr(iso) {
  if (!iso) return '—'
  const [year, month, day] = iso.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

// Etats HelloAsso d'un paiement, en clair.
const PAYMENT_STATES = {
  Authorized: 'encaissé',
  Registered: 'enregistré',
  Pending: 'à venir',
  Waiting: 'à venir',
  Refused: 'refusé',
  Refunded: 'remboursé',
  Refunding: 'remboursement en cours',
  Canceled: 'annulé',
  Contested: 'contesté',
}

// Age en annees revolues depuis une date "JJ/MM/AAAA" ; null si illisible.
function age(birth) {
  const match = (birth || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (!match) return null
  const [, day, month, year] = match.map(Number)
  const today = new Date()
  const before = today.getMonth() + 1 < month || (today.getMonth() + 1 === month && today.getDate() < day)
  return today.getFullYear() - year - (before ? 1 : 0)
}

// Photo ou document depose dans le formulaire, heberge par HelloAsso : le
// navigateur ne peut pas le charger directement (jeton de l'API requis), il
// passe par le relais du backend (GET /helloasso/document).
async function fetchDocument(url) {
  const response = await fetch(`${API_URL}/helloasso/document?url=${encodeURIComponent(url)}`, { credentials: 'include' })
  if (!response.ok) throw new Error(`Document indisponible (${response.status})`)
  return response.blob()
}

// Ouvre un document dans un nouvel onglet. L'onglet est ouvert tout de suite
// (pendant le clic, sinon le navigateur le bloque) puis recoit le fichier.
async function openDocument(url, label) {
  const tab = window.open('', '_blank')
  try {
    const blob = await fetchDocument(url)
    const blobUrl = URL.createObjectURL(blob)
    if (tab) tab.location = blobUrl
    else {
      // Onglet bloque : telechargement a la place.
      const link = document.createElement('a')
      link.href = blobUrl
      link.download = label
      link.click()
    }
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000)
  } catch (err) {
    tab?.close()
    showToast(err.message, 'warning')
  }
}

// Photo d'identite en grand, chargee par le relais des vignettes.
function Photo({ url }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    let objectUrl = null
    let cancelled = false
    fetch(`${API_URL}/helloasso/photo?url=${encodeURIComponent(url)}&size=320`, { credentials: 'include' })
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (blob && !cancelled) {
          objectUrl = URL.createObjectURL(blob)
          setSrc(objectUrl)
        }
      })
      .catch(() => {
        // Photo indisponible : la fiche reste lisible sans elle.
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [url])
  if (!src) return <div className="member-panel-photo member-panel-photo-empty" aria-hidden="true" />
  return (
    <button type="button" className="member-panel-photo" onClick={() => openDocument(url, 'photo')} title="Ouvrir la photo d'origine">
      <img src={src} alt="Photo d'identité" />
    </button>
  )
}

function Row({ label, children }) {
  return (
    <div className="member-panel-row">
      <dt>{label}</dt>
      <dd>{children ?? '—'}</dd>
    </div>
  )
}

// Fiche d'un adherent (onglet HelloAsso > Adherents, clic sur sa ligne) :
// toutes ses informations HelloAsso -- adhesion, reponses au formulaire,
// payeur, paiements -- et l'acces a ses documents (photo, certificat
// medical, autorisation parentale). memberId : identifiant HelloAsso de son
// adhesion.
// canValidate : peut valider le dossier a la main (mot de passe "comptes").
export function MemberPanel({ memberId, onClose, canValidate = false }) {
  const dialogRef = useRef(null)
  const [member, setMember] = useState(null)
  const [error, setError] = useState(null)
  // Mails deja envoyes a cet adherent depuis l'appli (journal en base).
  const [mails, setMails] = useState(null)
  // Resultat de la verification du dossier par IA (voir MemberChecks.jsx).
  const [check, setCheck] = useState(undefined)
  useEffect(() => {
    fetchChecks()
      .then((state) => setCheck(state.checks[memberId] ?? null))
      .catch(() => setCheck(null))
  }, [memberId])

  async function validate() {
    try {
      await markCheckOk(memberId)
      setCheck({ status: 'ok', issues: [], manual: true })
      showToast('Dossier marqué comme vérifié')
    } catch (err) {
      showToast(err.message, 'warning')
    }
  }

  useEffect(() => {
    fetch(`${API_URL}/helloasso/members/${memberId}/mails`, { credentials: 'include' })
      .then((response) => (response.ok ? response.json() : []))
      .then(setMails)
      .catch(() => setMails([]))
  }, [memberId])

  useEffect(() => {
    dialogRef.current.showModal()
    fetch(`${API_URL}/helloasso/members/${memberId}`, { credentials: 'include' })
      .then(async (response) => {
        const body = await response.json().catch(() => null)
        if (!response.ok) throw new Error(body?.detail || `Fiche indisponible (${response.status})`)
        setMember(body)
      })
      .catch((err) => setError(err.message))
  }, [memberId])

  const fields = member?.fields ?? []
  const files = fields.filter((f) => f.type === 'File' && f.answer)
  const photo = files.find((f) => /photo/i.test(f.name))
  const answers = fields.filter((f) => f.type !== 'File')
  const payer = member?.payer

  return (
    <dialog ref={dialogRef} className="trial-dialog member-panel" onClose={onClose}>
      <div className="trial-scan-header">
        <h3>{member ? `${member.firstName} ${member.lastName}` : 'Adhérent'}</h3>
        <button type="button" className="trial-scan-close" onClick={() => dialogRef.current.close()} aria-label="Fermer" title="Fermer">
          ✕
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!member && !error && <p>Chargement…</p>}

      {member && (
        <>
          <div className="member-panel-top">
            {photo && <Photo url={photo.answer} />}
            <dl>
              <Row label="Tarif">{member.tierName}</Row>
              <Row label="Montant">
                {euros(member.amount)}
                {member.initialAmount !== member.amount && ` (au lieu de ${euros(member.initialAmount)})`}
              </Row>
              <Row label="Code promo">{member.promoCode}</Row>
              <Row label="Inscrit le">{dateFr(member.orderDate)}</Row>
              <Row label="État HelloAsso">{member.state}</Row>
            </dl>
          </div>

          <h4>Vérification du dossier par IA</h4>
          {check === undefined ? (
            <p className="member-panel-note">Chargement…</p>
          ) : check === null ? (
            <p className="member-panel-note">Pas encore vérifié.</p>
          ) : check.status === 'ok' ? (
            <p className="member-panel-note">{check.manual ? 'Dossier validé à la main.' : "Dossier vérifié par l'IA : rien à signaler."}</p>
          ) : (
            <div className="member-panel-issues">
              <ul>
                {check.issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
              {canValidate && (
                <button type="button" onClick={validate}>
                  Marquer comme vérifié
                </button>
              )}
            </div>
          )}

          <h4>Documents</h4>
          {files.length === 0 ? (
            <p className="member-panel-note">Aucun document déposé.</p>
          ) : (
            <div className="member-panel-documents">
              {files.map((f) => (
                <button key={f.name} type="button" onClick={() => openDocument(f.answer, f.name)}>
                  {f.name}
                </button>
              ))}
            </div>
          )}

          <h4>Réponses au formulaire</h4>
          <dl>
            {answers.map((f) => (
              <Row key={f.name} label={f.name}>
                {f.answer}
                {f.type === 'Date' && age(f.answer) != null && ` (${age(f.answer)} ans)`}
              </Row>
            ))}
          </dl>

          <h4>Payeur</h4>
          <dl>
            <Row label="Nom">{[payer.firstName, payer.lastName].filter(Boolean).join(' ')}</Row>
            <Row label="E-mail">{payer.email}</Row>
            <Row label="Adresse">{[payer.address, payer.zipCode, payer.city].filter(Boolean).join(', ') || null}</Row>
          </dl>

          <h4>Paiements</h4>
          {member.payments.length === 0 ? (
            <p className="member-panel-note">Aucun paiement (adhésion gratuite).</p>
          ) : (
            <table className="members-summary-table">
              <tbody>
                {member.payments.map((p, i) => (
                  <tr key={i}>
                    <td>{dateFr(p.date)}</td>
                    <td className="members-summary-count">{PAYMENT_STATES[p.state] ?? p.state}</td>
                    <td className="members-summary-amount">{euros(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4>Mails envoyés</h4>
          {mails ? <MailHistory mails={mails} /> : <p className="member-panel-note">Chargement…</p>}

          {member.membershipCardUrl && (
            <p className="member-panel-note">
              <a href={member.membershipCardUrl} target="_blank" rel="noreferrer">
                Carte d'adhérent HelloAsso
              </a>
            </p>
          )}
        </>
      )}
    </dialog>
  )
}
