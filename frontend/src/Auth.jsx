import { createContext, useContext, useEffect, useState } from 'react'
// Version detouree (fond transparent, voir public/icons/icon-192.png et
// son commit "Icônes Android/PWA : ours détouré, fond transparent") --
// contrairement a club-logo.png (utilise ailleurs, ex: CampaignTitle),
// qui a un fond plein : se fond mal dans .login-screen. icon-192 (pas
// -512) : affiche a 96px ici, 192 suffit largement (2x, ecrans retina
// compris) pour 5x moins lourd.
import clubLogo from './assets/club-logo-transparent.png'
import { getPushState, subscribeToPush } from './push.js'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Notifications activees par defaut (demande explicite), sans etape
// manuelle dans l'onglet Profil -- tente l'abonnement des que possible.
// Best-effort et silencieux : Notification.requestPermission() n'aboutit
// (affiche vraiment le prompt navigateur) que dans la foulee d'un geste
// utilisateur (voir push.js) -- ici le clic sur "Valider" du formulaire
// de mot de passe. permission === 'default' uniquement : jamais re-tente
// si l'utilisateur a deja repondu (accorde puis desabonne manuellement
// depuis Profil = choix respecte, refuse = inutile de re-demander).
function tryAutoSubscribe() {
  getPushState()
    .then((state) => {
      if (state.supported && state.permission === 'default' && !state.subscribed) {
        return subscribeToPush(API_URL)
      }
    })
    .catch(() => {
      // Silencieux : simple confort par defaut, l'utilisateur garde la
      // main depuis l'onglet Profil dans tous les cas.
    })
}

// Expose logout() et canViewAccounts (2e niveau d'acces, voir
// backend/src/auth/ : mot de passe "comptes" -> onglet Finances/Comptes) aux
// composants enfants (voir Profile.jsx, App.jsx) sans avoir a faire
// redescendre des props.
const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

// Point d'entree unique de l'appli (demande explicite : pas d'adresse de
// login separee) -- tant que la session n'est pas authentifiee, ce
// composant affiche le formulaire de mot de passe a la place de tout le
// reste (children, jamais monte). Le backend fait deja tout le travail
// (require_auth sur chaque route API, voir backend/src/auth/) : ce
// composant ne fait que refleter GET /auth/status cote UI.
export function AuthGate({ children }) {
  // null tant que /auth/status n'a pas repondu : evite d'afficher le
  // formulaire une fraction de seconde avant de basculer sur l'appli pour
  // quelqu'un deja connecte (cookie valide envoye automatiquement).
  const [authenticated, setAuthenticated] = useState(null)
  // Simple confort d'affichage (masque l'onglet Comptes) : la vraie
  // protection est cote backend (require_accounts_auth, 403 sinon).
  const [canViewAccounts, setCanViewAccounts] = useState(false)

  function refreshStatus() {
    return fetch(`${API_URL}/auth/status`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => {
        setCanViewAccounts(Boolean(data.canViewAccounts))
        setAuthenticated(data.authenticated)
        if (data.authenticated) tryAutoSubscribe()
      })
      .catch(() => setAuthenticated(false))
  }

  useEffect(() => {
    refreshStatus()
  }, [])

  async function logout() {
    await fetch(`${API_URL}/auth/logout`, { method: 'POST', credentials: 'include' })
    setAuthenticated(false)
    setCanViewAccounts(false)
  }

  if (authenticated === null) {
    return (
      <div className="login-screen">
        <p className="loading-label">
          Vérification
          <span className="loading-dots">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </p>
      </div>
    )
  }

  if (!authenticated) {
    return (
      <LoginForm
        onSuccess={(data) => {
          setCanViewAccounts(Boolean(data?.canViewAccounts))
          setAuthenticated(true)
        }}
      />
    )
  }

  return <AuthContext.Provider value={{ logout, canViewAccounts }}>{children}</AuthContext.Provider>
}

function LoginForm({ onSuccess }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(false)
  // "Mot de passe oublié ?" : pas de vraie recuperation (mot de passe
  // partage, pas de compte individuel/email associe) -- juste une
  // indication de qui contacter, affichee au clic.
  const [showForgotHint, setShowForgotHint] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!password || pending) return
    setPending(true)
    setError(null)
    try {
      const response = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (!response.ok) throw new Error()
      onSuccess(await response.json().catch(() => null))
      // Ici, dans la continuite synchrone du clic sur "Valider" : c'est
      // le geste utilisateur necessaire pour que le navigateur affiche
      // vraiment le prompt de permission (voir tryAutoSubscribe).
      tryAutoSubscribe()
    } catch {
      // Message generique (demande explicite) : jamais de detail sur ce
      // qui est faux, il n'y a qu'un seul champ de toute facon.
      setError('Mot de passe incorrect.')
      setPassword('')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="login-form" onSubmit={submit}>
        <img src={clubLogo} alt="Alliance Sambo Combat La Ciotat" className="login-logo" />
        <p className="login-subtitle">Gestion de l'association Alliance Sambo Combat La Ciotat</p>
        <input
          type="password"
          placeholder="Mot de passe"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          disabled={pending}
        />
        <button type="submit" disabled={pending || !password}>
          Valider
        </button>
        {error && <p className="error">{error}</p>}
        <button type="button" className="login-forgot" onClick={() => setShowForgotHint(true)}>
          Mot de passe oublié ?
        </button>
        {showForgotHint && <p className="login-forgot-hint">Contacter le président ou Sébastien</p>}
      </form>
    </div>
  )
}
