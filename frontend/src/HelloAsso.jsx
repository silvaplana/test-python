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

export function MembersTable() {
  const { data: members, error, refetch } = useHelloAssoFetch('/helloasso/members')

  return (
    <section>
      <div className="section-header">
        <h2>Adhérents HelloAsso ({members?.length ?? '…'})</h2>
        <button onClick={refetch}>Rafraîchir</button>
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
                <th className="col-secondary">Statut</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m, i) => (
                <tr key={i}>
                  <td>{m.lastName}</td>
                  <td>{m.firstName}</td>
                  <td>{m.email}</td>
                  <td className="col-secondary">{euros(m.amount)}</td>
                  <td className="col-secondary">{m.state}</td>
                </tr>
              ))}
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
