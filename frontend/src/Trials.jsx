import { useCallback, useEffect, useRef, useState } from 'react'
import QrScanner from 'qr-scanner'
import { memberIdentifier, normaliserTexte } from './HelloAsso.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = Array.isArray(body?.detail) ? 'Champ invalide' : body?.detail
    throw new Error(detail || `${path} a échoué (${response.status})`)
  }
  return response.json()
}

function sendJson(path, method, body) {
  return callApi(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

function dateFr(isoDate) {
  if (!isoDate) return ''
  const [year, month, day] = isoDate.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

// Horodatage du serveur (UTC) -> date locale : une inscription a 1 h du
// matin a Paris ne doit pas s'afficher a la date de la veille.
function timestampFr(isoTimestamp) {
  return isoTimestamp ? new Date(isoTimestamp).toLocaleDateString('fr-FR') : ''
}

// Version courte (26/09/26) pour les colonnes de cours : le tableau doit
// tenir sur un ecran de telephone.
function shortDateFr(isoDate) {
  return dateFr(isoDate).replace(/\/\d\d(\d\d)$/, '/$1')
}

function shortTimestampFr(isoTimestamp) {
  return timestampFr(isoTimestamp).replace(/\/\d\d(\d\d)$/, '/$1')
}

// QR code scanne avec l'appareil photo "normal" du telephone : il contient
// l'adresse de l'appli suivie de ?essai=<jeton> (voir backend
// Trials.checkin_url), ce qui ouvre l'appli. Lu UNE fois au chargement (avant
// meme la connexion a l'appli) puis retire de la barre d'adresse, pour ne pas
// etre rejoue en rechargeant la page ; traite par TrialsTable une fois monte.
const checkinFromUrl = (() => {
  const token = new URLSearchParams(window.location.search).get('essai')
  if (!token) return null
  window.history.replaceState({}, '', window.location.pathname)
  return token
})()

// App.jsx l'utilise pour ouvrir directement l'onglet Essai.
export const hasTrialCheckin = checkinFromUrl !== null

// Une seule fois meme si le composant est monte deux fois (React StrictMode).
let urlCheckinPromise = null

function checkIn(scanned) {
  return sendJson('/trials/checkin', 'POST', { token: scanned })
}

// Puces de filtre (meme charte que HelloAsso/Adherents) : "Non-adherents"
// par defaut, les eleves a l'essai deja inscrits au club etant en general
// sans interet ici.
const MEMBER_FILTERS = [
  { value: 'tous', label: 'Tous' },
  { value: 'non-adherents', label: 'Non-adhérents' },
]

const EMPTY_FORM = {
  firstName: '',
  lastName: '',
  age: '',
  gender: '',
  email: '',
  phone: '',
  parentName: '',
  comment: '',
}

// Formulaire -> corps JSON : chaines vides -> null (champ efface), sauf le
// commentaire (toujours une chaine).
function formToBody(form) {
  return Object.fromEntries(
    Object.entries(form).map(([key, value]) => [key, key === 'comment' ? value : String(value).trim() || null])
  )
}

// Icone poubelle dessinee (pas un emoji : pas affiche pareil, voire pas du
// tout, selon les telephones).
function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" />
    </svg>
  )
}

// Commentaire modifiable directement dans le tableau : enregistre seulement
// apres validation (bouton ✓ ou touche Entree) ; ✕ ou Echap annule.
function CommentCell({ student, onSaved }) {
  const [draft, setDraft] = useState(student.comment)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const changed = draft !== student.comment

  // Commentaire modifie ailleurs (fiche de l'eleve, rafraichissement).
  useEffect(() => {
    setDraft(student.comment)
  }, [student.comment])

  async function save() {
    setPending(true)
    setError(null)
    try {
      onSaved(await sendJson(`/trials/students/${student.id}`, 'PATCH', { comment: draft }))
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && changed) {
      e.preventDefault()
      save()
    } else if (e.key === 'Escape') {
      setDraft(student.comment)
    }
  }

  return (
    <div className="trial-comment-edit">
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ajouter…"
        aria-label={`Commentaire sur ${student.firstName} ${student.lastName}`}
        className={changed ? 'trial-comment-changed' : undefined}
        disabled={pending}
      />
      {changed && (
        <>
          <button type="button" className="trial-comment-save" onClick={save} disabled={pending} title="Enregistrer">
            ✓
          </button>
          <button type="button" onClick={() => setDraft(student.comment)} disabled={pending} title="Annuler">
            ✕
          </button>
        </>
      )}
      {error && <span className="trial-comment-error">{error}</span>}
    </div>
  )
}

// Date du jour au format AAAA-MM-JJ (heure locale).
function todayIso() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

// Etat des cours d'essai d'un eleve, pour la couleur des colonnes de cours :
// aucun (blanc), un cours fait aujourd'hui (vert), un cours fait un autre
// jour (orange), les 2 cours faits (rouge).
function coursesState(student) {
  const done = student.courses.filter((c) => c.date)
  if (done.length === 0) return 'none'
  if (done.length >= 2) return 'done'
  return done[0].date === todayIso() ? 'today' : 'past'
}

function CourseCell({ course }) {
  if (!course.date) return <span className="trial-course-empty">—</span>
  return (
    <span className="trial-course">
      {shortDateFr(course.date)}
      <span className={`trial-mode trial-mode-${course.mode}`}>{course.mode === 'qr' ? 'QR' : 'manuel'}</span>
    </span>
  )
}

// Onglet "Essai" : eleves en cours d'essai (voir backend trials/trials.py
// pour les regles : un QR code a usage unique par eleve, 2 cours maximum).
// Normalement l'eleve s'inscrit lui-meme sur la page publique ; l'ajout a
// la main ici est exceptionnel.
export function TrialsTable() {
  const [students, setStudents] = useState(null)
  const [error, setError] = useState(null)
  const [pendingId, setPendingId] = useState(null)
  // Eleve dont la fiche est ouverte (modification), null sinon.
  const [editing, setEditing] = useState(null)
  // Fenetre du scanner (ouverte si non null) : {initial}, resultat deja
  // obtenu a l'ouverture (QR code scanne avec l'appareil photo), ou null.
  const [scan, setScan] = useState(null)
  // Filtres facon HelloAsso/Adherents : recherche textuelle (nom, prenom,
  // e-mail, sans tenir compte des majuscules ni des accents) et puce
  // "Tous" / "Non-adherents". Adherent = present dans HelloAsso/Adherents
  // (meme nom et prenom, voir memberIdentifier) ; liste chargee seulement
  // si la puce "Non-adherents" est choisie (l'API HelloAsso est lente).
  const [recherche, setRecherche] = useState('')
  const [filtreAdherents, setFiltreAdherents] = useState('non-adherents')
  const [memberIds, setMemberIds] = useState(null)
  const [membersError, setMembersError] = useState(null)
  const hideMembers = filtreAdherents === 'non-adherents'

  useEffect(() => {
    if (!hideMembers || memberIds || membersError) return
    callApi('/helloasso/members')
      .then((members) => setMemberIds(new Set(members.map((m) => memberIdentifier(m.lastName, m.firstName)))))
      .catch((err) => setMembersError(`Adhérents HelloAsso indisponibles : ${err.message}`))
  }, [hideMembers, memberIds, membersError])

  const visibleStudents = (students ?? []).filter((s) => {
    if (hideMembers && memberIds?.has(memberIdentifier(s.lastName, s.firstName))) return false
    if (recherche.trim()) {
      const cible = normaliserTexte(`${s.lastName} ${s.firstName} ${s.email ?? ''}`)
      if (!cible.includes(normaliserTexte(recherche))) return false
    }
    return true
  })

  const refetch = useCallback(async () => {
    try {
      setStudents(await callApi('/trials/students'))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  // Retour dans l'appli apres une inscription faite dans un autre onglet
  // (bouton "Ajouter un eleve") : la liste se met a jour d'elle-meme.
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === 'visible') refetch()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refetch])

  function replaceStudent(updated) {
    setStudents((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
  }

  // Resultat d'un scan : met a jour la ligne de l'eleve (le scanner, lui,
  // affiche le message et continue).
  const applyCheckin = useCallback((result) => {
    if (result.student) {
      setStudents((prev) => prev && prev.map((s) => (s.id === result.student.id ? result.student : s)))
    }
    if (result.status === 'added') navigator.vibrate?.(200)
  }, [])

  // Ouverture de l'appli par le QR code (appareil photo du telephone) :
  // resultat affiche dans le scanner, qui reste ouvert pour les suivants.
  useEffect(() => {
    if (!checkinFromUrl) return
    urlCheckinPromise ??= checkIn(checkinFromUrl)
    urlCheckinPromise.then(
      (result) => {
        applyCheckin(result)
        setScan({ initial: result })
      },
      (err) => setError(err.message)
    )
  }, [applyCheckin])

  async function addCourse(student) {
    setPendingId(student.id)
    setError(null)
    try {
      replaceStudent(await sendJson(`/trials/students/${student.id}/courses`, 'POST', {}))
    } catch (err) {
      setError(err.message)
    } finally {
      setPendingId(null)
    }
  }

  async function deleteStudent(student) {
    if (!window.confirm(`Supprimer définitivement ${student.firstName} ${student.lastName} ?`)) return
    setPendingId(student.id)
    setError(null)
    try {
      await callApi(`/trials/students/${student.id}`, { method: 'DELETE' })
      setStudents((prev) => prev.filter((s) => s.id !== student.id))
    } catch (err) {
      setError(err.message)
    } finally {
      setPendingId(null)
    }
  }

  return (
    <section>
      <div className="section-header">
        <h2>Élèves à l'essai ({students?.length ?? '…'})</h2>
        <button onClick={refetch}>Rafraîchir</button>
      </div>

      {/* Juste sous le titre, sur une meme ligne : scan du QR code presente
          par l'eleve en debut de cours (souvent d'une main), et ajout d'un
          inscrit avec le meme formulaire que l'inscription en ligne
          (majeur/mineur, parent, certificat, decharge, signatures, QR code
          et mail), ouvert dans un nouvel onglet. */}
      <div className="trial-actions">
        <button className="trial-scan-button" onClick={() => setScan({ initial: null })}>
          QR code
        </button>
        <a
          className="trial-add-student-button"
          href={`${import.meta.env.BASE_URL}essai.html`}
          target="_blank"
          rel="noreferrer"
        >
          Ajouter inscrit manuellement
        </a>
      </div>

      <div className="member-filters trial-filters">
        <label className="member-search">
          <span aria-hidden="true">🔍</span>
          <input
            type="search"
            name="trial-search"
            placeholder="Rechercher un inscrit au cours d'essai..."
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
          />
        </label>
        <div className="filter-chips" role="group" aria-label="Filtrer les adhérents">
          {MEMBER_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              className={filtreAdherents === value ? 'filter-chip filter-chip-active' : 'filter-chip'}
              aria-pressed={filtreAdherents === value}
              onClick={() => setFiltreAdherents(value)}
            >
              {label}
            </button>
          ))}
          {hideMembers && !memberIds && !membersError && (
            <span className="trial-filter-hint">chargement des adhérents…</span>
          )}
        </div>
      </div>
      {hideMembers && membersError && <p className="warning">{membersError}</p>}

      {error && <p className="error">{error}</p>}

      {students &&
        (students.length === 0 ? (
          <p className="empty-state">Aucun élève à l'essai pour l'instant</p>
        ) : visibleStudents.length === 0 ? (
          <p className="empty-state">
            {recherche.trim() ? 'Aucun inscrit ne correspond à la recherche' : "Tous les élèves à l'essai sont déjà adhérents"}
          </p>
        ) : (
          <div className="table-wrapper">
            <table className="trials-table">
              <thead>
                <tr>
                  <th>Élève</th>
                  <th>Âge</th>
                  <th className="col-secondary">QR code</th>
                  <th>1er cours</th>
                  <th>2e cours</th>
                  <th>Inscription</th>
                  <th>Commentaire</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {visibleStudents.map((s) => {
                  const full = s.courses.every((c) => c.date)
                  return (
                    <tr key={s.id}>
                      <td className="trial-name-cell">
                        {/* Clic sur le nom : fiche complete (modification,
                            correction des dates, suppression). */}
                        <button className="trial-name" onClick={() => setEditing(s)}>
                          {s.firstName} {s.lastName}
                        </button>
                      </td>
                      {/* Inscription en ligne : pas de date de naissance, seulement
                          majeur/mineur (mineur = autorisation parentale donnee). */}
                      <td>{s.age ?? (s.source === 'web' ? (s.parentalConsent ? 'mineur' : 'majeur') : '—')}</td>
                      <td className="col-secondary">{s.qrGenerated ? `✓ ${timestampFr(s.qrCreatedAt)}` : '—'}</td>
                      <td className={`trial-courses-${coursesState(s)}`}>
                        <CourseCell course={s.courses[0]} />
                      </td>
                      <td className={`trial-courses-${coursesState(s)}`}>
                        <CourseCell course={s.courses[1]} />
                      </td>
                      {/* Date d'inscription au cours d'essai (en ligne ou ajout
                          a la main). */}
                      <td title={s.source === 'web' ? 'Inscrit en ligne' : 'Ajouté à la main'}>
                        {shortTimestampFr(s.createdAt)}
                      </td>
                      <td className="trial-comment">
                        <CommentCell student={s} onSaved={replaceStudent} />
                      </td>
                      <td>
                        <button
                          className="trial-add-course"
                          disabled={full || pendingId === s.id}
                          title={full ? "Les 2 cours d'essai sont déjà renseignés" : "Ajoute la date du jour"}
                          onClick={() => addCourse(s)}
                        >
                          + Cours
                        </button>
                        <button
                          className="trial-delete-row"
                          disabled={pendingId === s.id}
                          title="Supprimer l'élève"
                          aria-label={`Supprimer ${s.firstName} ${s.lastName}`}
                          onClick={() => deleteStudent(s)}
                        >
                          <TrashIcon />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}

      {scan && <ScanDialog initialResult={scan.initial} onResult={applyCheckin} onClose={() => setScan(null)} />}

      {editing && (
        <StudentDialog
          student={editing}
          family={editing.familyId ? students.filter((s) => s.familyId === editing.familyId && s.id !== editing.id) : []}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null)
            replaceStudent(saved)
          }}
          onDeleted={(id) => {
            setEditing(null)
            setStudents((prev) => prev.filter((s) => s.id !== id))
          }}
        />
      )}
    </section>
  )
}

// Fiche d'un eleve : modification, correction des dates de cours,
// suppression (l'ajout passe par le formulaire d'inscription). <dialog>
// natif : fond assombri, touche Echap et accessibilite geres par le
// navigateur (Android comme iPhone).
function StudentDialog({ student, family, onClose, onSaved, onDeleted }) {
  const dialogRef = useRef(null)
  const [form, setForm] = useState(() =>
    Object.fromEntries(Object.keys(EMPTY_FORM).map((key) => [key, student[key] ?? '']))
  )
  const [courseDates, setCourseDates] = useState(() => student.courses.map((c) => c.date ?? ''))
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    dialogRef.current.showModal()
  }, [])

  function update(key) {
    return (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))
  }

  async function save(e) {
    e.preventDefault()
    setPending(true)
    setError(null)
    try {
      let saved = await sendJson(`/trials/students/${student.id}`, 'PATCH', formToBody(form))
      for (const [i, course] of student.courses.entries()) {
        if ((course.date ?? '') !== courseDates[i]) {
          saved = await sendJson(`/trials/students/${student.id}/courses/${course.number}`, 'PUT', {
            date: courseDates[i] || null,
          })
        }
      }
      onSaved(saved)
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  async function remove() {
    if (!window.confirm(`Supprimer définitivement ${student.firstName} ${student.lastName} ?`)) return
    setPending(true)
    setError(null)
    try {
      await callApi(`/trials/students/${student.id}`, { method: 'DELETE' })
      onDeleted(student.id)
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  return (
    <dialog ref={dialogRef} className="trial-dialog" onClose={onClose}>
      <form onSubmit={save}>
        <h3>
          {student.firstName} {student.lastName}
        </h3>

        <div className="trial-form-grid">
          <label>
            Prénom *
            <input value={form.firstName} onChange={update('firstName')} required autoComplete="off" />
          </label>
          <label>
            Nom *
            <input value={form.lastName} onChange={update('lastName')} required autoComplete="off" />
          </label>
          <label>
            Âge
            <input type="number" inputMode="numeric" min="3" max="100" value={form.age} onChange={update('age')} />
          </label>
          <label>
            Genre
            <select value={form.gender} onChange={update('gender')}>
              <option value="">—</option>
              <option value="M">Homme</option>
              <option value="F">Femme</option>
            </select>
          </label>
          <label>
            E-mail
            <input type="email" inputMode="email" value={form.email} onChange={update('email')} autoComplete="off" />
          </label>
          <label>
            Téléphone
            <input type="tel" inputMode="tel" value={form.phone} onChange={update('phone')} autoComplete="off" />
          </label>
          <label>
            Parent (si mineur)
            <input value={form.parentName} onChange={update('parentName')} autoComplete="off" />
          </label>
          {student.courses.map((course, i) => (
            <label key={course.number}>
              {course.number === 1 ? '1er' : '2e'} cours{course.mode === 'qr' ? ' (QR code)' : ''}
              <span className="trial-course-input">
                <input
                  type="date"
                  value={courseDates[i]}
                  onChange={(e) => setCourseDates((prev) => prev.map((d, j) => (j === i ? e.target.value : d)))}
                />
                {courseDates[i] && (
                  <button
                    type="button"
                    title="Effacer ce cours"
                    onClick={() => setCourseDates((prev) => prev.map((d, j) => (j === i ? '' : d)))}
                  >
                    ✕
                  </button>
                )}
              </span>
            </label>
          ))}
          <label className="trial-form-wide">
            Commentaire
            <textarea rows={3} value={form.comment} onChange={update('comment')} />
          </label>
        </div>

        <p className="profile-hint">
          {student.source === 'web' ? 'Inscrit en ligne' : 'Ajouté à la main'} le {timestampFr(student.createdAt)}
          {student.qrGenerated ? ' · QR code généré' : ' · pas de QR code'}
        </p>
        {family.length > 0 && (
          <p className="profile-hint">
            Même demande que : {family.map((s) => `${s.firstName} ${s.lastName}`).join(', ')}
          </p>
        )}
        {(student.hasSignature || student.hasMedicalCertificate) && (
          <p className="trial-documents">
            {student.hasSignature && (
              <a href={`${API_URL}/trials/students/${student.id}/signature`} target="_blank" rel="noreferrer">
                Voir la signature
              </a>
            )}
            {student.hasMedicalCertificate && (
              <a href={`${API_URL}/trials/students/${student.id}/certificate`} target="_blank" rel="noreferrer">
                Voir le certificat médical
              </a>
            )}
          </p>
        )}

        {error && <p className="error">{error}</p>}

        <div className="trial-dialog-actions">
          <button type="button" className="trial-delete" onClick={remove} disabled={pending}>
            Supprimer
          </button>
          <button type="button" onClick={() => dialogRef.current.close()} disabled={pending}>
            Annuler
          </button>
          <button type="submit" className="trial-save" disabled={pending}>
            Enregistrer
          </button>
        </div>
      </form>
    </dialog>
  )
}

// Resultat d'un scan (voir backend Trials.check_in) : message et couleur.
// Vert : 1er cours enregistre, ou deja enregistre aujourd'hui ; orange : 2e
// cours enregistre (exception) ; rouge : 2 cours deja faits, code inconnu.
function scanColor(result) {
  if (result.status === 'added') return result.course === 1 ? 'ok' : 'warn'
  return result.status === 'today' ? 'ok' : 'ko'
}

const CHECKIN_MESSAGES = {
  added: (r) => `${r.course === 1 ? '1er' : '2e'} cours d'essai enregistré`,
  today: () => "Déjà enregistré aujourd'hui",
  full: () => "Les 2 cours d'essai ont déjà été faits",
  unknown: () => 'Code inconnu',
}

// Scanner de QR code en continu (camera arriere, bibliotheque qr-scanner :
// fonctionne sur Android comme sur iPhone, ou Safari ne sait pas lire les QR
// codes seul). Chaque QR code lu
// est verifie (voir backend Trials.check_in), son resultat s'ajoute en haut
// d'une liste compacte (voir scanColor) et la camera continue : plusieurs eleves a la suite sans rien
// toucher. Un meme QR code n'est traite qu'une fois tant que la fenetre est
// ouverte (sinon, reste devant la camera, il serait relu en boucle).
function ScanDialog({ initialResult, onResult, onClose }) {
  const dialogRef = useRef(null)
  const videoRef = useRef(null)
  const seen = useRef(new Set())
  // Resultats des QR codes lus, le plus recent en premier.
  const nextKey = useRef(1)
  const [results, setResults] = useState(() => (initialResult ? [{ ...initialResult, key: 0 }] : []))
  const [cameraError, setCameraError] = useState(null)
  const [pending, setPending] = useState(0)

  // Focus sur la fenetre elle-meme (tabIndex -1) plutot que sur la croix de
  // fermeture (premier element focalisable) : pas de contour de focus
  // affiche sur la croix a l'ouverture.
  useEffect(() => {
    dialogRef.current.showModal()
    dialogRef.current.focus()
  }, [])

  const verify = useCallback(
    async (scanned) => {
      setPending((n) => n + 1)
      let entry
      try {
        const result = await checkIn(scanned)
        onResult(result)
        entry = result
      } catch (err) {
        entry = { status: 'error', message: err.message }
      } finally {
        setPending((n) => n - 1)
      }
      const key = nextKey.current++
      setResults((prev) => [{ ...entry, key }, ...prev])
    },
    [onResult]
  )

  // Camera allumee tant que la fenetre est ouverte.
  useEffect(() => {
    const scanner = new QrScanner(
      videoRef.current,
      (decoded) => {
        if (seen.current.has(decoded.data)) return
        seen.current.add(decoded.data)
        verify(decoded.data)
      },
      { preferredCamera: 'environment', highlightScanRegion: true, returnDetailedScanResult: true, maxScansPerSecond: 8 }
    )
    scanner.start().catch(() =>
      setCameraError(
        "Caméra indisponible : autorise l'accès à la caméra pour ce site dans les réglages du navigateur."
      )
    )
    return () => scanner.destroy()
  }, [verify])

  return (
    <dialog ref={dialogRef} className="trial-dialog trial-scan-dialog" tabIndex={-1} onClose={onClose}>
      <div className="trial-scan-header">
        <h3>Scanner les QR codes des inscrits</h3>
        <button
          type="button"
          className="trial-scan-close"
          onClick={() => dialogRef.current.close()}
          aria-label="Fermer"
          title="Fermer"
        >
          ✕
        </button>
      </div>
      <div className="trial-scan-video">
        <video ref={videoRef} muted playsInline />
      </div>
      {cameraError && <p className="warning">{cameraError}</p>}

      {pending > 0 && <p className="profile-hint">Vérification…</p>}
      {results.length > 0 && (
        <ul className="trial-scan-results">
          {results.map((r) => (
            <li key={r.key} className={`trial-scan-${r.status === 'error' ? 'ko' : scanColor(r)}`}>
              {r.student && (
                <strong>
                  {r.student.firstName} {r.student.lastName}
                </strong>
              )}
              {r.status === 'error' ? r.message : CHECKIN_MESSAGES[r.status](r)}
            </li>
          ))}
        </ul>
      )}
    </dialog>
  )
}
