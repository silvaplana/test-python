// Service worker "PWA light" : juste ce qu'il faut pour (1) rendre le
// site installable (Chrome/Android exige un service worker avec un
// gestionnaire "fetch", meme minimal, comme critere d'installabilite) et
// (2) recevoir/afficher les notifications push "nouvel adherent" (voir
// Profile.jsx). Pas de cache offline : cette appli affiche des donnees
// live (adherents, licences...), un mode hors-ligne n'aurait pas grand
// interet et ajouterait un risque de contenu perime.

// skipWaiting + clients.claim : la nouvelle version prend effet des le
// prochain chargement de page plutot que d'attendre la fermeture de tous
// les onglets -- important pour une appli qui change souvent, on ne veut
// pas qu'un utilisateur reste bloque sur un vieux service worker.
self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

// Pass-through pur (aucun cache) : present uniquement pour satisfaire le
// critere d'installabilite Chrome/Android.
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request))
})

// Compteur du badge d'icone (Badging API), stocke dans IndexedDB : c'est
// le SEUL moyen de le faire evoluer pendant que l'appli est fermee
// (notification recue en arriere-plan) -- localStorage n'existe pas dans
// un service worker, contrairement a IndexedDB, accessible aussi bien
// ici que depuis la page principale (voir resetBadgeCount dans
// HelloAsso.jsx, qui remet ce compteur a 0 quand l'onglet Adherents
// devient actif). Volontairement un simple entier incremente a chaque
// push recu (pas le compte exact d'adherents non consultes, qui
// necessiterait de recalculer le diff complet ici) : suffisant pour
// signaler "il y a du nouveau depuis la derniere consultation", et reste
// coherent avec le badge affiche dans l'appli (les 2 sont remis a 0 au
// meme moment).
const BADGE_DB_NAME = 'samboadmin-badge'
const BADGE_STORE = 'kv'
const BADGE_KEY = 'count'

function openBadgeDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(BADGE_DB_NAME, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(BADGE_STORE)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function incrementBadgeCount() {
  const db = await openBadgeDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(BADGE_STORE, 'readwrite')
    const store = tx.objectStore(BADGE_STORE)
    const getReq = store.get(BADGE_KEY)
    let next
    getReq.onsuccess = () => {
      next = (getReq.result || 0) + 1
      store.put(next, BADGE_KEY)
    }
    tx.oncomplete = () => resolve(next)
    tx.onerror = () => reject(tx.error)
  })
}

// Reception d'une notification push (voir PushNotifications.send_push_to_all
// cote backend, payload JSON {title, body, url}).
self.addEventListener('push', (event) => {
  let data = { title: 'samboAdmin', body: '' }
  try {
    if (event.data) data = { ...data, ...event.data.json() }
  } catch {
    // Payload non-JSON (improbable, mais ne doit jamais faire planter le
    // service worker) : on garde le titre par defaut.
  }
  event.waitUntil(
    (async () => {
      // Icone de l'app : voir le commentaire de BADGE_DB_NAME plus haut.
      // "navigator" existe dans un service worker (WorkerNavigator), pas
      // besoin de self.navigator.
      if ('setAppBadge' in navigator) {
        try {
          const count = await incrementBadgeCount()
          await navigator.setAppBadge(count)
        } catch (err) {
          console.error('setAppBadge (push) a echoue:', err)
        }
      }
      await self.registration.showNotification(data.title, {
        body: data.body,
        icon: 'icons/icon-192.png',
        badge: 'icons/icon-192.png',
        data: { url: data.url || '.' },
      })
    })()
  )
})

// Clic sur la notification : reprend un onglet deja ouvert sur l'appli
// s'il y en a un, sinon en ouvre un nouveau. L'URL du payload est
// resolue relativement au scope du service worker (pas a une URL
// absolue envoyee par le backend, qui ne connait pas le chemin de base
// /sambo-admin/ du frontend en prod).
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = new URL(event.notification.data?.url || '.', self.registration.scope).href
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.startsWith(self.registration.scope) && 'focus' in client) {
          return client.focus()
        }
      }
      return self.clients.openWindow(targetUrl)
    })
  )
})
