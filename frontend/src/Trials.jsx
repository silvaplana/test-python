import { useCallback, useEffect, useRef, useState } from 'react'

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

  return (
    <section>
      <div className="section-header">
        <h2>Élèves à l'essai ({students?.length ?? '…'})</h2>
        <div className="trial-header-actions">
          <button onClick={() => setEditing({})}>+ Élève</button>
          <button onClick={refetch}>Rafraîchir</button>
        </div>
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
                  <th className="col-secondary">Commentaire</th>
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
                      <td className="col-secondary trial-comment">{s.comment}</td>
                      <td>
                        <button
                          className="trial-add-course"
                          disabled={full || pendingId === s.id}
                          title={full ? "Les 2 cours d'essai sont déjà renseignés" : "Ajoute la date du jour"}
                          onClick={() => addCourse(s)}
                        >
                          + Cours
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}

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
