import { useCallback, useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function euros(amount) {
  return `${amount.toFixed(2)} €`
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
  // La colonne FFST distingue 3 cas pour chaque adherent : deja licencie,
  // demande en brouillon deja enregistree, ou ni l'un ni l'autre (bouton
  // pour lancer une demande).
  const { data: licences, refetch: refetchLicences } = useHelloAssoFetch('/ffst/licences')
  const { data: draftDemandes, refetch: refetchDraftDemandes } = useHelloAssoFetch('/ffst/demandes_draft')
  const ffstDataLoaded = licences !== null && draftDemandes !== null
  const licenceIdentifiers = ffstIdentifiers(licences)
  const draftIdentifiers = ffstIdentifiers(draftDemandes)
  // Etat du transfert vers le batch DRAFT FFST, par adherent (identifier) :
  // en cours (pilote un vrai navigateur cote backend, plusieurs secondes)
  // et erreur eventuelle (ex: aucun ancien licencie correspondant trouve).
  const [pendingIdentifiers, setPendingIdentifiers] = useState(new Set())
  const [transferErrors, setTransferErrors] = useState({})

  // Rafraichit les 3 sources (adherents + les 2 listes FFST utilisees pour
  // la colonne Statut FFST) : sinon un changement fait a la main sur le
  // site FFST (ex: demande validee) resterait invisible tant qu'on ne
  // recharge pas toute la page.
  function refetchAll() {
    refetchMembers()
    refetchLicences()
    refetchDraftDemandes()
  }

  async function transferToDraft(member, identifier) {
    setPendingIdentifiers((prev) => new Set(prev).add(identifier))
    setTransferErrors((prev) => ({ ...prev, [identifier]: null }))
    try {
      const response = await fetch(`${API_URL}/ffst/demandes_renouvellement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lastName: member.lastName, firstName: member.firstName }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `Échec du transfert (${response.status})`)
      }
      refetchDraftDemandes()
    } catch (err) {
      setTransferErrors((prev) => ({ ...prev, [identifier]: err.message }))
    } finally {
      setPendingIdentifiers((prev) => {
        const next = new Set(prev)
        next.delete(identifier)
        return next
      })
    }
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
                <th className="col-secondary">Montant</th>
                <th className="col-secondary">Statut HelloAsso</th>
                <th>Statut FFST</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m, i) => {
                const identifier = memberIdentifier(m.lastName, m.firstName)
                return (
                  <tr key={i}>
                    <td>{m.lastName}</td>
                    <td>{m.firstName}</td>
                    <td>{m.email}</td>
                    <td className="col-secondary">{euros(m.amount)}</td>
                    <td className="col-secondary">{m.state}</td>
                    <td>
                      {ffstDataLoaded &&
                        (licenceIdentifiers.has(identifier) ? (
                          'Licence FFST créée'
                        ) : draftIdentifiers.has(identifier) ? (
                          'Dans le batch DRAFT FFST'
                        ) : (
                          <>
                            <button
                              onClick={() => transferToDraft(m, identifier)}
                              disabled={pendingIdentifiers.has(identifier)}
                            >
                              {pendingIdentifiers.has(identifier)
                                ? 'Transfert en cours…'
                                : 'Transférer au batch DRAFT FFST'}
                            </button>
                            {transferErrors[identifier] && (
                              <p className="error">{transferErrors[identifier]}</p>
                            )}
                          </>
                        ))}
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
  const { data: campaign } = useHelloAssoFetch('/helloasso/campaign')
  return <h1 className="campaign-title">{campaign?.title ?? '…'}</h1>
}
