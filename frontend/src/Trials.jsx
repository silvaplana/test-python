import { useCallback, useEffect, useRef, useState } from 'react'
import QrScanner from 'qr-scanner'

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

const EMPTY_FORM = {
  firstName: '',
  lastName: '',
  birthDate: '',
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
    Object.entries(form).map(([key, value]) => [key, key === 'comment' ? value : value.trim() || null])
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
  // null : pas de fenetre ; {} : ajout ; {student} : modification.
  const [editing, setEditing] = useState(null)
  // Fenetre du scanner (ouverte si non null) : {result} une fois un QR code
  // verifie, {} pendant le scan.
  const [scan, setScan] = useState(null)

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

  function replaceStudent(updated) {
    setStudents((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
  }

  // Resultat d'un scan : met a jour la ligne de l'eleve et l'affiche.
  const showCheckin = useCallback((result) => {
    if (result.student) {
      setStudents((prev) => prev && prev.map((s) => (s.id === result.student.id ? result.student : s)))
    }
    if (result.status === 'added') navigator.vibrate?.(200)
    setScan({ result })
  }, [])

  // Ouverture de l'appli par le QR code (appareil photo du telephone).
  useEffect(() => {
    if (!checkinFromUrl) return
    urlCheckinPromise ??= checkIn(checkinFromUrl)
    urlCheckinPromise.then(showCheckin, (err) => setError(err.message))
  }, [showCheckin])

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

      {error && <p className="error">{error}</p>}

      {students &&
        (students.length === 0 ? (
          <p className="empty-state">Aucun élève à l'essai pour l'instant</p>
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
                {students.map((s) => {
                  const full = s.courses.every((c) => c.date)
                  return (
                    <tr key={s.id}>
                      <td className="trial-name-cell">
                        {/* Clic sur le nom : fiche complete (modification,
                            correction des dates, suppression). */}
                        <button className="trial-name" onClick={() => setEditing({ student: s })}>
                          {s.firstName} {s.lastName}
                        </button>
                      </td>
                      <td>{s.age ?? '—'}</td>
                      <td className="col-secondary">{s.qrGenerated ? `✓ ${timestampFr(s.qrCreatedAt)}` : '—'}</td>
                      <td>
                        <CourseCell course={s.courses[0]} />
                      </td>
                      <td>
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

      {/* Sous le tableau : scan du QR code presente par l'eleve en debut de
          cours. Gros bouton, souvent utilise d'une main. */}
      <button className="trial-scan-button" onClick={() => setScan({})}>
        QR code
      </button>
      {/* Exceptionnel : normalement l'eleve s'inscrit lui-meme en ligne. */}
      <button className="trial-add-student-button" onClick={() => setEditing({})}>
        Ajouter un élève
      </button>

      {scan && <ScanDialog result={scan.result} onResult={showCheckin} onRestart={() => setScan({})} onClose={() => setScan(null)} />}

      {editing && (
        <StudentDialog
          student={editing.student}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setEditing(null)
            if (editing.student) replaceStudent(saved)
            else setStudents((prev) => [saved, ...(prev ?? [])])
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

// Fenetre d'ajout (student absent) ou de modification d'un eleve. <dialog>
// natif : fond assombri, touche Echap et accessibilite geres par le
// navigateur (Android comme iPhone).
function StudentDialog({ student, onClose, onSaved, onDeleted }) {
  const dialogRef = useRef(null)
  const [form, setForm] = useState(() =>
    student
      ? Object.fromEntries(Object.keys(EMPTY_FORM).map((key) => [key, student[key] ?? '']))
      : EMPTY_FORM
  )
  const [courseDates, setCourseDates] = useState(() => student?.courses.map((c) => c.date ?? '') ?? [])
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
      let saved
      if (!student) {
        saved = await sendJson('/trials/students', 'POST', formToBody(form))
      } else {
        saved = await sendJson(`/trials/students/${student.id}`, 'PATCH', formToBody(form))
        for (const [i, course] of student.courses.entries()) {
          if ((course.date ?? '') !== courseDates[i]) {
            saved = await sendJson(`/trials/students/${student.id}/courses/${course.number}`, 'PUT', {
              date: courseDates[i] || null,
            })
          }
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
        <h3>{student ? `${student.firstName} ${student.lastName}` : 'Ajouter un élève'}</h3>
        {!student && (
          <p className="profile-hint">
            Exceptionnel : normalement l'élève s'inscrit lui-même sur la page d'essai et reçoit son QR code.
          </p>
        )}

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
            Date de naissance
            <input type="date" value={form.birthDate} onChange={update('birthDate')} />
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
          {student?.courses.map((course, i) => (
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

        {student && (
          <p className="profile-hint">
            {student.source === 'web' ? 'Inscrit en ligne' : 'Ajouté à la main'} le {timestampFr(student.createdAt)}
            {student.qrGenerated ? ' · QR code généré' : ' · pas de QR code'}
          </p>
        )}
        {(student?.hasSignature || student?.hasMedicalCertificate) && (
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
          {student && (
            <button type="button" className="trial-delete" onClick={remove} disabled={pending}>
              Supprimer
            </button>
          )}
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

const CHECKIN_MESSAGES = {
  added: (r) => `${r.course === 1 ? '1er' : '2e'} cours d'essai enregistré aujourd'hui`,
  used: (r) => `Cours d'essai déjà effectué le ${dateFr(r.date)}`,
  full: (r) => `Les 2 cours d'essai sont déjà renseignés (dernier le ${dateFr(r.date)})`,
  unknown: () => 'QR code non identifié',
}

// Scanner de QR code (camera arriere, bibliotheque qr-scanner : fonctionne
// sur Android comme sur iPhone, ou Safari ne sait pas lire les QR codes
// seul), avec saisie manuelle du code en secours. Affiche ensuite le
// resultat de la verification (voir backend Trials.check_in).
function ScanDialog({ result, onResult, onRestart, onClose }) {
  const dialogRef = useRef(null)
  const videoRef = useRef(null)
  const [cameraError, setCameraError] = useState(null)
  const [manualCode, setManualCode] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  // Focus sur la fenetre elle-meme (tabIndex -1) : sinon le navigateur le
  // donne au premier champ (la saisie manuelle du code), ce qui ouvre le
  // clavier du telephone par-dessus la camera.
  useEffect(() => {
    dialogRef.current.showModal()
    dialogRef.current.focus()
  }, [])

  const verify = useCallback(
    async (scanned) => {
      setPending(true)
      setError(null)
      try {
        onResult(await checkIn(scanned))
      } catch (err) {
        setError(err.message)
      } finally {
        setPending(false)
      }
    },
    [onResult]
  )

  // Camera allumee seulement pendant le scan (pas sur l'ecran de resultat).
  useEffect(() => {
    if (result) return
    let done = false
    const scanner = new QrScanner(
      videoRef.current,
      (decoded) => {
        if (done) return
        done = true
        scanner.stop()
        verify(decoded.data)
      },
      { preferredCamera: 'environment', highlightScanRegion: true, returnDetailedScanResult: true }
    )
    scanner.start().catch(() =>
      setCameraError(
        "Caméra indisponible : autorise l'accès à la caméra pour ce site dans les réglages du navigateur, ou saisis le code à la main."
      )
    )
    return () => scanner.destroy()
  }, [result, verify])

  function submitManual(e) {
    e.preventDefault()
    if (manualCode.trim()) verify(manualCode.trim())
  }

  const student = result?.student

  return (
    <dialog ref={dialogRef} className="trial-dialog trial-scan-dialog" tabIndex={-1} onClose={onClose}>
      {result ? (
        <div className={`trial-scan-result trial-scan-${result.status}`}>
          <p className="trial-scan-icon">{result.status === 'added' ? '✅' : result.status === 'unknown' ? '❌' : '⚠️'}</p>
          {student && (
            <h3>
              {student.firstName} {student.lastName}
              {student.age !== null && <span> · {student.age} ans</span>}
            </h3>
          )}
          <p>{CHECKIN_MESSAGES[result.status](result)}</p>
        </div>
      ) : (
        <>
          <h3>Scanner le QR code de l'élève</h3>
          <div className="trial-scan-video">
            <video ref={videoRef} muted playsInline />
          </div>
          {cameraError && <p className="warning">{cameraError}</p>}
          <form className="trial-scan-manual" onSubmit={submitManual}>
            <input
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value)}
              placeholder="ou code saisi à la main"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck="false"
            />
            <button type="submit" disabled={pending || !manualCode.trim()}>
              Vérifier
            </button>
          </form>
        </>
      )}

      {pending && <p className="profile-hint">Vérification…</p>}
      {error && <p className="error">{error}</p>}

      <div className="trial-dialog-actions">
        {result && (
          <button type="button" className="trial-save" onClick={onRestart}>
            Scanner un autre
          </button>
        )}
        <button type="button" onClick={() => dialogRef.current.close()}>
          Fermer
        </button>
      </div>
    </dialog>
  )
}
