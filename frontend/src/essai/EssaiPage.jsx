import { useEffect, useRef, useState } from 'react'
import SignaturePad from 'signature_pad'
import clubLogo from '../assets/club-logo-transparent.png'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const ADULT_AGE = 18

function ageOn(birthDate, today = new Date()) {
  if (!birthDate) return null
  const [year, month, day] = birthDate.split('-').map(Number)
  const beforeBirthday = today.getMonth() + 1 < month || (today.getMonth() + 1 === month && today.getDate() < day)
  return today.getFullYear() - year - (beforeBirthday ? 1 : 0)
}

// Date du jour au format AAAA-MM-JJ (heure locale), pour le max du champ date.
function todayIso() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

// Textes du serveur (voir backend trials/content.py) : {eleve} et {club}
// remplaces par le nom de l'eleve et du club.
function fill(text, studentName, club) {
  return text.replaceAll('{eleve}', studentName || "l'élève").replaceAll('{club}', club)
}

const EMPTY_FORM = {
  firstName: '',
  lastName: '',
  birthDate: '',
  gender: '',
  email: '',
  phone: '',
  parentName: '',
  medicalAttestation: false,
  parentalConsent: false,
  waiverAccepted: false,
  website: '',
}

// Page publique d'inscription au cours d'essai (voir essai.html) : modalites,
// horaires et lieux, formulaire (signature au doigt), puis QR code a montrer
// au debut du cours. Pensee d'abord pour le telephone (Android et iPhone).
export default function EssaiPage() {
  const [info, setInfo] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    fetch(`${API_URL}/public/trials/info`)
      .then((response) => {
        if (!response.ok) throw new Error()
        return response.json()
      })
      .then(setInfo)
      .catch(() => setLoadError('Impossible de charger la page, réessayez dans un instant.'))
  }, [])

  return (
    <main className="essai">
      <header className="essai-header">
        <img src={clubLogo} alt="" className="essai-logo" />
        <div>
          <h1>{info?.title ?? "Cours d'essai MMA / Sambo"}</h1>
          <p className="essai-club">{info?.club ?? 'Alliance Sambo Combat La Ciotat'}</p>
        </div>
      </header>

      {loadError && <p className="essai-error">{loadError}</p>}

      {info && !result && (
        <>
          <p className="essai-intro">{info.intro}</p>

          <section className="essai-card">
            <h2>Modalités</h2>
            <ul className="essai-rules">
              {info.rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </section>

          <section className="essai-card">
            <h2>Horaires et lieux</h2>
            {info.sessions.map((session) => (
              <div key={session.place} className="essai-place">
                <h3>{session.place}</h3>
                <p className="essai-address">{session.address}</p>
                <ul className="essai-slots">
                  {session.slots.map((slot) => (
                    <li key={`${slot.day}-${slot.time}`}>
                      <strong>{slot.day}</strong> {slot.time}
                      <span>{slot.audience}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>

          <RegistrationForm info={info} onDone={setResult} />
        </>
      )}

      {result && <Result result={result} />}

      {info && <p className="essai-privacy">{info.privacy}</p>}
    </main>
  )
}

function RegistrationForm({ info, onDone }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [certificate, setCertificate] = useState(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const padRef = useRef(null)

  const age = ageOn(form.birthDate)
  const minor = age !== null && age < ADULT_AGE
  const studentName = `${form.firstName} ${form.lastName}`.trim()

  function update(key) {
    return (e) => {
      const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
      setForm((prev) => ({ ...prev, [key]: value }))
    }
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    if (!form.gender) return setError('Merci d’indiquer le genre')
    if (padRef.current.isEmpty()) return setError('Merci de signer dans le cadre prévu')
    const body = new FormData()
    for (const [key, value] of Object.entries(form)) body.append(key, value)
    if (!minor) body.set('parentName', '')
    body.append('termsVersion', info.termsVersion)
    body.append('signature', padRef.current.toDataUrl())
    if (certificate) body.append('certificate', certificate)
    setPending(true)
    try {
      const response = await fetch(`${API_URL}/public/trials/register`, { method: 'POST', body })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(typeof data?.detail === 'string' ? data.detail : 'Inscription impossible, vérifiez le formulaire')
      }
      onDone({ ...data, email: form.email })
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Connexion impossible, réessayez' : err.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="essai-card essai-form" onSubmit={submit}>
      <h2>Inscription</h2>

      <fieldset>
        <legend>L'élève</legend>
        <label>
          Prénom
          <input value={form.firstName} onChange={update('firstName')} required autoComplete="given-name" />
        </label>
        <label>
          Nom
          <input value={form.lastName} onChange={update('lastName')} required autoComplete="family-name" />
        </label>
        <label>
          Date de naissance
          <input
            type="date"
            value={form.birthDate}
            onChange={update('birthDate')}
            required
            max={todayIso()}
            min="1920-01-01"
          />
        </label>
        <div className="essai-label" role="radiogroup" aria-label="Genre">
          Genre
          <div className="essai-choice">
            {[
              ['M', 'Homme'],
              ['F', 'Femme'],
            ].map(([value, label]) => (
              <label key={value} className={form.gender === value ? 'essai-choice-active' : undefined}>
                <input type="radio" name="gender" value={value} checked={form.gender === value} onChange={update('gender')} />
                {label}
              </label>
            ))}
          </div>
        </div>
      </fieldset>

      <fieldset>
        <legend>Contact</legend>
        <label>
          <span>E-mail {minor && <small>(du parent)</small>}</span>
          <input
            type="email"
            inputMode="email"
            value={form.email}
            onChange={update('email')}
            required
            autoComplete="email"
          />
          <small>Le QR code vous sera envoyé à cette adresse.</small>
        </label>
        <label>
          <span>Téléphone <small>(facultatif)</small></span>
          <input type="tel" inputMode="tel" value={form.phone} onChange={update('phone')} autoComplete="tel" />
        </label>
      </fieldset>

      {minor && (
        <fieldset>
          <legend>Parent ou représentant légal</legend>
          <label>
            Nom et prénom
            <input value={form.parentName} onChange={update('parentName')} required autoComplete="name" />
          </label>
          <label className="essai-check">
            <input type="checkbox" checked={form.parentalConsent} onChange={update('parentalConsent')} required />
            <span>{fill(info.parentalConsent, studentName, info.club)}</span>
          </label>
        </fieldset>
      )}

      <fieldset>
        <legend>Santé</legend>
        <label className="essai-check">
          <input
            type="checkbox"
            checked={form.medicalAttestation}
            onChange={update('medicalAttestation')}
            required
          />
          <span>{fill(info.medicalAttestation, studentName, info.club)}</span>
        </label>
        <p className="essai-hint">{info.medicalCertificateHint}</p>
        {/* accept image/* : propose l'appareil photo sur Android et iPhone. */}
        <label className="essai-file">
          <input
            type="file"
            accept="image/*,application/pdf,.heic,.heif"
            onChange={(e) => setCertificate(e.target.files[0] ?? null)}
          />
          {certificate ? `📎 ${certificate.name}` : '📷 Joindre un certificat médical'}
        </label>
        {certificate && (
          <button type="button" className="essai-link" onClick={() => setCertificate(null)}>
            Retirer le certificat
          </button>
        )}
      </fieldset>

      <fieldset>
        <legend>Décharge de responsabilité</legend>
        <label className="essai-check">
          <input type="checkbox" checked={form.waiverAccepted} onChange={update('waiverAccepted')} required />
          <span>{fill(info.waiver, studentName, info.club)}</span>
        </label>
      </fieldset>

      <fieldset>
        <legend>{minor ? 'Signature du parent ou représentant légal' : 'Signature'}</legend>
        <SignatureField padRef={padRef} />
      </fieldset>

      {/* Piege a robots : invisible pour un humain, rempli par les robots
          qui remplissent tous les champs (voir backend). */}
      <input
        className="essai-trap"
        name="website"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={form.website}
        onChange={update('website')}
      />

      {error && <p className="essai-error">{error}</p>}

      <button type="submit" className="essai-submit" disabled={pending}>
        {pending ? 'Envoi…' : 'Valider mon inscription'}
      </button>
    </form>
  )
}

// Signature au doigt (ou a la souris) : bibliotheque signature_pad, qui gere
// le tactile sur Android comme sur iPhone. Le canvas est redimensionne a la
// largeur de l'ecran (et a la densite de pixels) sans perdre le trace.
function SignatureField({ padRef }) {
  const canvasRef = useRef(null)
  const signaturePad = useRef(null)
  const [empty, setEmpty] = useState(true)

  useEffect(() => {
    const canvas = canvasRef.current
    const pad = new SignaturePad(canvas, { penColor: '#111', backgroundColor: 'rgb(255,255,255)' })
    signaturePad.current = pad
    pad.addEventListener('endStroke', () => setEmpty(pad.isEmpty()))
    padRef.current = {
      isEmpty: () => pad.isEmpty(),
      toDataUrl: () => pad.toDataURL('image/png'),
    }

    function resize() {
      const ratio = Math.max(window.devicePixelRatio || 1, 1)
      const data = pad.toData()
      canvas.width = canvas.offsetWidth * ratio
      canvas.height = canvas.offsetHeight * ratio
      canvas.getContext('2d').scale(ratio, ratio)
      pad.clear()
      pad.fromData(data)
    }
    resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      pad.off()
    }
  }, [padRef])

  function clear() {
    signaturePad.current.clear()
    setEmpty(true)
  }

  return (
    <>
      <div className="essai-signature">
        <canvas ref={canvasRef} />
        {empty && <span className="essai-signature-hint">Signez ici avec le doigt</span>}
      </div>
      {!empty && (
        <button type="button" className="essai-link" onClick={clear}>
          Effacer la signature
        </button>
      )}
    </>
  )
}

function Result({ result }) {
  if (result.status === 'existing') {
    return (
      <section className="essai-card essai-result">
        <h2>Vous êtes déjà inscrit(e)</h2>
        {result.emailSent ? (
          <p>
            Votre QR code vient de vous être renvoyé par e-mail à <strong>{result.email}</strong>. Pensez à regarder
            dans les courriers indésirables.
          </p>
        ) : (
          <p>Votre QR code a déjà été généré lors de votre première inscription. Contactez le club si vous l'avez perdu.</p>
        )}
      </section>
    )
  }
  const qrSrc = `data:image/png;base64,${result.qrPng}`
  return (
    <section className="essai-card essai-result">
      <h2>Inscription confirmée ✅</h2>
      <p>
        <strong>
          {result.firstName} {result.lastName}
        </strong>
        , présentez ce QR code à l'entraîneur <strong>au début de votre cours d'essai</strong>. Il n'est valable que
        pour un seul cours.
      </p>
      <img src={qrSrc} alt="QR code du cours d'essai" className="essai-qr" />
      <a href={qrSrc} download="qr-code-cours-essai.png" className="essai-submit">
        Enregistrer le QR code
      </a>
      <p className="essai-hint">
        {result.emailSent
          ? `Un e-mail récapitulatif avec ce QR code a été envoyé à ${result.email}.`
          : 'Faites une capture d’écran de ce QR code pour le garder.'}
      </p>
    </section>
  )
}
