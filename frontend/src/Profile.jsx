import { useEffect, useState } from 'react'
import { debugForgetOneSeenMember, setShowPhotos, useShowPhotos } from './HelloAsso.jsx'
import { getPushState, subscribeToPush, unsubscribeFromPush } from './push.js'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Onglet "Profil" : pour l'instant uniquement le reglage des
// notifications push (voir push.js) -- prevoit d'autres reglages plus
// tard, d'ou une section dediee plutot qu'un bouton perdu ailleurs.
export function Profile() {
  // null tant que l'etat initial (support/permission/abonnement, tous
  // asynchrones) n'est pas connu.
  const [state, setState] = useState(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const showPhotos = useShowPhotos()

  function refreshState() {
    getPushState()
      .then(setState)
      .catch(() => setState({ supported: false, permission: 'default', subscribed: false }))
  }

  useEffect(() => {
    refreshState()
  }, [])

  async function toggle() {
    setPending(true)
    setError(null)
    try {
      if (state.subscribed) {
        await unsubscribeFromPush(API_URL)
      } else {
        await subscribeToPush(API_URL)
      }
      refreshState()
    } catch (err) {
      setError(err.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <section>
      <div className="section-header">
        <h2>Profil</h2>
      </div>

      <div className="profile-card">
        <h3>Notifications</h3>
        <p>
          Reçois une notification sur ce téléphone/navigateur dès qu'un nouvel adhérent s'inscrit sur HelloAsso
          (même l'application fermée).
        </p>

        {!state ? (
          <p className="loading-label">
            Vérification
            <span className="loading-dots">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </span>
          </p>
        ) : !state.supported ? (
          <p className="error">Les notifications ne sont pas prises en charge par ce navigateur.</p>
        ) : (
          <>
            <label className="toggle-row">
              <input
                type="checkbox"
                name="notifications-enabled"
                checked={state.subscribed}
                disabled={pending || state.permission === 'denied'}
                onChange={toggle}
              />
              <span>Activer les notifications</span>
            </label>
            {state.permission === 'denied' && (
              <p className="warning">
                Les notifications sont bloquées pour ce site dans ton navigateur : autorise-les dans ses réglages
                (ex: icône de cadenas à côté de l'adresse) pour pouvoir les activer ici.
              </p>
            )}
            {error && <p className="error">{error}</p>}
          </>
        )}

        <p className="profile-hint">
          📱 Sur iPhone/iPad : ajoute d'abord ce site à l'écran d'accueil (bouton Partager de Safari → "Sur l'écran
          d'accueil") avant de pouvoir activer les notifications — c'est une limite d'iOS/Safari, pas de cette
          application.
        </p>
      </div>

      <div className="profile-card">
        <h3>Affichage</h3>
        <p>
          Affiche la photo d'identité de chaque adhérent (fournie à HelloAsso) dans le tableau Adhérents. À
          désactiver sur une connexion lente si le tableau met du temps à charger.
        </p>
        <label className="toggle-row">
          <input
            type="checkbox"
            name="show-photos"
            checked={showPhotos}
            onChange={(e) => setShowPhotos(e.target.checked)}
          />
          <span>Afficher les photos des élèves</span>
        </label>
      </div>

      {/* TEMPORAIRE (debug) : le badge "nouveaux adherents" compare a une
          memoire propre a cet appareil (localStorage), independante de
          celle du serveur -- simuler une nouvelle inscription cote
          serveur (SSH) ne peut donc pas la faire apparaitre ici. Ce
          bouton simule directement cote client, pour verifier
          badge/icone sans attendre une vraie inscription. A retirer une
          fois valide. */}
      <div className="profile-card">
        <h3>🔧 Debug</h3>
        <p>Simule un nouvel adhérent non consulté sur cet appareil (badge + icône), sans rien changer côté serveur.</p>
        <button onClick={() => debugForgetOneSeenMember()}>Simuler un nouvel adhérent</button>
      </div>
    </section>
  )
}
