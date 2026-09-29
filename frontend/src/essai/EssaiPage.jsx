import { useEffect, useRef, useState } from 'react'
import SignaturePad from 'signature_pad'
import banner from '../assets/essai-banner.jpg'
import clubLogo from '../assets/club-logo-transparent.png'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Personnes d'une meme famille dans une seule demande (voir backend
// Trials.register) : meme e-mail, une signature, un certificat et un QR
// code par personne.
const MAX_PEOPLE = 3

// Textes du serveur (voir backend trials/content.py) : {eleve} et {club}
// remplaces par le ou les noms des personnes et le nom du club.
function fill(text, names, club) {
  return text.replaceAll('{eleve}', names || "l'élève").replaceAll('{club}', club)
}

// ["Léa Martin", "Tom Martin"] -> "Léa Martin et Tom Martin".
function joinNames(names) {
  return names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} et ${names.at(-1)}`
}

let nextPersonKey = 0
function emptyPerson() {
  nextPersonKey += 1
  return { key: nextPersonKey, firstName: '', lastName: '', minor: false, age: '', certificate: null, waiverAccepted: false }
}

const EMPTY_FORM = {
  email: '',
  parentName: '',
  parentalConsent: false,
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

// Ordre voulu par le club : 1re personne (prenom, nom, e-mail, age si
// mineur, certificat, decharge), puis eventuellement jusqu'a 2 membres de la
// meme famille (prenom, age si mineur, certificat, decharge -- nom et e-mail
// repris de la 1re personne), puis le parent si un mineur est inscrit, puis
// la signature (une seule pour toute la demande).
function RegistrationForm({ info, onDone }) {
  const [people, setPeople] = useState(() => [emptyPerson()])
  const [form, setForm] = useState(EMPTY_FORM)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const padRef = useRef(null)

  const lastName = people[0].lastName
  const fullName = (p) => `${p.firstName} ${lastName}`.trim()
  const minors = people.filter((p) => p.minor)
  const anyMinor = minors.length > 0

  function update(key) {
    return (e) => {
      const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
      setForm((prev) => ({ ...prev, [key]: value }))
    }
  }

  function updatePerson(index, key) {
    return (e) => {
      const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
      setPeople((prev) => prev.map((p, i) => (i === index ? { ...p, [key]: value } : p)))
    }
  }

  function setCertificate(index, file) {
    setPeople((prev) => prev.map((p, i) => (i === index ? { ...p, certificate: file } : p)))
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    const missing = people.findIndex((p) => !p.certificate)
    if (missing !== -1) {
      return setError(
        people.length > 1
          ? `Merci de joindre le certificat médical de ${people[missing].firstName || `la personne ${missing + 1}`}`
          : 'Merci de joindre le certificat médical'
      )
    }
    if (padRef.current.isEmpty()) return setError('Merci de signer dans le cadre prévu')
    const body = new FormData()
    people.forEach((p, i) => {
      body.append(`firstName${i}`, p.firstName)
      body.append(`lastName${i}`, lastName)
      body.append(`minor${i}`, p.minor)
      body.append(`age${i}`, p.minor ? p.age : '')
      body.append(`waiverAccepted${i}`, p.waiverAccepted)
      body.append(`certificate${i}`, p.certificate)
    })
    body.append('email', form.email)
    body.append('parentName', anyMinor ? form.parentName : '')
    body.append('parentalConsent', anyMinor && form.parentalConsent)
    body.append('website', form.website)
    body.append('termsVersion', info.termsVersion)
    body.append('signature', padRef.current.toDataUrl())
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
      {people.map((p, i) => (
        <fieldset key={p.key}>
          <legend>{i === 0 ? 'La personne à inscrire' : `Membre de la famille ${i + 1}`}</legend>
          <label>
            Prénom
            <input
              value={p.firstName}
              onChange={updatePerson(i, 'firstName')}
              required
              autoComplete={i === 0 ? 'given-name' : 'off'}
            />
          </label>
          {i === 0 && (
            <>
              <label>
                Nom
                <input value={p.lastName} onChange={updatePerson(i, 'lastName')} required autoComplete="family-name" />
              </label>
              <label>
                E-mail
                <input
                  type="email"
                  inputMode="email"
                  value={form.email}
                  onChange={update('email')}
                  required
                  autoComplete="email"
                />
                <small>Le QR code vous sera envoyé à cette adresse (celui de chaque membre de la famille aussi).</small>
              </label>
            </>
          )}
          <label className="essai-check">
            <input type="checkbox" checked={p.minor} onChange={updatePerson(i, 'minor')} />
            <span>{i === 0 ? 'Cette personne est mineure' : 'Mineur(e)'}</span>
          </label>
          {p.minor && (
            <label>
              Âge
              <input
                type="number"
                inputMode="numeric"
                min="3"
                max="17"
                value={p.age}
                onChange={updatePerson(i, 'age')}
                required
                className="essai-age"
              />
            </label>
          )}
          <div className="essai-label">
            Certificat médical
            <small>{info.medicalCertificateHint}</small>
            {/* accept image/* : propose l'appareil photo sur Android et iPhone. */}
            <label className="essai-file">
              <input
                type="file"
                accept="image/*,application/pdf,.heic,.heif"
                onChange={(e) => setCertificate(i, e.target.files[0] ?? null)}
              />
              {p.certificate ? `📎 ${p.certificate.name}` : '📷 Joindre le certificat médical'}
            </label>
            {p.certificate && (
              <button type="button" className="essai-link" onClick={() => setCertificate(i, null)}>
                Retirer le certificat
              </button>
            )}
          </div>
          <label className="essai-check">
            <input type="checkbox" checked={p.waiverAccepted} onChange={updatePerson(i, 'waiverAccepted')} required />
            <span>
              <strong>Décharge de responsabilité : </strong>
              {fill(info.waiver, fullName(p), info.club)}
            </span>
          </label>
          {i > 0 && (
            <button
              type="button"
              className="essai-link essai-remove-person"
              onClick={() => setPeople((prev) => prev.filter((_, j) => j !== i))}
            >
              Retirer ce membre de la famille
            </button>
          )}
        </fieldset>
      ))}

      {people.length < MAX_PEOPLE && (
        <button
          type="button"
          className="essai-add-person"
          onClick={() => setPeople((prev) => [...prev, emptyPerson()])}
        >
          + Ajouter un membre de la même famille
        </button>
      )}

      {anyMinor && (
        <fieldset>
          <legend>Parent ou représentant légal</legend>
          <label>
            Nom et prénom
            <input value={form.parentName} onChange={update('parentName')} required autoComplete="name" />
          </label>
          <label className="essai-check">
            <input type="checkbox" checked={form.parentalConsent} onChange={update('parentalConsent')} required />
            <span>{fill(info.parentalConsent, joinNames(minors.map(fullName).filter(Boolean)), info.club)}</span>
          </label>
        </fieldset>
      )}

      <fieldset>
        <legend>{anyMinor ? 'Signature du parent ou représentant légal' : 'Signature'}</legend>
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

// Resultat : le QR code de chaque personne nouvellement inscrite. Une
// personne deja inscrite ne voit pas le sien (il lui est renvoye par mail).
function Result({ result }) {
  const created = result.people.filter((p) => p.status === 'created')
  const existing = result.people.filter((p) => p.status === 'existing')
  const name = (p) => `${p.firstName} ${p.lastName}`
  return (
    <div className="essai-result">
      {created.length > 0 && (
        <>
          <h2>Inscription confirmée</h2>
          <p>
            Présentez {created.length > 1 ? 'le QR code de chaque personne' : 'ce QR code'} à l'entraîneur{' '}
            <strong>au début du cours d'essai</strong>. {created.length > 1 ? 'Chacun n’est' : 'Il n’est'} valable que
            pour un seul cours.
          </p>
          {created.map((p) => (
            <figure key={name(p)} className="essai-qr-card">
              <img src={`data:image/png;base64,${p.qrPng}`} alt={`QR code de ${name(p)}`} className="essai-qr" />
              <figcaption>{name(p)}</figcaption>
            </figure>
          ))}
        </>
      )}
      {existing.length > 0 && (
        <div className="essai-existing">
          <h2>{existing.length > 1 ? 'Déjà inscrits' : 'Déjà inscrit(e)'}</h2>
          <p>
            <strong>{joinNames(existing.map(name))}</strong>{' '}
            {existing.length > 1 ? 'étaient déjà inscrits' : 'était déjà inscrit(e)'} au cours d'essai.{' '}
            {result.emailSent
              ? 'Le QR code vient d’être renvoyé par e-mail.'
              : 'Le QR code a été envoyé lors de la première inscription : contactez le club en cas de perte.'}
          </p>
        </div>
      )}
      <p className="essai-hint">
        {result.emailSent
          ? `Un e-mail récapitulatif avec ${result.people.length > 1 ? 'les QR codes' : 'le QR code'} a été envoyé à ${result.email} (pensez à regarder dans les courriers indésirables).`
          : 'Faites une capture d’écran pour garder vos QR codes.'}
      </p>
    </div>
  )
}
