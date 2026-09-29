import { useEffect, useRef, useState } from 'react'
import SignaturePad from 'signature_pad'
import banner from '../assets/essai-banner.jpg'
import clubLogo from '../assets/club-logo-transparent.png'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Textes du serveur (voir backend trials/content.py) : {eleve} et {club}
// remplaces par le nom de l'eleve et du club.
function fill(text, studentName, club) {
  return text.replaceAll('{eleve}', studentName || "l'élève").replaceAll('{club}', club)
}

const EMPTY_FORM = {
  firstName: '',
  lastName: '',
  // "adult" | "minor" : pas de date de naissance demandee, l'eleve (ou son
  // parent) indique simplement s'il est mineur.
  ageGroup: '',
  email: '',
  parentName: '',
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

  // Meme charte que le site du club (https://mma-sambo-bedoule-ciotat.e-monsite.com/) :
  // fond blanc, titres Cinzel Decorative, bandeaux vert pale, boutons noirs.
  return (
    <>
      <header className="essai-topbar">
        <img src={clubLogo} alt="" className="essai-logo" />
        <span>{info?.club ?? 'Alliance Sambo Combat La Ciotat'}</span>
      </header>

      <img src={banner} alt="" className="essai-banner" />

      <section className="essai-band essai-title">
        <h1>{info?.title ?? "S'inscrire à un cours d'essai gratuit"}</h1>
        {info && <p>{info.subtitle}</p>}
      </section>

      {loadError && (
        <section className="essai-band">
          <p className="essai-error">{loadError}</p>
        </section>
      )}

      {info && !result && (
        <>
          <section className="essai-band">
            <p className="essai-intro">{info.intro}</p>
          </section>

          <section className="essai-band essai-band-green">
            <h2>Modalités</h2>
            <ul className="essai-rules">
              {info.rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </section>

          <section className="essai-band">
            <h2>Horaires d'entraînement</h2>
            <table className="essai-schedule">
              <tbody>
                {info.schedule.map((slot) => (
                  <tr key={`${slot.day}-${slot.time}`}>
                    <td>
                      <strong>{slot.day}</strong>
                      <br />
                      {slot.time}
                    </td>
                    <td>{slot.course}</td>
                    <td>{slot.place}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {info.places.map((place) => (
              <div key={place.name} className="essai-place">
                <h3>{place.name}</h3>
                <p>{place.address}</p>
                <a href={place.map} target="_blank" rel="noreferrer" className="essai-button essai-button-small">
                  Voir sur la carte
                </a>
              </div>
            ))}
          </section>

          <section className="essai-band essai-band-form">
            <h2>Inscription</h2>
            <RegistrationForm info={info} onDone={setResult} />
          </section>
        </>
      )}

      {result && (
        <section className="essai-band">
          <Result result={result} />
        </section>
      )}

      {info && (
        <section className="essai-band essai-band-green">
          <h2>Contact téléphone</h2>
          <div className="essai-contacts">
            {info.contacts.map((contact) => (
              <a key={contact.phone} href={`tel:${contact.phone.replaceAll(' ', '')}`} className="essai-button">
                {contact.name} : {contact.phone}
              </a>
            ))}
          </div>
        </section>
      )}

      <footer className="essai-footer">{info && <p>{info.privacy}</p>}</footer>
    </>
  )
}

function RegistrationForm({ info, onDone }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [certificate, setCertificate] = useState(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const padRef = useRef(null)

  const minor = form.ageGroup === 'minor'
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
    if (!form.ageGroup) return setError('Merci d’indiquer si l’élève est majeur ou mineur')
    if (!certificate) return setError('Merci de joindre le certificat médical')
    if (padRef.current.isEmpty()) return setError('Merci de signer dans le cadre prévu')
    const body = new FormData()
    body.append('firstName', form.firstName)
    body.append('lastName', form.lastName)
    body.append('email', form.email)
    body.append('minor', minor)
    body.append('parentName', minor ? form.parentName : '')
    body.append('parentalConsent', minor && form.parentalConsent)
    body.append('waiverAccepted', form.waiverAccepted)
    body.append('website', form.website)
    body.append('termsVersion', info.termsVersion)
    body.append('signature', padRef.current.toDataUrl())
    body.append('certificate', certificate)
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
    <form className="essai-form" onSubmit={submit}>

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
        <div className="essai-label" role="radiogroup" aria-label="L'élève est">
          L'élève est
          <div className="essai-choice">
            {[
              ['adult', 'Majeur'],
              ['minor', 'Mineur'],
            ].map(([value, label]) => (
              <label key={value} className={form.ageGroup === value ? 'essai-choice-active' : undefined}>
                <input
                  type="radio"
                  name="ageGroup"
                  value={value}
                  checked={form.ageGroup === value}
                  onChange={update('ageGroup')}
                />
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
        <legend>Certificat médical</legend>
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
      <div className="essai-result">
        <h2>Vous êtes déjà inscrit(e)</h2>
        {result.emailSent ? (
          <p>
            Votre QR code vient de vous être renvoyé par e-mail à <strong>{result.email}</strong>. Pensez à regarder
            dans les courriers indésirables.
          </p>
        ) : (
          <p>Votre QR code a déjà été généré lors de votre première inscription. Contactez le club si vous l'avez perdu.</p>
        )}
      </div>
    )
  }
  const qrSrc = `data:image/png;base64,${result.qrPng}`
  return (
    <div className="essai-result">
      <h2>Inscription confirmée</h2>
      <p>
        <strong>
          {result.firstName} {result.lastName}
        </strong>
        , présentez ce QR code à l'entraîneur <strong>au début de votre cours d'essai</strong>. Il n'est valable que
        pour un seul cours.
      </p>
      <img src={qrSrc} alt="QR code du cours d'essai" className="essai-qr" />
      <p className="essai-hint">
        {result.emailSent
          ? `Un e-mail récapitulatif avec ce QR code a été envoyé à ${result.email}.`
          : 'Faites une capture d’écran de ce QR code pour le garder.'}
      </p>
    </div>
  )
}
