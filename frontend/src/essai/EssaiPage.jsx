import { useEffect, useRef, useState } from 'react'
import SignaturePad from 'signature_pad'
import banner from '../assets/essai-banner.jpg'
import clubLogo from '../assets/club-logo-transparent.png'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Personnes d'une meme famille dans une seule demande (voir backend
// Trials.register) : meme e-mail, une signature, un certificat et un QR
// code par personne.
const MAX_PEOPLE = 3

// Textes du serveur (voir backend trials/content.py) : {eleve}, {parent} et
// {club} remplaces par le ou les noms des eleves, le parent et le club.
function fill(text, names, club, parent = '') {
  return text.replaceAll('{eleve}', names || "l'élève").replaceAll('{club}', club).replaceAll('{parent}', parent)
}

// ["Léa Martin", "Tom Martin"] -> "Léa Martin et Tom Martin".
function joinNames(names) {
  return names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} et ${names.at(-1)}`
}

let nextPersonKey = 0
function emptyPerson(lastName = '') {
  nextPersonKey += 1
  return {
    key: nextPersonKey,
    firstName: '',
    lastName,
    minor: false,
    // Parent d'un mineur : la 1re personne inscrite, sauf case cochee (alors
    // son prenom et son nom sont demandes). Toujours quelqu'un d'autre pour
    // la 1re personne elle-meme.
    parentIsFirst: true,
    parentFirstName: '',
    parentLastName: '',
    age: '',
    certificate: null,
    waiverAccepted: false,
  }
}

const EMPTY_FORM = {
  email: '',
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

// Ordre voulu par le club, pour chaque personne : prenom, nom, "mineur",
// (mineur : parent ou representant legal), e-mail (1re personne seulement,
// recopie pour les autres), (mineur : age), certificat, decharge. Puis le
// bouton d'ajout d'une personne de la meme famille, et a la fin les
// signatures : la 1re personne, et chaque representant legal exterieur (sa
// signature vaut autorisation parentale).
function RegistrationForm({ info, onDone }) {
  const [people, setPeople] = useState(() => [emptyPerson()])
  const [form, setForm] = useState(EMPTY_FORM)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  // Pads de signature montes, par cle ("first", "parent-0", "parent-1"...).
  const pads = useRef({})

  const fullName = (p) => `${p.firstName} ${p.lastName}`.trim()
  const firstName = fullName(people[0]) || 'la 1re personne'
  const parentIsFirst = (p, i) => i > 0 && p.parentIsFirst
  const parentName = (p, i) =>
    parentIsFirst(p, i) ? fullName(people[0]) : `${p.parentFirstName} ${p.parentLastName}`.trim()
  // Qui signe : la 1re personne si elle est majeure (un mineur ne signe
  // pas), puis les autres signataires, un seul par nom (voir backend
  // Trials._validate_registration) : chaque representant legal exterieur
  // (avec ses enfants, pour le texte d'autorisation parentale), et un majeur
  // de la famille quand la 1re personne est mineure (il signe pour lui).
  const firstSigns = !people[0].minor
  const childrenOfFirst = people.filter((p, i) => p.minor && parentIsFirst(p, i))
  const externalParents = []
  people.forEach((p, i) => {
    let name
    if (p.minor && !parentIsFirst(p, i)) name = parentName(p, i)
    else if (!p.minor && !firstSigns) name = fullName(p)
    else return
    const existing = externalParents.find((parent) => parent.name.toLowerCase() === name.toLowerCase())
    if (existing) {
      if (p.minor) existing.children.push(p)
    } else {
      externalParents.push({ name, children: p.minor ? [p] : [] })
    }
  })

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
      return setError(`Merci de joindre le certificat médical de ${fullName(people[missing]) || 'chaque personne'}`)
    }
    if (firstSigns && pads.current.first?.isEmpty()) return setError(`Merci de faire signer ${firstName}`)
    const unsigned = externalParents.find((parent, k) => pads.current[`parent-${k}`]?.isEmpty())
    if (unsigned) return setError(`Merci de faire signer ${unsigned.name || 'le parent ou représentant légal'}`)
    const body = new FormData()
    body.append('email', form.email)
    people.forEach((p, i) => {
      body.append(`firstName${i}`, p.firstName)
      body.append(`lastName${i}`, p.lastName)
      body.append(`minor${i}`, p.minor)
      body.append(`age${i}`, p.minor ? p.age : '')
      body.append(`parentIsFirst${i}`, p.minor && parentIsFirst(p, i))
      body.append(`parentFirstName${i}`, p.minor && !parentIsFirst(p, i) ? p.parentFirstName : '')
      body.append(`parentLastName${i}`, p.minor && !parentIsFirst(p, i) ? p.parentLastName : '')
      body.append(`waiverAccepted${i}`, p.waiverAccepted)
      body.append(`certificate${i}`, p.certificate)
    })
    body.append('signature', firstSigns ? pads.current.first.toDataUrl() : '')
    externalParents.forEach((parent, k) => {
      body.append(`parentSignatureName${k}`, parent.name)
      body.append(`parentSignature${k}`, pads.current[`parent-${k}`].toDataUrl())
    })
    body.append('termsVersion', info.termsVersion)
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
          <legend>{i === 0 ? 'La personne à inscrire' : `Personne ${i + 1} (même famille)`}</legend>
          <label>
            Prénom
            <input
              value={p.firstName}
              onChange={updatePerson(i, 'firstName')}
              required
              autoComplete={i === 0 ? 'given-name' : 'off'}
            />
          </label>
          <label>
            Nom
            <input
              value={p.lastName}
              onChange={updatePerson(i, 'lastName')}
              required
              autoComplete={i === 0 ? 'family-name' : 'off'}
            />
          </label>
          <label className="essai-check">
            <input type="checkbox" checked={p.minor} onChange={updatePerson(i, 'minor')} />
            <span>Cette personne est mineure</span>
          </label>

          {p.minor && (
            <div className="essai-subgroup">
              <span className="essai-subgroup-title">Parent ou représentant légal</span>
              {i > 0 && (
                <label className="essai-check">
                  <input
                    type="checkbox"
                    checked={!p.parentIsFirst}
                    onChange={(e) =>
                      setPeople((prev) => prev.map((q, j) => (j === i ? { ...q, parentIsFirst: !e.target.checked } : q)))
                    }
                  />
                  <span>Le parent ou représentant légal n'est pas {firstName}</span>
                </label>
              )}
              {parentIsFirst(p, i) ? (
                <p className="essai-hint">{firstName}</p>
              ) : (
                <>
                  <label>
                    Prénom du parent
                    <input value={p.parentFirstName} onChange={updatePerson(i, 'parentFirstName')} required />
                  </label>
                  <label>
                    Nom du parent
                    <input value={p.parentLastName} onChange={updatePerson(i, 'parentLastName')} required />
                  </label>
                </>
              )}
            </div>
          )}

          {i === 0 && (
            <label>
              E-mail
              <input
                type="email"
                inputMode="email"
                value={form.email}
                onChange={(e) => setForm((prev) => ({ ...prev, email: e.target.value }))}
                required
                autoComplete="email"
              />
              <small>Le QR code vous sera envoyé à cette adresse.</small>
            </label>
          )}

          {p.minor && (
            <label>
              Âge
              <input
                type="number"
                inputMode="numeric"
                min="9"
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
              Retirer cette personne
            </button>
          )}
        </fieldset>
      ))}

      {people.length < MAX_PEOPLE && (
        <button
          type="button"
          className="essai-add-person"
          onClick={() => setPeople((prev) => [...prev, emptyPerson(prev[0].lastName)])}
        >
          + Ajouter une personne de la même famille
          <small>(celle-ci aura le même mail, sinon faire une autre demande)</small>
        </button>
      )}

      <fieldset>
        <legend>{(firstSigns ? 1 : 0) + externalParents.length > 1 ? 'Signatures' : 'Signature'}</legend>
        {firstSigns && (
          <div className="essai-signature-block">
            <span className="essai-subgroup-title">Signature de {firstName}</span>
            {childrenOfFirst.length > 0 && (
              <p className="essai-hint">
                {fill(info.parentalConsent, joinNames(childrenOfFirst.map(fullName)), info.club, fullName(people[0]))}
              </p>
            )}
            <SignatureField pads={pads} name="first" />
          </div>
        )}
        {externalParents.map((parent, k) => (
          // Cle = numero (pas le nom) : corriger le nom du parent ne doit pas
          // effacer sa signature.
          <div key={k} className="essai-signature-block">
            <span className="essai-subgroup-title">
              Signature de {parent.name || 'du parent ou représentant légal'}
            </span>
            {parent.children.length > 0 && (
              <p className="essai-hint">
                {fill(info.parentalConsent, joinNames(parent.children.map(fullName)), info.club, parent.name)}
              </p>
            )}
            <SignatureField pads={pads} name={`parent-${k}`} />
          </div>
        ))}
      </fieldset>

      {error && <p className="essai-error">{error}</p>}

      <button type="submit" className="essai-submit" disabled={pending}>
        {pending ? 'Envoi…' : 'Valider mon inscription'}
      </button>
    </form>
  )
}

// Signature au doigt (ou a la souris) : bibliotheque signature_pad, qui gere
// le tactile sur Android comme sur iPhone. Le canvas est redimensionne a la
// largeur de l'ecran (et a la densite de pixels) sans perdre le trace. Le
// pad est enregistre dans pads.current[name] (isEmpty, toDataUrl).
function SignatureField({ pads, name }) {
  const canvasRef = useRef(null)
  const signaturePad = useRef(null)
  const [empty, setEmpty] = useState(true)

  useEffect(() => {
    const canvas = canvasRef.current
    const pad = new SignaturePad(canvas, { penColor: '#111', backgroundColor: 'rgb(255,255,255)' })
    signaturePad.current = pad
    pad.addEventListener('endStroke', () => setEmpty(pad.isEmpty()))
    const registry = pads.current
    registry[name] = {
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
      delete registry[name]
    }
  }, [pads, name])

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
