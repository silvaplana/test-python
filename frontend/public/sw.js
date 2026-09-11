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
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: 'icons/icon-192.png',
      badge: 'icons/icon-192.png',
      data: { url: data.url || '.' },
    })
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
