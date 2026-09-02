import { useCallback, useEffect, useState } from 'react'
import clubLogo from './assets/club-logo.png'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function euros(amount) {
  return `${amount.toFixed(2)} €`
}

// Libelle d'action en cours (ex: "Envoi en cours") : italique + 3 points
// animes en boucle (voir .loading-label/.loading-dots dans App.css),
// plutot qu'un simple "..." statique.
function LoadingLabel({ text }) {
  return (
    <span className="loading-label">
      {text}
      <span className="loading-dots">
        <span>.</span>
        <span>.</span>
        <span>.</span>
      </span>
    </span>
  )
}

// Tableau simple avec etat loading/error/data, factorise pour les 2 tableaux
// (membres, impayes) qui ont la meme mecanique de chargement.
function useHelloAssoFetch(path) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}${path}`)
      if (!response.ok) throw new Error(`GET ${path} a échoué (${response.status})`)
      setData(await response.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [path])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { data, error, refetch: fetchData }
}

// Identifiant normalise (nom + prenom, insensible a la casse et aux
// espaces superflus) pour comparer un adherent HelloAsso (lastName +
// firstName separes) a une ligne FFST ("Nom et Prénom" combine).
function memberIdentifier(lastName, firstName) {
  return `${lastName} ${firstName}`.replace(/\s+/g, ' ').trim().toUpperCase()
}

// Ensemble des identifiants (voir memberIdentifier) presents dans une liste
// FFST (licences ou demandes), pour un test d'appartenance en O(1).
function ffstIdentifiers(ffstRows) {
  return new Set(
    (ffstRows ?? []).map((row) => (row['Nom et Prénom'] || '').replace(/\s+/g, ' ').trim().toUpperCase())
  )
}

export function MembersTable() {
  const { data: members, error, refetch: refetchMembers } = useHelloAssoFetch('/helloasso/members')
  // La colonne Statut FFST distingue 4 cas pour chaque adherent, par
  // ordre de priorite : licencie (payee), demande validee (a payer),
  // demande en brouillon (bouton pour la supprimer), ou aucun des 3
  // (bouton pour en faire une).
  const { data: licences, refetch: refetchLicences } = useHelloAssoFetch('/ffst/licences')
  const { data: validatedDemandes, refetch: refetchValidatedDemandes } = useHelloAssoFetch(
    '/ffst/demandes_validated'
  )
  const { data: draftDemandes, refetch: refetchDraftDemandes } = useHelloAssoFetch('/ffst/demandes_draft')
  const ffstDataLoaded = licences !== null && validatedDemandes !== null && draftDemandes !== null
  const licenceIdentifiers = ffstIdentifiers(licences)
  const validatedIdentifiers = ffstIdentifiers(validatedDemandes)
  const draftIdentifiers = ffstIdentifiers(draftDemandes)
  // Etat des actions FFST en cours, par adherent (identifier) : en cours
  // (pilote un vrai navigateur cote backend, plusieurs secondes) et
  // erreur eventuelle (ex: aucun ancien licencie correspondant trouve).
  const [pendingIdentifiers, setPendingIdentifiers] = useState(new Set())
  const [actionErrors, setActionErrors] = useState({})

  // Rafraichit les 4 sources (adherents + les 3 listes FFST utilisees pour
  // la colonne Statut FFST) : sinon un changement fait a la main sur le
  // site FFST (ex: demande validee) resterait invisible tant qu'on ne
  // recharge pas toute la page.
  function refetchAll() {
    refetchMembers()
    refetchLicences()
    refetchValidatedDemandes()
    refetchDraftDemandes()
  }

  async function appelerFfst(identifier, method, path, body) {
    setPendingIdentifiers((prev) => new Set(prev).add(identifier))
    setActionErrors((prev) => ({ ...prev, [identifier]: null }))
    try {
      const response = await fetch(`${API_URL}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        const responseBody = await response.json().catch(() => null)
        throw new Error(responseBody?.detail || `Échec (${response.status})`)
      }
      refetchDraftDemandes()
    } catch (err) {
      setActionErrors((prev) => ({ ...prev, [identifier]: err.message }))
    } finally {
      setPendingIdentifiers((prev) => {
        const next = new Set(prev)
        next.delete(identifier)
        return next
      })
    }
  }

  function creerDemande(member, identifier) {
    // gender/birthDate/etc. ne servent que si l'adherent n'a pas
    // d'ancienne licence renouvelable (chemin "nouvelle demande" cote
    // backend) : on les envoie systematiquement, au cas ou.
    const fields = member.customFields || {}
    appelerFfst(identifier, 'POST', '/ffst/demandes_renouvellement', {
      lastName: member.lastName,
      firstName: member.firstName,
      gender: fields['Genre(H/F)'],
      birthDate: fields['date de naissance'],
      addressLine1: fields['Adresse'],
      postalCode: fields['code postal'],
      city: fields['Ville'],
      phone: fields['Numéro de téléphone'],
      email: member.email,
    })
  }

  function supprimerDemande(member, identifier) {
    appelerFfst(identifier, 'DELETE', '/ffst/demandes_draft', {
      lastName: member.lastName,
      firstName: member.firstName,
    })
  }

  return (
    <section>
      <div className="section-header">
        <h2>Adhérents HelloAsso ({members?.length ?? '…'})</h2>
        <button onClick={refetchAll}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {members && (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Prénom</th>
                <th>Email</th>
                <th>Montant</th>
                <th>Code promo</th>
                <th className="col-secondary">Statut HelloAsso</th>
                <th>Statut FFST</th>
                <th>Actions FFST</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m, i) => {
                const identifier = memberIdentifier(m.lastName, m.firstName)
                const pending = pendingIdentifiers.has(identifier)
                const ffstStatus = licenceIdentifiers.has(identifier)
                  ? 'Licence créée'
                  : validatedIdentifiers.has(identifier)
                    ? 'Validée, à payer'
                    : draftIdentifiers.has(identifier)
                      ? 'Brouillon'
                      : 'Inconnu'
                return (
                  <tr key={i}>
                    <td>{m.lastName}</td>
                    <td>{m.firstName}</td>
                    <td>{m.email}</td>
                    <td>{euros(m.amount)}</td>
                    <td>{m.promoCode || '—'}</td>
                    <td className="col-secondary">{m.state}</td>
                    <td>{ffstDataLoaded ? ffstStatus : '…'}</td>
                    <td>
                      {ffstDataLoaded && (
                        <>
                          {ffstStatus === 'Inconnu' && (
                            <button onClick={() => creerDemande(m, identifier)} disabled={pending}>
                              {pending ? <LoadingLabel text="Envoi en cours" /> : 'Faire la demande'}
                            </button>
                          )}
                          {ffstStatus === 'Brouillon' && (
                            <button onClick={() => supprimerDemande(m, identifier)} disabled={pending}>
                              {pending ? <LoadingLabel text="Suppression en cours" /> : 'Supprimer la demande'}
                            </button>
                          )}
                          {actionErrors[identifier] && <p className="error">{actionErrors[identifier]}</p>}
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function UnpaidTable() {
  const { data: unpaid, error, refetch } = useHelloAssoFetch('/helloasso/unpaid')

  return (
    <section>
      <div className="section-header">
        <h2>Impayés HelloAsso ({unpaid?.length ?? '…'})</h2>
        <button onClick={refetch}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}

      {unpaid && (unpaid.length === 0 ? (
        <p className="empty-state">Aucun impayé 🎉</p>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Prénom</th>
                <th>Email</th>
                <th className="col-secondary">Total</th>
                <th>Impayé</th>
                <th className="col-secondary">Échéances refusées</th>
              </tr>
            </thead>
            <tbody>
              {unpaid.map((m, i) => (
                <tr key={i}>
                  <td>{m.lastName}</td>
                  <td>{m.firstName}</td>
                  <td>{m.email}</td>
                  <td className="col-secondary">{euros(m.totalAmount)}</td>
                  <td className="unpaid-amount">{euros(m.unpaidAmount)}</td>
                  <td className="col-secondary">
                    {m.refusedPayments.map((p) => (p.date || '').slice(0, 10)).join(', ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}

export function CampaignTitle() {
  // Nom du club plutot que le titre (variable d'une saison a l'autre) du
  // formulaire d'adhesion HelloAsso : plus de fetch necessaire ici. Logo
  // recupere manuellement depuis le tableau de bord HelloAsso du club
  // (pas accessible via l'API, page admin necessitant une connexion).
  return (
    <h1 className="campaign-title">
      <img src={clubLogo} alt="" className="club-logo" />
      Alliance Sambo Combat La Ciotat
    </h1>
  )
}
