import { useEffect, useState } from 'react'
import { BankHistory } from './BankHistory.jsx'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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

// Onglet Finances/Comptes : etat des comptes de l'association (compte
// courant + Livret Bleu), lu dans la base (voir BankHistory.jsx) et complete
// des dernieres operations de la banque a chaque ouverture. Ici : la
// connexion bancaire (autorisation chez la banque, a renouveler). Reserve au
// mot de passe "comptes" (voir Auth.jsx / App.jsx) ; le backend refuse (403)
// sinon.
// Jours avant l'expiration de l'autorisation de la banque a partir desquels
// l'ecran propose de se reconnecter.
const RECONNECT_WARNING_DAYS = 7

function expiresSoon(validUntil) {
  return Date.parse(validUntil) - Date.now() < RECONNECT_WARNING_DAYS * 24 * 3600 * 1000
}

export function BankAccounts({ active }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [connecting, setConnecting] = useState(false)

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

  useEffect(() => {
    ;(async () => {
      try {
        await processBankCallback()
      } catch (err) {
        setError(err.message)
      }
      try {
        setStatus(await callApi('/bankaccounts/status'))
      } catch (err) {
        setError(err.message)
      }
    })()
  }, [])

  return (
    <section>
      <div className="section-header">
        <h2>Comptes</h2>
      </div>

      {error && <p className="error">{error}</p>}

      {/* La synchronisation avec la banque attend le retour eventuel de
          l'autorisation (status charge) : sinon elle partirait avant que la
          nouvelle session bancaire existe. */}
      <BankHistory active={active} syncReady={status !== null} />

      {status?.mode === 'live' && !status.connected && (
        <div className="account-card">
          <h3>Connexion à la banque</h3>
          <p>
            Pour ajouter automatiquement les dernières opérations, autorise l'accès en lecture seule chez{' '}
            {status.bank}. Tu seras redirigé vers ta banque, puis ramené ici.
          </p>
          <button onClick={connect} disabled={connecting}>
            {connecting ? 'Redirection…' : 'Connecter la banque'}
          </button>
        </div>
      )}

      {/* Connexion en place : rien a dire, sauf quand il va falloir se
          reconnecter (autorisation de la banque bientot expiree). */}
      {status?.mode === 'live' && status.connected && expiresSoon(status.validUntil) && (
        <p className="account-connection">
          La connexion à {status.bank} expire le {dateFr(status.validUntil.slice(0, 10))} : reconnecte-toi pour garder
          les opérations à jour.{' '}
          <button onClick={connect} disabled={connecting}>
            {connecting ? 'Redirection…' : 'Reconnecter'}
          </button>
        </p>
      )}
    </section>
  )
}
