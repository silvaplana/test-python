import { useCallback, useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const OPERATIONS_COUNT = 5

function euros(amount) {
  return `${amount.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
}

function dateFr(isoDate) {
  const [year, month, day] = isoDate.split('-')
  return `${day}/${month}/${year}`
}

async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include' })
  if (!response.ok) throw new Error(`GET ${path} a échoué (${response.status})`)
  return response.json()
}

// Onglet Finances/Comptes : solde et dernieres operations des comptes de
// l'association (compte courant + Livret bleu). Meme charte que
// HelloAsso/Adherents (section-header, table-wrapper). Reserve au mot de
// passe "comptes" (voir Auth.jsx / App.jsx) ; le backend refuse (403) sinon.
export function BankAccounts() {
  const [accounts, setAccounts] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const list = await getJson('/bankaccounts/accounts')
      // Un appel par compte (les operations ne sont pas incluses dans la
      // liste des comptes) : en parallele, pour ne pas additionner les
      // latences.
      const withOperations = await Promise.all(
        list.map(async (account) => ({
          ...account,
          operations: await getJson(
            `/bankaccounts/accounts/${encodeURIComponent(account.id)}/transactions?limit=${OPERATIONS_COUNT}`
          ),
        }))
      )
      setAccounts(withOperations)
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section>
      <div className="section-header">
        <h2>Comptes</h2>
        <button onClick={load}>Rafraîchir</button>
      </div>

      {error && <p className="error">{error}</p>}
      {!accounts && !error && (
        <p className="loading-label">
          Chargement
          <span className="loading-dots">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </p>
      )}

      {accounts?.some((a) => a.simulated) && (
        <p className="warning">Données de démonstration : aucune connexion bancaire pour l'instant.</p>
      )}

      {accounts?.map((account) => (
        <div key={account.id} className="account-card">
          <div className="account-card-header">
            <div>
              <h3>{account.name}</h3>
              <span className="account-iban">{account.iban}</span>
            </div>
            <span className="account-balance">{euros(account.balance)}</span>
          </div>

          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Libellé</th>
                  <th className="amount-cell">Montant</th>
                </tr>
              </thead>
              <tbody>
                {account.operations.map((op, i) => (
                  <tr key={i}>
                    <td>{dateFr(op.date)}</td>
                    <td>{op.label}</td>
                    <td className={`amount-cell ${op.amount < 0 ? 'unpaid-amount' : 'success-state'}`}>
                      {op.amount > 0 ? '+' : ''}
                      {euros(op.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  )
}
