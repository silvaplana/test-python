import { useCallback, useEffect, useState } from 'react'
import { BalanceChart, balanceSeries } from './BalanceChart.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Operations demandees au serveur (les plus recentes, maximum accepte) :
// toutes s'affichent, dans une fenetre de 10 lignes qui defile (voir
// .operations-scroll).
const OPERATIONS_FETCHED = 1000

const HIDDEN_OPERATIONS_KEY = 'bankaccounts-hidden-operations'
function readHiddenOperations() {
  try {
    return new Set(JSON.parse(localStorage.getItem(HIDDEN_OPERATIONS_KEY) ?? '[]'))
  } catch {
    return new Set()
  }
}

function euros(amount) {
  return `${amount.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
}

function dateFr(isoDate) {
  const [year, month, day] = isoDate.split('-')
  return `${day}/${month}/${year}`
}

async function callApi(path, options) {
  const response = await fetch(`${API_URL}${path}`, { credentials: 'include', ...options })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(body?.detail || `${path} a échoué (${response.status})`)
    error.status = response.status
    throw error
  }
  return response.json()
}

const getJson = (path) => callApi(path)

// Retour de la banque : apres l'autorisation, elle redirige vers l'URL de
// l'appli avec ?code=...&state=... (ou ?error=... si refuse). Lu UNE fois au
// chargement du module (avant meme la connexion a l'appli) puis retire de
// la barre d'adresse ; traite par BankAccounts une fois monte
// (voir processBankCallback). App.jsx l'utilise aussi pour ouvrir
// directement l'onglet Comptes.
const bankCallback = (() => {
  const params = new URLSearchParams(window.location.search)
  const state = params.get('state')
  if (!state || !(params.get('code') || params.get('error'))) return null
  window.history.replaceState({}, '', window.location.pathname)
  return { code: params.get('code'), state, error: params.get('error_description') || params.get('error') }
})()

export const hasBankCallback = bankCallback !== null

// Une seule fois meme si le composant est monte deux fois (React StrictMode).
let callbackPromise = null
function processBankCallback() {
  if (!bankCallback) return null
  if (!callbackPromise) {
    callbackPromise = bankCallback.error
      ? Promise.reject(new Error(`Connexion refusée par la banque : ${bankCallback.error}`))
      : callApi('/bankaccounts/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: bankCallback.code, state: bankCallback.state }),
        })
  }
  return callbackPromise
}

// Onglet Finances/Comptes : solde et dernieres operations des comptes de
// l'association (compte courant + Livret bleu). Meme charte que
// HelloAsso/Adherents (section-header, table-wrapper). Reserve au mot de
// passe "comptes" (voir Auth.jsx / App.jsx) ; le backend refuse (403) sinon.
export function BankAccounts() {
  const [accounts, setAccounts] = useState(null)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [connecting, setConnecting] = useState(false)
  // Tableaux d'operations replies (par nom de compte), memorises sur cet appareil :
  // laisse la place aux graphiques.
  const [hiddenOperations, setHiddenOperations] = useState(readHiddenOperations)

  function toggleOperations(name) {
    setHiddenOperations((current) => {
      const next = new Set(current)
      if (!next.delete(name)) next.add(name)
      try {
        localStorage.setItem(HIDDEN_OPERATIONS_KEY, JSON.stringify([...next]))
      } catch {
        // Stockage indisponible : le choix ne sera juste pas retenu.
      }
      return next
    })
  }

  // Envoie l'utilisateur s'autoriser chez sa banque (retour sur l'appli :
  // voir bankCallback). Sert a la 1ere connexion comme au renouvellement.
  async function connect() {
    setConnecting(true)
    try {
      const { url } = await callApi('/bankaccounts/connect', { method: 'POST' })
      window.location.href = url
    } catch (err) {
      setError(err.message)
      setConnecting(false)
    }
  }

  // refresh : ignore le cache serveur (bouton "Rafraichir" ; le chargement
  // initial le reutilise, pour menager le quota d'acces de la banque).
  const load = useCallback(async (refresh = false) => {
    const refreshParam = refresh ? 'refresh=true' : ''
    try {
      try {
        await processBankCallback()
      } catch (err) {
        setError(err.message)
      }
      const currentStatus = await getJson('/bankaccounts/status')
      setStatus(currentStatus)
      if (!currentStatus.connected) {
        setAccounts([])
        return
      }
      const list = await getJson(`/bankaccounts/accounts?${refreshParam}`)
      // Un appel par compte (les operations ne sont pas incluses dans la
      // liste des comptes) : en parallele, pour ne pas additionner les
      // latences.
      const withOperations = await Promise.all(
        list.map(async (account) => {
          const operations = await getJson(
            `/bankaccounts/accounts/${encodeURIComponent(account.id)}/transactions?limit=${OPERATIONS_FETCHED}&${refreshParam}`
          )
          return { ...account, operations, series: balanceSeries(operations, account.balance) }
        })
      )
      setAccounts(withOperations)
    } catch (err) {
      setError(err.message)
      // Session expiree entre-temps : repasse sur l'ecran de connexion.
      if (err.status === 409) setStatus((s) => (s ? { ...s, connected: false } : s))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section>
      <div className="section-header">
        <h2>Comptes</h2>
        <button onClick={() => load(true)}>Rafraîchir</button>
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

      {status?.mode === 'live' && !status.connected && (
        <div className="account-card">
          <h3>Connexion à la banque</h3>
          <p>
            Pour afficher les comptes, autorise l'accès en lecture seule chez {status.bank}. Tu seras redirigé vers
            ta banque, puis ramené ici.
          </p>
          <button onClick={connect} disabled={connecting}>
            {connecting ? 'Redirection…' : 'Connecter la banque'}
          </button>
        </div>
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
            <span className="account-balance">{account.balance == null ? '—' : euros(account.balance)}</span>
          </div>

          <BalanceChart series={account.series} />

          <button
            className="account-toggle"
            aria-expanded={!hiddenOperations.has(account.name)}
            onClick={() => toggleOperations(account.name)}
          >
            <span aria-hidden="true">{hiddenOperations.has(account.name) ? '▸' : '▾'}</span> Opérations (
            {account.operations.length})
          </button>

          <div className="table-wrapper operations-scroll" hidden={hiddenOperations.has(account.name)}>
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

      {status?.mode === 'live' && status.connected && (
        <p className="account-connection">
          Connexion à {status.bank} valable jusqu'au {dateFr(status.validUntil.slice(0, 10))}.{' '}
          <button onClick={connect} disabled={connecting}>
            {connecting ? 'Redirection…' : 'Reconnecter'}
          </button>
        </p>
      )}
    </section>
  )
}
