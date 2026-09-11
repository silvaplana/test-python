// Abonnement aux notifications push (Web Push standard), utilise par
// Profile.jsx. Regroupe ici la mecanique brute (peu lisible, beaucoup de
// conversions d'encodage) pour garder Profile.jsx concentre sur l'UI.

// applicationServerKey de PushManager.subscribe() attend un Uint8Array,
// pas la chaine base64url renvoyee par le backend (GET
// /notifications/vapid_public_key) : conversion standard, copiee de la
// documentation MDN du Push API.
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)))
}

// Support navigateur : les 3 API necessaires (service worker, Push,
// Notification) doivent toutes exister -- absentes ex. sur un navigateur
// desktop ancien, ou (Push/Notification) sur iOS/Safari si le site n'a
// pas ete ajoute a l'ecran d'accueil au prealable.
export function isPushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

// État actuel : permission navigateur ('granted'/'denied'/'default') +
// abonnement push existant ou non (les 2 peuvent diverger, ex:
// permission accordee mais abonnement jamais cree si l'utilisateur avait
// quitte l'onglet Profil avant la fin du processus).
export async function getPushState() {
  if (!isPushSupported()) return { supported: false, permission: 'default', subscribed: false }
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  return {
    supported: true,
    permission: Notification.permission,
    subscribed: subscription !== null,
  }
}

// Active les notifications : demande la permission navigateur (doit
// venir d'un clic utilisateur, pas d'un appel automatique -- sinon la
// plupart des navigateurs refusent silencieusement), s'abonne, puis
// transmet l'abonnement au backend pour qu'il puisse pousser des
// notifications.
export async function subscribeToPush(apiUrl) {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error(
      permission === 'denied'
        ? 'Permission refusée : autorise les notifications pour ce site dans les réglages de ton navigateur.'
        : 'Permission non accordée.'
    )
  }

  const keyResponse = await fetch(`${apiUrl}/notifications/vapid_public_key`)
  if (!keyResponse.ok) throw new Error(`Échec de récupération de la clé VAPID (${keyResponse.status})`)
  const { publicKey } = await keyResponse.json()

  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  })

  const response = await fetch(`${apiUrl}/notifications/subscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscription.toJSON()),
  })
  if (!response.ok) throw new Error(`Échec d'enregistrement de l'abonnement (${response.status})`)
}

// Desactive les notifications : desabonne le navigateur ET previent le
// backend (sinon il continuerait a tenter de pousser vers un abonnement
// que ce navigateur a localement abandonne).
export async function unsubscribeFromPush(apiUrl) {
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return
  const endpoint = subscription.endpoint
  await subscription.unsubscribe()
  await fetch(`${apiUrl}/notifications/unsubscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint }),
  })
}
